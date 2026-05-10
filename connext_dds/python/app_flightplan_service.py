"""
Flight Plan Filing Service — Central replier that validates and accepts/rejects
flight plans, then publishes accepted plans on the FlightPlan topic.
"""

import argparse
import os
import signal
import sys
import time


import rti.connextdds as dds
from rti.rpc import Replier
from air_traffic_types import NationalAirTrafficControl as ATC

FlightPlan = ATC.FlightPlan
FlightPlanRequest = ATC.FlightPlanRequest
FlightPlanResponse = ATC.FlightPlanResponse
FlightPlanStatus = ATC.FlightPlanStatus
from common import (
    create_participant,
    create_publisher,
    load_qos_provider,
    now_ms,
    reader_qos,
    setup_logging,
    writer_qos,
)
import common

log = setup_logging("flightplan_service")

shutdown_flag = False


def signal_handler(_sig, _frame):
    global shutdown_flag
    shutdown_flag = True


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


class FlightPlanService:
    """Validates flight plan requests and publishes accepted plans."""

    def __init__(self, service_name: str = "main"):
        self.filed_plans: dict[str, FlightPlan] = {}

        # DDS setup
        self.qos_provider = load_qos_provider()
        dp_partitions = [f"OPS/FPS/{service_name}"]
        self.participant = create_participant(
            self.qos_provider,
            dp_partitions=dp_partitions,
            participant_name=f"FlightPlanService_{service_name}",
            app_name="ATC_FlightPlanService",
        )

        self.publisher = create_publisher(self.participant)

        # FlightPlan writer (publishes accepted plans)
        fp_topic = dds.Topic(self.participant, "FlightPlan", FlightPlan)
        self.fp_writer = dds.DataWriter(
            self.publisher, fp_topic,
            writer_qos(self.qos_provider, "FlightPlanProfile"),
        )

        # Flight plan filing replier
        self.replier = Replier(
            request_type=FlightPlanRequest,
            reply_type=FlightPlanResponse,
            participant=self.participant,
            service_name="FlightPlanFilingService",
            datawriter_qos=writer_qos(self.qos_provider, "FlightPlanRequestReplyProfile"),
            datareader_qos=reader_qos(self.qos_provider, "FlightPlanRequestReplyProfile"),
        )

        log.info("FlightPlanFilingService initialized")

    def validate_plan(self, plan: FlightPlan) -> tuple[bool, str]:
        """Basic validation of a flight plan."""
        if not plan.tail_number:
            return False, "Missing tail_number"
        if not plan.departure_airport:
            return False, "Missing departure_airport"
        if not plan.arrival_airport:
            return False, "Missing arrival_airport"
        if plan.departure_airport == plan.arrival_airport:
            return False, "Departure and arrival airports must differ"
        if plan.scheduled_departure_time <= 0:
            return False, "Invalid scheduled departure time"
        return True, "Flight plan accepted"

    def handle_requests(self):
        """Process incoming flight plan filing requests."""
        try:
            requests = self.replier.receive_requests(dds.Duration(seconds=0))
        except dds.TimeoutError:
            return
        for request, info in requests:
            if not info.valid:
                continue

            plan = request.plan
            log.info("Filing request: %s (%s -> %s)",
                     plan.flight_plan_id, plan.departure_airport, plan.arrival_airport)

            accepted, message = self.validate_plan(plan)

            if accepted:
                plan.status = FlightPlanStatus.ACTIVE
                plan.last_updated = now_ms()
                self.filed_plans[plan.flight_plan_id] = plan

                # Publish the accepted flight plan
                self.fp_writer.write(plan)
                log.info("Accepted flight plan %s — publishing", plan.flight_plan_id)
            else:
                log.warning("Rejected flight plan %s: %s", plan.flight_plan_id, message)

            reply = FlightPlanResponse(
                flight_plan_id=plan.flight_plan_id,
                accepted=accepted,
                message=message,
                response_timestamp=now_ms(),
            )
            self.replier.send_reply(reply, info)

    def run(self, duration_s: float = 300.0):
        """Main service loop."""
        log.info("FlightPlanFilingService operational — %d plans on record",
                 len(self.filed_plans))
        start = time.time()

        while not shutdown_flag and (time.time() - start) < duration_s:
            self.handle_requests()
            time.sleep(0.2)

        log.info("FlightPlanFilingService shutting down — processed %d plans",
                 len(self.filed_plans))


def main():
    parser = argparse.ArgumentParser(description="ATC Flight Plan Filing Service")
    parser.add_argument("--config", required=True, help="Path to scenario config JSON")
    parser.add_argument("--qos-file", required=True, help="Path to QoS XML file")
    parser.add_argument("--service-name", default="main", help="FPS instance name (partition: OPS/FPS/<name>)")
    parser.add_argument("--duration", type=float, default=300.0, help="Duration in seconds")
    args = parser.parse_args()

    common.QOS_FILE = args.qos_file

    svc = FlightPlanService(service_name=args.service_name)
    svc.run(duration_s=args.duration)


if __name__ == "__main__":
    main()
