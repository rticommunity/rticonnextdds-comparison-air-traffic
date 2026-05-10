# Dashboard Application — Specification

> This document fully specifies `app_dashboard.py` so that an AI agent or
> developer can re-create it from scratch.

---

## 1  Purpose

A real-time web dashboard for full-system ATC observability.  Subscribes to
all 11 pub/sub topics, publishes `ConvectiveCell` for manual weather injection,
and spawns aircraft subprocesses on demand.

Renders a full-screen Leaflet.js dark map with aircraft icons, flight trails,
airport markers, weather popups, convective cell circles, route lines, center
boundary polygons, and a collapsible side panel with data tables.

---

## 2  Technology Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| Web Framework | Flask (single file, inline HTML template) |
| Real-time | Server-Sent Events (SSE) at 1 Hz |
| Map | Leaflet.js 1.9.4 (CDN) |
| Middleware | RTI Connext DDS 7.7.0+ (`rti.connextdds`) |
| Concurrency | `threading` (DDS poll thread + Flask server) |
| Subprocess | `subprocess.Popen` (dynamic aircraft spawning) |

---

## 3  Command-Line Interface

```
python app_dashboard.py --config CONFIG --qos-file QOS_XML [options]
```

| Argument | Type | Default | Description |
|---|---|---|---|
| `--config` | str (required) | — | Path to `air_traffic_scenario.json` |
| `--qos-file` | str (required) | — | Path to `air_traffic_qos.xml` |
| `--port` | int | `8050` | Flask HTTP port |
| `--duration` | float | `3600.0` | Duration (not strictly enforced; Flask runs until killed) |

---

## 4  Architecture

```
┌──────────────────┐      ┌───────────────┐      ┌────────────┐
│  DDS Poll Thread │─────►│  Shared State │◄─────│   Flask    │
│  (take samples)  │      │  (dict + lock)│      │   /stream  │
│  0.25s interval  │      │               │      │   SSE 1Hz  │
└──────────────────┘      └───────────────┘      └────────────┘
```

### 4.1  Shared State (`state` dict, protected by `state_lock`)

| Key | Type | Description |
|---|---|---|
| `positions` | `dict[str, dict]` | Tail → position dict |
| `trails` | `defaultdict[str, deque]` | Tail → last 60 `[lat, lon]` points |
| `weather` | `dict[str, dict]` | Airport → weather dict |
| `runways` | `dict[str, dict]` | `"airport/runway"` → runway dict |
| `flight_plans` | `dict[str, dict]` | Plan ID → flight plan dict |
| `alerts` | `list[dict]` | Alert history (unbounded) |
| `handoffs` | `list[dict]` | Handoff history (unbounded) |
| `instructions` | `list[dict]` | Instruction history |
| `acks` | `list[dict]` | Acknowledgment history |
| `counters` | `defaultdict[str, int]` | Topic → sample count |
| `tracking` | `dict[str, dict]` | Tail → tracking dict |
| `handoff_log` | `deque[dict]` | Last 50 handoffs |
| `pending_pulses` | `list[str]` | Center IDs to pulse on map |
| `facility_status` | `dict[str, dict]` | Facility → status dict |
| `convective_cells` | `dict[str, dict]` | Cell ID → cell dict |

---

## 5  DDS Initialisation

### 5.1  DP Partitions

- `OPS/*` — global wildcard; discovers all `OPS/` endpoints

### 5.2  Topic Subscriptions (11 topics)

All topics in `TOPIC_MAP` are subscribed via a single reader per topic:

| Topic | Type | QoS Profile |
|---|---|---|
| `AircraftPosition` | `AircraftPosition` | `AircraftPositionProfile` |
| `ControllerInstruction` | `ControllerInstruction` | `ControllerInstructionProfile` |
| `PilotAcknowledgment` | `PilotAcknowledgment` | `PilotAcknowledgmentProfile` |
| `FlightPlan` | `FlightPlan` | `FlightPlanProfile` |
| `RunwayStatus` | `RunwayStatus` | `RunwayStatusProfile` |
| `WeatherReport` | `WeatherReport` | `WeatherReportProfile` |
| `Handoff` | `Handoff` | `HandoffProfile` |
| `Alert` | `Alert` | `AlertProfile` |
| `AircraftTracking` | `AircraftTracking` | `AircraftTrackingProfile` |
| `FacilityStatus` | `FacilityStatus` | `FacilityStatusProfile` |
| `ConvectiveCell` | `ConvectiveCell` | `ConvectiveCellProfile` |

### 5.3  ConvectiveCell Writer

A `DataWriter` for `ConvectiveCell` enables manual weather cell injection from the dashboard UI.

---

## 6  DDS Polling Thread (`dds_poll_loop`)

Background daemon thread, 0.25s interval. Uses `take_data()` for most topics, `take()` for `FacilityStatus` and `ConvectiveCell` to detect instance state changes.

### 6.1  Special Handling

- **FacilityStatus:** Tracks `publication_handle → facility_id` mapping.
  Detects NOT_ALIVE instances to mark facilities as OFFLINE.
