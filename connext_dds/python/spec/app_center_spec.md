# En-Route Center Application — Specification

> This document fully specifies `app_center.py` so that an AI agent or
> developer can re-create it from scratch.  It assumes access to the IDL
> types (`air_traffic_types.idl`), the generated Python types
> (`air_traffic_types.py`), the QoS profiles (`air_traffic_qos.xml`), and
> the shared utilities (`common.py`).

---

## 1  Purpose

An en-route ATC center simulator managing aircraft transiting between
airports at high altitude (FL180–FL600).  Each center defines a geographic
boundary polygon and uses a two-layer filtering approach:

1. **DDS CFT** with a padded rectangular bounding box + altitude band —
   infrastructure-level filtering.
2. **Application-level** point-in-polygon check for precise boundary
   awareness.

Aircraft are tracked only after an explicit handoff is accepted.
Uncoordinated aircraft inside the polygon trigger alerts.  Exiting
aircraft are handed to the neighboring center (by polygon lookup) or to
the arrival TRACON (if descending).  The center also monitors convective
weather cells and reroutes aircraft around them.

---

## 2  Technology Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| Middleware | RTI Connext DDS 7.7.0+ (`rti.connextdds`) |
| Type generation | `rtiddsgen -language python air_traffic_types.idl` → `air_traffic_types.py` |
| QoS configuration | `air_traffic_qos.xml` |
| Math | `math` (bearing, distance) |
| Logging | Python `logging` via `common.setup_logging()` |

---

## 3  Command-Line Interface

```
python app_center.py --config CONFIG --qos-file QOS_XML [options]
```

| Argument | Type | Default | Description |
|---|---|---|---|
| `--config` | str (required) | — | Path to `air_traffic_scenario.json` |
| `--qos-file` | str (required) | — | Path to `air_traffic_qos.xml` |
| `--center-id` | str | `ZNY` | Center ID |
| `--controller-id` | str | `CTR-<center_id>` | Controller identifier |
| `--min-alt` | int | from config | Minimum altitude in feet |
| `--max-alt` | int | from config | Maximum altitude in feet |
| `--duration` | float | `120.0` | Duration in wall-clock seconds |

At startup `main()`:

1. Parses arguments, sets `common.QOS_FILE`.
2. Loads center config (boundary, altitude limits).
3. Loads all center boundaries for cross-center polygon lookups.
4. Loads TRACON-for-airport mapping.
5. Derives controller ID: `CTR-<center_id>`.
6. Creates `EnRouteCenter(...)` and calls `run()`.

---

## 4  `EnRouteCenter` Class — State & Attributes

### 4.1  Constants

| Constant | Value | Description |
|---|---|---|
| `BBOX_PAD_DEG` | `3.0` | Bounding box padding for CFT (module-level) |
| `NEVER_ENTERED_GRACE_S` | `30.0` | Seconds before forwarding a never-entered aircraft |
| `_SEP_COOLDOWN_S` | `30` | Suppress duplicate separation alerts |
| `_WX_DEVIATION_COOLDOWN_S` | `30` | Cooldown between weather deviations per aircraft |
| `_WX_THREAT_FACTOR` | `1.5` | Deviate if within 1.5× cell radius |

### 4.2  Identity & Configuration

| Attribute | Type | Description |
|---|---|---|
| `center_id` | `str` | Center ID (e.g., `ZNY`) |
| `controller_id` | `str` | Controller name (e.g., `CTR-ZNY`) |
| `min_alt` | `int` | Minimum altitude in feet (default 18000) |
| `max_alt` | `int` | Maximum altitude in feet (default 60000) |
| `boundary` | `list[list[float]]` | Polygon as `[[lat, lon], ...]` |
| `all_boundaries` | `dict[str, list]` | All center polygons for neighbor lookup |
| `tracon_for_airport` | `dict[str, str]` | Airport code → TRACON ID mapping |
| `bbox` | `tuple[float, float, float, float]` | Padded bounding box `(min_lat, max_lat, min_lon, max_lon)` |

### 4.3  Traffic State

| Attribute | Type | Description |
|---|---|---|
| `controlled_aircraft` | `dict[str, AircraftPosition \| None]` | Tail → last position (or `None` if just accepted, no position yet) |
| `last_seen` | `dict[str, float]` | Tail → wall-clock time of last position update |
| `acquired_at` | `dict[str, float]` | Tail → wall-clock time of handoff acceptance |
| `handed_off` | `set[str]` | Tails already handed off |
| `pending_handoffs` | `dict[str, str]` | Tail → handoff_id awaiting ACCEPTED |
| `seen_inside` | `set[str]` | Aircraft confirmed inside polygon (prevents premature handoff) |
| `_sep_cooldown` | `dict[tuple, float]` | Separation alert cooldown per pair |
| `alerted_uncoordinated` | `set[str]` | Tails already alerted for unauthorized entry |
| `_sim_speed` | `float` | Current simulation speed |

### 4.4  Weather State

