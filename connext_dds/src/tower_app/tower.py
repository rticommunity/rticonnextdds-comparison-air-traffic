"""
Control Tower Application — Airport tower simulator.

Subscribes to AircraftPosition (CFT for local traffic), publishes
ControllerInstruction and RunwayStatus, subscribes to PilotAcknowledgment,
handles Handoff, and publishes Alert.
"""

import argparse
import os
import signal
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import rti.connextdds as dds
from air_traffic import NationalAirTrafficControl as ATC

AircraftPosition = ATC.AircraftPosition
AircraftTracking = ATC.AircraftTracking
Alert = ATC.Alert
AlertSeverity = ATC.AlertSeverity
AlertType = ATC.AlertType
ControllerInstruction = ATC.ControllerInstruction
FacilityType = ATC.FacilityType
FlightPlan = ATC.FlightPlan
Handoff = ATC.Handoff
HandoffStatus = ATC.HandoffStatus
InstructionType = ATC.InstructionType
PilotAcknowledgment = ATC.PilotAcknowledgment
RunwayOperationalStatus = ATC.RunwayOperationalStatus
RunwayStatus = ATC.RunwayStatus
WeatherReport = ATC.WeatherReport
from common import (
    create_participant,
    create_publisher,
    create_subscriber,
    load_qos_provider,
    make_id,
    now_ms,
    reader_qos,
    setup_logging,
    writer_qos,
)

log = setup_logging("tower")

shutdown_flag = False


def signal_handler(_sig, _frame):
    global shutdown_flag
    shutdown_flag = True


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