- **ConvectiveCell:** Detects disposed instances (dissipated cells) and removes
  them from the shared state.
- **Handoff:** On ACCEPTED handoffs to a CENTER, adds center ID to
  `pending_pulses` for map animation.

---

## 7  Flask Routes

### 7.1  `GET /` — Main Page

Returns inline HTML template with Leaflet.js map, CSS, and JavaScript.

### 7.2  `GET /stream` — SSE Endpoint

Returns `text/event-stream` response, sending JSON snapshot every 1 second.

### 7.3  `POST /speed` — Set Simulation Speed

Accepts `{"speed": N}`. Updates participant property and persists to config JSON.

### 7.4  `GET /speed` — Get Simulation Speed

Returns `{"speed": N}`.

### 7.5  `GET /airports` — List Airports

Returns `{"airports": ["KJFK", ...]}`.

### 7.6  `POST /weather_cell` — Create Weather Cell

Accepts: `{lat, lon, radius, severity, top_alt, base_alt, heading, speed, duration_min}`.
Validates parameters, publishes `ConvectiveCell` sample, starts background thread
to auto-dispose after `duration_min` sim-minutes.

### 7.7  `DELETE /weather_cell/<cell_id>` — Remove Weather Cell

Disposes a dashboard-injected cell. Returns 404 if not dashboard-injected.

### 7.8  `POST /aircraft` — Spawn Aircraft

Accepts: `{callsign, origin, destination}`. Launches `app_airplane.py` as subprocess.
Returns 409 if callsign already running.

### 7.9  `GET /aircraft` — List Spawned Aircraft

Returns status of dynamically spawned aircraft subprocesses.

---

## 8  SSE Snapshot (`_snapshot`)

JSON payload sent each second:

| Field | Content |
|---|---|
| `positions` | All aircraft position dicts |
| `trails` | Tail → `[[lat,lon], ...]` (last 60 points) |
| `weather` | All weather dicts |
| `flight_plans` | All flight plan dicts |
| `alerts` | Last 20 alerts |
| `counters` | Sample counts per topic |
| `tracking` | All tracking dicts |
| `handoff_log` | Last 50 handoffs |
| `pulse_centers` | Center IDs for map pulse animation |
| `facility_status` | Sorted facility status list (CENTER → TRACON → TOWER) |
| `convective_cells` | All active cell dicts |
| `kpi` | `{aircraft, flight_plans, airports, total_alerts}` |

---

## 9  Frontend (Inline HTML)

The entire frontend is an inline HTML string (`HTML_PAGE`) rendered via
`render_template_string()`. Template variables: `airports_json`, `centers_json`,
`tracons_json` (injected from scenario config at startup).

### 9.1  Map Features

- Dark tile layer (CartoDB dark_matter)
- Aircraft markers with rotation (Leaflet DivIcon, CSS-rotated ✈ emoji)
- Flight trail polylines (last 60 positions)
- Airport markers with weather popups
- Route lines (from flight plan waypoints)
- Center boundary polygons (dashed cyan outline)
- TRACON radius circles
- Convective cell circles (color-coded by severity)
- Pulse animation on center polygon when handoff accepted

### 9.2  Side Panel

Collapsible sections:
- Aircraft table (tail, callsign, alt, speed, phase, gate, fuel, nav)
- Facility Status (facility, type, status, tracked count)
- Alerts (severity, type, aircraft, message)
- Handoff Log (tail, from, to, status)
- Weather (airport, condition, wind, vis, ceiling, temp)
- Flight Plans (callsign, route, status)
- DDS Sample Counters (topic → count)
- Add Weather Cell form
- Add Aircraft form

### 9.3  Top Bar

- Logo
- KPI badges (aircraft, flight plans, airports, alerts)
- Simulation speed slider (0.1×–50×)

---

## 10  Subprocess Management

### Spawned Aircraft

- Launched via `subprocess.Popen` with `--duration 3600`.
- Tracked in `_spawned_procs` dict (callsign → Popen).
- `atexit` handler terminates all spawned processes on dashboard shutdown.

### Injected Weather Cells

- Tracked in `_injected_cells` set and `_cell_cancel` dict (cell_id → Event).
- Background thread auto-disposes after `duration_min` sim-minutes.
- `DELETE` route sets cancel event and disposes immediately.

---

## 11  Thread Summary

| Thread | Description |
|---|---|
| Main | Flask HTTP server |
| DDS Poll | `dds_poll_loop()` — background daemon, 0.25s interval |
| Cell timers | One daemon thread per injected weather cell (auto-dispose) |

---

## 12  File Structure

Single file: `app_dashboard.py` (1,736 lines including inline HTML/CSS/JS)

### Imports from `air_traffic_types.py`

All 11 topic types plus `ConvectiveSeverity`

### Imports from `common.py`

`create_participant`, `create_publisher`, `create_subscriber`,
`load_qos_provider`, `make_id`, `now_ms`, `reader_qos`, `writer_qos`
