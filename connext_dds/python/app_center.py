# SPDX-FileCopyrightText: 2026 Real-Time Innovations, Inc.
# SPDX-License-Identifier: Apache-2.0
"""
En-Route Center Application — Manages aircraft in transit between airports.

Each center loads its boundary polygon from the scenario config and uses a
two-layer filtering approach:
  1. DDS Content-Filtered Topic (CFT) with a rectangular bounding box
     (latitude + longitude + altitude) — filters at the infrastructure level.
  2. Application-level point-in-polygon check for precise boundary awareness.

Aircraft are tracked only after an explicit Handoff is accepted.  If an
aircraft appears inside the polygon without having been handed off, the
center publishes an UNAUTHORIZED_ENTRY alert.  When a tracked aircraft
exits the polygon, the center initiates a handoff to the neighboring
center (looked up via polygon containment) or to the arrival TRACON
if the aircraft is descending.

Subscribes to AircraftPosition (CFT by bounding box + altitude), publishes
ControllerInstruction, handles Handoff coordination, and publishes Alert.
"""

import argparse
import math
import os
import signal
import sys
import time


import rti.connextdds as dds
from air_traffic_types import NationalAirTrafficControl as ATC

AircraftPosition = ATC.AircraftPosition
AircraftTracking = ATC.AircraftTracking
Alert = ATC.Alert
AlertSeverity = ATC.AlertSeverity
AlertType = ATC.AlertType
ControllerInstruction = ATC.ControllerInstruction
ConvectiveCell = ATC.ConvectiveCell
ConvectiveSeverity = ATC.ConvectiveSeverity
FacilityStatus = ATC.FacilityStatus
FacilityType = ATC.FacilityType
FlightPhase = ATC.FlightPhase
FlightPlan = ATC.FlightPlan
Handoff = ATC.Handoff
HandoffStatus = ATC.HandoffStatus
InstructionType = ATC.InstructionType
NavStatus = ATC.NavStatus
PilotAcknowledgment = ATC.PilotAcknowledgment
from common import (
    bearing_deg,
    create_participant,
    create_publisher,
    create_subscriber,
    distance_nm,
    find_center_for_position,
    load_center_boundaries,
    load_center_config,
    load_qos_provider,
    load_tracon_for_airport,
    make_id,
    now_ms,
    point_in_polygon,
    polygon_bbox,
    read_sim_speed_from_discovery,
    reader_qos,
    setup_logging,
    writer_qos,
)
import common

log = setup_logging("center")

shutdown_flag = False


def signal_handler(_sig, _frame):
    global shutdown_flag
    shutdown_flag = True


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Pad bounding box generously so CFT captures aircraft approaching or
# exiting the boundary.  At max sim speed (50×) an aircraft moves ~0.14°/s,
# so 3° gives ~20 s of margin for handoff detection.
BBOX_PAD_DEG = 3.0


