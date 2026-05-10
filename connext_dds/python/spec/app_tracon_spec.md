# TRACON Application — Specification

> This document fully specifies `app_tracon.py` so that an AI agent or
> developer can re-create it from scratch.  It assumes access to the IDL
> types (`air_traffic_types.idl`), the generated Python types
> (`air_traffic_types.py`), the QoS profiles (`air_traffic_qos.xml`), and
> the shared utilities (`common.py`).

---

## 1  Purpose

A Terminal Radar Approach Control (TRACON) simulator managing aircraft in
the terminal area (~500–18,000 ft AGL) around one or more airports.
Sequences arrivals with speed instructions, hands departures up to the
en-route center, hands arrivals down to the tower, checks for separation
violations, and publishes alerts.

---

## 2  Technology Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| Middleware | RTI Connext DDS 7.7.0+ (`rti.connextdds`) |
| Type generation | `rtiddsgen -language python air_traffic_types.idl` → `air_traffic_types.py` |
| QoS configuration | `air_traffic_qos.xml` |
| Logging | Python `logging` via `common.setup_logging()` |

No Request/Reply — TRACON uses only pub/sub topics.

---

## 3  Command-Line Interface

```
python app_tracon.py --config CONFIG --qos-file QOS_XML [options]
```

| Argument | Type | Default | Description |
|---|---|---|---|
| `--config` | str (required) | — | Path to `air_traffic_scenario.json` |
| `--qos-file` | str (required) | — | Path to `air_traffic_qos.xml` |
| `--tracon-id` | str | `N90` | TRACON facility ID |
| `--controller-id` | str | `APP-<tracon_id>` | Controller identifier |
| `--airports` | str[] | from config | Airport codes served |
| `--serving-center` | str | from config | Overlying en-route center |
| `--duration` | float | `120.0` | Duration in wall-clock seconds |

At startup `main()`:

1. Parses arguments, sets `common.QOS_FILE`.
2. Loads `AIRPORT_COORDS` from scenario config.
3. Loads TRACON config (derives served airports via reverse-lookup).
4. Derives controller ID: `APP-<tracon_id>`.
5. Creates `TraconController(...)` and calls `run()`.

---

## 4  `TraconController` Class — State & Attributes

### 4.1  Constants

| Constant | Value | Description |
|---|---|---|
| `MIN_ALT` | `500` | Below this altitude → tower jurisdiction |
| `MAX_ALT` | `18000` | Above this altitude → center jurisdiction |
| `TOWER_HANDOFF_ALT` | `3000` | Hand arriving aircraft to tower below this |
| `CENTER_HANDOFF_ALT` | `17000` | Hand departing aircraft to center above this |
| `TERMINAL_RADIUS_DEG` | `0.66` | Terminal area radius (~40 nm) |
| `_SEP_COOLDOWN_S` | `30` | Suppress duplicate separation alerts (seconds) |

### 4.2  Identity

| Attribute | Type | Description |
|---|---|---|
| `tracon_id` | `str` | Facility ID (e.g., `N90`) |
| `controller_id` | `str` | Controller name (e.g., `APP-N90`) |
| `airport_codes` | `list[str]` | Airports served (e.g., `["KJFK", "KLGA", "KEWR"]`) |
| `serving_center` | `str` | Overlying center (e.g., `ZNY`) |
| `config_path` | `str` | Path to scenario config JSON |

### 4.3  Traffic State

| Attribute | Type | Description |
|---|---|---|
| `tracked_aircraft` | `dict[str, AircraftPosition]` | Tail → last position |
| `handed_off` | `set[str]` | Tails already handed off this cycle |
| `acquired_aircraft` | `set[str]` | Aircraft formally received via handoff |
| `controlling` | `set[str]` | Tails with active AircraftTracking instance |
| `pending_handoffs` | `dict[str, str]` | Tail → handoff_id awaiting ACCEPTED |
| `_sep_cooldown` | `dict[tuple, float]` | (tail_a, tail_b) → last alert time |
| `_last_speed_issued` | `dict[str, float]` | Tail → last speed target issued |
| `_sim_speed` | `float` | Current simulation speed (updated each loop) |

### 4.4  DDS Entities

| Attribute | Type | Description |
|---|---|---|
| `participant` | `dds.DomainParticipant` | Single participant |
| `pos_reader` | `dds.DataReader` | Reads `AircraftPosition` (CFT by altitude) |
| `instr_writer` | `dds.DataWriter` | Writes `ControllerInstruction` |
| `ack_reader` | `dds.DataReader` | Reads `PilotAcknowledgment` |
| `ho_writer` | `dds.DataWriter` | Writes `Handoff` |
| `ho_reader` | `dds.DataReader` | Reads `Handoff` (CFT) |
| `alert_writer` | `dds.DataWriter` | Writes `Alert` |
| `wx_reader` | `dds.DataReader` | Reads `WeatherReport` |
| `fp_reader` | `dds.DataReader` | Reads `FlightPlan` |
| `tracking_writer` | `dds.DataWriter` | Writes `AircraftTracking` |
| `status_writer` | `dds.DataWriter` | Writes `FacilityStatus` |

---

## 5  DDS Initialisation

