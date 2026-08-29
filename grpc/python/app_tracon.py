# SPDX-FileCopyrightText: 2026 Real-Time Innovations, Inc.
# SPDX-License-Identifier: Apache-2.0
"""
TRACON Application (gRPC) — Terminal Radar Approach Control.

Serves: TraconService (StreamInstructions, StreamHandoffs, StreamAlerts,
        StreamTracking, StreamFacilityStatus, SendHandoff)
Subscribes to: AircraftService (StreamPositions), TowerService (StreamHandoffs),
               CenterService (StreamHandoffs), AirportService (StreamWeatherReports),
               FlightPlanService (StreamFlightPlans)
"""

import argparse
import threading
import time

import grpc

import air_traffic_types_pb2 as pb
import air_traffic_types_pb2_grpc as pb_grpc
from common import (
    DiscoveryManager,
    StreamBroadcaster,
    ZeroconfRegistrar,
    create_grpc_server,
    get_sim_speed,
    initial_sim_speed,
    install_signal_handlers,
    load_airport_coords,
    load_tracon_config,
    make_id,
    now_ts,
    serve_stream,
    set_sim_speed,
    start_sim_speed_listener,
    setup_logging,
    shutdown_event,
)

log = setup_logging("tracon")
AIRPORT_COORDS = {}


class TraconServiceServicer(pb_grpc.TraconServiceServicer):
    """gRPC TraconService implementation."""

    def __init__(self, controller):
        self.ctrl = controller

    def StreamInstructions(self, request, context):
        def filter_fn(msg):
            if request.tail_number and msg.tail_number != request.tail_number:
                return False
            return True
        return serve_stream(self.ctrl.instr_bc, context, filter_fn=filter_fn)

    def StreamHandoffs(self, request, context):
        def filter_fn(msg):
            if request.controller_id:
                if msg.to_controller_id != request.controller_id and \
                   msg.from_controller_id != request.controller_id:
                    return False
            return True
        return serve_stream(self.ctrl.handoff_bc, context, filter_fn=filter_fn)

    def StreamAlerts(self, request, context):
        return serve_stream(self.ctrl.alert_bc, context)

    def StreamTracking(self, request, context):
        return serve_stream(self.ctrl.tracking_bc, context)

    def StreamFacilityStatus(self, request, context):
        return serve_stream(self.ctrl.status_bc, context)

    def SendHandoff(self, request, context):
        return self.ctrl.receive_handoff(request)


