# SPDX-FileCopyrightText: 2026 Real-Time Innovations, Inc.
# SPDX-License-Identifier: Apache-2.0
"""
Airplane Application (gRPC) — Aircraft simulator.

Serves: AircraftService (StreamPositions, StreamAcknowledgments)
Subscribes to: TowerService/TraconService/CenterService (StreamInstructions),
               AirportService (StreamWeatherReports), FlightPlanService (FileFlightPlan),
               AirportService (RequestGate)
"""

import argparse
import math
import random
import threading
import time

import grpc

import air_traffic_types_pb2 as pb
import air_traffic_types_pb2_grpc as pb_grpc
from common import (
    DiscoveryManager,
    StreamBroadcaster,
    ZeroconfRegistrar,
    bearing_deg,
    create_grpc_server,
    distance_nm,
    get_sim_speed,
    initial_sim_speed,
    install_signal_handlers,
    load_aircraft_config,
    load_airport_coords,
    make_id,
    now_ts,
    serve_stream,
    set_sim_speed,
    setup_logging,
    shutdown_event,
)

log = setup_logging("airplane")
AIRPORT_COORDS = {}


class AircraftServiceServicer(pb_grpc.AircraftServiceServicer):
    """gRPC AircraftService — serves position and acknowledgment streams."""

    def __init__(self, simulator):
        self.sim = simulator

    def StreamPositions(self, request, context):
        return serve_stream(self.sim.position_bc, context)

    def StreamAcknowledgments(self, request, context):
        return serve_stream(self.sim.ack_bc, context)