class EnRouteCenter:
    """Simulates an en-route ATC center managing a sector with geographic awareness."""

    def __init__(
        self,
        center_id: str,
        controller_id: str,
        boundary: list[list[float]],
        all_boundaries: dict[str, list[list[float]]],
        tracon_for_airport: dict[str, str],
        min_altitude_ft: int = 18000,
        max_altitude_ft: int = 60000,
        config_path: str = "",
    ):
        self.center_id = center_id
        self.controller_id = controller_id
        self.config_path = config_path
        self.min_alt = min_altitude_ft
        self.max_alt = max_altitude_ft
        self.boundary = boundary
        self.all_boundaries = all_boundaries
        self.tracon_for_airport = tracon_for_airport

        # Aircraft we are responsible for (accepted handoff)
        self.controlled_aircraft: dict[str, AircraftPosition] = {}
        # Timestamp of last position update per controlled aircraft
        self.last_seen: dict[str, float] = {}
        # Timestamp when each aircraft was first acquired (for grace period)
        self.acquired_at: dict[str, float] = {}
        # Aircraft we've already handed off (avoid re-triggering)
        self.handed_off: set[str] = set()
        # Pending handoff confirmations: tail → handoff_id
        self.pending_handoffs: dict[str, str] = {}
        # Aircraft we've confirmed inside our polygon (prevents premature handoff)
        self.seen_inside: set[str] = set()
        # Cooldown for separation alerts per aircraft pair
        self._sep_cooldown: dict[tuple[str, str], float] = {}
        # Aircraft we've already alerted about (avoid spam)
        self.alerted_uncoordinated: set[str] = set()
        # Grace period (seconds) before forwarding a never-entered aircraft
        self.NEVER_ENTERED_GRACE_S = 30.0
        # Startup grace: suppress uncoordinated alerts while handoffs settle
        self._startup_time = time.time()
        self.STARTUP_GRACE_S = 15.0

        # Compute bounding box for the CFT geographic filter
        min_lat, max_lat, min_lon, max_lon = polygon_bbox(boundary)
        self.bbox = (
            min_lat - BBOX_PAD_DEG,
            max_lat + BBOX_PAD_DEG,
            min_lon - BBOX_PAD_DEG,
            max_lon + BBOX_PAD_DEG,
        )

        # DDS setup
        self.qos_provider = load_qos_provider()
        dp_partitions = [
            f"OPS/ENROUTE/{center_id}",
            "OPS/ENROUTE/*",   # cross-center handoffs
            "OPS/FPS/*",
        ]
        self.participant = create_participant(
            self.qos_provider,
            dp_partitions=dp_partitions,
            participant_name=f"Center_{center_id}",
            app_name="ATC_Center",
        )

        self.publisher = create_publisher(self.participant)
        self.subscriber = create_subscriber(self.participant)

        # AircraftPosition reader — CFT by bounding box + altitude band
        pos_topic = dds.Topic(self.participant, "AircraftPosition", AircraftPosition)
        self.pos_cft = dds.ContentFilteredTopic(
            pos_topic,
            f"SectorTraffic_{center_id}",
            dds.Filter(
                "position.altitude_feet >= %0 AND position.altitude_feet < %1 "
                "AND position.latitude >= %2 AND position.latitude <= %3 "
                "AND position.longitude >= %4 AND position.longitude <= %5",
                [
                    str(min_altitude_ft),
                    str(max_altitude_ft),
                    str(self.bbox[0]),
                    str(self.bbox[1]),
                    str(self.bbox[2]),
                    str(self.bbox[3]),
                ],
            ),
        )
        self.pos_reader = dds.DataReader(
            self.subscriber, self.pos_cft,
            reader_qos(self.qos_provider, "AircraftPositionProfile"),
        )

        # ControllerInstruction writer
        instr_topic = dds.Topic(self.participant, "ControllerInstruction", ControllerInstruction)
        self.instr_writer = dds.DataWriter(
            self.publisher, instr_topic,
            writer_qos(self.qos_provider, "ControllerInstructionProfile"),
        )

        # PilotAcknowledgment reader
        ack_topic = dds.Topic(self.participant, "PilotAcknowledgment", PilotAcknowledgment)
        self.ack_reader = dds.DataReader(
            self.subscriber, ack_topic,
            reader_qos(self.qos_provider, "PilotAcknowledgmentProfile"),
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
            writer_qos(self.qos_provider, "AlertProfile"),
        )

        # FlightPlan reader
        fp_topic = dds.Topic(self.participant, "FlightPlan", FlightPlan)
        self.fp_reader = dds.DataReader(
            self.subscriber, fp_topic,
            reader_qos(self.qos_provider, "FlightPlanProfile"),
        )

        # AircraftTracking writer — publishes current controller of record
        tracking_topic = dds.Topic(self.participant, "AircraftTracking", AircraftTracking)
        self.tracking_writer = dds.DataWriter(
            self.publisher, tracking_topic,
            writer_qos(self.qos_provider, "AircraftTrackingProfile"),
        )

        # FacilityStatus writer — per-facility heartbeat & workload
        status_topic = dds.Topic(self.participant, "FacilityStatus", FacilityStatus)
        self.status_writer = dds.DataWriter(
            self.publisher, status_topic,
            writer_qos(self.qos_provider, "FacilityStatusProfile"),
        )
        self._publish_facility_status()

        # ConvectiveCell reader — en-route weather hazards from WeatherService
        cell_topic = dds.Topic(self.participant, "ConvectiveCell", ConvectiveCell)
        self.cell_reader = dds.DataReader(
            self.subscriber, cell_topic,
            reader_qos(self.qos_provider, "ConvectiveCellProfile"),
        )
        # Active weather cells (cell_id → ConvectiveCell sample)
        self._active_cells: dict[str, ConvectiveCell] = {}
        # Cooldown per aircraft for weather deviation instructions (avoid spamming)
        self._wx_deviation_cooldown: dict[str, float] = {}
        # Aircraft currently being vectored around weather (tail → True)
        self._wx_deviating: set[str] = set()
        # Cached flight plans by tail_number for waypoint lookup
        self._flight_plans: dict[str, FlightPlan] = {}

        log.info(
            "Center %s (%s) initialized — FL%d-FL%d, boundary=%d vertices, "
            "bbox=[%.1f,%.1f]×[%.1f,%.1f]",
            center_id, controller_id,
            min_altitude_ft // 100, max_altitude_ft // 100,
            len(boundary),
            self.bbox[0], self.bbox[1], self.bbox[2], self.bbox[3],
        )

    # ── Traffic monitoring ─────────────────────────────────────────────

    def monitor_traffic(self):
        """Read positions from CFT, classify as controlled / exiting / uncoordinated."""
        seen_this_cycle: set[str] = set()
        for sample in self.pos_reader.take_data():
            tail = sample.tail_number
            inside = point_in_polygon(
                sample.position.latitude, sample.position.longitude, self.boundary
            )

            if tail in self.controlled_aircraft:
                seen_this_cycle.add(tail)
                self.last_seen[tail] = time.time()
                # Always update position — we are the controller of record
                self.controlled_aircraft[tail] = sample
                # Detect weather deviation inherited from a previous controller
                if sample.nav_status == NavStatus.WEATHER_DEVIATION \
                        and tail not in self._wx_deviating:
                    self._wx_deviating.add(tail)
                    log.info(
                        "Inherited weather deviation for %s from previous controller",
                        tail,
                    )
                if inside:
                    self.seen_inside.add(tail)
                elif tail not in self.handed_off:
                    if tail in self.seen_inside:
                        # Was inside, now outside → hand off
                        self._handoff_exiting_aircraft(sample)
                    else:
                        # Never entered our polygon — after grace period, check
                        # if it's actually in another center and forward it
                        acq = self.acquired_at.get(tail, time.time())
                        if (time.time() - acq) > self.NEVER_ENTERED_GRACE_S:
                            neighbor = find_center_for_position(
                                sample.position.latitude, sample.position.longitude,
                                self.all_boundaries, exclude=self.center_id,
                            )
                            if neighbor:
                                log.info(
                                    "Aircraft %s never entered %s (in %s after %.0fs) — forwarding",
                                    tail, self.center_id, neighbor, time.time() - acq,
                                )
                                self._handoff_exiting_aircraft(sample)
            elif inside and tail not in self.controlled_aircraft and tail not in self.handed_off:
                # Aircraft in our polygon that we're not tracking → alert
                # (suppress during startup while handoffs settle)
                if tail not in self.alerted_uncoordinated and \
                        (time.time() - self._startup_time) > self.STARTUP_GRACE_S:
                    self._alert_uncoordinated(sample)

        # Check for controlled aircraft that disappeared from CFT (flew beyond bbox)
        now = time.time()
        stale_threshold = 3.0  # seconds without an update
        for tail in list(self.controlled_aircraft):
            if tail in self.handed_off or tail in seen_this_cycle:
                continue
            last_pos = self.controlled_aircraft[tail]
            last_t = self.last_seen.get(tail, 0)
            if last_pos is None or (now - last_t) <= stale_threshold:
                continue
            if tail in self.seen_inside:
                # Was inside our polygon and now lost from CFT → hand off
                log.info(
                    "Aircraft %s lost from CFT (beyond bbox) — initiating handoff from last position",
                    tail,
                )
                self._handoff_exiting_aircraft(last_pos)
            else:
                # Never entered our polygon — check if it's in another center
                neighbor = find_center_for_position(
                    last_pos.position.latitude, last_pos.position.longitude,
                    self.all_boundaries, exclude=self.center_id,
                )
                if neighbor:
                    log.info(
                        "Aircraft %s never entered %s, currently in %s — forwarding handoff",
                        tail, self.center_id, neighbor,
                    )
                    self._handoff_exiting_aircraft(last_pos)

        if self.controlled_aircraft:
            log.debug(
                "Center %s: controlling %d aircraft",
                self.center_id, len(self.controlled_aircraft),
            )

    # ── Separation checking ────────────────────────────────────────────

    _GROUND_PHASES = frozenset([
        FlightPhase.PREFLIGHT, FlightPhase.TAXI_OUT,
        FlightPhase.TAXI_IN, FlightPhase.PARKED,
    ])
    _SEP_COOLDOWN_S = 30  # suppress duplicate alerts for the same pair

    def check_separation(self):
        """Check for separation violations between controlled aircraft pairs.

        Skips ground-phase aircraft and suppresses duplicate alerts per pair.
        """
        airborne = [
            p for p in self.controlled_aircraft.values()
            if p is not None and p.flight_phase not in self._GROUND_PHASES
        ]
        now = time.time()
        for i, a in enumerate(airborne):
            for b in airborne[i + 1:]:
                lat_diff = abs(a.position.latitude - b.position.latitude)
                lon_diff = abs(a.position.longitude - b.position.longitude)
                alt_diff = abs(a.position.altitude_feet - b.position.altitude_feet)

                # Simplified separation check (5nm lateral ≈ 0.083°, 1000ft vertical)
                if lat_diff < 0.083 and lon_diff < 0.083 and alt_diff < 1000:
                    pair = tuple(sorted((a.tail_number, b.tail_number)))
                    cooldown = self._SEP_COOLDOWN_S / max(self._sim_speed, 0.1)
                    if now - self._sep_cooldown.get(pair, 0) < cooldown:
                        continue
                    self._sep_cooldown[pair] = now
                    log.warning(
                        "SEPARATION VIOLATION: %s and %s in %s",
                        a.tail_number, b.tail_number, self.center_id,
                    )
                    alert = Alert(
                        alert_id=make_id("ALERT-"),
                        alert_type=AlertType.TRAFFIC_CONFLICT,
                        severity=AlertSeverity.CRITICAL,
                        involved_aircraft=[a.tail_number, b.tail_number],
                        message=(
                            f"Separation violation between {a.tail_number} "
                            f"and {b.tail_number} in {self.center_id}"
                        ),
                        timestamp=now_ms(),
                    )
                    self.alert_writer.write(alert)

    # ── Handoff: exiting aircraft ──────────────────────────────────────

    def _handoff_exiting_aircraft(self, pos: AircraftPosition):
        """Initiate handoff for an aircraft leaving our polygon."""
        tail = pos.tail_number

        # If descending toward destination, hand to arrival TRACON
        if pos.position.altitude_feet < self.min_alt + 2000 and pos.vertical_speed_fpm < -500:
            tracon_id = self.tracon_for_airport.get(pos.destination_airport)
            if tracon_id:
                to_id = f"APP-{tracon_id}"
                to_type = FacilityType.TRACON
                log.info(
                    "Handoff %s → TRACON %s (descending, FL%d)",
                    tail, tracon_id, int(pos.position.altitude_feet) // 100,
                )
            else:
                log.warning("No TRACON for %s, skipping handoff of %s", pos.destination_airport, tail)
                return
        else:
            # Find neighboring center by position
            neighbor = find_center_for_position(
                pos.position.latitude, pos.position.longitude,
                self.all_boundaries, exclude=self.center_id,
            )
            if neighbor:
                to_id = f"CTR-{neighbor}"
                to_type = FacilityType.CENTER
                log.info(
                    "Handoff %s → Center %s (exiting %s boundary)",
                    tail, neighbor, self.center_id,
                )
            else:
                log.warning(
                    "Aircraft %s left %s but no neighboring center found at (%.2f, %.2f)",
                    tail, self.center_id, pos.position.latitude, pos.position.longitude,
                )
                # If the aircraft is weather-deviating and we can't hand it
                # off, clear the deviation now — keeping it on a fixed heading
                # into uncontrolled airspace is worse than resuming navigation.
                if tail in self._wx_deviating:
                    wp_name = self._find_forward_waypoint(tail, pos)
                    clearance_text = f"RESUME OWN NAV DIRECT {wp_name}" if wp_name else "RESUME OWN NAV"
                    instr = ControllerInstruction(
                        instruction_id=make_id("WX-CLR-"),
                        controller_id=self.controller_id,
                        tail_number=tail,
                        instruction_type=InstructionType.CLEARANCE,
                        clearance_text=clearance_text,
                        issued_at=now_ms(),
                    )
                    self.instr_writer.write(instr)
                    self._wx_deviating.discard(tail)
                    log.info(
                        "WEATHER CLEAR (no neighbor): %s — %s",
                        tail, clearance_text,
                    )
                return

        ho = Handoff(
            handoff_id=make_id("HO-"),
            tail_number=tail,
            from_controller_id=self.controller_id,
            to_controller_id=to_id,
            status=HandoffStatus.INITIATED,
            from_facility_type=FacilityType.CENTER,
            to_facility_type=to_type,
            sector=self.center_id,
            initiated_at=now_ms(),
        )
        self.ho_writer.write(ho)
        # Retain tracking — with SHARED_OWNERSHIP + BY_SOURCE_TIMESTAMP,
        # the accepting controller's write will supersede ours by timestamp.
        # We clean up when we see the ACCEPTED response.
        self.pending_handoffs[tail] = ho.handoff_id
        self.handed_off.add(tail)
        self.seen_inside.discard(tail)
        self._wx_deviating.discard(tail)

    # ── Handoff: accept incoming ───────────────────────────────────────

    def process_handoffs(self):
        """Accept incoming handoffs and process confirmations of outgoing ones."""
        for sample in self.ho_reader.take_data():
            if sample.to_controller_id == self.controller_id and \
               sample.status == HandoffStatus.INITIATED:
                from_type = ""
                if sample.from_facility_type is not None:
                    from_type = f" ({sample.from_facility_type.name})"
                log.info(
                    "Accepting handoff of %s from %s%s into %s",
                    sample.tail_number, sample.from_controller_id,
                    from_type, self.center_id,
                )
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
                # Begin tracking this aircraft
                self.controlled_aircraft[sample.tail_number] = None
                now = time.time()
                self.last_seen[sample.tail_number] = now
                self.acquired_at[sample.tail_number] = now
                self.handed_off.discard(sample.tail_number)
                self.seen_inside.discard(sample.tail_number)
                self.alerted_uncoordinated.discard(sample.tail_number)
                # Publish tracking — with SHARED_OWNERSHIP + BY_SOURCE_TIMESTAMP,
                # this newer sample immediately supersedes the old controller's at
                # all readers, regardless of arrival order.
                self._publish_tracking(sample.tail_number)

            elif sample.from_controller_id == self.controller_id and \
                 sample.status == HandoffStatus.ACCEPTED:
                # Our outgoing handoff was accepted — clean up local state
                tail = sample.tail_number
                if tail in self.pending_handoffs:
                    log.info(
                        "Handoff of %s accepted by %s — releasing",
                        tail, sample.to_controller_id,
                    )
                    del self.pending_handoffs[tail]
                    self._unregister_tracking(tail)
                    self.controlled_aircraft.pop(tail, None)
                    self.last_seen.pop(tail, None)
                    self.acquired_at.pop(tail, None)

    # ── AircraftTracking lifecycle ─────────────────────────────────────

    def _publish_facility_status(self):
        """Publish current facility status (heartbeat + workload)."""
        sample = FacilityStatus(
            facility_id=self.center_id,
            facility_type=FacilityType.CENTER,
            controller_id=self.controller_id,
            tracked_aircraft_count=len(self.controlled_aircraft),
            last_updated=now_ms(),
        )
        self.status_writer.write(sample)

    def _publish_tracking(self, tail_number: str):
        """Publish that we are now the controller of record for this aircraft."""
        sample = AircraftTracking(
            tail_number=tail_number,
            controller_id=self.controller_id,
            facility_id=self.center_id,
            facility_type=FacilityType.CENTER,
            acquired_at=now_ms(),
        )
        self.tracking_writer.write(sample)
        self._publish_facility_status()
        log.info("Tracking %s — controller of record: %s (%s)",
                 tail_number, self.controller_id, self.center_id)

    def _unregister_tracking(self, tail_number: str):
        """Unregister our tracking claim (hand off without disposing)."""
        sample = AircraftTracking(tail_number=tail_number)
        handle = self.tracking_writer.lookup_instance(sample)
        if handle is not None and handle.is_nil is False:
            self.tracking_writer.unregister_instance(handle)
            self._publish_facility_status()
            log.info("Unregistered tracking for %s", tail_number)
        else:
            log.debug("No tracking instance to unregister for %s", tail_number)

    # ── Uncoordinated traffic alert ────────────────────────────────────

    def _alert_uncoordinated(self, pos: AircraftPosition):
        """Publish alert for aircraft in our polygon without a handoff."""
        log.warning(
            "UNCOORDINATED: %s inside %s at (%.2f, %.2f) FL%d — no handoff received",
            pos.tail_number, self.center_id,
            pos.position.latitude, pos.position.longitude,
            int(pos.position.altitude_feet) // 100,
        )
        alert = Alert(
            alert_id=make_id("ALERT-"),
            alert_type=AlertType.UNAUTHORIZED_ENTRY,
            severity=AlertSeverity.WARNING,
            involved_aircraft=[pos.tail_number],
            message=(
                f"Uncoordinated traffic: {pos.tail_number} in {self.center_id} "
                f"at FL{int(pos.position.altitude_feet) // 100} — no handoff"
            ),
            timestamp=now_ms(),
        )
        self.alert_writer.write(alert)
        self.alerted_uncoordinated.add(pos.tail_number)

    # ── Flight plan caching ──────────────────────────────────────────

    def cache_flight_plans(self):
        """Cache flight plans from DDS for waypoint lookup during reroutes."""
        for sample in self.fp_reader.take_data():
            self._flight_plans[sample.tail_number] = sample

    # ── Weather hazard avoidance ──────────────────────────────────────

    _WX_DEVIATION_COOLDOWN_S = 30
    _WX_THREAT_FACTOR = 1.5  # deviate if within 1.5× cell radius

    def poll_weather_cells(self):
        """Read ConvectiveCell topic and maintain active-cells cache.

        Uses take() (not take_data()) so we can detect disposed instances
        (cell dissipated) via instance_state.
        """
        for sample in self.cell_reader.take():
            if sample.info.valid:
                data = sample.data
                self._active_cells[data.cell_id] = data
            else:
                # Instance disposed or not-alive — remove from cache
                # Try to identify cell_id via key_value / existing cache
                ist = sample.info.state.instance_state
                if ist != dds.InstanceState.ALIVE:
                    # Remove any cell whose instance handle matches
                    ih = sample.info.instance_handle
                    to_remove = [
                        cid for cid, c in self._active_cells.items()
                        if self.cell_reader.lookup_instance(ConvectiveCell(cell_id=cid)) == ih
                    ]
                    for cid in to_remove:
                        del self._active_cells[cid]
                        log.info("Weather cell %s dissipated", cid)

    def check_weather_cells(self):
        """Issue heading deviations for aircraft that are near active convective cells."""
        if not self._active_cells:
            return

        now = time.time()
        # Only deviate aircraft in climb/cruise.  Descending aircraft are
        # committed to arrival and will be handed to TRACON shortly — TRACON
        # has no weather-cell logic, so deviating here would strand them on
        # a fixed heading with no one to issue the CLEARANCE.
        airborne_phases = frozenset([
            FlightPhase.CLIMB, FlightPhase.CRUISE,
        ])

        for tail, pos in list(self.controlled_aircraft.items()):
            if pos is None or pos.flight_phase not in airborne_phases:
                continue
            # Skip aircraft already deviating — they'll be cleared by check_clear_of_weather
            if tail in self._wx_deviating:
                continue
            # Check cooldown
            wx_cooldown = self._WX_DEVIATION_COOLDOWN_S / max(self._sim_speed, 0.1)
            if now - self._wx_deviation_cooldown.get(tail, 0) < wx_cooldown:
                continue

            for cell in self._active_cells.values():
                # Altitude check — aircraft must be within the cell's vertical extent
                if pos.position.altitude_feet < cell.base_altitude_ft or \
                   pos.position.altitude_feet > cell.top_altitude_ft:
                    continue

                dist = distance_nm(
                    pos.position.latitude, pos.position.longitude,
                    cell.center_latitude, cell.center_longitude,
                )
                threat_radius = cell.radius_nm * self._WX_THREAT_FACTOR

                if dist < threat_radius:
                    # Compute deviation heading: perpendicular to bearing toward cell
                    bearing_to_cell = bearing_deg(
                        pos.position.latitude, pos.position.longitude,
                        cell.center_latitude, cell.center_longitude,
                    )
                    # Deviate 90° to the right of the cell bearing
                    deviation_hdg = (bearing_to_cell + 90) % 360

                    instr = ControllerInstruction(
                        instruction_id=make_id("WX-INSTR-"),
                        controller_id=self.controller_id,
                        tail_number=tail,
                        instruction_type=InstructionType.HEADING,
                        assigned_heading_degrees=deviation_hdg,
                        clearance_text=(
                            f"DEVIATE HDG {int(deviation_hdg)} — "
                            f"WX cell {cell.cell_id} {cell.severity.name} "
                            f"at {dist:.0f}nm"
                        ),
                        issued_at=now_ms(),
                    )
                    self.instr_writer.write(instr)
                    self._wx_deviation_cooldown[tail] = now
                    self._wx_deviating.add(tail)

                    # Publish WEATHER_DEVIATION alert
                    alert = Alert(
                        alert_id=make_id("ALERT-"),
                        alert_type=AlertType.WEATHER_DEVIATION,
                        severity=(
                            AlertSeverity.CRITICAL
                            if cell.severity == ConvectiveSeverity.EXTREME
                            else AlertSeverity.WARNING
                        ),
                        involved_aircraft=[tail],
                        message=(
                            f"Weather deviation: {tail} rerouted HDG "
                            f"{int(deviation_hdg)} around {cell.severity.name} "
                            f"cell {cell.cell_id} ({dist:.0f}nm)"
                        ),
                        timestamp=now_ms(),
                    )
                    self.alert_writer.write(alert)

                    log.warning(
                        "WEATHER DEVIATION: %s → HDG %d (cell %s %s at %.0fnm)",
                        tail, int(deviation_hdg), cell.cell_id,
                        cell.severity.name, dist,
                    )
                    break  # one deviation per aircraft per cycle

    def check_clear_of_weather(self):
        """For each deviating aircraft, check if it's now clear of all cells.
        If clear, issue a CLEARANCE instruction to resume own navigation
        direct a forward waypoint along the filed route.
        """
        if not self._wx_deviating:
            return

        cleared = []
        for tail in list(self._wx_deviating):
            pos = self.controlled_aircraft.get(tail)
            if pos is None:
                # Aircraft no longer controlled (handed off) — clean up
                cleared.append(tail)
                continue

            # Check against every active cell
            still_threatened = False
            for cell in self._active_cells.values():
                if pos.position.altitude_feet < cell.base_altitude_ft or \
                   pos.position.altitude_feet > cell.top_altitude_ft:
                    continue
                dist = distance_nm(
                    pos.position.latitude, pos.position.longitude,
                    cell.center_latitude, cell.center_longitude,
                )
                # Clear when beyond 2× cell radius (safe margin beyond the 1.5× trigger)
                if dist < cell.radius_nm * 2.0:
                    still_threatened = True
                    break

            if not still_threatened:
                cleared.append(tail)
                # Find the forward waypoint from cached flight plan
                wp_name = self._find_forward_waypoint(tail, pos)
                clearance_text = f"RESUME OWN NAV DIRECT {wp_name}" if wp_name else "RESUME OWN NAV"
                instr = ControllerInstruction(
                    instruction_id=make_id("WX-CLR-"),
                    controller_id=self.controller_id,
                    tail_number=tail,
                    instruction_type=InstructionType.CLEARANCE,
                    clearance_text=clearance_text,
                    issued_at=now_ms(),
                )
                self.instr_writer.write(instr)
                log.info(
                    "WEATHER CLEAR: %s — %s",
                    tail, clearance_text,
                )

        for tail in cleared:
            self._wx_deviating.discard(tail)

    def _find_forward_waypoint(self, tail: str, pos) -> str | None:
        """Find the first waypoint along the filed route that is ahead of
        the aircraft's current position (closer to destination).
        """
        fp = self._flight_plans.get(tail)
        if not fp or not fp.waypoints:
            return None

        dest_lat = pos.destination_airport  # need coords
        # Use the last waypoint (ARRIVE) as destination reference
        dest_wp = fp.waypoints[-1]
        dest_lat_v = dest_wp.position.latitude
        dest_lon_v = dest_wp.position.longitude
        my_dist = distance_nm(
            pos.position.latitude, pos.position.longitude,
            dest_lat_v, dest_lon_v,
        )

        for wp in fp.waypoints:
            wp_dist = distance_nm(
                wp.position.latitude, wp.position.longitude,
                dest_lat_v, dest_lon_v,
            )
            if wp_dist < my_dist:
                return wp.name

        # All waypoints behind us — go direct destination
        return fp.waypoints[-1].name

    # ── Misc ───────────────────────────────────────────────────────────

    def process_acknowledgments(self):
        for sample in self.ack_reader.take_data():
            log.debug("ACK from %s: %s", sample.tail_number, sample.status.name)

    def run(self, duration_s: float = 120.0):
        """Main center control loop at ~1 Hz."""
        log.info("En-route center %s operational", self.center_id)
        start = time.time()
        self._sim_speed = 1.0

        while not shutdown_flag and (time.time() - start) < duration_s:
            self._sim_speed = read_sim_speed_from_discovery(
                self.participant, self.config_path,
            )
            self.process_handoffs()
            self.monitor_traffic()
            self.check_separation()
            self.cache_flight_plans()
            self.poll_weather_cells()
            self.check_weather_cells()
            self.check_clear_of_weather()
            self.process_acknowledgments()
            self.status_writer.assert_liveliness()
            time.sleep(1.0)

        log.info("Center %s shutting down — controlled %d, handed off %d, alerts %d",
                 self.center_id, len(self.controlled_aircraft),
                 len(self.handed_off), len(self.alerted_uncoordinated))


def main():
    parser = argparse.ArgumentParser(description="ATC En-Route Center")
    parser.add_argument("--config", required=True, help="Path to scenario config JSON")
    parser.add_argument("--qos-file", required=True, help="Path to QoS XML file")
    parser.add_argument("--center-id", default="ZNY", help="Center ID")
    parser.add_argument("--controller-id", default=None, help="Controller ID (default: CTR-<center-id>)")
    parser.add_argument("--min-alt", type=int, default=None, help="Min altitude ft (default: from config)")
    parser.add_argument("--max-alt", type=int, default=None, help="Max altitude ft (default: from config)")
    parser.add_argument("--duration", type=float, default=120.0, help="Duration in seconds")
    args = parser.parse_args()

    common.QOS_FILE = args.qos_file

    cfg = load_center_config(args.center_id, args.config)
    controller_id = args.controller_id or f"CTR-{args.center_id}"

    global log
    log = setup_logging(controller_id)
    min_alt = args.min_alt if args.min_alt is not None else cfg.get("min_altitude_ft", 18000)
    max_alt = args.max_alt if args.max_alt is not None else cfg.get("max_altitude_ft", 60000)

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
    center.run(duration_s=args.duration)
    center.participant.close()


if __name__ == "__main__":
    main()
