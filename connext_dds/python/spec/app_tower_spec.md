# Control Tower Application — Specification

> This document fully specifies `app_tower.py` so that an AI agent or
> developer can re-create it from scratch.  It assumes access to the IDL
> types (`air_traffic_types.idl`), the generated Python types
> (`air_traffic_types.py`), the QoS profiles (`air_traffic_qos.xml`), and
> the shared utilities (`common.py`).

---

## 1  Purpose

A control tower simulator for a single airport.  Manages aircraft in the
immediate airport vicinity (surface to ~3,000 ft), issues clearances and
approach instructions, publishes runway status, and coordinates handoffs
with the serving TRACON.

The tower is the initial controller-of-record for all departing aircraft
(publishes `AircraftTracking`) and the final controller for arriving
aircraft (accepts handoff from TRACON).

---

## 2  Technology Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| Middleware | RTI Connext DDS 7.7.0+ (`rti.connextdds`) |
| Type generation | `rtiddsgen -language python air_traffic_types.idl` → `air_traffic_types.py` |
| QoS configuration | `air_traffic_qos.xml` |
| Logging | Python `logging` via `common.setup_logging()` |

No Request/Reply — tower uses only pub/sub topics.

---

## 3  Command-Line Interface

```
python app_tower.py --config CONFIG --qos-file QOS_XML [options]
```

| Argument | Type | Default | Description |
|---|---|---|---|
| `--config` | str (required) | — | Path to `air_traffic_scenario.json` |
| `--qos-file` | str (required) | — | Path to `air_traffic_qos.xml` |
| `--airport-code` | str | `KJFK` | Airport ICAO code |
| `--controller-id` | str | `TWR-<airport>` | Controller identifier |
| `--serving-tracon` | str | from config | Serving TRACON ID |
| `--duration` | float | `120.0` | Duration in wall-clock seconds |

At startup `main()`:

1. Parses arguments, sets `common.QOS_FILE`.
2. Loads airport config by code.
3. Derives controller ID: `TWR-<airport_code>`.
4. Re-initializes logger with controller ID.
5. Resolves `serving_tracon` from CLI or config.
6. Creates `TowerController(...)` and calls `run()`.

---

## 4  `TowerController` Class — State & Attributes

### 4.1  Identity

| Attribute | Type | Description |
|---|---|---|
| `airport_code` | `str` | ICAO code (e.g., `KJFK`) |
| `controller_id` | `str` | Controller name (e.g., `TWR-KJFK`) |
| `serving_tracon` | `str` | Serving TRACON ID (e.g., `N90`) |

### 4.2  Traffic State

| Attribute | Type | Description |
|---|---|---|
| `tracked_aircraft` | `dict[str, AircraftPosition]` | Tail → last position for aircraft in tower airspace |
| `handed_off` | `set[str]` | Tail numbers already handed to TRACON (avoid re-triggering) |
| `controlling` | `set[str]` | Tails with active `AircraftTracking` instance |
| `pending_handoffs` | `dict[str, str]` | Tail → handoff_id awaiting ACCEPTED |

### 4.3  DDS Entities

| Attribute | Type | Description |
|---|---|---|
| `participant` | `dds.DomainParticipant` | Single participant for this tower |
| `publisher` | `dds.Publisher` | Default publisher |
| `subscriber` | `dds.Subscriber` | Default subscriber |
| `pos_reader` | `dds.DataReader` | Reads `AircraftPosition` (CFT) |
| `instr_writer` | `dds.DataWriter` | Writes `ControllerInstruction` |
| `ack_reader` | `dds.DataReader` | Reads `PilotAcknowledgment` |
| `rwy_writer` | `dds.DataWriter` | Writes `RunwayStatus` |
| `ho_writer` | `dds.DataWriter` | Writes `Handoff` |
| `ho_reader` | `dds.DataReader` | Reads `Handoff` (CFT) |
| `alert_writer` | `dds.DataWriter` | Writes `Alert` |
| `wx_reader` | `dds.DataReader` | Reads `WeatherReport` (CFT) |
| `fp_reader` | `dds.DataReader` | Reads `FlightPlan` |
| `tracking_writer` | `dds.DataWriter` | Writes `AircraftTracking` |
| `status_writer` | `dds.DataWriter` | Writes `FacilityStatus` |

---

## 5  DDS Initialisation

### 5.1  DP Partitions

- `OPS/AIRPORT/<airport_code>` — matches aircraft and airport at this field
- `OPS/FPS/*` — discovers Flight Plan Service
- `OPS/TERMINAL/<serving_tracon>` — matches TRACON for handoffs

### 5.2  Writers

| Writer | Topic | QoS Profile |
|---|---|---|
| `instr_writer` | `ControllerInstruction` | `ControllerInstructionProfile` |
| `rwy_writer` | `RunwayStatus` | `RunwayStatusProfile` |
| `ho_writer` | `Handoff` | `HandoffProfile` |
| `alert_writer` | `Alert` | `AlertProfile` |
| `tracking_writer` | `AircraftTracking` | `AircraftTrackingProfile` |
| `status_writer` | `FacilityStatus` | `FacilityStatusProfile` |