class AirplaneSimulator:
    """Simulates a single aircraft in the ATC system."""

    def __init__(self, tail_number: str, callsign: str, origin: str,
                 destination: str, config_path: str, cruise_alt: float = 35000.0):
        self.tail_number = tail_number
        self.callsign = callsign
        self.origin = origin
        self.destination = destination
        self.config_path = config_path
        self.cruise_alt = cruise_alt

        # Simulation state
        olat, olon = AIRPORT_COORDS.get(origin, (40.6413, -73.7781))
        dlat, dlon = AIRPORT_COORDS.get(destination, (33.9425, -118.4081))
        self.lat = olat + random.uniform(-0.02, 0.02)
        self.lon = olon + random.uniform(-0.02, 0.02)
        self.alt = 0.0
        self.heading = bearing_deg(self.lat, self.lon, dlat, dlon)
        self.ground_speed = 0.0
        self.vertical_speed = 0.0
        self.phase = pb.PREFLIGHT
        self.assigned_runway: str | None = None
        self.assigned_gate: str | None = None
        self.fuel = 80.0
        self._wx_deviating = False

        # Waypoints
        self.waypoints = self._build_waypoints(olat, olon, dlat, dlon)
        self.current_wp_index = 0
        self._total_route_nm = distance_nm(olat, olon, dlat, dlon)

        # Fuel proportional to distance
        estimated_burn = self._total_route_nm * 0.04
        self.fuel = min(100.0, max(40.0, estimated_burn + 20.0))

        # Broadcasters
        self.position_bc = StreamBroadcaster(
            key_fn=lambda m: m.tail_number, max_cache=1, ttl_s=1.0
        )
        self.ack_bc = StreamBroadcaster(max_cache=50)

        # Discovery
        self.discovery = DiscoveryManager(
            browse_roles=["tower", "tracon", "center", "airport", "fps"]
        )

        # Active instruction stream
        self._instr_stream_cancel = threading.Event()

        log.info("Aircraft %s (%s) initialized: %s -> %s (%d waypoints, %.0f nm)",
                 tail_number, callsign, origin, destination,
                 len(self.waypoints), self._total_route_nm)

    @staticmethod
    def _interpolate(lat1, lon1, lat2, lon2, frac):
        return (lat1 + (lat2 - lat1) * frac, lon1 + (lon2 - lon1) * frac)

    def _build_waypoints(self, olat, olon, dlat, dlon):
        dist_nm = distance_nm(olat, olon, dlat, dlon)
        n_intermediate = max(1, min(6, int(dist_nm / 400)))
        wpts = [("DEPART", olat, olon, 0.0)]
        for i in range(1, n_intermediate + 1):
            frac = i / (n_intermediate + 1)
            ilat, ilon = self._interpolate(olat, olon, dlat, dlon, frac)
            ilat += random.uniform(-0.3, 0.3)
            ilon += random.uniform(-0.3, 0.3)
            wpts.append((f"WP{i:02d}", ilat, ilon, self.cruise_alt))
        wpts.append(("ARRIVE", dlat, dlon, 0.0))
        return wpts

    def _steer_to_waypoint(self):
        if self.current_wp_index >= len(self.waypoints):
            return
        _, wlat, wlon, _ = self.waypoints[self.current_wp_index]
        dist = distance_nm(self.lat, self.lon, wlat, wlon)
        if dist < 5.0 and self.current_wp_index < len(self.waypoints) - 1:
            self.current_wp_index += 1
            _, wlat, wlon, _ = self.waypoints[self.current_wp_index]
            log.info("Passing waypoint → next: %s", self.waypoints[self.current_wp_index][0])
        self.heading = bearing_deg(self.lat, self.lon, wlat, wlon)

    def file_flight_plan(self):
        """File a flight plan via the FlightPlanService."""
        # Retry discovery briefly — FPS may not be advertised yet at startup
        endpoint = None
        for _ in range(10):
            endpoint = self.discovery.get_endpoint("fps", "fps")
            if endpoint:
                break
            time.sleep(0.5)
        if not endpoint:
            log.warning("FlightPlanService not discovered, proceeding without filing")
            return
        try:
            channel = grpc.insecure_channel(f"{endpoint[0]}:{endpoint[1]}")
            stub = pb_grpc.FlightPlanServiceStub(channel)

            waypoints = [
                pb.Waypoint(name=n, position=pb.GeoPosition(
                    latitude=lat, longitude=lon, altitude_feet=alt))
                for n, lat, lon, alt in self.waypoints
            ]
            plan = pb.FlightPlan(
                flight_plan_id=make_id("FP-"),
                tail_number=self.tail_number,
                callsign=self.callsign,
                departure_airport=self.origin,
                arrival_airport=self.destination,
                waypoints=waypoints,
                scheduled_departure_time=now_ts(),
                status=pb.FILED,
                last_updated=now_ts(),
            )
            response = stub.FileFlightPlan(
                pb.FlightPlanRequest(plan=plan), timeout=10
            )
            status = "ACCEPTED" if response.accepted else "REJECTED"
            log.info("Flight plan %s: %s", status, response.message)
            channel.close()
        except Exception as e:
            log.warning("Flight plan filing failed: %s", e)

    def request_gate(self):
        """Request a gate assignment from the destination airport."""
        endpoint = self.discovery.get_endpoint("airport", self.destination)
        if not endpoint:
            log.warning("Airport %s not discovered for gate request", self.destination)
            return
        try:
            channel = grpc.insecure_channel(f"{endpoint[0]}:{endpoint[1]}")
            stub = pb_grpc.AirportServiceStub(channel)
            responses = stub.RequestGate(
                pb.GateRequest(
                    flight_id=self.tail_number,
                    aerodrome_id=self.destination,
                    requested_timestamp=now_ts(),
                    requires_assignment=True,
                ), timeout=10
            )
            for reply in responses:
                a = reply.assignment
                self.assigned_gate = a.gate_name or None
                log.info("Gate assignment: %s at %s (%s)",
                         a.gate_name, self.destination,
                         pb.GateAssignmentStatusKind.Name(a.status))
            channel.close()
        except Exception as e:
            log.warning("Gate request failed: %s", e)

    _STUB_CLASSES = {
        "tower": pb_grpc.TowerServiceStub,
        "tracon": pb_grpc.TraconServiceStub,
        "center": pb_grpc.CenterServiceStub,
    }

    def _subscribe_instructions(self):
        """Background thread: discover controller services and spawn parallel streams."""
        known: set[tuple[str, int]] = set()
        while not shutdown_event.is_set() and not self._instr_stream_cancel.is_set():
            for role in ["tower", "tracon", "center"]:
                for host, port, props in self.discovery.get_all_endpoints(role):
                    key = (host, port)
                    if key not in known:
                        known.add(key)
                        t = threading.Thread(
                            target=self._stream_instructions_from,
                            args=(role, host, port),
                            daemon=True,
                        )
                        t.start()
            self._instr_stream_cancel.wait(3.0)

    def _stream_instructions_from(self, role: str, host: str, port: int):
        """Maintain a persistent instruction stream to one controller service."""
        stub_class = self._STUB_CLASSES[role]
        while not shutdown_event.is_set() and not self._instr_stream_cancel.is_set():
            try:
                channel = grpc.insecure_channel(f"{host}:{port}")
                stub = stub_class(channel)
                filter_msg = pb.ControllerInstructionFilter(
                    tail_number=self.tail_number
                )
                for instr in stub.StreamInstructions(filter_msg, timeout=60):
                    if shutdown_event.is_set() or self._instr_stream_cancel.is_set():
                        channel.close()
                        return
                    self._process_instruction(instr)
                channel.close()
            except grpc.RpcError:
                pass
            except Exception:
                pass
            self._instr_stream_cancel.wait(5.0)

    def _process_instruction(self, sample):
        log.debug("Instruction from %s: %s %s",
                  sample.controller_id, pb.InstructionType.Name(sample.instruction_type),
                  sample.clearance_text or "")

        if sample.instruction_type == pb.HEADING and sample.HasField("assigned_heading_degrees"):
            self.heading = sample.assigned_heading_degrees
            self._wx_deviating = True
            log.info("Weather deviation: HDG %.0f (holding until CLEARANCE)", self.heading)
        elif sample.instruction_type == pb.CLEARANCE and sample.clearance_text:
            self._handle_clearance(sample)
        elif sample.instruction_type == pb.ALTITUDE and sample.HasField("assigned_altitude_feet"):
            target = sample.assigned_altitude_feet
            self.vertical_speed = 2000 if target > self.alt else -1500
            if target < self.alt:
                self.phase = pb.DESCENT

        ack = pb.PilotAcknowledgment(
            acknowledgment_id=make_id("ACK-"),
            instruction_id=sample.instruction_id,
            tail_number=self.tail_number,
            status=pb.WILCO,
            response_text=f"WILCO {pb.InstructionType.Name(sample.instruction_type)}",
            acknowledged_at=now_ts(),
        )
        self.ack_bc.publish(ack)

    def _handle_clearance(self, sample):
        text = sample.clearance_text or ""
        wp_name = None
        if "DIRECT " in text:
            wp_name = text.split("DIRECT ", 1)[1].split()[0]
        if wp_name:
            for i, (name, _, _, _) in enumerate(self.waypoints):
                if name == wp_name:
                    self.current_wp_index = i
                    self._wx_deviating = False
                    log.info("Resume own navigation: direct %s (cleared by %s)",
                             wp_name, sample.controller_id)
                    return
        self._wx_deviating = False
        log.info("CLEARANCE received from %s — resuming own navigation: %s",
                 sample.controller_id, text)

    def _subscribe_weather(self):
        """Background thread: subscribe to destination weather."""
        while not shutdown_event.is_set():
            endpoint = self.discovery.get_endpoint("airport", self.destination)
            if not endpoint:
                shutdown_event.wait(2.0)
                continue
            try:
                channel = grpc.insecure_channel(f"{endpoint[0]}:{endpoint[1]}")
                stub = pb_grpc.AirportServiceStub(channel)
                for wx in stub.StreamWeatherReports(
                    pb.WeatherReportFilter(airport_code=self.destination), timeout=60
                ):
                    if shutdown_event.is_set():
                        break
                    log.info("Weather at %s: %s, vis=%.0fm, wind=%d@%.0fkt",
                             wx.airport_code,
                             pb.WeatherCondition.Name(wx.conditions),
                             wx.visibility_meters,
                             wx.wind.direction_degrees,
                             wx.wind.speed_knots)
                channel.close()
            except grpc.RpcError:
                pass
            except Exception:
                pass
            shutdown_event.wait(5.0)

    def _dist_to_destination(self):
        dlat, dlon = AIRPORT_COORDS.get(self.destination, (33.9425, -118.4081))
        return distance_nm(self.lat, self.lon, dlat, dlon)

    def build_position(self) -> pb.AircraftPosition:
        pos = pb.AircraftPosition(
            tail_number=self.tail_number,
            callsign=self.callsign,
            position=pb.GeoPosition(
                latitude=self.lat, longitude=self.lon, altitude_feet=self.alt
            ),
            ground_speed_knots=self.ground_speed,
            vertical_speed_fpm=self.vertical_speed,
            heading_degrees=self.heading,
            flight_phase=self.phase,
            origin_airport=self.origin,
            destination_airport=self.destination,
            fuel_level_percent=self.fuel,
            nav_status=pb.NAV_WEATHER_DEVIATION if self._wx_deviating else pb.NORMAL,
            timestamp=now_ts(),
        )
        if self.assigned_runway:
            pos.assigned_runway = self.assigned_runway
        if self.assigned_gate:
            pos.assigned_gate = self.assigned_gate
        return pos

    def advance_simulation(self):
        speed = get_sim_speed()
        TICK = 0.2 * speed

        if self.phase not in (pb.PREFLIGHT, pb.TAXI_OUT, pb.TAXI_IN, pb.PARKED):
            if not self._wx_deviating:
                self._steer_to_waypoint()

        # Auto-trigger descent
        if self.phase == pb.CRUISE:
            descent_nm = (self.alt / 1000.0) * 3.0
            if self._dist_to_destination() <= descent_nm:
                self.phase = pb.DESCENT
                self.vertical_speed = -1500.0
                self.ground_speed = 350.0
                log.info("Top of descent — %.0f nm from %s",
                         self._dist_to_destination(), self.destination)

        if self.phase == pb.PREFLIGHT:
            self.phase = pb.TAXI_OUT
            self.ground_speed = 15.0
        elif self.phase == pb.TAXI_OUT:
            self.phase = pb.TAKEOFF
            self.ground_speed = 150.0
            self.vertical_speed = 2500.0
        elif self.phase == pb.TAKEOFF:
            self.alt += self.vertical_speed / 60.0 * TICK
            if self.alt >= 1500:
                self.phase = pb.CLIMB
                self.ground_speed = 350.0
                log.info("Leaving tower airspace — CLIMB (%.0fft)", self.alt)
        elif self.phase == pb.CLIMB:
            self.alt += self.vertical_speed / 60.0 * TICK
            if self.alt >= self.cruise_alt:
                self.alt = self.cruise_alt
                self.phase = pb.CRUISE
                self.vertical_speed = 0
                self.ground_speed = 450.0
        elif self.phase == pb.CRUISE:
            pass
        elif self.phase == pb.DESCENT:
            self.alt += self.vertical_speed / 60.0 * TICK
            if self.alt <= 3000:
                self.phase = pb.APPROACH
                self.ground_speed = 180.0
                log.info("Entering tower airspace — APPROACH (%.0fft)", self.alt)
        elif self.phase == pb.APPROACH:
            self.alt += self.vertical_speed / 60.0 * TICK
            if self.alt <= 200:
                self.phase = pb.LANDING
        elif self.phase == pb.LANDING:
            self.alt = 0
            self.ground_speed = 60.0
            self.vertical_speed = 0
            self.phase = pb.TAXI_IN
        elif self.phase == pb.TAXI_IN:
            self.ground_speed = 15.0
            dlat, dlon = AIRPORT_COORDS.get(self.destination, (self.lat, self.lon))
            self.lat, self.lon = dlat, dlon
            self.phase = pb.PARKED
            self.ground_speed = 0.0
            self.vertical_speed = 0.0

        if self.ground_speed > 0 and self.phase != pb.PARKED:
            nm_per_tick = self.ground_speed / 3600.0 * TICK
            self.lat += (nm_per_tick * math.cos(math.radians(self.heading))) / 60.0
            cos_lat = math.cos(math.radians(self.lat))
            if cos_lat > 0.001:
                self.lon += (nm_per_tick * math.sin(math.radians(self.heading))) / (60.0 * cos_lat)

        if self.phase not in (pb.PREFLIGHT, pb.PARKED):
            self.fuel = max(5.0, self.fuel - 0.001 * speed)

    def run(self, duration_s: float = 60.0):
        log.info("Starting flight %s -> %s", self.origin, self.destination)
        self.file_flight_plan()

        # Start background subscription threads
        instr_thread = threading.Thread(target=self._subscribe_instructions, daemon=True)
        instr_thread.start()
        wx_thread = threading.Thread(target=self._subscribe_weather, daemon=True)
        wx_thread.start()

        start = time.time()
        while not shutdown_event.is_set() and (time.time() - start) < duration_s:
            self.advance_simulation()
            pos = self.build_position()
            self.position_bc.publish(pos)

            if self.phase == pb.PARKED:
                log.info("Aircraft parked, requesting gate")
                self.request_gate()
                self.position_bc.publish(self.build_position())
                break

            time.sleep(0.2)

        self._instr_stream_cancel.set()
        log.info("Aircraft %s simulation ended (phase=%s)",
                 self.tail_number, pb.FlightPhase.Name(self.phase))