class TraconController:
    """Simulates a TRACON facility managing the terminal area."""

    MIN_ALT = 500
    MAX_ALT = 18000
    TOWER_HANDOFF_ALT = 3000
    CENTER_HANDOFF_ALT = 17000
    TERMINAL_RADIUS_DEG = 0.66

    def __init__(self, tracon_id: str, controller_id: str, airport_codes: list[str],
                 serving_center: str = "", config_path: str = ""):
        self.tracon_id = tracon_id
        self.controller_id = controller_id
        self.airport_codes = airport_codes
        self.serving_center = serving_center
        self.config_path = config_path
        self.tracked_aircraft: dict[str, pb.AircraftPosition] = {}
        self.handed_off: set[str] = set()
        self.acquired_aircraft: set[str] = set()
        self.controlling: set[str] = set()
        self.pending_handoffs: dict[str, str] = {}
        self._sep_cooldown: dict[tuple[str, str], float] = {}
        self._last_speed_issued: dict[str, float] = {}
        self._startup_time = time.time()
        self._STARTUP_GRACE_S = 15.0

        # Broadcasters
        self.instr_bc = StreamBroadcaster(max_cache=50)
        self.handoff_bc = StreamBroadcaster(
            key_fn=lambda m: m.handoff_id, max_cache=20
        )
        self.alert_bc = StreamBroadcaster(max_cache=50, ttl_s=60.0)
        self.tracking_bc = StreamBroadcaster(
            key_fn=lambda m: m.tail_number, max_cache=50
        )
        self.status_bc = StreamBroadcaster(
            key_fn=lambda m: m.facility_id, max_cache=1
        )

        # Discovery
        self.discovery = DiscoveryManager(
            browse_roles=["aircraft", "tower", "center", "airport", "fps"]
        )

        log.info("TRACON %s (%s) initialized — airports: %s, FL%d–FL%d",
                 tracon_id, controller_id, ", ".join(airport_codes),
                 self.MIN_ALT // 100, self.MAX_ALT // 100)

    def _is_in_terminal_area(self, pos) -> bool:
        for code in self.airport_codes:
            alat, alon = AIRPORT_COORDS.get(code, (0, 0))
            dlat = abs(pos.position.latitude - alat)
            dlon = abs(pos.position.longitude - alon)
            if dlat < self.TERMINAL_RADIUS_DEG and dlon < self.TERMINAL_RADIUS_DEG:
                return True
        return False

    def _is_arriving(self, pos) -> bool:
        return pos.destination_airport in self.airport_codes

    def _is_departing(self, pos) -> bool:
        return pos.origin_airport in self.airport_codes

    def _publish_facility_status(self):
        status = pb.FacilityStatus(
            facility_id=self.tracon_id,
            facility_type=pb.TRACON,
            controller_id=self.controller_id,
            tracked_aircraft_count=len(self.controlling),
            last_updated=now_ts(),
        )
        self.status_bc.publish(status)

    def _publish_tracking(self, tail_number: str):
        sample = pb.AircraftTracking(
            tail_number=tail_number,
            controller_id=self.controller_id,
            facility_id=self.tracon_id,
            facility_type=pb.TRACON,
            acquired_at=now_ts(),
        )
        self.tracking_bc.publish(sample)
        self.controlling.add(tail_number)
        self._publish_facility_status()
        log.info("Tracking %s — controller of record: %s (%s)",
                 tail_number, self.controller_id, self.tracon_id)

    def _unregister_tracking(self, tail_number: str):
        self.tracking_bc.remove_key(tail_number)
        self.controlling.discard(tail_number)
        self._publish_facility_status()
        log.info("Unregistered tracking for %s", tail_number)

    def issue_instruction(self, tail_number: str, instr_type, **kwargs):
        instr = pb.ControllerInstruction(
            instruction_id=make_id("INSTR-"),
            controller_id=self.controller_id,
            tail_number=tail_number,
            instruction_type=instr_type,
            issued_at=now_ts(),
        )
        if kwargs.get("heading") is not None:
            instr.assigned_heading_degrees = kwargs["heading"]
        if kwargs.get("altitude") is not None:
            instr.assigned_altitude_feet = kwargs["altitude"]
        if kwargs.get("speed") is not None:
            instr.assigned_speed_knots = kwargs["speed"]
        if kwargs.get("clearance") is not None:
            instr.clearance_text = kwargs["clearance"]
        self.instr_bc.publish(instr)
        log.debug("Issued %s to %s", pb.InstructionType.Name(instr_type), tail_number)

    def receive_handoff(self, handoff: pb.Handoff) -> pb.HandoffAck:
        if handoff.status == pb.INITIATED:
            log.info("Accepting handoff of %s from %s",
                     handoff.tail_number, handoff.from_controller_id)
            accept = pb.Handoff(
                handoff_id=handoff.handoff_id,
                tail_number=handoff.tail_number,
                from_controller_id=handoff.from_controller_id,
                to_controller_id=self.controller_id,
                status=pb.ACCEPTED,
                from_facility_type=handoff.from_facility_type,
                to_facility_type=pb.TRACON,
                initiated_at=handoff.initiated_at,
                completed_at=now_ts(),
            )
            self.handoff_bc.publish(accept)
            self.acquired_aircraft.add(handoff.tail_number)
            self._publish_tracking(handoff.tail_number)
            return pb.HandoffAck(success=True, message="Accepted")

        elif handoff.status == pb.ACCEPTED:
            tail = handoff.tail_number
            if tail in self.pending_handoffs:
                log.info("Handoff of %s accepted by %s — releasing",
                         tail, handoff.to_controller_id)
                del self.pending_handoffs[tail]
                self._unregister_tracking(tail)
                self.tracked_aircraft.pop(tail, None)
            return pb.HandoffAck(success=True)

        return pb.HandoffAck(success=False, message="Unexpected handoff status")

    def _poll_aircraft_positions(self):
        """Background thread: discover and stream positions from aircraft."""
        known: set[str] = set()
        while not shutdown_event.is_set():
            services = self.discovery.get_services("aircraft")
            for sname, (host, port, props) in services.items():
                origin = props.get("origin", "")
                dest = props.get("destination", "")
                if origin not in self.airport_codes and dest not in self.airport_codes:
                    continue
                if sname in known:
                    continue
                known.add(sname)
                t = threading.Thread(
                    target=self._stream_aircraft, args=(host, port), daemon=True
                )
                t.start()
            shutdown_event.wait(2.0)

    def _stream_aircraft(self, host: str, port: int):
        try:
            channel = grpc.insecure_channel(f"{host}:{port}")
            stub = pb_grpc.AircraftServiceStub(channel)
            for pos in stub.StreamPositions(pb.EmptyFilter(), timeout=300):
                if shutdown_event.is_set():
                    break
                self._handle_position(pos)
            channel.close()
        except grpc.RpcError:
            pass

    def _handle_position(self, sample: pb.AircraftPosition):
        tail = sample.tail_number
        alt = sample.position.altitude_feet
        if alt < self.MIN_ALT or alt >= self.MAX_ALT:
            self.tracked_aircraft.pop(tail, None)
            return
        if self._is_in_terminal_area(sample) or \
           sample.origin_airport in self.airport_codes or \
           sample.destination_airport in self.airport_codes:
            self.tracked_aircraft[tail] = sample
        else:
            self.tracked_aircraft.pop(tail, None)

    def check_separation(self):
        if (time.time() - self._startup_time) < self._STARTUP_GRACE_S:
            return
        GROUND_PHASES = frozenset([pb.PREFLIGHT, pb.TAXI_OUT, pb.TAXI_IN, pb.PARKED])
        airborne = [p for p in self.tracked_aircraft.values()
                    if p.flight_phase not in GROUND_PHASES]
        now = time.time()
        sim_speed = get_sim_speed()
        for i, a in enumerate(airborne):
            for b in airborne[i + 1:]:
                if a.flight_phase == pb.CLIMB and b.flight_phase == pb.CLIMB:
                    continue
                lat_diff = abs(a.position.latitude - b.position.latitude)
                lon_diff = abs(a.position.longitude - b.position.longitude)
                alt_diff = abs(a.position.altitude_feet - b.position.altitude_feet)
                if lat_diff < 0.05 and lon_diff < 0.05 and alt_diff < 1000:
                    pair = tuple(sorted((a.tail_number, b.tail_number)))
                    cooldown = 30.0 / max(sim_speed, 0.1)
                    if now - self._sep_cooldown.get(pair, 0) < cooldown:
                        continue
                    self._sep_cooldown[pair] = now
                    log.warning("TERMINAL SEPARATION VIOLATION: %s and %s",
                                a.tail_number, b.tail_number)
                    alert = pb.Alert(
                        alert_id=make_id("ALERT-"),
                        alert_type=pb.TRAFFIC_CONFLICT,
                        severity=pb.WARNING,
                        involved_aircraft=[a.tail_number, b.tail_number],
                        message=f"Terminal separation violation: {a.tail_number} and {b.tail_number} in {self.tracon_id}",
                        timestamp=now_ts(),
                    )
                    self.alert_bc.publish(alert)

    def sequence_arrivals(self):
        for tail, pos in self.tracked_aircraft.items():
            if not self._is_arriving(pos):
                continue
            alt = pos.position.altitude_feet
            target_speed = None
            if 10000 < alt < 15000 and pos.ground_speed_knots > 280:
                target_speed = 250.0
            elif 5000 < alt <= 10000 and pos.ground_speed_knots > 220:
                target_speed = 210.0
            if target_speed is not None and self._last_speed_issued.get(tail) != target_speed:
                self.issue_instruction(tail, pb.SPEED, speed=target_speed)
                self._last_speed_issued[tail] = target_speed

    def manage_handoffs(self):
        for tail, pos in list(self.tracked_aircraft.items()):
            if tail in self.handed_off:
                continue
            if tail not in self.acquired_aircraft:
                continue
            alt = pos.position.altitude_feet

            # Departing → center
            if self._is_departing(pos) and alt >= self.CENTER_HANDOFF_ALT:
                self._initiate_handoff_to_center(tail, pos)
                self.handed_off.add(tail)
            # Arriving → tower
            elif self._is_arriving(pos) and alt <= self.TOWER_HANDOFF_ALT:
                self._initiate_handoff_to_tower(tail, pos)
                self.handed_off.add(tail)

    def _initiate_handoff_to_center(self, tail: str, pos):
        ho = pb.Handoff(
            handoff_id=make_id("HO-"),
            tail_number=tail,
            from_controller_id=self.controller_id,
            to_controller_id=f"CTR-{self.serving_center}",
            status=pb.INITIATED,
            from_facility_type=pb.TRACON,
            to_facility_type=pb.CENTER,
            sector=self.tracon_id,
            initiated_at=now_ts(),
        )
        self.handoff_bc.publish(ho)
        self.pending_handoffs[tail] = ho.handoff_id
        log.info("Handoff %s → Center (departing, FL%d)", tail, int(pos.position.altitude_feet) // 100)
        self._send_handoff_to_facility("center", self.serving_center, ho)

    def _initiate_handoff_to_tower(self, tail: str, pos):
        tower_airport = pos.destination_airport
        ho = pb.Handoff(
            handoff_id=make_id("HO-"),
            tail_number=tail,
            from_controller_id=self.controller_id,
            to_controller_id=f"TWR-{tower_airport}",
            status=pb.INITIATED,
            from_facility_type=pb.TRACON,
            to_facility_type=pb.TOWER,
            sector=self.tracon_id,
            initiated_at=now_ts(),
        )
        self.handoff_bc.publish(ho)
        self.pending_handoffs[tail] = ho.handoff_id
        log.info("Handoff %s → Tower %s (arriving, %.0fft)",
                 tail, tower_airport, pos.position.altitude_feet)
        self._send_handoff_to_facility("tower", tower_airport, ho)

    def _send_handoff_to_facility(self, role: str, name: str, handoff: pb.Handoff):
        endpoint = self.discovery.get_endpoint(role, name)
        if not endpoint:
            log.warning("%s %s not discovered for handoff", role, name)
            return
        try:
            channel = grpc.insecure_channel(f"{endpoint[0]}:{endpoint[1]}")
            stub_class = {
                "tower": pb_grpc.TowerServiceStub,
                "center": pb_grpc.CenterServiceStub,
            }.get(role)
            if stub_class:
                stub = stub_class(channel)
                ack = stub.SendHandoff(handoff, timeout=5)
                if ack.success:
                    log.info("%s accepted handoff of %s", role, handoff.tail_number)
                    self.receive_handoff(pb.Handoff(
                        handoff_id=handoff.handoff_id,
                        tail_number=handoff.tail_number,
                        from_controller_id=self.controller_id,
                        to_controller_id=handoff.to_controller_id,
                        status=pb.ACCEPTED,
                    ))
            channel.close()
        except Exception as e:
            log.warning("Failed to send handoff to %s: %s", role, e)

    def run(self, duration_s: float = 120.0):
        log.info("TRACON %s operational — serving %s",
                 self.tracon_id, ", ".join(self.airport_codes))
        self._publish_facility_status()

        poll_thread = threading.Thread(target=self._poll_aircraft_positions, daemon=True)
        poll_thread.start()

        start = time.time()
        while not shutdown_event.is_set() and (time.time() - start) < duration_s:
            self.check_separation()
            self.sequence_arrivals()
            self.manage_handoffs()
            self._publish_facility_status()
            shutdown_event.wait(1.0)

        log.info("TRACON %s shutting down", self.tracon_id)


def main():
    global AIRPORT_COORDS
    parser = argparse.ArgumentParser(description="ATC TRACON Facility (gRPC)")
    parser.add_argument("--config", required=True, help="Path to scenario config JSON")
    parser.add_argument("--tracon-id", default="N90", help="TRACON facility ID")
    parser.add_argument("--controller-id", default=None, help="Controller ID")
    parser.add_argument("--airports", nargs="+", default=None, help="Airport codes")
    parser.add_argument("--serving-center", default=None, help="Overlying center")
    parser.add_argument("--port", type=int, default=0, help="gRPC port (0=auto)")
    parser.add_argument("--duration", type=float, default=120.0, help="Duration in seconds")
    args = parser.parse_args()

    install_signal_handlers()
    AIRPORT_COORDS = load_airport_coords(args.config)
    set_sim_speed(initial_sim_speed(args.config))
    start_sim_speed_listener()

    cfg = load_tracon_config(args.tracon_id, args.config)
    controller_id = args.controller_id or f"APP-{args.tracon_id}"

    port = args.port

    global log
    log = setup_logging(controller_id)

    ctrl = TraconController(
        tracon_id=args.tracon_id,
        controller_id=controller_id,
        airport_codes=args.airports or cfg.get("airports", []),
        serving_center=args.serving_center if args.serving_center is not None else cfg.get("serving_center", ""),
        config_path=args.config,
    )

    servicer = TraconServiceServicer(ctrl)
    server, actual_port = create_grpc_server(port)
    pb_grpc.add_TraconServiceServicer_to_server(servicer, server)
    server.start()
    log.info("TraconService gRPC server on port %d", actual_port)

    zc = ZeroconfRegistrar()
    zc.register("tracon", args.tracon_id, actual_port, {
        "tracon_id": args.tracon_id,
        "controller_id": controller_id,
        "airports": ",".join(ctrl.airport_codes),
        "serving_center": ctrl.serving_center,
    })

    ctrl.run(duration_s=args.duration)
    zc.close()
    server.stop(grace=2)
    ctrl.discovery.close()


if __name__ == "__main__":
    main()
