"""
TRACON Application — Terminal Radar Approach Control.

Manages aircraft in the terminal area (~3,000–18,000 ft AGL) around one
or more airports.  Sequences arrivals onto approach paths, hands departures
up to the en-route center, and coordinates with tower for the final segment.

Subscribes to AircraftPosition (CFT by altitude band), publishes
ControllerInstruction, handles Handoff to/from Center and Tower, and
publishes Alert for terminal-area conflicts.
"""

import argparse
import os
import signal
import sys
import time


import rti.connextdds as dds
from air_traffic import NationalAirTrafficControl as ATC

AircraftPosition = ATC.AircraftPosition
AircraftTracking = ATC.AircraftTracking
Alert = ATC.Alert
AlertSeverity = ATC.AlertSeverity
AlertType = ATC.AlertType
ControllerInstruction = ATC.ControllerInstruction
FacilityStatus = ATC.FacilityStatus
FacilityType = ATC.FacilityType
FlightPhase = ATC.FlightPhase
FlightPlan = ATC.FlightPlan
Handoff = ATC.Handoff
HandoffStatus = ATC.HandoffStatus
InstructionType = ATC.InstructionType
PilotAcknowledgment = ATC.PilotAcknowledgment
WeatherReport = ATC.WeatherReport
from common import (
    create_participant,
    create_publisher,
    create_subscriber,
    load_airport_coords,
    load_qos_provider,
    load_tracon_config,
    make_id,
    now_ms,
    reader_qos,
    setup_logging,
    writer_qos,
)
import common

log = setup_logging("tracon")

# Loaded lazily after --config is parsed
AIRPORT_COORDS = {}

shutdown_flag = False


def signal_handler(_sig, _frame):
    global shutdown_flag
    shutdown_flag = True


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