def _random_tail_number():
    fmt = random.choice(["digits", "mixed"])
    if fmt == "digits":
        return f"N{random.randint(1, 99999)}"
    else:
        letters = "ABCDEFGHJKLMNPRSTUVWXYZ"
        return f"N{random.randint(1, 999)}{random.choice(letters)}{random.choice(letters)}"


def main():
    global AIRPORT_COORDS
    parser = argparse.ArgumentParser(description="ATC Aircraft Simulator (gRPC)")
    parser.add_argument("--config", required=True, help="Path to scenario config JSON")
    parser.add_argument("--tail-number", default=None, help="Aircraft tail number")
    parser.add_argument("--callsign", default="AAL123", help="Callsign")
    parser.add_argument("--origin", default=None, help="Origin airport")
    parser.add_argument("--destination", default=None, help="Destination airport")
    parser.add_argument("--port", type=int, default=0, help="gRPC port (0=auto)")
    parser.add_argument("--duration", type=float, default=60.0, help="Duration in seconds")
    args = parser.parse_args()

    install_signal_handlers()
    AIRPORT_COORDS = load_airport_coords(args.config)
    set_sim_speed(initial_sim_speed(args.config))

    cfg = load_aircraft_config(args.callsign, args.config)
    tail = args.tail_number or (cfg.get("tail_number") if cfg else None) or _random_tail_number()

    global log
    log = setup_logging(tail)
    origin = args.origin or (cfg.get("origin") if cfg else None) or "KJFK"
    destination = args.destination or (cfg.get("destination") if cfg else None) or "KLAX"

    sim = AirplaneSimulator(
        tail_number=tail, callsign=args.callsign,
        origin=origin, destination=destination,
        config_path=args.config,
    )

    servicer = AircraftServiceServicer(sim)
    server, actual_port = create_grpc_server(args.port)
    pb_grpc.add_AircraftServiceServicer_to_server(servicer, server)
    server.start()
    log.info("AircraftService gRPC server on port %d", actual_port)

    zc = ZeroconfRegistrar()
    zc.register("aircraft", args.callsign, actual_port, {
        "tail_number": tail,
        "callsign": args.callsign,
        "origin": origin,
        "destination": destination,
    })

    sim.run(duration_s=args.duration)
    zc.close()
    server.stop(grace=2)
    sim.discovery.close()


if __name__ == "__main__":
    main()