class TowerController:
    """Simulates a control tower at a single airport."""

    def __init__(self, airport_code: str, controller_id: str, serving_tracon: str = ""):
        self.airport_code = airport_code
        self.controller_id = controller_id
        self.serving_tracon = serving_tracon
        self.tracked_aircraft: dict[str, AircraftPosition] = {}
        self.handed_off: set[str] = set()  # tail numbers already handed to TRACON

        # DDS setup
        self.qos_provider = load_qos_provider()
        dp_partitions = [f"OPS/AIRPORT/{airport_code}", "OPS/FPS/*"]
        if serving_tracon:
            dp_partitions.append(f"OPS/TERMINAL/{serving_tracon}")
        self.participant = create_participant(self.qos_provider, dp_partitions=dp_partitions)

        self.publisher = create_publisher(self.participant)
        self.subscriber = create_subscriber(self.participant)

        # AircraftPosition reader (CFT: local traffic only)
        pos_topic = dds.Topic(self.participant, "AircraftPosition", AircraftPosition)
        self.pos_cft = dds.ContentFilteredTopic(
            pos_topic,
            f"LocalTraffic_{airport_code}",
            dds.Filter(
                f"origin_airport = '{airport_code}' OR destination_airport = '{airport_code}'"
            ),
        )
        self.pos_reader = dds.DataReader(
            self.subscriber, self.pos_cft,
            reader_qos(self.qos_provider, "PositionReportingProfile"),
        )

        # ControllerInstruction writer
        instr_topic = dds.Topic(self.participant, "ControllerInstruction", ControllerInstruction)
        self.instr_writer = dds.DataWriter(
            self.publisher, instr_topic,
            writer_qos(self.qos_provider, "ReliableCommandProfile"),
        )

        # PilotAcknowledgment reader
        ack_topic = dds.Topic(self.participant, "PilotAcknowledgment", PilotAcknowledgment)
        self.ack_reader = dds.DataReader(
            self.subscriber, ack_topic,
            reader_qos(self.qos_provider, "ReliableCommandProfile"),
        )

        # RunwayStatus writer
        rwy_topic = dds.Topic(self.participant, "RunwayStatus", RunwayStatus)
        self.rwy_writer = dds.DataWriter(
            self.publisher, rwy_topic,
            writer_qos(self.qos_provider, "StateDataProfile"),
        )

        # Handoff writer + reader (CFT on controller_id)
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
            writer_qos(self.qos_provider, "AlertBroadcastProfile"),
        )

        # Weather reader (local)
        wx_topic = dds.Topic(self.participant, "WeatherReport", WeatherReport)
        wx_cft = dds.ContentFilteredTopic(
            wx_topic,
            f"LocalWeather_{airport_code}",
            dds.Filter(f"airport_code = '{airport_code}'"),
        )
        self.wx_reader = dds.DataReader(
            self.subscriber, wx_cft,
            reader_qos(self.qos_provider, "StateDataProfile"),
        )

        # FlightPlan reader
        fp_topic = dds.Topic(self.participant, "FlightPlan", FlightPlan)
        self.fp_reader = dds.DataReader(
            self.subscriber, fp_topic,
            reader_qos(self.qos_provider, "StateDataProfile"),
        )

        # AircraftTracking writer — publishes current controller of record
        tracking_topic = dds.Topic(self.participant, "AircraftTracking", AircraftTracking)
        self.tracking_writer = dds.DataWriter(
            self.publisher, tracking_topic,
            writer_qos(self.qos_provider, "StateDataProfile"),
        )

        # Publish initial runway status
        self._publish_runway_status("09L", RunwayOperationalStatus.OPEN)
        self._publish_runway_status("27R", RunwayOperationalStatus.OPEN)

        log.info("Tower %s at %s initialized", controller_id, airport_code)

    def _publish_runway_status(self, runway_id: str, status: RunwayOperationalStatus):
        sample = RunwayStatus(
            airport_code=self.airport_code,
            runway_id=runway_id,
            status=status,
            timestamp=now_ms(),
        )
        self.rwy_writer.write(sample)
        log.info("Runway %s/%s: %s", self.airport_code, runway_id, status.name)

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

    def monitor_traffic(self):
        """Read aircraft positions and track local traffic."""
        for sample in self.pos_reader.take_data():
            tail = sample.tail_number
            is_new = tail not in self.tracked_aircraft
            self.tracked_aircraft[tail] = sample
            # First time seeing a departing aircraft → we are the initial controller
            if is_new and sample.origin_airport == self.airport_code and tail not in self.handed_off:
                self._publish_tracking(tail)

        if self.tracked_aircraft:
            log.info("Tracking %d aircraft", len(self.tracked_aircraft))

        # Issue approach clearances to arriving aircraft below 3000 ft
        for ac_id, pos in self.tracked_aircraft.items():
            if (pos.flight_phase.value >= 5  # DESCENT or later
                    and pos.destination_airport == self.airport_code
                    and pos.assigned_runway is None):
                self.issue_instruction(
                    ac_id,
                    InstructionType.CLEARANCE,
                    clearance=f"Cleared ILS approach runway 09L at {self.airport_code}",
                )

        # Hand departing aircraft to TRACON once above 1500 ft
        for ac_id, pos in self.tracked_aircraft.items():
            if ac_id in self.handed_off:
                continue
            if (pos.origin_airport == self.airport_code
                    and pos.position.altitude_feet >= 1500
                    and pos.vertical_speed_fpm > 0):
                tracon_id = f"APP-{self.serving_tracon}" if self.serving_tracon else f"APP-{self.airport_code}"
                ho = Handoff(
                    handoff_id=make_id("HO-"),
                    tail_number=ac_id,
                    from_controller_id=self.controller_id,
                    to_controller_id=tracon_id,
                    status=HandoffStatus.INITIATED,
                    from_facility_type=FacilityType.TOWER,
                    to_facility_type=FacilityType.TRACON,
                    sector=self.airport_code,
                    initiated_at=now_ms(),
                )
                self.ho_writer.write(ho)
                self._unregister_tracking(ac_id)
                self.handed_off.add(ac_id)
                log.info("Handoff %s → TRACON (departing, %.0fft)", ac_id, pos.position.altitude_feet)

    def process_acknowledgments(self):
        """Read pilot acknowledgments."""
        for sample in self.ack_reader.take_data():
            log.info(
                "ACK from %s: %s for instruction %s",
                sample.tail_number,
                sample.status.name,
                sample.instruction_id,
            )

    def process_handoffs(self):
        """Process incoming handoff requests."""
        for sample in self.ho_reader.take_data():
            if sample.to_controller_id == self.controller_id and sample.status == HandoffStatus.INITIATED:
                from_type = ""
                if sample.from_facility_type is not None:
                    from_type = f" ({sample.from_facility_type.name})"
                log.info(
                    "Accepting handoff of %s from %s%s",
                    sample.tail_number,
                    sample.from_controller_id,
                    from_type,
                )
                accept = Handoff(
                    handoff_id=sample.handoff_id,
                    tail_number=sample.tail_number,
                    from_controller_id=sample.from_controller_id,
                    to_controller_id=self.controller_id,
                    status=HandoffStatus.ACCEPTED,
                    from_facility_type=sample.from_facility_type,
                    to_facility_type=FacilityType.TOWER,
                    initiated_at=sample.initiated_at,
                    completed_at=now_ms(),
                )
                self.ho_writer.write(accept)
                self._publish_tracking(sample.tail_number)

    # ── AircraftTracking lifecycle ─────────────────────────────────────

    def _publish_tracking(self, tail_number: str):
        """Publish that we are now the controller of record."""
        sample = AircraftTracking(
            tail_number=tail_number,
            controller_id=self.controller_id,
            facility_id=self.airport_code,
            facility_type=FacilityType.TOWER,
            acquired_at=now_ms(),
        )
        self.tracking_writer.write(sample)
        log.info("Tracking %s — controller of record: %s (%s)",
                 tail_number, self.controller_id, self.airport_code)

    def _unregister_tracking(self, tail_number: str):
        """Unregister our tracking claim (hand off without disposing)."""
        sample = AircraftTracking(tail_number=tail_number)
        handle = self.tracking_writer.lookup_instance(sample)
        if handle is not None and handle.is_nil is False:
            self.tracking_writer.unregister_instance(handle)
            log.info("Unregistered tracking for %s", tail_number)
        else:
            log.debug("No tracking instance to unregister for %s", tail_number)

    def check_weather(self):
        """Read local weather."""
        for sample in self.wx_reader.take_data():
            log.info(
                "Weather: %s, vis=%.0fm, wind=%d@%.0fkt",
                sample.conditions.name,
                sample.visibility_meters,
                sample.wind.direction_degrees,
                sample.wind.speed_knots,
            )

    def run(self, duration_s: float = 120.0):
        """Main tower control loop at ~1 Hz."""
        log.info("Tower %s operational", self.airport_code)
        start = time.time()

        while not shutdown_flag and (time.time() - start) < duration_s:
            self.monitor_traffic()
            self.process_acknowledgments()
            self.process_handoffs()
            self.check_weather()
            time.sleep(1.0)

        log.info("Tower %s shutting down", self.airport_code)


def main():
    parser = argparse.ArgumentParser(description="ATC Control Tower")
    parser.add_argument("--airport-code", default="KJFK", help="Airport ICAO code")
    parser.add_argument("--controller-id", default=None, help="Controller ID")
    parser.add_argument("--serving-tracon", default="", help="Serving TRACON facility ID")
    parser.add_argument("--duration", type=float, default=120.0, help="Duration in seconds")
    args = parser.parse_args()

    controller_id = args.controller_id or f"TWR-{args.airport_code}"

    tower = TowerController(
        airport_code=args.airport_code,
        controller_id=controller_id,
        serving_tracon=args.serving_tracon,
    )
    tower.run(duration_s=args.duration)


if __name__ == "__main__":
    main()
