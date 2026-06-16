# SPDX-FileCopyrightText: 2026 Real-Time Innovations, Inc.
# SPDX-License-Identifier: Apache-2.0
"""
Airport Infrastructure Application — Publishes weather reports, runway status,
and acts as Gate Assignment replier.
"""

import argparse
import os
import random
import signal
import sys
import time


import rti.connextdds as dds
from rti.rpc import Replier
from air_traffic_types import NationalAirTrafficControl as ATC

GateAssignment = ATC.GateAssignment
GateAssignmentReply = ATC.GateAssignmentReply
GateAssignmentStatusKind = ATC.GateAssignmentStatusKind
GateRequest = ATC.GateRequest
RunwayOperationalStatus = ATC.RunwayOperationalStatus
RunwayStatus = ATC.RunwayStatus
WeatherCondition = ATC.WeatherCondition
WeatherReport = ATC.WeatherReport
Wind = ATC.Wind
from common import (
    create_participant,
    create_publisher,
    create_subscriber,
    load_airport_config,
    load_qos_provider,
    now_ms,
    read_sim_speed_from_discovery,
    reader_qos,
    setup_logging,
    writer_qos,
    writer_qos_for_speed,
)
import common

log = setup_logging("airport")

shutdown_flag = False


def signal_handler(_sig, _frame):
    global shutdown_flag
    shutdown_flag = True


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


class AirportInfrastructure:
    """Publishes weather, runway status and handles gate assignment requests."""

    GATE_NAMES = [f"{t}{n}" for t in ("A", "B", "C") for n in range(1, 11)]

    def __init__(self, airport_code: str, runways: list[str], serving_tracon: str = "",
                 config_path: str = "", weather_interval_s: float = 1800.0):
        self.airport_code = airport_code
        self.runways = runways
        self.config_path = config_path
        self.weather_interval_s = weather_interval_s
        self.assigned_gates: dict[str, str] = {}  # flight_id -> gate

        # DDS setup
        self.qos_provider = load_qos_provider()
        dp_partitions = [f"OPS/AIRPORT/{airport_code}"]
        if serving_tracon:
            dp_partitions.append(f"OPS/TERMINAL/{serving_tracon}")
        self.participant = create_participant(
            self.qos_provider,
            dp_partitions=dp_partitions,
            participant_name=f"Airport_{airport_code}",
            app_name="ATC_Airport",
        )

        self.publisher = create_publisher(self.participant)
        self.subscriber = create_subscriber(self.participant)

        # WeatherReport writer — QoS scaled for current sim speed
        wx_topic = dds.Topic(self.participant, "WeatherReport", WeatherReport)
        speed = read_sim_speed_from_discovery(self.participant, self.config_path)
        self.wx_writer = dds.DataWriter(
            self.publisher, wx_topic,
            writer_qos_for_speed(self.qos_provider, "WeatherReportProfile", speed),
        )
        self._last_qos_speed = speed

        # RunwayStatus writer
        rwy_topic = dds.Topic(self.participant, "RunwayStatus", RunwayStatus)
        self.rwy_writer = dds.DataWriter(
            self.publisher, rwy_topic,
            writer_qos(self.qos_provider, "RunwayStatusProfile"),
        )

        # Gate assignment replier
        self.gate_replier = Replier(
            request_type=GateRequest,
            reply_type=GateAssignmentReply,
            participant=self.participant,
            service_name="GateAssignmentService",
            datawriter_qos=writer_qos(self.qos_provider, "GateAssignmentRequestReplyProfile"),
            datareader_qos=reader_qos(self.qos_provider, "GateAssignmentRequestReplyProfile"),
        )

        log.info("Airport %s initialized — runways: %s, gates: %d",
                 airport_code, runways, len(self.GATE_NAMES))

    def publish_weather(self):
        """Publish a simulated weather observation."""
        wx = WeatherReport(
            airport_code=self.airport_code,
            wind=Wind(
                direction_degrees=random.randint(0, 359),
                speed_knots=random.uniform(0, 25),
                gust_knots=random.uniform(15, 40) if random.random() > 0.7 else None,
            ),
            visibility_meters=random.uniform(200, 10000),
            ceiling_feet=random.randint(200, 25000),
            temperature_celsius=random.uniform(-10, 40),
            altimeter_hpa=random.uniform(980, 1040),
            conditions=random.choice(list(WeatherCondition)),
            observation_time=now_ms(),
        )
        self.wx_writer.write(wx)
        log.info("Weather published: %s wind %03d/%02.0fkt vis %.0fm",
                 wx.conditions.name,
                 wx.wind.direction_degrees,
                 wx.wind.speed_knots,
                 wx.visibility_meters)

    def publish_runway_status(self):
        """Publish status for all runways."""
        for rwy_id in self.runways:
            status = RunwayStatus(
                airport_code=self.airport_code,
                runway_id=rwy_id,
                status=RunwayOperationalStatus.OPEN,
                timestamp=now_ms(),
            )
            self.rwy_writer.write(status)

    def _next_gate(self) -> str | None:
        used = set(self.assigned_gates.values())
        for g in self.GATE_NAMES:
            if g not in used:
                return g
        return None

    def handle_gate_requests(self):
        """Process incoming gate assignment requests."""
        try:
            requests = self.gate_replier.receive_requests(dds.Duration(seconds=0))
        except dds.TimeoutError:
            return
        for request, info in requests:
            if not info.valid:
                continue

            flight_id = request.flight_id
            log.info("Gate request from flight %s", flight_id)

            if flight_id in self.assigned_gates:
                gate = self.assigned_gates[flight_id]
            else:
                gate = self._next_gate()

            if gate:
                self.assigned_gates[flight_id] = gate
                reply = GateAssignmentReply(
                    flight_id=flight_id,
                    assignment=GateAssignment(
                        flight_id=flight_id,
                        gate_name=gate,
                        status=GateAssignmentStatusKind.ASSIGNED,
                        assignment_timestamp=now_ms(),
                    ),
                )
                log.info("Assigned gate %s to %s", gate, flight_id)
            else:
                reply = GateAssignmentReply(
                    flight_id=flight_id,
                    assignment=GateAssignment(
                        flight_id=flight_id,
                        gate_name="",
                        status=GateAssignmentStatusKind.REJECTED,
                        assignment_timestamp=now_ms(),
                        message="No gates available",
                    ),
                )
                log.warning("No gates available for %s", flight_id)

            self.gate_replier.send_reply(reply, info)

    def run(self, duration_s: float = 120.0):
        """Main loop: publish weather periodically, respond to gate requests."""
        log.info("Airport %s operational", self.airport_code)
        start = time.time()
        last_wx = 0.0

        # Publish initial runway status
        self.publish_runway_status()

        while not shutdown_flag and (time.time() - start) < duration_s:
            now = time.time()

            # Scale interval by sim speed so weather cadence tracks sim-time
            speed = read_sim_speed_from_discovery(self.participant, self.config_path)
            wall_interval = self.weather_interval_s / max(speed, 0.1)
            if speed != self._last_qos_speed:
                self._last_qos_speed = speed
                self.wx_writer.qos = writer_qos_for_speed(
                    self.qos_provider, "WeatherReportProfile", speed,
                )
                log.info("Weather QoS rescaled for speed=%.1fx", speed)
            if now - last_wx >= wall_interval:
                self.publish_weather()
                last_wx = now

            self.handle_gate_requests()
            time.sleep(0.5)

        log.info("Airport %s shutting down", self.airport_code)