### 5.1  DP Partitions

- `OPS/TERMINAL/<tracon_id>` — matches towers reaching up
- `OPS/FPS/*` — discovers Flight Plan Service
- `OPS/ENROUTE/<serving_center>` — matches overlying center for handoffs

### 5.2  Content-Filtered Topics

| CFT Name | Base Topic | Filter | Parameters |
|---|---|---|---|
| `TerminalTraffic_<tracon_id>` | `AircraftPosition` | `position.altitude_feet >= %0 AND position.altitude_feet < %1` | `[500, 18000]` |
| `MyHandoffs_<controller_id>` | `Handoff` | `to_controller_id = '<id>' OR from_controller_id = '<id>'` | — |

### 5.3  Initialisation Actions

1. Publish initial `FacilityStatus` (heartbeat).

---

## 6  Traffic Monitoring (`monitor_traffic`)

Takes all position samples from the altitude-band CFT:

- If the aircraft is in the terminal area (within `TERMINAL_RADIUS_DEG` of a
  served airport) OR has origin/destination at a served airport → track it.
- Otherwise → remove from tracking dict.

Logs arrival/departure counts at debug level.

### Helper: `_is_in_terminal_area(pos)`

Returns `True` if the aircraft position is within ±0.66° of any served airport.

---

## 7  Separation Checking (`check_separation`)

Checks all pairs of airborne (non-ground-phase) tracked aircraft:

- **Terminal separation:** 3 nm lateral (≈ 0.05°) and 1,000 ft vertical.
- If violated and not in cooldown → publish `Alert` with type `TRAFFIC_CONFLICT`,
  severity `WARNING`.
- Cooldown: `30 / sim_speed` seconds per aircraft pair.

Skips ground-phase aircraft: `PREFLIGHT`, `TAXI_OUT`, `TAXI_IN`, `PARKED`.

---

## 8  Approach Sequencing (`sequence_arrivals`)

For each arriving aircraft (destination at a served airport):

| Altitude Band | Speed Threshold | Target Speed |
|---|---|---|
| 10,000–15,000 ft | > 280 kt | 250 kt |
| 5,000–10,000 ft | > 220 kt | 210 kt |

Only issues a speed instruction if the target differs from the last one issued to that aircraft (`_last_speed_issued`), preventing redundant commands.

---

## 9  Handoff Management (`manage_handoffs`)

Only manages handoffs for aircraft in `acquired_aircraft` (formally received via handoff). Skips already handed-off aircraft.

### 9.1  To Center (Departures)

Condition: departing aircraft at altitude ≥ 17,000 ft.
- `to_controller_id = CTR-<serving_center>`
- `from_facility_type = TRACON`, `to_facility_type = CENTER`

### 9.2  To Tower (Arrivals)

Condition: arriving aircraft at altitude ≤ 3,000 ft.
- `to_controller_id = TWR-<destination_airport>`
- `from_facility_type = TRACON`, `to_facility_type = TOWER`

---

## 10  Handoff Processing (`process_handoffs`)

Takes all samples from the handoff CFT reader:

- **Incoming INITIATED** (addressed to this controller): Accept by writing
  `Handoff` with `ACCEPTED`. Add to `acquired_aircraft`. Publish `AircraftTracking`.
- **Outgoing ACCEPTED** (from this controller): Remove from `pending_handoffs`,
  unregister tracking, remove from `tracked_aircraft`.

---

## 11  AircraftTracking Lifecycle

Same pattern as Tower (§8 in tower spec):
- `_publish_tracking()` → writes sample, adds to `controlling`, updates facility status.
- `_unregister_tracking()` → unregisters instance, removes from `controlling`.
- `_publish_facility_status()` → writes `FacilityStatus` with `facility_type = TRACON`.

---

## 12  Main Run Loop (`run`)

Loop at ~1 Hz until `shutdown_flag` or `duration_s` elapsed:

1. Read `sim_speed` via `read_sim_speed_from_discovery()`.
2. `monitor_traffic()`
3. `check_separation()`
4. `sequence_arrivals()`
5. `manage_handoffs()`
6. `process_handoffs()`
7. `process_acknowledgments()`
8. `status_writer.assert_liveliness()`

---

## 13  Signal Handling

Global `shutdown_flag` set by `SIGINT` and `SIGTERM`.

---

## 14  Thread Summary

| Thread | Description |
|---|---|
| Main | `run()` — control loop at 1 Hz |

Single-threaded application.

---

## 15  File Structure

Single file: `app_tracon.py`

### Imports from `air_traffic_types.py`

`AircraftPosition`, `AircraftTracking`, `Alert`, `AlertSeverity`, `AlertType`,
`ControllerInstruction`, `FacilityStatus`, `FacilityType`, `FlightPhase`,
`FlightPlan`, `Handoff`, `HandoffStatus`, `InstructionType`,
`PilotAcknowledgment`, `WeatherReport`

### Imports from `common.py`

`create_participant`, `create_publisher`, `create_subscriber`,
`load_airport_coords`, `load_qos_provider`, `load_tracon_config`,
`make_id`, `now_ms`, `read_sim_speed_from_discovery`, `reader_qos`,
`setup_logging`, `writer_qos`
