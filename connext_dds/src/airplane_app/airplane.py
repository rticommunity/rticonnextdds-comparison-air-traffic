"""
Airplane Application — Aircraft simulator.

Publishes AircraftPosition at ~5 Hz, subscribes to ControllerInstruction via CFT,
publishes PilotAcknowledgment, and uses Request/Reply for flight plan filing and
gate assignment.
"""

import argparse
import math
import os
import random
import signal
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import rti.connextdds as dds
from rti.rpc import Requester
from air_traffic import NationalAirTrafficControl as ATC

AircraftPosition = ATC.AircraftPosition
AcknowledgmentStatus = ATC.AcknowledgmentStatus
ControllerInstruction = ATC.ControllerInstruction
FlightPlan = ATC.FlightPlan
FlightPlanRequest = ATC.FlightPlanRequest
FlightPlanResponse = ATC.FlightPlanResponse
FlightPlanStatus = ATC.FlightPlanStatus
FlightPhase = ATC.FlightPhase
GateAssignmentReply = ATC.GateAssignmentReply
GateRequest = ATC.GateRequest
GeoPosition = ATC.GeoPosition
InstructionType = ATC.InstructionType
NavStatus = ATC.NavStatus
PilotAcknowledgment = ATC.PilotAcknowledgment
Waypoint = ATC.Waypoint
WeatherReport = ATC.WeatherReport
from common import (
    bearing_deg,
    create_participant,
    create_publisher,
    create_subscriber,
    distance_nm,
    load_aircraft_config,
    load_airport_coords,
    load_qos_provider,
    make_id,
    now_ms,
    read_sim_speed_from_discovery,
    reader_qos,
    setup_logging,
    writer_qos,
)

log = setup_logging("airplane")

# Load airport coordinates from scenario config
AIRPORT_COORDS = load_airport_coords()

shutdown_flag = False


def signal_handler(_sig, _frame):
    global shutdown_flag
    shutdown_flag = True


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