def main():
    parser = argparse.ArgumentParser(description="ATC Airport Infrastructure")
    parser.add_argument("--config", required=True, help="Path to scenario config JSON")
    parser.add_argument("--qos-file", required=True, help="Path to QoS XML file")
    parser.add_argument("--airport-code", default="KJFK", help="ICAO airport code")
    parser.add_argument("--runways", nargs="+", default=None, help="Runway IDs (default: from config)")
    parser.add_argument("--serving-tracon", default=None, help="Serving TRACON (default: from config)")
    parser.add_argument("--duration", type=float, default=120.0, help="Duration in seconds")
    parser.add_argument("--wx-interval", type=float, default=1800.0,
                        help="Weather report interval in sim-time seconds (default: 1800 = 30 min)")
    args = parser.parse_args()

    common.QOS_FILE = args.qos_file

    global log
    log = setup_logging(args.airport_code)

    cfg = load_airport_config(args.airport_code, args.config)
    airport = AirportInfrastructure(
        airport_code=args.airport_code,
        runways=args.runways or cfg["runways"],
        serving_tracon=args.serving_tracon if args.serving_tracon is not None else cfg.get("serving_tracon", ""),
        config_path=args.config,
        weather_interval_s=args.wx_interval,
    )
    airport.run(duration_s=args.duration)
    airport.gate_replier.close()
    airport.participant.close()
    
    dds.DomainParticipant.finalize_participant_factory()


if __name__ == "__main__":
    main()
