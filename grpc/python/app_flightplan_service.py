# SPDX-FileCopyrightText: 2026 Real-Time Innovations, Inc.
# SPDX-License-Identifier: Apache-2.0
"""
Flight Plan Filing Service (gRPC) — Validates and accepts/rejects flight plans,
then broadcasts accepted plans to all subscribers.

Serves: FlightPlanService (FileFlightPlan, StreamFlightPlans)
"""

import argparse
import threading

import grpc

import air_traffic_types_pb2 as pb
import air_traffic_types_pb2_grpc as pb_grpc
from common import (
    StreamBroadcaster,
    ZeroconfRegistrar,
    create_grpc_server,
    initial_sim_speed,
    install_signal_handlers,
    now_ts,
    serve_stream,
    set_sim_speed,
    start_sim_speed_listener,
    setup_logging,
    shutdown_event,
)

log = setup_logging("flightplan_service")


class FlightPlanServiceServicer(pb_grpc.FlightPlanServiceServicer):
    """gRPC FlightPlanService implementation."""

    def __init__(self):
        self.filed_plans: dict[str, pb.FlightPlan] = {}
        self.plan_bc = StreamBroadcaster(
            key_fn=lambda m: m.flight_plan_id, max_cache=100
        )

    def FileFlightPlan(self, request, context):
        plan = request.plan
        log.info("Filing request: %s (%s -> %s)",
                 plan.flight_plan_id, plan.departure_airport, plan.arrival_airport)

        accepted, message = self._validate_plan(plan)

        if accepted:
            # Update plan status and timestamp
            plan.status = pb.ACTIVE
            plan.last_updated.CopyFrom(now_ts())
            self.filed_plans[plan.flight_plan_id] = plan
            self.plan_bc.publish(plan)
            log.info("Accepted flight plan %s — broadcasting", plan.flight_plan_id)
        else:
            log.warning("Rejected flight plan %s: %s", plan.flight_plan_id, message)

        return pb.FlightPlanResponse(
            flight_plan_id=plan.flight_plan_id,
            accepted=accepted,
            message=message,
            response_timestamp=now_ts(),
        )

    def StreamFlightPlans(self, request, context):
        return serve_stream(self.plan_bc, context)

    def _validate_plan(self, plan: pb.FlightPlan) -> tuple[bool, str]:
        if not plan.tail_number:
            return False, "Missing tail_number"
        if not plan.departure_airport:
            return False, "Missing departure_airport"
        if not plan.arrival_airport:
            return False, "Missing arrival_airport"
        if plan.departure_airport == plan.arrival_airport:
            return False, "Departure and arrival airports must differ"
        if not plan.HasField("scheduled_departure_time"):
            return False, "Invalid scheduled departure time"
        return True, "Flight plan accepted"


def main():
    parser = argparse.ArgumentParser(description="ATC Flight Plan Filing Service (gRPC)")
    parser.add_argument("--config", required=True, help="Path to scenario config JSON")
    parser.add_argument("--port", type=int, default=0, help="gRPC port (0=auto)")
    parser.add_argument("--duration", type=float, default=300.0, help="Duration in seconds")
    args = parser.parse_args()

    install_signal_handlers()
    set_sim_speed(initial_sim_speed(args.config))
    start_sim_speed_listener()

    servicer = FlightPlanServiceServicer()
    server, actual_port = create_grpc_server(args.port)
    pb_grpc.add_FlightPlanServiceServicer_to_server(servicer, server)
    server.start()
    log.info("FlightPlanService gRPC server on port %d", actual_port)

    zc = ZeroconfRegistrar()
    zc.register("fps", "fps", actual_port)

    shutdown_event.wait(timeout=args.duration)
    log.info("FlightPlanService shutting down — processed %d plans", len(servicer.filed_plans))
    zc.close()
    server.stop(grace=2)


if __name__ == "__main__":
    main()