class TraconController:
    """Simulates a TRACON facility managing the terminal area around an airport."""

    # Altitude boundaries
    MIN_ALT = 500     # Below this the tower has jurisdiction
    MAX_ALT = 18000   # Above this the en-route center has jurisdiction
    TOWER_HANDOFF_ALT = 3000   # Hand to tower below this altitude
    CENTER_HANDOFF_ALT = 17000  # Hand to center above this altitude

    # Terminal area radius in degrees (~40 nm ≈ 0.66°)
    TERMINAL_RADIUS_DEG = 0.66

    def __init__(
        self,
        tracon_id: str,
        controller_id: str,
        airport_codes: list[str],
        serving_center: str = "",
    ):
        self.tracon_id = tracon_id
        self.controller_id = controller_id
        self.airport_codes = airport_codes
        self.serving_center = serving_center
        self.tracked_aircraft: dict[str, AircraftPosition] = {}
        self.handed_off: set[str] = set()  # tail numbers already handed off this cycle
        self.acquired_aircraft: set[str] = set()  # aircraft formally received via handoff
        self.controlling: set[str] = set()  # tails with active AircraftTracking instance
        self._sep_cooldown: dict[tuple[str, str], float] = {}  # (tail_a, tail_b) -> last alert time

        # DDS setup
        self.qos_provider = load_qos_provider()

        # DP partitions: terminal scope + overlying center (towers reach up to terminal)
        dp_partitions = [f"OPS/TERMINAL/{tracon_id}", "OPS/FPS/*"]
        if serving_center:
            dp_partitions.append(f"OPS/ENROUTE/{serving_center}")
        self.participant = create_participant(
            self.qos_provider,
            dp_partitions=dp_partitions,
            participant_name=f"TRACON_{tracon_id}",
            app_name="ATC_TRACON",
        )

        self.publisher = create_publisher(self.participant)
        self.subscriber = create_subscriber(self.participant)

        # AircraftPosition reader — CFT by altitude band in terminal area
        pos_topic = dds.Topic(self.participant, "AircraftPosition", AircraftPosition)
        self.pos_cft = dds.ContentFilteredTopic(
            pos_topic,
            f"TerminalTraffic_{tracon_id}",
            dds.Filter(
                "position.altitude_feet >= %0 AND position.altitude_feet < %1",
                [str(self.MIN_ALT), str(self.MAX_ALT)],
            ),
        )
        self.pos_reader = dds.DataReader(
            self.subscriber, self.pos_cft,
            reader_qos(self.qos_provider, "AircraftPositionProfile"),
        )

        # ControllerInstruction writer
        instr_topic = dds.Topic(self.participant, "ControllerInstruction", ControllerInstruction)
        self.instr_writer = dds.DataWriter(
            self.publisher, instr_topic,
            writer_qos(self.qos_provider, "ControllerInstructionProfile"),
        )

        # PilotAcknowledgment reader
        ack_topic = dds.Topic(self.participant, "PilotAcknowledgment", PilotAcknowledgment)
        self.ack_reader = dds.DataReader(
            self.subscriber, ack_topic,
            reader_qos(self.qos_provider, "PilotAcknowledgmentProfile"),
        )

        # Handoff writer + reader
        ho_topic = dds.Topic(self.participant, "Handoff", Handoff)
        self.ho_writer = dds.DataWriter(
            self.publisher, ho_topic,
            writer_qos(self.qos_provider, "HandoffProfile"),
        )
        self.ho_cft = dds.ContentFilteredTopic(
            ho_topic,
            f"MyHandoffs_{controller_id}",
            dds.Filter(
                f"to_controller_id = '{controller_id}' OR from_controller_id = '{controller_id}'"
            ),
        )
        self.ho_reader = dds.DataReader(
            self.subscriber, self.ho_cft,
            reader_qos(self.qos_provider, "HandoffProfile"),
        )

        # Alert writer
        alert_topic = dds.Topic(self.participant, "Alert", Alert)
        self.alert_writer = dds.DataWriter(
            self.publisher, alert_topic,
            writer_qos(self.qos_provider, "AlertProfile"),
        )

        # Weather reader (for the airports we serve)
        wx_topic = dds.Topic(self.participant, "WeatherReport", WeatherReport)
        self.wx_reader = dds.DataReader(
            self.subscriber, wx_topic,
            reader_qos(self.qos_provider, "WeatherReportProfile"),
        )

        # FlightPlan reader
        fp_topic = dds.Topic(self.participant, "FlightPlan", FlightPlan)
        self.fp_reader = dds.DataReader(
            self.subscriber, fp_topic,
            reader_qos(self.qos_provider, "FlightPlanProfile"),
        )

        # AircraftTracking writer — publishes current controller of record
        tracking_topic = dds.Topic(self.participant, "AircraftTracking", AircraftTracking)
        self.tracking_writer = dds.DataWriter(
            self.publisher, tracking_topic,
            writer_qos(self.qos_provider, "AircraftTrackingProfile"),
        )

        # FacilityStatus writer — per-facility heartbeat & workload
        status_topic = dds.Topic(self.participant, "FacilityStatus", FacilityStatus)
        self.status_writer = dds.DataWriter(
            self.publisher, status_topic,
            writer_qos(self.qos_provider, "FacilityStatusProfile"),
        )
        self._publish_facility_status()

        log.info(
            "TRACON %s (%s) initialized — airports: %s, FL%d–FL%d",
            tracon_id, controller_id, ", ".join(airport_codes),
            self.MIN_ALT // 100, self.MAX_ALT // 100,
        )

    # ── Helpers ────────────────────────────────────────────────────────

    def _is_in_terminal_area(self, pos: AircraftPosition) -> bool:
        """Check if aircraft is near one of our airports."""
        for code in self.airport_codes:
            alat, alon = AIRPORT_COORDS.get(code, (0, 0))
            dlat = abs(pos.position.latitude - alat)
            dlon = abs(pos.position.longitude - alon)
            if dlat < self.TERMINAL_RADIUS_DEG and dlon < self.TERMINAL_RADIUS_DEG:
                return True
        return False

    def _is_arriving(self, pos: AircraftPosition) -> bool:
        return pos.destination_airport in self.airport_codes

    def _is_departing(self, pos: AircraftPosition) -> bool:
        return pos.origin_airport in self.airport_codes

    # ── Traffic monitoring ─────────────────────────────────────────────

    def monitor_traffic(self):
        """Read and track aircraft in the terminal area."""
        for sample in self.pos_reader.take_data():
            # Only track if associated with our airports
            if self._is_in_terminal_area(sample) or \
               sample.origin_airport in self.airport_codes or \
               sample.destination_airport in self.airport_codes:
                self.tracked_aircraft[sample.tail_number] = sample
            else:
                self.tracked_aircraft.pop(sample.tail_number, None)

        if self.tracked_aircraft:
            arrivals = sum(1 for p in self.tracked_aircraft.values() if self._is_arriving(p))
            departures = sum(1 for p in self.tracked_aircraft.values() if self._is_departing(p))
            log.info(
                "Tracking %d aircraft in terminal area (%d arr, %d dep)",
                len(self.tracked_aircraft), arrivals, departures,
            )

    # ── Separation checking ────────────────────────────────────────────

    _GROUND_PHASES = frozenset([
        FlightPhase.PREFLIGHT, FlightPhase.TAXI_OUT,
        FlightPhase.TAXI_IN, FlightPhase.PARKED,
    ])
    _SEP_COOLDOWN_S = 30  # suppress duplicate alerts for the same pair

    def check_separation(self):
        """Check for separation violations in the terminal area.

        Terminal area uses tighter separation: 3 nm lateral / 1000 ft vertical.
        Skips ground-phase aircraft and suppresses duplicate alerts per pair.
        """
        airborne = [
            p for p in self.tracked_aircraft.values()
            if p.flight_phase not in self._GROUND_PHASES
        ]
        now = time.time()
        for i, a in enumerate(airborne):
            for b in airborne[i + 1:]:
                lat_diff = abs(a.position.latitude - b.position.latitude)
                lon_diff = abs(a.position.longitude - b.position.longitude)
                alt_diff = abs(a.position.altitude_feet - b.position.altitude_feet)

                # 3 nm lateral ≈ 0.05°, 1000 ft vertical
                if lat_diff < 0.05 and lon_diff < 0.05 and alt_diff < 1000:
                    pair = tuple(sorted((a.tail_number, b.tail_number)))
                    if now - self._sep_cooldown.get(pair, 0) < self._SEP_COOLDOWN_S:
                        continue
                    self._sep_cooldown[pair] = now
                    log.warning(
                        "TERMINAL SEPARATION VIOLATION: %s and %s (%.0fft / %.0fft)",
                        a.tail_number, b.tail_number,
                        a.position.altitude_feet, b.position.altitude_feet,
                    )
                    alert = Alert(
                        alert_id=make_id("ALERT-"),
                        alert_type=AlertType.TRAFFIC_CONFLICT,
                        severity=AlertSeverity.WARNING,
                        involved_aircraft=[a.tail_number, b.tail_number],
                        message=(
                            f"Terminal separation violation: {a.tail_number} "
                            f"and {b.tail_number} in {self.tracon_id}"
                        ),
                        timestamp=now_ms(),
                    )
                    self.alert_writer.write(alert)

    # ── Approach sequencing ────────────────────────────────────────────

    def sequence_arrivals(self):
        """Issue approach instructions to arriving aircraft."""
        for tail, pos in self.tracked_aircraft.items():
            if not self._is_arriving(pos):
                continue

            alt = pos.position.altitude_feet

            # Issue descent instructions to step aircraft down
            if 10000 < alt < 15000 and pos.ground_speed_knots > 280:
                self.issue_instruction(
                    tail, InstructionType.SPEED,
                    speed=250.0,
                )
            elif 5000 < alt <= 10000 and pos.ground_speed_knots > 220:
                self.issue_instruction(
                    tail, InstructionType.SPEED,
                    speed=210.0,
                )

    # ── Handoff management ─────────────────────────────────────────────

    def manage_handoffs(self):
        """Initiate handoffs to tower (descending) or center (climbing)."""
        for tail, pos in list(self.tracked_aircraft.items()):
            if tail in self.handed_off:
                continue
            # Only manage handoffs for aircraft formally acquired via handoff
            if tail not in self.acquired_aircraft:
                continue

            alt = pos.position.altitude_feet

            # Departing aircraft climbing above center handoff altitude → hand to center
            if self._is_departing(pos) and alt >= self.CENTER_HANDOFF_ALT:
                self._initiate_handoff_to_center(tail, pos)
                self._unregister_tracking(tail)
                self.handed_off.add(tail)

            # Arriving aircraft descended below tower handoff altitude → hand to tower
            elif self._is_arriving(pos) and alt <= self.TOWER_HANDOFF_ALT:
                self._initiate_handoff_to_tower(tail, pos)
                self._unregister_tracking(tail)
                self.handed_off.add(tail)

    def _initiate_handoff_to_center(self, tail: str, pos: AircraftPosition):
        """Hand departing aircraft off to overlying en-route center."""
        ho = Handoff(
            handoff_id=make_id("HO-"),
            tail_number=tail,
            from_controller_id=self.controller_id,
            to_controller_id=f"CTR-{self.serving_center}",  # deterministic center controller ID
            status=HandoffStatus.INITIATED,
            from_facility_type=FacilityType.TRACON,
            to_facility_type=FacilityType.CENTER,
            sector=self.tracon_id,
            initiated_at=now_ms(),
        )
        self.ho_writer.write(ho)
        log.info("Handoff %s → Center (departing, FL%d)", tail, int(pos.position.altitude_feet) // 100)

    def _initiate_handoff_to_tower(self, tail: str, pos: AircraftPosition):
        """Hand arriving aircraft off to tower."""
        ho = Handoff(
            handoff_id=make_id("HO-"),
            tail_number=tail,
            from_controller_id=self.controller_id,
            to_controller_id=f"TWR-{pos.destination_airport}",  # resolved by tower
            status=HandoffStatus.INITIATED,
            from_facility_type=FacilityType.TRACON,
            to_facility_type=FacilityType.TOWER,
            sector=self.tracon_id,
            initiated_at=now_ms(),
        )
        self.ho_writer.write(ho)
        log.info("Handoff %s → Tower %s (arriving, %.0fft)",
                 tail, pos.destination_airport, pos.position.altitude_feet)

    def process_handoffs(self):
        """Process incoming handoffs (from center or tower)."""
        for sample in self.ho_reader.take_data():
            if sample.to_controller_id == self.controller_id and \
               sample.status == HandoffStatus.INITIATED:
                from_type = ""
                if sample.from_facility_type is not None:
                    from_type = f" ({sample.from_facility_type.name})"
                log.info(
                    "Accepting handoff of %s from %s%s",
                    sample.tail_number, sample.from_controller_id, from_type,
                )
                accept = Handoff(
                    handoff_id=sample.handoff_id,
                    tail_number=sample.tail_number,
                    from_controller_id=sample.from_controller_id,
                    to_controller_id=self.controller_id,
                    status=HandoffStatus.ACCEPTED,
                    from_facility_type=sample.from_facility_type,
                    to_facility_type=FacilityType.TRACON,
                    initiated_at=sample.initiated_at,
                    completed_at=now_ms(),
                )
                self.ho_writer.write(accept)
                self.acquired_aircraft.add(sample.tail_number)
                self._publish_tracking(sample.tail_number)

    # ── AircraftTracking lifecycle ─────────────────────────────────────

    def _publish_facility_status(self):
        """Publish current facility status (heartbeat + workload)."""
        sample = FacilityStatus(
            facility_id=self.tracon_id,
            facility_type=FacilityType.TRACON,
            controller_id=self.controller_id,
            tracked_aircraft_count=len(self.controlling),
            last_updated=now_ms(),
        )
        self.status_writer.write(sample)

    def _publish_tracking(self, tail_number: str):
        """Publish that we are now the controller of record."""
        sample = AircraftTracking(
            tail_number=tail_number,
            controller_id=self.controller_id,
            facility_id=self.tracon_id,
            facility_type=FacilityType.TRACON,
            acquired_at=now_ms(),
        )
        self.tracking_writer.write(sample)
        self.controlling.add(tail_number)
        self._publish_facility_status()
        log.info("Tracking %s — controller of record: %s (%s)",
                 tail_number, self.controller_id, self.tracon_id)

    def _unregister_tracking(self, tail_number: str):
        """Unregister our tracking claim (hand off without disposing)."""
        sample = AircraftTracking(tail_number=tail_number)
        handle = self.tracking_writer.lookup_instance(sample)
        if handle is not None and handle.is_nil is False:
            self.tracking_writer.unregister_instance(handle)
            self.controlling.discard(tail_number)
            self._publish_facility_status()
            log.info("Unregistered tracking for %s", tail_number)
        else:
            log.debug("No tracking instance to unregister for %s", tail_number)

    # ── Instruction helpers ────────────────────────────────────────────

    def issue_instruction(
        self,
        tail_number: str,
        instr_type: InstructionType,
        heading: float | None = None,
        altitude: int | None = None,
        speed: float | None = None,
        clearance: str | None = None,
    ):
        instr = ControllerInstruction(
            instruction_id=make_id("INSTR-"),
            controller_id=self.controller_id,
            tail_number=tail_number,
            instruction_type=instr_type,
            assigned_heading_degrees=heading,
            assigned_altitude_feet=altitude,
            assigned_speed_knots=speed,
            clearance_text=clearance,
            issued_at=now_ms(),
        )
        self.instr_writer.write(instr)
        log.info("Issued %s to %s", instr_type.name, tail_number)

    def process_acknowledgments(self):
        for sample in self.ack_reader.take_data():
            log.info("ACK from %s: %s", sample.tail_number, sample.status.name)

    # ── Main loop ──────────────────────────────────────────────────────

    def run(self, duration_s: float = 120.0):
        """Main TRACON control loop at ~1 Hz."""
        log.info("TRACON %s operational — serving %s",
                 self.tracon_id, ", ".join(self.airport_codes))
        start = time.time()

        while not shutdown_flag and (time.time() - start) < duration_s:
            self.monitor_traffic()
            self.check_separation()
            self.sequence_arrivals()
            self.manage_handoffs()
            self.process_handoffs()
            self.process_acknowledgments()
            self.status_writer.assert_liveliness()
            time.sleep(1.0)

        log.info("TRACON %s shutting down", self.tracon_id)


def main():
    global AIRPORT_COORDS
    parser = argparse.ArgumentParser(description="ATC TRACON Facility")
    parser.add_argument("--config", required=True, help="Path to scenario config JSON")
    parser.add_argument("--qos-file", required=True, help="Path to QoS XML file")
    parser.add_argument("--tracon-id", default="N90", help="TRACON facility ID")
    parser.add_argument("--controller-id", default=None, help="Controller ID")
    parser.add_argument("--airports", nargs="+", default=None, help="Airport codes (default: from config)")
    parser.add_argument("--serving-center", default=None, help="Overlying center (default: from config)")
    parser.add_argument("--duration", type=float, default=120.0, help="Duration in seconds")
    args = parser.parse_args()

    common.QOS_FILE = args.qos_file
    AIRPORT_COORDS = load_airport_coords(args.config)

    cfg = load_tracon_config(args.tracon_id, args.config)
    controller_id = args.controller_id or f"APP-{args.tracon_id}"

    tracon = TraconController(
        tracon_id=args.tracon_id,
        controller_id=controller_id,
        airport_codes=args.airports or cfg.get("airports", []),
        serving_center=args.serving_center if args.serving_center is not None else cfg.get("serving_center", ""),
    )
    tracon.run(duration_s=args.duration)


if __name__ == "__main__":
    main()