| Attribute | Type | Description |
|---|---|---|
| `_active_cells` | `dict[str, ConvectiveCell]` | `cell_id` → active cell sample |
| `_wx_deviation_cooldown` | `dict[str, float]` | Tail → last deviation time |
| `_wx_deviating` | `set[str]` | Aircraft currently being vectored around weather |
| `_flight_plans` | `dict[str, FlightPlan]` | Cached flight plans by `tail_number` |

### 4.5  DDS Entities

| Attribute | Type | Description |
|---|---|---|
| `participant` | `dds.DomainParticipant` | Single participant |
| `pos_reader` | `dds.DataReader` | Reads `AircraftPosition` (CFT: bbox + altitude) |
| `instr_writer` | `dds.DataWriter` | Writes `ControllerInstruction` |
| `ack_reader` | `dds.DataReader` | Reads `PilotAcknowledgment` |
| `ho_writer` | `dds.DataWriter` | Writes `Handoff` |
| `ho_reader` | `dds.DataReader` | Reads `Handoff` (CFT) |
| `alert_writer` | `dds.DataWriter` | Writes `Alert` |
| `fp_reader` | `dds.DataReader` | Reads `FlightPlan` |
| `tracking_writer` | `dds.DataWriter` | Writes `AircraftTracking` |
| `status_writer` | `dds.DataWriter` | Writes `FacilityStatus` |
| `cell_reader` | `dds.DataReader` | Reads `ConvectiveCell` |

---

## 5  DDS Initialisation

### 5.1  DP Partitions

- `OPS/ENROUTE/<center_id>` — own scope
- `OPS/ENROUTE/*` — cross-center handoff discovery
- `OPS/FPS/*` — discovers Flight Plan Service

### 5.2  Content-Filtered Topics

| CFT Name | Base Topic | Filter | Parameters |
|---|---|---|---|
| `SectorTraffic_<id>` | `AircraftPosition` | `altitude >= %0 AND altitude < %1 AND lat >= %2 AND lat <= %3 AND lon >= %4 AND lon <= %5` | `[min_alt, max_alt, bbox_min_lat, bbox_max_lat, bbox_min_lon, bbox_max_lon]` |
| `MyHandoffs_<id>` | `Handoff` | `to_controller_id = '<id>' OR from_controller_id = '<id>'` | — |

The bounding box is padded by `BBOX_PAD_DEG = 3.0°` beyond the polygon
extremes to ensure aircraft are seen before they enter and after they exit.

### 5.3  Initialisation Actions

1. Publish initial `FacilityStatus` (heartbeat).

---

## 6  Traffic Monitoring (`monitor_traffic`)

The most complex method in the application. Takes position samples from the CFT
and classifies each aircraft into one of several categories:

### 6.1  Controlled Aircraft (in `controlled_aircraft`)

For each controlled aircraft:
1. Update position and `last_seen` timestamp.
2. Detect inherited weather deviation (`nav_status == WEATHER_DEVIATION`).
3. **Inside polygon** → add to `seen_inside`.
4. **Outside polygon + not handed off:**
   - If previously `seen_inside` → initiate handoff (§8).
   - If never entered (not in `seen_inside`) and grace period expired (30 sim-seconds) →
     look up correct center via `find_center_for_position()` and forward.

### 6.2  Uncoordinated Aircraft

Aircraft inside the polygon that are NOT in `controlled_aircraft` and NOT in
`handed_off` → publish `UNAUTHORIZED_ENTRY` alert (§10).

### 6.3  Stale Aircraft Detection

After processing samples, check for controlled aircraft missing from the
current cycle (no update for > 3 seconds):
- If `seen_inside` → hand off from last known position.
- If never entered → look up neighbor center and forward.

---

## 7  Separation Checking (`check_separation`)

