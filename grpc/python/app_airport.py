# SPDX-FileCopyrightText: 2026 Real-Time Innovations, Inc.
# SPDX-License-Identifier: Apache-2.0
"""
Airport Infrastructure Application (gRPC) — Publishes weather reports, runway
status, and handles gate assignment requests.

Serves: AirportService (StreamWeatherReports, StreamRunwayStatus, RequestGate)
"""

import argparse
import random
import time

import grpc

import air_traffic_types_pb2 as pb
import air_traffic_types_pb2_grpc as pb_grpc
from common import (
    StreamBroadcaster,
    SubscriberQueue,
    ZeroconfRegistrar,
    create_grpc_server,
    get_sim_speed,
    initial_sim_speed,
    install_signal_handlers,
    load_airport_config,
    make_id,
    now_ts,
    serve_stream,
    set_sim_speed,
    setup_logging,
    shutdown_event,
)

log = setup_logging("airport")


class AirportServiceServicer(pb_grpc.AirportServiceServicer):
    """gRPC AirportService implementation."""

    def __init__(self, airport_code: str, runways: list[str],
                 weather_interval_s: float = 1800.0, config_path: str = ""):
        self.airport_code = airport_code
        self.runways = runways
        self.config_path = config_path
        self.weather_interval_s = weather_interval_s

        # Gate state
        self.GATE_NAMES = [f"{t}{n}" for t in ("A", "B", "C") for n in range(1, 11)]
        self.assigned_gates: dict[str, str] = {}

        # Broadcasters for streaming RPCs (with late-join replay)
        self.weather_bc = StreamBroadcaster(
            key_fn=lambda m: m.airport_code, max_cache=10
        )
        self.runway_bc = StreamBroadcaster(
            key_fn=lambda m: f"{m.airport_code}/{m.runway_id}", max_cache=50
        )

    # ── StreamWeatherReports ──────────────────────────────────────────

    def StreamWeatherReports(self, request, context):
        def filter_fn(msg):
            if request.airport_code and msg.airport_code != request.airport_code:
                return False
            return True
        return serve_stream(self.weather_bc, context, filter_fn=filter_fn)

    # ── StreamRunwayStatus ────────────────────────────────────────────

    def StreamRunwayStatus(self, request, context):
        def filter_fn(msg):
            if request.airport_code and msg.airport_code != request.airport_code:
                return False
            return True
        return serve_stream(self.runway_bc, context, filter_fn=filter_fn)

    # ── RequestGate ───────────────────────────────────────────────────

    def RequestGate(self, request, context):
        flight_id = request.flight_id
        log.info("Gate request from flight %s", flight_id)

        if flight_id in self.assigned_gates:
            gate = self.assigned_gates[flight_id]
        else:
            gate = self._next_gate()

        if gate:
            self.assigned_gates[flight_id] = gate
            log.info("Assigned gate %s to %s", gate, flight_id)
            yield pb.GateAssignmentReply(
                flight_id=flight_id,
                assignment=pb.GateAssignment(
                    flight_id=flight_id,
                    gate_name=gate,
                    status=pb.ASSIGNED,
                    assignment_timestamp=now_ts(),
                ),
            )
        else:
            log.warning("No gates available for %s", flight_id)
            yield pb.GateAssignmentReply(
                flight_id=flight_id,
                assignment=pb.GateAssignment(
                    flight_id=flight_id,
                    gate_name="",
                    status=pb.GATE_REJECTED,
                    assignment_timestamp=now_ts(),
                    message="No gates available",
                ),
            )

    def _next_gate(self) -> str | None:
        used = set(self.assigned_gates.values())
        for g in self.GATE_NAMES:
            if g not in used:
                return g
        return None

    # ── Weather + runway publishing (background) ──────────────────────

    def publish_weather(self):
        conditions_list = [
            pb.VMC, pb.IMC, pb.RAIN, pb.SNOW, pb.FOG,
            pb.THUNDERSTORM, pb.WIND_SHEAR, pb.ICE,
        ]
        wx = pb.WeatherReport(
            airport_code=self.airport_code,
            wind=pb.Wind(
                direction_degrees=random.randint(0, 359),
                speed_knots=random.uniform(0, 25),
                gust_knots=random.uniform(15, 40) if random.random() > 0.7 else 0,
            ),
            visibility_meters=random.uniform(200, 10000),
            ceiling_feet=random.randint(200, 25000),
            temperature_celsius=random.uniform(-10, 40),
            altimeter_hpa=random.uniform(980, 1040),
            conditions=random.choice(conditions_list),
            observation_time=now_ts(),
        )
        self.weather_bc.publish(wx)
        log.info("Weather published: %s wind %03d/%02.0fkt vis %.0fm",
                 pb.WeatherCondition.Name(wx.conditions),
                 wx.wind.direction_degrees,
                 wx.wind.speed_knots,
                 wx.visibility_meters)

    def publish_runway_status(self):
        for rwy_id in self.runways:
            status = pb.RunwayStatus(
                airport_code=self.airport_code,
                runway_id=rwy_id,
                status=pb.OPEN,
                timestamp=now_ts(),
            )
            self.runway_bc.publish(status)

    def run_publishing_loop(self):
        """Background loop: publish weather periodically."""
        last_wx = 0.0
        self.publish_runway_status()
        while not shutdown_event.is_set():
            now = time.time()
            speed = get_sim_speed()
            wall_interval = self.weather_interval_s / max(speed, 0.1)
            if now - last_wx >= wall_interval:
                self.publish_weather()
                last_wx = now
            shutdown_event.wait(0.5)


def main():
    parser = argparse.ArgumentParser(description="ATC Airport Infrastructure (gRPC)")
    parser.add_argument("--config", required=True, help="Path to scenario config JSON")
    parser.add_argument("--airport-code", default="KJFK", help="ICAO airport code")
    parser.add_argument("--port", type=int, default=0, help="gRPC port (0=auto)")
    parser.add_argument("--duration", type=float, default=120.0, help="Duration in seconds")
    parser.add_argument("--wx-interval", type=float, default=1800.0,
                        help="Weather report interval in sim-time seconds")
    args = parser.parse_args()

    install_signal_handlers()
    global log
    log = setup_logging(args.airport_code)

    set_sim_speed(initial_sim_speed(args.config))
    cfg = load_airport_config(args.airport_code, args.config)
    runways = cfg["runways"]

    port = args.port

    servicer = AirportServiceServicer(
        airport_code=args.airport_code,
        runways=runways,
        weather_interval_s=args.wx_interval,
        config_path=args.config,
    )

    server, actual_port = create_grpc_server(port)
    pb_grpc.add_AirportServiceServicer_to_server(servicer, server)
    server.start()
    log.info("Airport %s gRPC server on port %d — runways: %s, gates: %d",
             args.airport_code, actual_port, runways, len(servicer.GATE_NAMES))

    # Zeroconf registration
    zc = ZeroconfRegistrar()
    zc.register("airport", args.airport_code, actual_port, {
        "airport_code": args.airport_code,
        "serving_tracon": cfg.get("serving_tracon", ""),
    })

    import threading
    pub_thread = threading.Thread(target=servicer.run_publishing_loop, daemon=True)
    pub_thread.start()

    # Wait for shutdown
    shutdown_event.wait(timeout=args.duration)
    log.info("Airport %s shutting down", args.airport_code)
    zc.close()
    server.stop(grace=2)


if __name__ == "__main__":
    main()