class AirplaneSimulator:
    """Simulates a single aircraft in the ATC system."""

    def __init__(
        self,
        tail_number: str,
        callsign: str,
        origin: str,
        destination: str,
        cruise_alt: float = 35000.0,
    ):
        self.tail_number = tail_number
        self.callsign = callsign
        self.origin = origin
        self.destination = destination
        self.cruise_alt = cruise_alt

        # Simulation state — start at origin airport
        olat, olon = AIRPORT_COORDS.get(origin, (40.6413, -73.7781))
        dlat, dlon = AIRPORT_COORDS.get(destination, (33.9425, -118.4081))
        self.lat = olat + random.uniform(-0.02, 0.02)
        self.lon = olon + random.uniform(-0.02, 0.02)
        self.alt = 0.0
        self.heading = bearing_deg(self.lat, self.lon, dlat, dlon)
        self.ground_speed = 0.0
        self.vertical_speed = 0.0
        self.fuel = 100.0
        self.phase = FlightPhase.PREFLIGHT
        self.assigned_runway: str | None = None

        # Build waypoint list along the route
        self.waypoints = self._build_waypoints(olat, olon, dlat, dlon)
        self.current_wp_index = 0  # index of next waypoint to fly to

        # Distance tracking for descent planning
        self._total_route_nm = distance_nm(olat, olon, dlat, dlon)

        # Weather deviation: when a HEADING instruction is received for
        # weather avoidance, hold heading indefinitely until Center issues
        # a CLEARANCE to resume own navigation.
        self._wx_deviating = False

        # DDS setup
        self.qos_provider = load_qos_provider()
        dp_partitions = [
            "OPS/FPS/*",
            "OPS/TERMINAL/*",
            "OPS/ENROUTE/*",
            f"OPS/AIRPORT/{origin}",
            f"OPS/AIRPORT/{destination}",
        ]
        self.participant = create_participant(
            self.qos_provider,
            dp_partitions=dp_partitions,
            participant_name=f"Airplane_{callsign}",
            app_name="ATC_Airplane",
        )

        self.publisher = create_publisher(self.participant)
        self.subscriber = create_subscriber(self.participant)

        # Position writer
        pos_topic = dds.Topic(self.participant, "AircraftPosition", AircraftPosition)
        self.pos_writer = dds.DataWriter(
            self.publisher, pos_topic,
            writer_qos(self.qos_provider, "PositionReportingProfile"),
        )

        # Ack writer
        ack_topic = dds.Topic(self.participant, "PilotAcknowledgment", PilotAcknowledgment)
        self.ack_writer = dds.DataWriter(
            self.publisher, ack_topic,
            writer_qos(self.qos_provider, "ReliableCommandProfile"),
        )

        # Instruction reader (content-filtered by tail_number)
        instr_topic = dds.Topic(self.participant, "ControllerInstruction", ControllerInstruction)
        self.instr_cft = dds.ContentFilteredTopic(
            instr_topic,
            f"MyInstructions_{tail_number}",
            dds.Filter(f"tail_number = '{tail_number}'"),
        )
        self.instr_reader = dds.DataReader(
            self.subscriber, self.instr_cft,
            reader_qos(self.qos_provider, "ReliableCommandProfile"),
        )

        # Weather reader (content-filtered by destination)
        wx_topic = dds.Topic(self.participant, "WeatherReport", WeatherReport)
        self.wx_cft = dds.ContentFilteredTopic(
            wx_topic,
            f"DestWeather_{destination}",
            dds.Filter(f"airport_code = '{destination}'"),
        )
        self.wx_reader = dds.DataReader(
            self.subscriber, self.wx_cft,
            reader_qos(self.qos_provider, "StateDataProfile"),
        )

        log.info(
            "Aircraft %s (%s) initialized: %s -> %s (%d waypoints, %.0f nm)",
            tail_number, callsign, origin, destination,
            len(self.waypoints), self._total_route_nm,
        )

    # ── Navigation helpers ──────────────────────────────────────────────

    @staticmethod
    def _interpolate(lat1, lon1, lat2, lon2, frac):
        """Linearly interpolate between two points by fraction [0,1]."""
        return (lat1 + (lat2 - lat1) * frac, lon1 + (lon2 - lon1) * frac)

    def _build_waypoints(self, olat, olon, dlat, dlon):
        """Generate waypoints along the route: DEPART, intermediate points, ARRIVE."""
        dist_nm = distance_nm(olat, olon, dlat, dlon)
        # Short routes get fewer waypoints; long routes get more
        n_intermediate = max(1, min(6, int(dist_nm / 400)))
        wpts = [("DEPART", olat, olon, 0.0)]
        for i in range(1, n_intermediate + 1):
            frac = i / (n_intermediate + 1)
            ilat, ilon = self._interpolate(olat, olon, dlat, dlon, frac)
            # Add slight lateral offset for realism (±0.3°)
            ilat += random.uniform(-0.3, 0.3)
            ilon += random.uniform(-0.3, 0.3)
            name = f"WP{i:02d}"
            wpts.append((name, ilat, ilon, self.cruise_alt))
        wpts.append(("ARRIVE", dlat, dlon, 0.0))
        return wpts  # list of (name, lat, lon, alt)

    def _steer_to_waypoint(self):
        """Update heading to aim at the current target waypoint."""
        if self.current_wp_index >= len(self.waypoints):
            return
        _, wlat, wlon, _ = self.waypoints[self.current_wp_index]
        dist = distance_nm(self.lat, self.lon, wlat, wlon)
        # Advance to next waypoint if we're within 5nm
        if dist < 5.0 and self.current_wp_index < len(self.waypoints) - 1:
            self.current_wp_index += 1
            _, wlat, wlon, _ = self.waypoints[self.current_wp_index]
            log.info("Passing waypoint → next: %s", self.waypoints[self.current_wp_index][0])
        self.heading = bearing_deg(self.lat, self.lon, wlat, wlon)

    # ── Flight plan filing ──────────────────────────────────────────────

    def file_flight_plan(self):
        """File a flight plan via Request/Reply."""
        try:
            requester = Requester(
                request_type=FlightPlanRequest,
                reply_type=FlightPlanResponse,
                participant=self.participant,
                service_name="FlightPlanFilingService",
                datawriter_qos=writer_qos(self.qos_provider, "FlightPlanRequestReplyProfile"),
                datareader_qos=reader_qos(self.qos_provider, "FlightPlanRequestReplyProfile"),
            )

            if not requester.wait_for_service(dds.Duration(seconds=5)):
                log.warning("FlightPlanFilingService not available, proceeding without filing")
                return

            plan = FlightPlan(
                flight_plan_id=make_id("FP-"),
                tail_number=self.tail_number,
                callsign=self.callsign,
                departure_airport=self.origin,
                arrival_airport=self.destination,
                waypoints=[
                    Waypoint(name=n, position=GeoPosition(lat, lon, alt))
                    for n, lat, lon, alt in self.waypoints
                ],
                scheduled_departure_time=now_ms(),
                status=FlightPlanStatus.FILED,
                last_updated=now_ms(),
            )

            request = FlightPlanRequest(plan=plan)
            request_id = requester.send_request(request)
            replies = requester.receive_replies(
                dds.Duration(seconds=10),
                related_request_id=request_id,
            )

            for reply, info in replies:
                if info.valid:
                    status = "ACCEPTED" if reply.accepted else "REJECTED"
                    log.info("Flight plan %s: %s", status, reply.message)

        except Exception as e:
            log.warning("Flight plan filing failed: %s", e)

    def request_gate(self):
        """Request a gate assignment via Request/Reply."""
        try:
            requester = Requester(
                request_type=GateRequest,
                reply_type=GateAssignmentReply,
                participant=self.participant,
                service_name="GateAssignmentService",
                datawriter_qos=writer_qos(self.qos_provider, "GateAssignmentRequestReplyProfile"),
                datareader_qos=reader_qos(self.qos_provider, "GateAssignmentRequestReplyProfile"),
            )

            if not requester.wait_for_service(dds.Duration(seconds=5)):
                log.warning("GateAssignmentService not available")
                return

            request = GateRequest(
                flight_id=self.tail_number,
                aerodrome_id=self.destination,
                requested_timestamp=now_ms(),
                requires_assignment=True,
            )
            request_id = requester.send_request(request)
            replies = requester.receive_replies(
                dds.Duration(seconds=10),
                related_request_id=request_id,
            )

            for reply, info in replies:
                if info.valid:
                    a = reply.assignment
                    log.info("Gate assignment: %s at %s (%s)",
                             a.gate_name, self.destination, a.status.name)

        except Exception as e:
            log.warning("Gate request failed: %s", e)

    def _dist_to_destination(self):
        """Distance in nm from current position to destination airport."""
        dlat, dlon = AIRPORT_COORDS.get(self.destination, (33.9425, -118.4081))
        return distance_nm(self.lat, self.lon, dlat, dlon)

    def advance_simulation(self):
        """Advance aircraft position and state by one tick."""
        speed = read_sim_speed_from_discovery(self.participant)
        TICK = 0.2 * speed  # seconds of sim-time per tick (5 Hz wall-clock)

        # Always steer toward waypoints when airborne (unless wx deviation active)
        if self.phase not in (FlightPhase.PREFLIGHT, FlightPhase.TAXI_OUT,
                               FlightPhase.TAXI_IN, FlightPhase.PARKED):
            if not self._wx_deviating:
                self._steer_to_waypoint()

        # Auto-trigger descent when close enough to destination
        # Descent from cruise_alt at 1500 fpm, at ~450 kt ground speed
        # Rule of thumb: start descent at (alt_to_lose / 1000) * 3 nm
        if self.phase == FlightPhase.CRUISE:
            descent_nm = (self.alt / 1000.0) * 3.0
            if self._dist_to_destination() <= descent_nm:
                self.phase = FlightPhase.DESCENT
                self.vertical_speed = -1500.0
                self.ground_speed = 350.0
                log.info("Top of descent — %.0f nm from %s", self._dist_to_destination(), self.destination)

        if self.phase == FlightPhase.PREFLIGHT:
            self.phase = FlightPhase.TAXI_OUT
            self.ground_speed = 15.0
        elif self.phase == FlightPhase.TAXI_OUT:
            self.phase = FlightPhase.TAKEOFF
            self.ground_speed = 150.0
            self.vertical_speed = 2500.0
        elif self.phase == FlightPhase.TAKEOFF:
            self.alt += self.vertical_speed / 60.0 * TICK
            if self.alt >= 1500:
                self.phase = FlightPhase.CLIMB
                self.ground_speed = 350.0
                log.info("Leaving tower airspace — CLIMB (%.0fft)", self.alt)
        elif self.phase == FlightPhase.CLIMB:
            self.alt += self.vertical_speed / 60.0 * TICK
            if self.alt >= self.cruise_alt:
                self.alt = self.cruise_alt
                self.phase = FlightPhase.CRUISE
                self.vertical_speed = 0
                self.ground_speed = 450.0
        elif self.phase == FlightPhase.CRUISE:
            pass  # Steady state — descent auto-triggered above
        elif self.phase == FlightPhase.DESCENT:
            self.alt += self.vertical_speed / 60.0 * TICK
            if self.alt <= 3000:
                self.phase = FlightPhase.APPROACH
                self.ground_speed = 180.0
                log.info("Entering tower airspace — APPROACH (%.0fft)", self.alt)
        elif self.phase == FlightPhase.APPROACH:
            self.alt += self.vertical_speed / 60.0 * TICK
            if self.alt <= 200:
                self.phase = FlightPhase.LANDING
        elif self.phase == FlightPhase.LANDING:
            self.alt = 0
            self.ground_speed = 60.0
            self.vertical_speed = 0
            self.phase = FlightPhase.TAXI_IN
        elif self.phase == FlightPhase.TAXI_IN:
            self.ground_speed = 15.0
            # Snap to destination coords
            dlat, dlon = AIRPORT_COORDS.get(self.destination, (self.lat, self.lon))
            self.lat, self.lon = dlat, dlon
            self.phase = FlightPhase.PARKED

        # Advance position based on heading
        if self.ground_speed > 0 and self.phase not in (FlightPhase.PARKED,):
            nm_per_tick = self.ground_speed / 3600.0 * TICK
            # Correct for longitude convergence at latitude
            self.lat += (nm_per_tick * math.cos(math.radians(self.heading))) / 60.0
            self.lon += (nm_per_tick * math.sin(math.radians(self.heading))) / (60.0 * math.cos(math.radians(self.lat)))

        # Burn fuel
        self.fuel = max(0.0, self.fuel - 0.002)

    def publish_position(self):
        """Publish current aircraft position."""
        sample = AircraftPosition(
            tail_number=self.tail_number,
            callsign=self.callsign,
            position=GeoPosition(self.lat, self.lon, self.alt),
            ground_speed_knots=self.ground_speed,
            vertical_speed_fpm=self.vertical_speed,
            heading_degrees=self.heading,
            flight_phase=self.phase,
            origin_airport=self.origin,
            destination_airport=self.destination,
            fuel_level_percent=self.fuel,
            nav_status=NavStatus.WEATHER_DEVIATION if self._wx_deviating else NavStatus.NORMAL,
            assigned_runway=self.assigned_runway,
            timestamp=now_ms(),
        )
        self.pos_writer.write(sample)

    def process_instructions(self):
        """Read and acknowledge any pending controller instructions."""
        for sample in self.instr_reader.take_data():
            log.info(
                "Instruction from %s: %s %s",
                sample.controller_id,
                sample.instruction_type.name,
                sample.clearance_text or "",
            )

            # Apply instruction
            if sample.instruction_type == InstructionType.HEADING and sample.assigned_heading_degrees is not None:
                self.heading = sample.assigned_heading_degrees
                self._wx_deviating = True
                log.info("Weather deviation: HDG %.0f (holding until CLEARANCE)", self.heading)
            elif sample.instruction_type == InstructionType.CLEARANCE and sample.clearance_text:
                self._handle_clearance(sample)
            elif sample.instruction_type == InstructionType.ALTITUDE and sample.assigned_altitude_feet is not None:
                target = sample.assigned_altitude_feet
                self.vertical_speed = 2000 if target > self.alt else -1500
                if target < self.alt:
                    self.phase = FlightPhase.DESCENT

            # Send acknowledgment
            ack = PilotAcknowledgment(
                acknowledgment_id=make_id("ACK-"),
                instruction_id=sample.instruction_id,
                tail_number=self.tail_number,
                status=AcknowledgmentStatus.WILCO,
                response_text=f"WILCO {sample.instruction_type.name}",
                acknowledged_at=now_ms(),
            )
            self.ack_writer.write(ack)

    def _handle_clearance(self, sample):
        """Handle a CLEARANCE instruction — typically 'resume own nav direct WPxx'.

        The Center picks the forward waypoint and sends it in clearance_text
        as 'RESUME OWN NAV DIRECT <waypoint_name>'.  We parse the waypoint
        name and update our waypoint index accordingly.
        """
        text = sample.clearance_text or ""
        # Extract waypoint name after "DIRECT "
        wp_name = None
        if "DIRECT " in text:
            wp_name = text.split("DIRECT ", 1)[1].split()[0]

        if wp_name:
            for i, (name, _, _, _) in enumerate(self.waypoints):
                if name == wp_name:
                    old_name = self.waypoints[self.current_wp_index][0]
                    self.current_wp_index = i
                    self._wx_deviating = False
                    log.info(
                        "Resume own navigation: %s → direct %s (cleared by %s)",
                        old_name, wp_name, sample.controller_id,
                    )
                    return

        # Fallback: waypoint not found or no DIRECT — just resume nav
        self._wx_deviating = False
        log.info("CLEARANCE received from %s — resuming own navigation: %s",
                 sample.controller_id, text)

    def check_weather(self):
        """Check destination weather reports."""
        for sample in self.wx_reader.take_data():
            log.info(
                "Weather at %s: %s, vis=%.0fm, wind=%d@%.0fkt",
                sample.airport_code,
                sample.conditions.name,
                sample.visibility_meters,
                sample.wind.direction_degrees,
                sample.wind.speed_knots,
            )

    def run(self, duration_s: float = 60.0):
        """Run the aircraft simulation loop at ~5 Hz."""
        log.info("Starting flight %s -> %s", self.origin, self.destination)
        self.file_flight_plan()

        start = time.time()
        tick = 0
        while not shutdown_flag and (time.time() - start) < duration_s:
            self.advance_simulation()
            self.publish_position()
            self.process_instructions()

            if tick % 50 == 0:  # Every ~10 seconds
                self.check_weather()

            if self.phase == FlightPhase.PARKED:
                log.info("Aircraft parked, requesting gate")
                self.request_gate()
                break

            tick += 1
            time.sleep(0.2)  # 5 Hz

        log.info("Aircraft %s simulation ended (phase=%s)", self.tail_number, self.phase.name)


