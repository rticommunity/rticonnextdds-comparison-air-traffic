# SPDX-FileCopyrightText: 2026 Real-Time Innovations, Inc.
# SPDX-License-Identifier: Apache-2.0
"""
Control Tower Application (gRPC) — Airport tower simulator.

Serves: TowerService (StreamInstructions, StreamHandoffs, StreamAlerts,
        StreamTracking, StreamFacilityStatus, StreamRunwayStatus, SendHandoff)
Subscribes to: AircraftService (StreamPositions), TraconService (StreamHandoffs),
               AirportService (StreamWeatherReports), FlightPlanService (StreamFlightPlans)
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
    load_airport_config,
    make_id,
    now_ts,
    serve_stream,
    set_sim_speed,
    setup_logging,
    shutdown_event,
)

log = setup_logging("tower")


class TowerServiceServicer(pb_grpc.TowerServiceServicer):
    """gRPC TowerService implementation."""

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

    def StreamRunwayStatus(self, request, context):
        def filter_fn(msg):
            if request.airport_code and msg.airport_code != request.airport_code:
                return False
            return True
        return serve_stream(self.ctrl.runway_bc, context, filter_fn=filter_fn)

    def SendHandoff(self, request, context):
        return self.ctrl.receive_handoff(request)


class TowerController:
    """Simulates a control tower at a single airport."""

    def __init__(self, airport_code: str, controller_id: str, serving_tracon: str = "",
                 config_path: str = ""):
        self.airport_code = airport_code
        self.controller_id = controller_id
        self.serving_tracon = serving_tracon
        self.config_path = config_path
        self.tracked_aircraft: dict[str, pb.AircraftPosition] = {}
        self.handed_off: set[str] = set()
        self.controlling: set[str] = set()
        self.pending_handoffs: dict[str, str] = {}

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
        self.runway_bc = StreamBroadcaster(
            key_fn=lambda m: f"{m.airport_code}/{m.runway_id}", max_cache=20
        )

        # Discovery
        self.discovery = DiscoveryManager(
            browse_roles=["aircraft", "tracon", "airport", "fps"]
        )

        # Active aircraft streams: tail -> channel
        self._aircraft_channels: dict[str, grpc.Channel] = {}

        log.info("Tower %s at %s initialized", controller_id, airport_code)

    def _publish_facility_status(self):
        status = pb.FacilityStatus(
            facility_id=self.airport_code,
            facility_type=pb.TOWER,
            controller_id=self.controller_id,
            tracked_aircraft_count=len(self.controlling),
            last_updated=now_ts(),
        )
        self.status_bc.publish(status)

    def _publish_tracking(self, tail_number: str):
        sample = pb.AircraftTracking(
            tail_number=tail_number,
            controller_id=self.controller_id,
            facility_id=self.airport_code,
            facility_type=pb.TOWER,
            acquired_at=now_ts(),
        )
        self.tracking_bc.publish(sample)
        self.controlling.add(tail_number)
        self._publish_facility_status()
        log.info("Tracking %s — controller of record: %s (%s)",
                 tail_number, self.controller_id, self.airport_code)

    def _unregister_tracking(self, tail_number: str):
        self.tracking_bc.remove_key(tail_number)
        self.controlling.discard(tail_number)
        self._publish_facility_status()
        log.info("Unregistered tracking for %s", tail_number)

    def _publish_runway_status(self, runway_id: str, status_val):
        sample = pb.RunwayStatus(
            airport_code=self.airport_code,
            runway_id=runway_id,
            status=status_val,
            timestamp=now_ts(),
        )
        self.runway_bc.publish(sample)
        log.info("Runway %s/%s: %s", self.airport_code, runway_id,
                 pb.RunwayOperationalStatus.Name(status_val))

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
        log.info("Issued %s to %s", pb.InstructionType.Name(instr_type), tail_number)

    def receive_handoff(self, handoff: pb.Handoff) -> pb.HandoffAck:
        """Handle an incoming SendHandoff RPC."""
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
                to_facility_type=pb.TOWER,
                initiated_at=handoff.initiated_at,
                completed_at=now_ts(),
            )
            self.handoff_bc.publish(accept)
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
                callsign = props.get("callsign", "")
                origin = props.get("origin", "")
                dest = props.get("destination", "")
                # Only subscribe to aircraft related to our airport
                if origin != self.airport_code and dest != self.airport_code:
                    continue
                if sname in known:
                    continue
                known.add(sname)
                t = threading.Thread(
                    target=self._stream_aircraft,
                    args=(host, port, props.get("tail_number", callsign)),
                    daemon=True,
                )
                t.start()
            shutdown_event.wait(2.0)

    def _stream_aircraft(self, host: str, port: int, tail: str):
        """Stream positions from a single aircraft."""
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
        except Exception as e:
            log.debug("Stream from %s error: %s", tail, e)

    def _handle_position(self, sample: pb.AircraftPosition):
        TOWER_CEILING_FT = 3000
        tail = sample.tail_number
        if tail in self.handed_off:
            return
        if sample.flight_phase == pb.PARKED:
            if tail in self.tracked_aircraft:
                self.tracked_aircraft.pop(tail)
                self._unregister_tracking(tail)
            return

        is_local_departure = (
            sample.origin_airport == self.airport_code
            and sample.position.altitude_feet < TOWER_CEILING_FT
        )
        is_local_arrival = (
            sample.destination_airport == self.airport_code
            and (sample.position.altitude_feet < TOWER_CEILING_FT
                 or sample.flight_phase >= 6)  # APPROACH or later
        )
        is_ground = sample.flight_phase <= 1  # PREFLIGHT or TAXI_OUT

        if not (is_local_departure or is_local_arrival or is_ground):
            return

        is_new = tail not in self.tracked_aircraft
        self.tracked_aircraft[tail] = sample
        if is_new and sample.origin_airport == self.airport_code:
            self._publish_tracking(tail)

        # Issue approach clearances
        if (sample.flight_phase >= 5 and
                sample.destination_airport == self.airport_code and
                not sample.assigned_runway):
            self.issue_instruction(
                tail, pb.CLEARANCE,
                clearance=f"Cleared ILS approach runway 09L at {self.airport_code}",
            )

        # Hand departing aircraft to TRACON
        if tail not in self.handed_off and \
           sample.origin_airport == self.airport_code and \
           sample.position.altitude_feet >= 1500 and sample.vertical_speed_fpm > 0:
            tracon_id = f"APP-{self.serving_tracon}" if self.serving_tracon else f"APP-{self.airport_code}"
            ho = pb.Handoff(
                handoff_id=make_id("HO-"),
                tail_number=tail,
                from_controller_id=self.controller_id,
                to_controller_id=tracon_id,
                status=pb.INITIATED,
                from_facility_type=pb.TOWER,
                to_facility_type=pb.TRACON,
                sector=self.airport_code,
                initiated_at=now_ts(),
            )
            self.handoff_bc.publish(ho)
            self._send_handoff_to_tracon(ho)
            self.pending_handoffs[tail] = ho.handoff_id
            self.handed_off.add(tail)
            log.info("Handoff %s → TRACON (departing, %.0fft)",
                     tail, sample.position.altitude_feet)

    def _send_handoff_to_tracon(self, handoff: pb.Handoff):
        """Send handoff via direct RPC to the TRACON server."""
        tracon_name = self.serving_tracon
        if not tracon_name:
            return
        endpoint = self.discovery.get_endpoint("tracon", tracon_name)
        if not endpoint:
            log.warning("TRACON %s not discovered for handoff", tracon_name)
            return
        try:
            channel = grpc.insecure_channel(f"{endpoint[0]}:{endpoint[1]}")
            stub = pb_grpc.TraconServiceStub(channel)
            ack = stub.SendHandoff(handoff, timeout=5)
            if ack.success:
                log.info("TRACON accepted handoff of %s", handoff.tail_number)
                self.receive_handoff(pb.Handoff(
                    handoff_id=handoff.handoff_id,
                    tail_number=handoff.tail_number,
                    from_controller_id=self.controller_id,
                    to_controller_id=handoff.to_controller_id,
                    status=pb.ACCEPTED,
                ))
            channel.close()
        except Exception as e:
            log.warning("Failed to send handoff to TRACON: %s", e)

    def run(self, duration_s: float = 120.0):
        log.info("Tower %s operational", self.airport_code)
        self._publish_facility_status()
        self._publish_runway_status("09L", pb.OPEN)
        self._publish_runway_status("27R", pb.OPEN)

        # Start background aircraft polling
        poll_thread = threading.Thread(target=self._poll_aircraft_positions, daemon=True)
        poll_thread.start()

        start = time.time()
        while not shutdown_event.is_set() and (time.time() - start) < duration_s:
            self._publish_facility_status()
            shutdown_event.wait(1.0)

        log.info("Tower %s shutting down", self.airport_code)


def main():
    parser = argparse.ArgumentParser(description="ATC Control Tower (gRPC)")
    parser.add_argument("--config", required=True, help="Path to scenario config JSON")
    parser.add_argument("--airport-code", default="KJFK", help="Airport ICAO code")
    parser.add_argument("--controller-id", default=None, help="Controller ID")
    parser.add_argument("--serving-tracon", default=None, help="Serving TRACON")
    parser.add_argument("--port", type=int, default=0, help="gRPC port (0=auto)")
    parser.add_argument("--duration", type=float, default=120.0, help="Duration in seconds")
    args = parser.parse_args()

    install_signal_handlers()
    set_sim_speed(initial_sim_speed(args.config))

    cfg = load_airport_config(args.airport_code, args.config)
    controller_id = args.controller_id or f"TWR-{args.airport_code}"
    serving_tracon = args.serving_tracon if args.serving_tracon is not None else cfg.get("serving_tracon", "")

    port = args.port

    global log
    log = setup_logging(controller_id)

    ctrl = TowerController(
        airport_code=args.airport_code,
        controller_id=controller_id,
        serving_tracon=serving_tracon,
        config_path=args.config,
    )

    servicer = TowerServiceServicer(ctrl)
    server, actual_port = create_grpc_server(port)
    pb_grpc.add_TowerServiceServicer_to_server(servicer, server)
    server.start()
    log.info("TowerService gRPC server on port %d", actual_port)

    zc = ZeroconfRegistrar()
    zc.register("tower", args.airport_code, actual_port, {
        "airport_code": args.airport_code,
        "controller_id": controller_id,
        "serving_tracon": serving_tracon,
    })

    ctrl.run(duration_s=args.duration)
    zc.close()
    server.stop(grace=2)
    ctrl.discovery.close()


if __name__ == "__main__":
    main()
