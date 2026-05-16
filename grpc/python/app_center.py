# SPDX-FileCopyrightText: 2026 Real-Time Innovations, Inc.
# SPDX-License-Identifier: Apache-2.0
"""
En-Route Center Application (gRPC) — Manages aircraft in transit between airports.

Serves: CenterService (StreamInstructions, StreamHandoffs, StreamAlerts,
        StreamTracking, StreamFacilityStatus, SendHandoff)
Subscribes to: AircraftService (StreamPositions), TraconService (StreamHandoffs),
               FlightPlanService (StreamFlightPlans), WeatherService (StreamConvectiveCells)
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
    bearing_deg,
    create_grpc_server,
    distance_nm,
    find_center_for_position,
    get_sim_speed,
    initial_sim_speed,
    install_signal_handlers,
    load_center_boundaries,
    load_center_config,
    load_tracon_for_airport,
    make_id,
    now_ts,
    point_in_polygon,
    polygon_bbox,
    serve_stream,
    set_sim_speed,
    setup_logging,
    shutdown_event,
)

log = setup_logging("center")

BBOX_PAD_DEG = 3.0


class CenterServiceServicer(pb_grpc.CenterServiceServicer):
    """gRPC CenterService implementation."""

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


class EnRouteCenter:
    """Simulates an en-route ATC center with geographic boundary awareness."""

    def __init__(self, center_id: str, controller_id: str,
                 boundary: list[list[float]],
                 all_boundaries: dict[str, list[list[float]]],
                 tracon_for_airport: dict[str, str],
                 min_altitude_ft: int = 18000, max_altitude_ft: int = 60000,
                 config_path: str = ""):
        self.center_id = center_id
        self.controller_id = controller_id
        self.config_path = config_path
        self.min_alt = min_altitude_ft
        self.max_alt = max_altitude_ft
        self.boundary = boundary
        self.all_boundaries = all_boundaries
        self.tracon_for_airport = tracon_for_airport

        # Controlled aircraft state
        self.controlled_aircraft: dict[str, pb.AircraftPosition | None] = {}
        self.last_seen: dict[str, float] = {}
        self.acquired_at: dict[str, float] = {}
        self.handed_off: set[str] = set()
        self.pending_handoffs: dict[str, str] = {}
        self.seen_inside: set[str] = set()
        self._sep_cooldown: dict[tuple[str, str], float] = {}
        self.alerted_uncoordinated: set[str] = set()
        self.NEVER_ENTERED_GRACE_S = 30.0
        self._startup_time = time.time()
        self.STARTUP_GRACE_S = 15.0

        # Weather state
        self._active_cells: dict[str, pb.ConvectiveCell] = {}
        self._wx_deviation_cooldown: dict[str, float] = {}
        self._wx_deviating: set[str] = set()
        self._flight_plans: dict[str, pb.FlightPlan] = {}

        # Bounding box for position filtering
        min_lat, max_lat, min_lon, max_lon = polygon_bbox(boundary)
        self.bbox = (min_lat - BBOX_PAD_DEG, max_lat + BBOX_PAD_DEG,
                     min_lon - BBOX_PAD_DEG, max_lon + BBOX_PAD_DEG)

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
            browse_roles=["aircraft", "tracon", "center", "fps", "weather"]
        )

        log.info("Center %s (%s) initialized — FL%d-FL%d, boundary=%d vertices, "
                 "bbox=[%.1f,%.1f]×[%.1f,%.1f]",
                 center_id, controller_id,
                 min_altitude_ft // 100, max_altitude_ft // 100,
                 len(boundary),
                 self.bbox[0], self.bbox[1], self.bbox[2], self.bbox[3])

    # ── Publishing helpers ─────────────────────────────────────────────

    def _publish_facility_status(self):
        status = pb.FacilityStatus(
            facility_id=self.center_id,
            facility_type=pb.CENTER,
            controller_id=self.controller_id,
            tracked_aircraft_count=len(self.controlled_aircraft),
            last_updated=now_ts(),
        )
        self.status_bc.publish(status)

    def _publish_tracking(self, tail_number: str):
        sample = pb.AircraftTracking(
            tail_number=tail_number,
            controller_id=self.controller_id,
            facility_id=self.center_id,
            facility_type=pb.CENTER,
            acquired_at=now_ts(),
        )
        self.tracking_bc.publish(sample)
        self._publish_facility_status()
        log.info("Tracking %s — controller of record: %s (%s)",
                 tail_number, self.controller_id, self.center_id)

    def _unregister_tracking(self, tail_number: str):
        self.tracking_bc.remove_key(tail_number)
        self._publish_facility_status()
        log.info("Unregistered tracking for %s", tail_number)

    def issue_instruction(self, tail_number: str, instr_type, **kwargs):
        instr = pb.ControllerInstruction(
            instruction_id=make_id(kwargs.get("id_prefix", "INSTR-")),
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

    # ── Handoff handling ───────────────────────────────────────────────

    def receive_handoff(self, handoff: pb.Handoff) -> pb.HandoffAck:
        if handoff.status == pb.INITIATED:
            log.info("Accepting handoff of %s from %s into %s",
                     handoff.tail_number, handoff.from_controller_id, self.center_id)
            accept = pb.Handoff(
                handoff_id=handoff.handoff_id,
                tail_number=handoff.tail_number,
                from_controller_id=handoff.from_controller_id,
                to_controller_id=self.controller_id,
                status=pb.ACCEPTED,
                from_facility_type=handoff.from_facility_type,
                to_facility_type=pb.CENTER,
                initiated_at=handoff.initiated_at,
                completed_at=now_ts(),
            )
            self.handoff_bc.publish(accept)
            now = time.time()
            self.controlled_aircraft[handoff.tail_number] = None
            self.last_seen[handoff.tail_number] = now
            self.acquired_at[handoff.tail_number] = now
            self.handed_off.discard(handoff.tail_number)
            self.seen_inside.discard(handoff.tail_number)
            self.alerted_uncoordinated.discard(handoff.tail_number)
            self._publish_tracking(handoff.tail_number)
            return pb.HandoffAck(success=True, message="Accepted")

        elif handoff.status == pb.ACCEPTED:
            tail = handoff.tail_number
            if tail in self.pending_handoffs:
                log.info("Handoff of %s accepted by %s — releasing",
                         tail, handoff.to_controller_id)
                del self.pending_handoffs[tail]
                self._unregister_tracking(tail)
                self.controlled_aircraft.pop(tail, None)
                self.last_seen.pop(tail, None)
                self.acquired_at.pop(tail, None)
            return pb.HandoffAck(success=True)

        return pb.HandoffAck(success=False, message="Unexpected handoff status")

    # ── Aircraft position streaming ────────────────────────────────────

    def _poll_aircraft_positions(self):
        """Background thread: discover and stream from aircraft servers."""
        known: set[str] = set()
        while not shutdown_event.is_set():
            services = self.discovery.get_services("aircraft")
            for sname, (host, port, props) in services.items():
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

        # Altitude filter (like CFT)
        if alt < self.min_alt or alt >= self.max_alt:
            return
        # Bounding box filter
        lat = sample.position.latitude
        lon = sample.position.longitude
        if lat < self.bbox[0] or lat > self.bbox[1] or \
           lon < self.bbox[2] or lon > self.bbox[3]:
            return

        inside = point_in_polygon(lat, lon, self.boundary)

        if tail in self.controlled_aircraft:
            self.last_seen[tail] = time.time()
            self.controlled_aircraft[tail] = sample

            # Detect inherited weather deviation
            if sample.nav_status == pb.NAV_WEATHER_DEVIATION and tail not in self._wx_deviating:
                self._wx_deviating.add(tail)
                log.info("Inherited weather deviation for %s from previous controller", tail)

            if inside:
                self.seen_inside.add(tail)
            elif tail not in self.handed_off:
                if tail in self.seen_inside:
                    self._handoff_exiting_aircraft(sample)
                else:
                    acq = self.acquired_at.get(tail, time.time())
                    if (time.time() - acq) > self.NEVER_ENTERED_GRACE_S:
                        neighbor = find_center_for_position(
                            lat, lon, self.all_boundaries, exclude=self.center_id
                        )
                        if neighbor:
                            log.info("Aircraft %s never entered %s (in %s) — forwarding",
                                     tail, self.center_id, neighbor)
                            self._handoff_exiting_aircraft(sample)

        elif inside and tail not in self.handed_off:
            if tail not in self.alerted_uncoordinated and \
               (time.time() - self._startup_time) > self.STARTUP_GRACE_S:
                self._alert_uncoordinated(sample)

    # ── Separation checking ────────────────────────────────────────────

    def check_separation(self):
        GROUND_PHASES = frozenset([pb.PREFLIGHT, pb.TAXI_OUT, pb.TAXI_IN, pb.PARKED])
        airborne = [p for p in self.controlled_aircraft.values()
                    if p is not None and p.flight_phase not in GROUND_PHASES]
        now = time.time()
        sim_speed = get_sim_speed()
        for i, a in enumerate(airborne):
            for b in airborne[i + 1:]:
                lat_diff = abs(a.position.latitude - b.position.latitude)
                lon_diff = abs(a.position.longitude - b.position.longitude)
                alt_diff = abs(a.position.altitude_feet - b.position.altitude_feet)
                if lat_diff < 0.083 and lon_diff < 0.083 and alt_diff < 1000:
                    pair = tuple(sorted((a.tail_number, b.tail_number)))
                    cooldown = 30.0 / max(sim_speed, 0.1)
                    if now - self._sep_cooldown.get(pair, 0) < cooldown:
                        continue
                    self._sep_cooldown[pair] = now
                    log.warning("SEPARATION VIOLATION: %s and %s in %s",
                                a.tail_number, b.tail_number, self.center_id)
                    alert = pb.Alert(
                        alert_id=make_id("ALERT-"),
                        alert_type=pb.TRAFFIC_CONFLICT,
                        severity=pb.CRITICAL,
                        involved_aircraft=[a.tail_number, b.tail_number],
                        message=f"Separation violation between {a.tail_number} and {b.tail_number} in {self.center_id}",
                        timestamp=now_ts(),
                    )
                    self.alert_bc.publish(alert)

    # ── Handoff: exiting aircraft ──────────────────────────────────────

    def _handoff_exiting_aircraft(self, pos: pb.AircraftPosition):
        tail = pos.tail_number

        if pos.position.altitude_feet < self.min_alt + 2000 and pos.vertical_speed_fpm < -500:
            tracon_id = self.tracon_for_airport.get(pos.destination_airport)
            if tracon_id:
                to_id = f"APP-{tracon_id}"
                to_type = pb.TRACON
                role = "tracon"
                name = tracon_id
                log.info("Handoff %s → TRACON %s (descending, FL%d)",
                         tail, tracon_id, int(pos.position.altitude_feet) // 100)
            else:
                log.warning("No TRACON for %s, skipping handoff of %s",
                            pos.destination_airport, tail)
                return
        else:
            neighbor = find_center_for_position(
                pos.position.latitude, pos.position.longitude,
                self.all_boundaries, exclude=self.center_id
            )
            if neighbor:
                to_id = f"CTR-{neighbor}"
                to_type = pb.CENTER
                role = "center"
                name = neighbor
                log.info("Handoff %s → Center %s (exiting %s boundary)",
                         tail, neighbor, self.center_id)
            else:
                log.warning("Aircraft %s left %s but no neighboring center at (%.2f, %.2f)",
                            tail, self.center_id,
                            pos.position.latitude, pos.position.longitude)
                if tail in self._wx_deviating:
                    wp_name = self._find_forward_waypoint(tail, pos)
                    clearance_text = f"RESUME OWN NAV DIRECT {wp_name}" if wp_name else "RESUME OWN NAV"
                    self.issue_instruction(tail, pb.CLEARANCE, clearance=clearance_text,
                                           id_prefix="WX-CLR-")
                    self._wx_deviating.discard(tail)
                    log.info("WEATHER CLEAR (no neighbor): %s — %s", tail, clearance_text)
                return

        ho = pb.Handoff(
            handoff_id=make_id("HO-"),
            tail_number=tail,
            from_controller_id=self.controller_id,
            to_controller_id=to_id,
            status=pb.INITIATED,
            from_facility_type=pb.CENTER,
            to_facility_type=to_type,
            sector=self.center_id,
            initiated_at=now_ts(),
        )
        self.handoff_bc.publish(ho)
        self.pending_handoffs[tail] = ho.handoff_id
        self.handed_off.add(tail)
        self.seen_inside.discard(tail)
        self._wx_deviating.discard(tail)

        # Send handoff via direct RPC
        self._send_handoff_to_facility(role, name, ho)

    def _send_handoff_to_facility(self, role: str, name: str, handoff: pb.Handoff):
        endpoint = self.discovery.get_endpoint(role, name)
        if not endpoint:
            log.warning("%s %s not discovered for handoff", role, name)
            return
        try:
            channel = grpc.insecure_channel(f"{endpoint[0]}:{endpoint[1]}")
            stub_class = {
                "tracon": pb_grpc.TraconServiceStub,
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
            log.warning("Failed to send handoff to %s %s: %s", role, name, e)

    # ── Uncoordinated traffic ──────────────────────────────────────────

    def _alert_uncoordinated(self, pos: pb.AircraftPosition):
        log.warning("UNCOORDINATED: %s inside %s at (%.2f, %.2f) FL%d",
                     pos.tail_number, self.center_id,
                     pos.position.latitude, pos.position.longitude,
                     int(pos.position.altitude_feet) // 100)
        alert = pb.Alert(
            alert_id=make_id("ALERT-"),
            alert_type=pb.UNAUTHORIZED_ENTRY,
            severity=pb.WARNING,
            involved_aircraft=[pos.tail_number],
            message=f"Uncoordinated traffic: {pos.tail_number} in {self.center_id} at FL{int(pos.position.altitude_feet) // 100}",
            timestamp=now_ts(),
        )
        self.alert_bc.publish(alert)
        self.alerted_uncoordinated.add(pos.tail_number)

    # ── Flight plan caching ────────────────────────────────────────────

    def _subscribe_flight_plans(self):
        """Background thread: subscribe to flight plans."""
        while not shutdown_event.is_set():
            endpoint = self.discovery.get_endpoint("fps", "fps")
            if not endpoint:
                shutdown_event.wait(2.0)
                continue
            try:
                channel = grpc.insecure_channel(f"{endpoint[0]}:{endpoint[1]}")
                stub = pb_grpc.FlightPlanServiceStub(channel)
                for plan in stub.StreamFlightPlans(pb.EmptyFilter(), timeout=300):
                    if shutdown_event.is_set():
                        break
                    self._flight_plans[plan.tail_number] = plan
                channel.close()
            except grpc.RpcError:
                pass
            shutdown_event.wait(5.0)

    # ── Weather hazard avoidance ───────────────────────────────────────

    _WX_DEVIATION_COOLDOWN_S = 30
    _WX_THREAT_FACTOR = 1.5

    def _subscribe_weather_cells(self):
        """Background thread: subscribe to convective cells from WeatherService."""
        while not shutdown_event.is_set():
            endpoint = self.discovery.get_endpoint("weather", "weather")
            if not endpoint:
                shutdown_event.wait(2.0)
                continue
            try:
                channel = grpc.insecure_channel(f"{endpoint[0]}:{endpoint[1]}")
                stub = pb_grpc.WeatherServiceStub(channel)
                # Track which cells we received in the latest publish cycle
                received_ids: set[str] = set()
                last_refresh = time.time()
                for cell in stub.StreamConvectiveCells(pb.EmptyFilter(), timeout=300):
                    if shutdown_event.is_set():
                        break
                    self._active_cells[cell.cell_id] = cell
                    received_ids.add(cell.cell_id)
                    # After a batch of updates arrives (>2s gap), prune cells
                    # that were NOT re-published (they expired/dissipated)
                    now = time.time()
                    if now - last_refresh > 2.0 and received_ids:
                        stale = [cid for cid in self._active_cells if cid not in received_ids]
                        for cid in stale:
                            del self._active_cells[cid]
                        received_ids.clear()
                        last_refresh = now
                channel.close()
            except grpc.RpcError:
                pass
            shutdown_event.wait(5.0)

    def check_weather_cells(self):
        if not self._active_cells:
            return
        now = time.time()
        sim_speed = get_sim_speed()
        airborne_phases = frozenset([pb.CLIMB, pb.CRUISE])

        for tail, pos in list(self.controlled_aircraft.items()):
            if pos is None or pos.flight_phase not in airborne_phases:
                continue
            if tail in self._wx_deviating:
                continue
            wx_cooldown = self._WX_DEVIATION_COOLDOWN_S / max(sim_speed, 0.1)
            if now - self._wx_deviation_cooldown.get(tail, 0) < wx_cooldown:
                continue

            for cell in self._active_cells.values():
                if pos.position.altitude_feet < cell.base_altitude_ft or \
                   pos.position.altitude_feet > cell.top_altitude_ft:
                    continue
                dist = distance_nm(
                    pos.position.latitude, pos.position.longitude,
                    cell.center_latitude, cell.center_longitude,
                )
                threat_radius = cell.radius_nm * self._WX_THREAT_FACTOR
                if dist < threat_radius:
                    bearing_to_cell = bearing_deg(
                        pos.position.latitude, pos.position.longitude,
                        cell.center_latitude, cell.center_longitude,
                    )
                    deviation_hdg = (bearing_to_cell + 90) % 360
                    self.issue_instruction(
                        tail, pb.HEADING,
                        heading=deviation_hdg,
                        clearance=f"DEVIATE HDG {int(deviation_hdg)} — WX cell {cell.cell_id} {pb.ConvectiveSeverity.Name(cell.severity)} at {dist:.0f}nm",
                        id_prefix="WX-INSTR-",
                    )
                    self._wx_deviation_cooldown[tail] = now
                    self._wx_deviating.add(tail)

                    sev = pb.CRITICAL if cell.severity == pb.EXTREME else pb.WARNING
                    alert = pb.Alert(
                        alert_id=make_id("ALERT-"),
                        alert_type=pb.WEATHER_DEVIATION,
                        severity=sev,
                        involved_aircraft=[tail],
                        message=f"Weather deviation: {tail} rerouted HDG {int(deviation_hdg)} around {pb.ConvectiveSeverity.Name(cell.severity)} cell {cell.cell_id} ({dist:.0f}nm)",
                        timestamp=now_ts(),
                    )
                    self.alert_bc.publish(alert)
                    log.warning("WEATHER DEVIATION: %s → HDG %d (cell %s at %.0fnm)",
                                tail, int(deviation_hdg), cell.cell_id, dist)
                    break

    def check_clear_of_weather(self):
        if not self._wx_deviating:
            return
        cleared = []
        for tail in list(self._wx_deviating):
            pos = self.controlled_aircraft.get(tail)
            if pos is None:
                cleared.append(tail)
                continue
            still_threatened = False
            for cell in self._active_cells.values():
                if pos.position.altitude_feet < cell.base_altitude_ft or \
                   pos.position.altitude_feet > cell.top_altitude_ft:
                    continue
                dist = distance_nm(
                    pos.position.latitude, pos.position.longitude,
                    cell.center_latitude, cell.center_longitude,
                )
                if dist < cell.radius_nm * 2.0:
                    still_threatened = True
                    break
            if not still_threatened:
                cleared.append(tail)
                wp_name = self._find_forward_waypoint(tail, pos)
                clearance_text = f"RESUME OWN NAV DIRECT {wp_name}" if wp_name else "RESUME OWN NAV"
                self.issue_instruction(tail, pb.CLEARANCE, clearance=clearance_text,
                                       id_prefix="WX-CLR-")
                log.info("WEATHER CLEAR: %s — %s", tail, clearance_text)
        for tail in cleared:
            self._wx_deviating.discard(tail)

    def _find_forward_waypoint(self, tail: str, pos) -> str | None:
        fp = self._flight_plans.get(tail)
        if not fp or not fp.waypoints:
            return None
        dest_wp = fp.waypoints[-1]
        my_dist = distance_nm(
            pos.position.latitude, pos.position.longitude,
            dest_wp.position.latitude, dest_wp.position.longitude,
        )
        for wp in fp.waypoints:
            wp_dist = distance_nm(
                wp.position.latitude, wp.position.longitude,
                dest_wp.position.latitude, dest_wp.position.longitude,
            )
            if wp_dist < my_dist:
                return wp.name
        return fp.waypoints[-1].name

    # ── Stale aircraft check ───────────────────────────────────────────

    def _check_stale_aircraft(self):
        now = time.time()
        stale_threshold = 3.0
        for tail in list(self.controlled_aircraft):
            if tail in self.handed_off:
                continue
            last_pos = self.controlled_aircraft[tail]
            last_t = self.last_seen.get(tail, 0)
            if last_pos is None or (now - last_t) <= stale_threshold:
                continue
            if tail in self.seen_inside:
                log.info("Aircraft %s lost from position feed — initiating handoff", tail)
                self._handoff_exiting_aircraft(last_pos)
            else:
                neighbor = find_center_for_position(
                    last_pos.position.latitude, last_pos.position.longitude,
                    self.all_boundaries, exclude=self.center_id,
                )
                if neighbor:
                    log.info("Aircraft %s never entered %s, in %s — forwarding",
                             tail, self.center_id, neighbor)
                    self._handoff_exiting_aircraft(last_pos)

    # ── Main loop ──────────────────────────────────────────────────────

    def run(self, duration_s: float = 120.0):
        log.info("En-route center %s operational", self.center_id)
        self._publish_facility_status()

        # Start background threads
        threads = [
            threading.Thread(target=self._poll_aircraft_positions, daemon=True),
            threading.Thread(target=self._subscribe_flight_plans, daemon=True),
            threading.Thread(target=self._subscribe_weather_cells, daemon=True),
        ]
        for t in threads:
            t.start()

        start = time.time()
        while not shutdown_event.is_set() and (time.time() - start) < duration_s:
            self.check_separation()
            self.check_weather_cells()
            self.check_clear_of_weather()
            self._check_stale_aircraft()
            self._publish_facility_status()
            shutdown_event.wait(1.0)

        log.info("Center %s shutting down — controlled %d, handed off %d",
                 self.center_id, len(self.controlled_aircraft), len(self.handed_off))


def main():
    parser = argparse.ArgumentParser(description="ATC En-Route Center (gRPC)")
    parser.add_argument("--config", required=True, help="Path to scenario config JSON")
    parser.add_argument("--center-id", default="ZNY", help="Center ID")
    parser.add_argument("--controller-id", default=None, help="Controller ID")
    parser.add_argument("--min-alt", type=int, default=None, help="Min altitude ft")
    parser.add_argument("--max-alt", type=int, default=None, help="Max altitude ft")
    parser.add_argument("--port", type=int, default=0, help="gRPC port (0=auto)")
    parser.add_argument("--duration", type=float, default=120.0, help="Duration in seconds")
    args = parser.parse_args()

    install_signal_handlers()
    set_sim_speed(initial_sim_speed(args.config))

    cfg = load_center_config(args.center_id, args.config)
    controller_id = args.controller_id or f"CTR-{args.center_id}"
    min_alt = args.min_alt if args.min_alt is not None else cfg.get("min_altitude_ft", 18000)
    max_alt = args.max_alt if args.max_alt is not None else cfg.get("max_altitude_ft", 60000)

    port = args.port

    global log
    log = setup_logging(controller_id)

    all_boundaries = load_center_boundaries(args.config)

    center = EnRouteCenter(
        center_id=args.center_id,
        controller_id=controller_id,
        boundary=cfg["boundary"],
        all_boundaries=all_boundaries,
        tracon_for_airport=load_tracon_for_airport(args.config),
        min_altitude_ft=min_alt,
        max_altitude_ft=max_alt,
        config_path=args.config,
    )

    servicer = CenterServiceServicer(center)
    server, actual_port = create_grpc_server(port)
    pb_grpc.add_CenterServiceServicer_to_server(servicer, server)
    server.start()
    log.info("CenterService gRPC server on port %d", actual_port)

    zc = ZeroconfRegistrar()
    zc.register("center", args.center_id, actual_port, {
        "center_id": args.center_id,
        "controller_id": controller_id,
    })

    center.run(duration_s=args.duration)
    zc.close()
    server.stop(grace=2)
    center.discovery.close()


if __name__ == "__main__":
    main()