def _random_tail_number():
    """Generate a realistic US N-number (e.g., N738WN, N12345)."""
    fmt = random.choice(["digits", "mixed"])
    if fmt == "digits":
        return f"N{random.randint(1, 99999)}"
    else:
        letters = "ABCDEFGHJKLMNPRSTUVWXYZ"  # no I, O, Q
        return f"N{random.randint(1, 999)}{random.choice(letters)}{random.choice(letters)}"


def main():
    parser = argparse.ArgumentParser(description="ATC Aircraft Simulator")
    parser.add_argument("--tail-number", default=None, help="Aircraft tail number (e.g., N738WN)")
    parser.add_argument("--callsign", default="AAL123", help="Callsign")
    parser.add_argument("--origin", default=None, help="Origin airport (default: from config)")
    parser.add_argument("--destination", default=None, help="Destination airport (default: from config)")
    parser.add_argument("--duration", type=float, default=60.0, help="Duration in seconds")
    args = parser.parse_args()

    cfg = load_aircraft_config(args.callsign)
    tail = args.tail_number or (cfg.get("tail_number") if cfg else None) or _random_tail_number()
    origin = args.origin or (cfg.get("origin") if cfg else None) or "KJFK"
    destination = args.destination or (cfg.get("destination") if cfg else None) or "KLAX"

    airplane = AirplaneSimulator(
        tail_number=tail,
        callsign=args.callsign,
        origin=origin,
        destination=destination,
    )
    airplane.run(duration_s=args.duration)


if __name__ == "__main__":
    main()
