"""
En-Route Center Application — Manages aircraft in transit between airports.

Each center loads its boundary polygon from the scenario config and uses a
two-layer filtering approach:
  1. DDS Content-Filtered Topic (CFT) with a rectangular bounding box
     (latitude + longitude + altitude) — filters at the infrastructure level.
  2. Application-level point-in-polygon check for precise boundary awareness.

Aircraft are tracked only after an explicit Handoff is accepted.  If an
aircraft appears inside the polygon without having been handed off, the
center publishes an UNAUTHORIZED_ENTRY alert.  When a tracked aircraft
exits the polygon, the center initiates a handoff to the neighboring
center (looked up via polygon containment) or to the arrival TRACON
if the aircraft is descending.

Subscribes to AircraftPosition (CFT by bounding box + altitude), publishes
ControllerInstruction, handles Handoff coordination, and publishes Alert.
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
from common import (
    create_participant,
    create_publisher,
    create_subscriber,
    find_center_for_position,
    load_center_boundaries,
    load_qos_provider,
    load_tracon_for_airport,
    make_id,
    now_ms,
    point_in_polygon,
    polygon_bbox,
    reader_qos,
    setup_logging,
    writer_qos,
)

log = setup_logging("center")

shutdown_flag = False


def signal_handler(_sig, _frame):
    global shutdown_flag
    shutdown_flag = True


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Pad bounding box by this many degrees so CFT captures aircraft
# approaching the boundary (not just inside it).
BBOX_PAD_DEG = 0.5


class EnRouteCenter:
    """Simulates an en-route ATC center managing a sector with geographic awareness."""

    def __init__(
        self,
        center_id: str,
        controller_id: str,
        boundary: list[list[float]],
        all_boundaries: dict[str, list[list[float]]],
        tracon_for_airport: dict[str, str],
        min_altitude_ft: int = 18000,
        max_altitude_ft: int = 60000,
    ):
        self.center_id = center_id
        self.controller_id = controller_id
        self.min_alt = min_altitude_ft
        self.max_alt = max_altitude_ft
        self.boundary = boundary
        self.all_boundaries = all_boundaries
        self.tracon_for_airport = tracon_for_airport

        # Aircraft we are responsible for (accepted handoff)
        self.controlled_aircraft: dict[str, AircraftPosition] = {}
        # Aircraft we've already handed off (avoid re-triggering)
        self.handed_off: set[str] = set()
        # Aircraft we've already alerted about (avoid spam)
        self.alerted_uncoordinated: set[str] = set()

        # Compute bounding box for the CFT geographic filter
        min_lat, max_lat, min_lon, max_lon = polygon_bbox(boundary)
        self.bbox = (
            min_lat - BBOX_PAD_DEG,
            max_lat + BBOX_PAD_DEG,
            min_lon - BBOX_PAD_DEG,
            max_lon + BBOX_PAD_DEG,
        )

        # DDS setup
        self.qos_provider = load_qos_provider()
        dp_partitions = [
            f"OPS/ENROUTE/{center_id}",
            "OPS/ENROUTE/*",   # cross-center handoffs
            "OPS/FPS/*",
        ]
        self.participant = create_participant(self.qos_provider, dp_partitions=dp_partitions)

        self.publisher = create_publisher(self.participant)
        self.subscriber = create_subscriber(self.participant)

        # AircraftPosition reader — CFT by bounding box + altitude band
        pos_topic = dds.Topic(self.participant, "AircraftPosition", AircraftPosition)
        self.pos_cft = dds.ContentFilteredTopic(
            pos_topic,
            f"SectorTraffic_{center_id}",
            dds.Filter(
                "position.altitude_feet >= %0 AND position.altitude_feet < %1 "
                "AND position.latitude >= %2 AND position.latitude <= %3 "
                "AND position.longitude >= %4 AND position.longitude <= %5",
                [
                    str(min_altitude_ft),
                    str(max_altitude_ft),
                    str(self.bbox[0]),
                    str(self.bbox[1]),
                    str(self.bbox[2]),
                    str(self.bbox[3]),
                ],
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
            writer_qos(self.qos_provider, "AlertBroadcastProfile"),
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

        log.info(
            "Center %s (%s) initialized — FL%d-FL%d, boundary=%d vertices, "
            "bbox=[%.1f,%.1f]×[%.1f,%.1f]",
            center_id, controller_id,
            min_altitude_ft // 100, max_altitude_ft // 100,
            len(boundary),
            self.bbox[0], self.bbox[1], self.bbox[2], self.bbox[3],
        )

    # ── Traffic monitoring ─────────────────────────────────────────────

    def monitor_traffic(self):
        """Read positions from CFT, classify as controlled / exiting / uncoordinated."""
        for sample in self.pos_reader.take_data():
            tail = sample.tail_number
            inside = point_in_polygon(
                sample.position.latitude, sample.position.longitude, self.boundary
            )

            if tail in self.controlled_aircraft:
                if inside:
                    # Normal: update position for our controlled aircraft
                    self.controlled_aircraft[tail] = sample
                else:
                    # Aircraft left our polygon → initiate handoff
                    if tail not in self.handed_off:
                        self._handoff_exiting_aircraft(sample)
            elif inside and tail not in self.handed_off:
                # Aircraft in our polygon but not handed off to us → alert
                if tail not in self.alerted_uncoordinated:
                    self._alert_uncoordinated(sample)

        if self.controlled_aircraft:
            log.info(
                "Center %s: controlling %d aircraft",
                self.center_id, len(self.controlled_aircraft),
            )

    # ── Separation checking ────────────────────────────────────────────

    def check_separation(self):
        """Check for separation violations between controlled aircraft pairs."""
        positions = list(self.controlled_aircraft.values())
        for i, a in enumerate(positions):
            for b in positions[i + 1:]:
                lat_diff = abs(a.position.latitude - b.position.latitude)
                lon_diff = abs(a.position.longitude - b.position.longitude)
                alt_diff = abs(a.position.altitude_feet - b.position.altitude_feet)

                # Simplified separation check (5nm lateral ≈ 0.083°, 1000ft vertical)
                if lat_diff < 0.083 and lon_diff < 0.083 and alt_diff < 1000:
                    log.warning(
                        "SEPARATION VIOLATION: %s and %s in %s",
                        a.tail_number, b.tail_number, self.center_id,
                    )
                    alert = Alert(
                        alert_id=make_id("ALERT-"),
                        alert_type=AlertType.TRAFFIC_CONFLICT,
                        severity=AlertSeverity.CRITICAL,
                        involved_aircraft=[a.tail_number, b.tail_number],
                        message=(
                            f"Separation violation between {a.tail_number} "
                            f"and {b.tail_number} in {self.center_id}"
                        ),
                        timestamp=now_ms(),
                    )
                    self.alert_writer.write(alert)

    # ── Handoff: exiting aircraft ──────────────────────────────────────

    def _handoff_exiting_aircraft(self, pos: AircraftPosition):
        """Initiate handoff for an aircraft leaving our polygon."""
        tail = pos.tail_number

        # If descending toward destination, hand to arrival TRACON
        if pos.position.altitude_feet < self.min_alt + 2000 and pos.vertical_speed_fpm < -500:
            tracon_id = self.tracon_for_airport.get(pos.destination_airport)
            if tracon_id:
                to_id = f"APP-{tracon_id}"
                to_type = FacilityType.TRACON
                log.info(
                    "Handoff %s → TRACON %s (descending, FL%d)",
                    tail, tracon_id, int(pos.position.altitude_feet) // 100,
                )
            else:
                log.warning("No TRACON for %s, skipping handoff of %s", pos.destination_airport, tail)
                return
        else:
            # Find neighboring center by position
            neighbor = find_center_for_position(
                pos.position.latitude, pos.position.longitude,
                self.all_boundaries, exclude=self.center_id,
            )
            if neighbor:
                to_id = f"CTR-{neighbor}"
                to_type = FacilityType.CENTER
                log.info(
                    "Handoff %s → Center %s (exiting %s boundary)",
                    tail, neighbor, self.center_id,
                )
            else:
                log.warning(
                    "Aircraft %s left %s but no neighboring center found at (%.2f, %.2f)",
                    tail, self.center_id, pos.position.latitude, pos.position.longitude,
                )
                return

        ho = Handoff(
            handoff_id=make_id("HO-"),
            tail_number=tail,
            from_controller_id=self.controller_id,
            to_controller_id=to_id,
            status=HandoffStatus.INITIATED,
            from_facility_type=FacilityType.CENTER,
            to_facility_type=to_type,
            sector=self.center_id,
            initiated_at=now_ms(),
        )
        self.ho_writer.write(ho)
        self._unregister_tracking(tail)
        self.handed_off.add(tail)
        self.controlled_aircraft.pop(tail, None)

    # ── Handoff: accept incoming ───────────────────────────────────────

    def process_handoffs(self):
        """Accept incoming handoffs from TRACON or neighboring center."""
        for sample in self.ho_reader.take_data():
            if sample.to_controller_id == self.controller_id and \
               sample.status == HandoffStatus.INITIATED:
                from_type = ""
                if sample.from_facility_type is not None:
                    from_type = f" ({sample.from_facility_type.name})"
                log.info(
                    "Accepting handoff of %s from %s%s into %s",
                    sample.tail_number, sample.from_controller_id,
                    from_type, self.center_id,
                )
                accept = Handoff(
                    handoff_id=sample.handoff_id,
                    tail_number=sample.tail_number,
                    from_controller_id=sample.from_controller_id,
                    to_controller_id=self.controller_id,
                    status=HandoffStatus.ACCEPTED,
                    from_facility_type=sample.from_facility_type,
                    to_facility_type=FacilityType.CENTER,
                    initiated_at=sample.initiated_at,
                    completed_at=now_ms(),
                )
                self.ho_writer.write(accept)
                # Begin tracking this aircraft
                self.controlled_aircraft[sample.tail_number] = None
                self.alerted_uncoordinated.discard(sample.tail_number)
                self._publish_tracking(sample.tail_number)

    # ── AircraftTracking lifecycle ─────────────────────────────────────

    def _publish_tracking(self, tail_number: str):
        """Publish that we are now the controller of record for this aircraft."""
        sample = AircraftTracking(
            tail_number=tail_number,
            controller_id=self.controller_id,
            facility_id=self.center_id,
            facility_type=FacilityType.CENTER,
            acquired_at=now_ms(),
        )
        self.tracking_writer.write(sample)
        log.info("Tracking %s — controller of record: %s (%s)",
                 tail_number, self.controller_id, self.center_id)

    def _unregister_tracking(self, tail_number: str):
        """Unregister our tracking claim (hand off without disposing)."""
        sample = AircraftTracking(tail_number=tail_number)
        handle = self.tracking_writer.lookup_instance(sample)
        if handle is not None and handle.is_nil is False:
            self.tracking_writer.unregister_instance(handle)
            log.info("Unregistered tracking for %s", tail_number)
        else:
            log.debug("No tracking instance to unregister for %s", tail_number)

    # ── Uncoordinated traffic alert ────────────────────────────────────

    def _alert_uncoordinated(self, pos: AircraftPosition):
        """Publish alert for aircraft in our polygon without a handoff."""
        log.warning(
            "UNCOORDINATED: %s inside %s at (%.2f, %.2f) FL%d — no handoff received",
            pos.tail_number, self.center_id,
            pos.position.latitude, pos.position.longitude,
            int(pos.position.altitude_feet) // 100,
        )
        alert = Alert(
            alert_id=make_id("ALERT-"),
            alert_type=AlertType.UNAUTHORIZED_ENTRY,
            severity=AlertSeverity.WARNING,
            involved_aircraft=[pos.tail_number],
            message=(
                f"Uncoordinated traffic: {pos.tail_number} in {self.center_id} "
                f"at FL{int(pos.position.altitude_feet) // 100} — no handoff"
            ),
            timestamp=now_ms(),
        )
        self.alert_writer.write(alert)
        self.alerted_uncoordinated.add(pos.tail_number)

    # ── Misc ───────────────────────────────────────────────────────────

    def process_acknowledgments(self):
        for sample in self.ack_reader.take_data():
            log.info("ACK from %s: %s", sample.tail_number, sample.status.name)

    def initiate_handoff(
        self,
        tail_number: str,
        to_controller_id: str,
        from_type: FacilityType = FacilityType.CENTER,
        to_type: FacilityType | None = None,
    ):
        """Hand off an aircraft to another controller."""
        ho = Handoff(
            handoff_id=make_id("HO-"),
            tail_number=tail_number,
            from_controller_id=self.controller_id,
            to_controller_id=to_controller_id,
            status=HandoffStatus.INITIATED,
            from_facility_type=from_type,
            to_facility_type=to_type,
            sector=self.center_id,
            initiated_at=now_ms(),
        )
        self.ho_writer.write(ho)
        log.info("Initiated handoff of %s to %s", tail_number, to_controller_id)

    def run(self, duration_s: float = 120.0):
        """Main center control loop at ~1 Hz."""
        log.info("En-route center %s operational", self.center_id)
        start = time.time()

        while not shutdown_flag and (time.time() - start) < duration_s:
            self.process_handoffs()
            self.monitor_traffic()
            self.check_separation()
            self.process_acknowledgments()
            time.sleep(1.0)

        log.info("Center %s shutting down — controlled %d, handed off %d, alerts %d",
                 self.center_id, len(self.controlled_aircraft),
                 len(self.handed_off), len(self.alerted_uncoordinated))


def main():
    parser = argparse.ArgumentParser(description="ATC En-Route Center")
    parser.add_argument("--center-id", default="ZNY", help="Center ID")
    parser.add_argument("--controller-id", default=None, help="Controller ID (default: CTR-<center-id>)")
    parser.add_argument("--min-alt", type=int, default=18000, help="Min altitude (ft)")
    parser.add_argument("--max-alt", type=int, default=60000, help="Max altitude (ft)")
    parser.add_argument("--duration", type=float, default=120.0, help="Duration in seconds")
    args = parser.parse_args()

    # Deterministic controller ID so other facilities can address us
    controller_id = args.controller_id or f"CTR-{args.center_id}"

    # Load boundary data from scenario config
    all_boundaries = load_center_boundaries()
    if args.center_id not in all_boundaries:
        log.error("Center %s not found in scenario config", args.center_id)
        sys.exit(1)

    center = EnRouteCenter(
        center_id=args.center_id,
        controller_id=controller_id,
        boundary=all_boundaries[args.center_id],
        all_boundaries=all_boundaries,
        tracon_for_airport=load_tracon_for_airport(),
        min_altitude_ft=args.min_alt,
        max_altitude_ft=args.max_alt,
    )
    center.run(duration_s=args.duration)


if __name__ == "__main__":
    main()
