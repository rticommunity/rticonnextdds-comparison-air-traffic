"""
En-Route Center Application — Manages aircraft in transit between airports.

Subscribes to AircraftPosition (CFT by altitude band), publishes
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
    load_qos_provider,
    make_id,
    now_ms,
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


class EnRouteCenter:
    """Simulates an en-route ATC center managing a sector."""

    def __init__(
        self,
        center_id: str,
        controller_id: str,
        min_altitude_ft: int = 18000,
        max_altitude_ft: int = 60000,
    ):
        self.center_id = center_id
        self.controller_id = controller_id
        self.min_alt = min_altitude_ft
        self.max_alt = max_altitude_ft
        self.tracked_aircraft: dict[str, AircraftPosition] = {}
        self.handed_off: set[str] = set()  # tail numbers already handed off

        # DDS setup
        self.qos_provider = load_qos_provider()
        dp_partitions = [f"OPS/ENROUTE/{center_id}", "OPS/FPS/*"]
        self.participant = create_participant(self.qos_provider, dp_partitions=dp_partitions)

        self.publisher = create_publisher(self.participant)
        self.subscriber = create_subscriber(self.participant)

        # AircraftPosition reader (CFT by altitude band)
        pos_topic = dds.Topic(self.participant, "AircraftPosition", AircraftPosition)
        self.pos_cft = dds.ContentFilteredTopic(
            pos_topic,
            f"SectorTraffic_{center_id}",
            dds.Filter(
                "position.altitude_feet >= %0 AND position.altitude_feet < %1",
                [str(min_altitude_ft), str(max_altitude_ft)],
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

        log.info(
            "Center %s (%s) initialized: FL%d-FL%d",
            center_id, controller_id,
            min_altitude_ft // 100, max_altitude_ft // 100,
        )

    def monitor_traffic(self):
        """Read and track aircraft in sector."""
        for sample in self.pos_reader.take_data():
            self.tracked_aircraft[sample.tail_number] = sample

        if self.tracked_aircraft:
            log.info(
                "Tracking %d aircraft in sector (FL%d-FL%d)",
                len(self.tracked_aircraft),
                self.min_alt // 100,
                self.max_alt // 100,
            )

    def check_separation(self):
        """Check for separation violations between aircraft pairs."""
        positions = list(self.tracked_aircraft.values())
        for i, a in enumerate(positions):
            for b in positions[i + 1:]:
                lat_diff = abs(a.position.latitude - b.position.latitude)
                lon_diff = abs(a.position.longitude - b.position.longitude)
                alt_diff = abs(a.position.altitude_feet - b.position.altitude_feet)

                # Simplified separation check (5nm lateral ≈ 0.083°, 1000ft vertical)
                if lat_diff < 0.083 and lon_diff < 0.083 and alt_diff < 1000:
                    log.warning(
                        "SEPARATION VIOLATION: %s and %s",
                        a.tail_number, b.tail_number,
                    )
                    alert = Alert(
                        alert_id=make_id("ALERT-"),
                        alert_type=AlertType.TRAFFIC_CONFLICT,
                        severity=AlertSeverity.CRITICAL,
                        involved_aircraft=[a.tail_number, b.tail_number],
                        message=f"Separation violation between {a.tail_number} and {b.tail_number}",
                        timestamp=now_ms(),
                    )
                    self.alert_writer.write(alert)

    def manage_handoffs_to_tracon(self):
        """When an aircraft descends near our min altitude, hand to TRACON."""
        for tail, pos in list(self.tracked_aircraft.items()):
            if tail in self.handed_off:
                continue
            # Aircraft descending below 19000 ft → hand off to TRACON
            if pos.position.altitude_feet < self.min_alt + 1000 and pos.vertical_speed_fpm < -500:
                tracon_id = f"APP-{pos.destination_airport}"
                self.initiate_handoff(
                    tail, tracon_id,
                    from_type=FacilityType.CENTER,
                    to_type=FacilityType.TRACON,
                )
                self.handed_off.add(tail)

    def process_acknowledgments(self):
        for sample in self.ack_reader.take_data():
            log.info("ACK from %s: %s", sample.tail_number, sample.status.name)

    def process_handoffs(self):
        for sample in self.ho_reader.take_data():
            if sample.to_controller_id == self.controller_id and sample.status == HandoffStatus.INITIATED:
                from_type = ""
                if sample.from_facility_type is not None:
                    from_type = f" ({sample.from_facility_type.name})"
                log.info("Accepting handoff of %s from %s%s",
                         sample.tail_number, sample.from_controller_id, from_type)
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
            self.monitor_traffic()
            self.check_separation()
            self.manage_handoffs_to_tracon()
            self.process_acknowledgments()
            self.process_handoffs()
            time.sleep(1.0)

        log.info("Center %s shutting down", self.center_id)


def main():
    parser = argparse.ArgumentParser(description="ATC En-Route Center")
    parser.add_argument("--center-id", default="ZNY", help="Center ID")
    parser.add_argument("--controller-id", default=None, help="Controller ID")
    parser.add_argument("--min-alt", type=int, default=18000, help="Min altitude (ft)")
    parser.add_argument("--max-alt", type=int, default=60000, help="Max altitude (ft)")
    parser.add_argument("--duration", type=float, default=120.0, help="Duration in seconds")
    args = parser.parse_args()

    controller_id = args.controller_id or make_id(f"CTR-{args.center_id}-")

    center = EnRouteCenter(
        center_id=args.center_id,
        controller_id=controller_id,
        min_altitude_ft=args.min_alt,
        max_altitude_ft=args.max_alt,
    )
    center.run(duration_s=args.duration)


if __name__ == "__main__":
    main()