### 5.3  Readers

| Reader | Topic | CFT Name | Filter | QoS Profile |
|---|---|---|---|---|
| `pos_reader` | `AircraftPosition` | `LocalTraffic_<code>` | `origin_airport = '<code>' OR destination_airport = '<code>'` | `AircraftPositionProfile` |
| `ack_reader` | `PilotAcknowledgment` | — (unfiltered) | — | `PilotAcknowledgmentProfile` |
| `ho_reader` | `Handoff` | `MyHandoffs_<id>` | `to_controller_id = '<id>' OR from_controller_id = '<id>'` | `HandoffProfile` |
| `wx_reader` | `WeatherReport` | `LocalWeather_<code>` | `airport_code = '<code>'` | `WeatherReportProfile` |
| `fp_reader` | `FlightPlan` | — (unfiltered) | — | `FlightPlanProfile` |

### 5.4  Initialisation Actions

1. Publish initial `FacilityStatus` (heartbeat).
2. Publish runway status for `09L` and `27R` as `OPEN`.

---

## 6  Traffic Monitoring (`monitor_traffic`)

Takes all position samples from the CFT reader. For each sample:

### 6.1  Filtering Logic

The CFT matches `origin_airport` OR `destination_airport`, which can deliver
positions for aircraft far from the airport. Only track aircraft that are
actually in tower airspace:

- **PARKED aircraft:** Remove from `tracked_aircraft`, unregister tracking.
- **Handed-off aircraft:** Skip (already passed to TRACON).
- **Local departure:** `origin == this airport` AND `altitude < 3,000 ft`
- **Local arrival:** `destination == this airport` AND (`altitude < 3,000 ft` OR phase ≥ APPROACH)
- **Ground phase:** `PREFLIGHT` or `TAXI_OUT`

If none of these conditions match → skip (aircraft matched CFT but is not in tower airspace).

### 6.2  Initial Tracking

When a departing aircraft is seen for the first time (`origin == this airport`),
the tower publishes an `AircraftTracking` sample, claiming controller-of-record.

### 6.3  Approach Clearances

For tracked aircraft in `DESCENT` or later phase, with `destination == this airport`
and no `assigned_runway`: issue a CLEARANCE instruction for ILS approach runway 09L.

### 6.4  Departure Handoffs

For departing aircraft originating here, at altitude ≥ 1,500 ft with positive
vertical speed:
1. Write `Handoff` with status `INITIATED`, `to_controller_id = APP-<serving_tracon>`.
2. Add to `pending_handoffs` and `handed_off`.

---

## 7  Handoff Processing (`process_handoffs`)

Takes all samples from the handoff CFT reader:

- **Incoming INITIATED** (addressed to this controller): Accept by writing
  `Handoff` with `ACCEPTED`, publish `AircraftTracking` claiming the aircraft.
- **Outgoing ACCEPTED** (from this controller, accepted by remote): Remove
  from `pending_handoffs`, unregister tracking, remove from `tracked_aircraft`.

---

## 8  AircraftTracking Lifecycle

### `_publish_tracking(tail_number)`

Writes `AircraftTracking` sample with:
- `controller_id`, `facility_id = airport_code`, `facility_type = TOWER`
- Adds tail to `controlling` set
- Publishes updated `FacilityStatus` (tracked count)

### `_unregister_tracking(tail_number)`

Looks up instance handle, calls `tracking_writer.unregister_instance()`.
Removes from `controlling`, publishes updated `FacilityStatus`.

### `_publish_facility_status()`

Writes `FacilityStatus` with `facility_type = TOWER`, tracked count = `len(controlling)`.

---

## 9  Instruction Issuing (`issue_instruction`)

Writes a `ControllerInstruction` with:
- Auto-generated `instruction_id`
- `controller_id`, `tail_number`
- `instruction_type`, optional heading/altitude/speed/clearance fields

---

## 10  Main Run Loop (`run`)

Loop at ~1 Hz until `shutdown_flag` or `duration_s` elapsed:

1. `monitor_traffic()`
2. `process_acknowledgments()`
3. `process_handoffs()`
4. `check_weather()`
5. `status_writer.assert_liveliness()`

---

## 11  Signal Handling

Global `shutdown_flag` set by `SIGINT` and `SIGTERM`. Main loop checks each iteration.

---

## 12  Thread Summary

| Thread | Description |
|---|---|
| Main | `run()` — control loop at 1 Hz |

Single-threaded application.

---

## 13  File Structure

Single file: `app_tower.py`

### Imports from `air_traffic_types.py`

`AircraftPosition`, `AircraftTracking`, `Alert`, `AlertSeverity`, `AlertType`,
`ControllerInstruction`, `FacilityStatus`, `FacilityType`, `FlightPlan`,
`Handoff`, `HandoffStatus`, `InstructionType`, `PilotAcknowledgment`,
`RunwayOperationalStatus`, `RunwayStatus`, `WeatherReport`

### Imports from `common.py`

`create_participant`, `create_publisher`, `create_subscriber`,
`load_airport_config`, `load_qos_provider`, `make_id`, `now_ms`,
`reader_qos`, `setup_logging`, `writer_qos`