Same algorithm as TRACON but with en-route separation standards:
- **5 nm lateral** (≈ 0.083°) and **1,000 ft vertical**.
- Alert severity: `CRITICAL` (vs TRACON's `WARNING`).
- Cooldown: `30 / sim_speed` seconds per pair.
- Skips ground-phase aircraft.

---

## 8  Handoff: Exiting Aircraft (`_handoff_exiting_aircraft`)

Determines handoff target based on aircraft state:

### 8.1  To TRACON (Descending)

Condition: altitude < `min_alt + 2000` AND vertical speed < −500 fpm.
- Look up arrival TRACON from `tracon_for_airport[destination]`.
- `to_controller_id = APP-<tracon_id>`, `to_facility_type = TRACON`.

### 8.2  To Neighboring Center (Lateral Exit)

Condition: not descending to arrival.
- Look up neighbor via `find_center_for_position()` excluding self.
- `to_controller_id = CTR-<neighbor>`, `to_facility_type = CENTER`.
- If no neighbor found → log warning and return (no handoff).

### 8.3  Weather Deviation Cleanup on Handoff

When handing off an aircraft, discard weather deviation state.
If no neighbor found and aircraft is weather-deviating, issue a CLEARANCE
to resume own navigation (can't strand aircraft on fixed heading).

### 8.4  Post-Handoff Actions

- Write `Handoff` with `status = INITIATED`.
- Add to `pending_handoffs` and `handed_off`.
- Remove from `seen_inside` and `_wx_deviating`.

---

## 9  Handoff: Accept Incoming (`process_handoffs`)

Takes all samples from the handoff CFT reader:

- **Incoming INITIATED:** Accept by writing `ACCEPTED`. Initialise tracking:
  `controlled_aircraft[tail] = None`, set `last_seen` and `acquired_at` to now,
  clear any prior `handed_off` / `seen_inside` / `alerted_uncoordinated` state.
  Publish `AircraftTracking`.
- **Outgoing ACCEPTED:** Remove from `pending_handoffs`, unregister tracking,
  remove from `controlled_aircraft`, `last_seen`, `acquired_at`.

---

## 10  Uncoordinated Traffic Alert (`_alert_uncoordinated`)

Publishes `Alert` with:
- `alert_type = UNAUTHORIZED_ENTRY`, `severity = WARNING`
- Message includes tail, center ID, position, flight level.
- Adds tail to `alerted_uncoordinated` (prevents duplicate alerts).

---

## 11  Weather Hazard Avoidance

### 11.1  Cell Polling (`poll_weather_cells`)

Uses `cell_reader.take()` (not `take_data()`) to detect disposed instances:
- Valid samples → update `_active_cells`.
- Not-alive instances → remove from `_active_cells` (cell dissipated).

### 11.2  Weather Deviation (`check_weather_cells`)

For each controlled aircraft in `CLIMB` or `CRUISE` phase (not descending):
1. Skip if already deviating or in cooldown.
2. For each active cell: check altitude overlap and distance.
3. If distance < `cell.radius_nm × 1.5` → issue HEADING instruction:
   - Deviation heading: 90° to the right of bearing toward cell center.
   - Mark aircraft as deviating.
   - Publish `WEATHER_DEVIATION` alert (CRITICAL if EXTREME cell, else WARNING).

**Note:** Descending aircraft are NOT deviated — they are committed to arrival
and will be handed to TRACON shortly. TRACON has no weather-cell logic, so
deviating here would strand them.

### 11.3  Weather Clearance (`check_clear_of_weather`)

For each deviating aircraft:
1. Check distance to ALL active cells.
2. If clear of all cells (beyond 2× cell radius) → issue CLEARANCE:
   - `RESUME OWN NAV DIRECT <forward_waypoint>` (from cached flight plan).
   - Remove from `_wx_deviating`.

### 11.4  Forward Waypoint Lookup (`_find_forward_waypoint`)

From the cached flight plan, find the first waypoint that is closer to the
destination than the aircraft's current position. If all waypoints are behind
→ return the last waypoint (ARRIVE).

---

## 12  Flight Plan Caching (`cache_flight_plans`)

Takes all flight plan samples and stores in `_flight_plans[tail_number]`.
Used by weather clearance logic to find forward waypoints.

---

## 13  AircraftTracking Lifecycle

Same pattern as Tower/TRACON:
- `_publish_tracking()` → writes sample with `facility_type = CENTER`.
- `_unregister_tracking()` → unregisters instance.
- `_publish_facility_status()` → writes `FacilityStatus` with tracked count.

---

## 14  Main Run Loop (`run`)

Loop at ~1 Hz until `shutdown_flag` or `duration_s` elapsed:

1. Read `sim_speed` via `read_sim_speed_from_discovery()`.
2. `process_handoffs()` — accept incoming before monitoring
3. `monitor_traffic()`
4. `check_separation()`
5. `cache_flight_plans()`
6. `poll_weather_cells()`
7. `check_weather_cells()`
8. `check_clear_of_weather()`
9. `process_acknowledgments()`
10. `status_writer.assert_liveliness()`

**Note:** `process_handoffs()` is called **before** `monitor_traffic()` so that
newly accepted aircraft are in `controlled_aircraft` when positions arrive.

---

## 15  Signal Handling

Global `shutdown_flag` set by `SIGINT` and `SIGTERM`.

---

## 16  Thread Summary

| Thread | Description |
|---|---|
| Main | `run()` — control loop at 1 Hz |

Single-threaded application.

---

## 17  File Structure

Single file: `app_center.py`

### Imports from `air_traffic_types.py`

`AircraftPosition`, `AircraftTracking`, `Alert`, `AlertSeverity`, `AlertType`,
`ControllerInstruction`, `ConvectiveCell`, `ConvectiveSeverity`,
`FacilityStatus`, `FacilityType`, `FlightPhase`, `FlightPlan`, `Handoff`,
`HandoffStatus`, `InstructionType`, `NavStatus`, `PilotAcknowledgment`

### Imports from `common.py`

`bearing_deg`, `create_participant`, `create_publisher`, `create_subscriber`,
`distance_nm`, `find_center_for_position`, `load_center_boundaries`,
`load_center_config`, `load_qos_provider`, `load_tracon_for_airport`,
`make_id`, `now_ms`, `point_in_polygon`, `polygon_bbox`,
`read_sim_speed_from_discovery`, `reader_qos`, `setup_logging`, `writer_qos`
