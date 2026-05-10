# Airport Infrastructure Application — Specification

> This document fully specifies `app_airport.py` so that an AI agent or
> developer can re-create it from scratch.

---

## 1  Purpose

An airport infrastructure simulator that publishes periodic weather
observations, runway status, and acts as a Gate Assignment replier.
One instance per airport.

---

## 2  Command-Line Interface

```
python app_airport.py --config CONFIG --qos-file QOS_XML [options]
```

| Argument | Type | Default | Description |
|---|---|---|---|
| `--config` | str (required) | — | Path to `air_traffic_scenario.json` |
| `--qos-file` | str (required) | — | Path to `air_traffic_qos.xml` |
| `--airport-code` | str | `KJFK` | ICAO airport code |
| `--runways` | str[] | from config | Runway IDs |
| `--serving-tracon` | str | from config | Serving TRACON ID |
| `--duration` | float | `120.0` | Duration in wall-clock seconds |
| `--wx-interval` | float | `1800.0` | Weather interval in sim-time seconds (30 min) |

---

## 3  `AirportInfrastructure` Class — State & Attributes

### 3.1  Constants

| Constant | Value | Description |
|---|---|---|
| `GATE_NAMES` | `["A1"..."C10"]` | 30 gates: terminals A, B, C with gates 1–10 |

### 3.2  State

| Attribute | Type | Description |
|---|---|---|
| `airport_code` | `str` | ICAO code |
| `runways` | `list[str]` | Runway IDs from config |
| `config_path` | `str` | Scenario config path |
| `weather_interval_s` | `float` | Sim-time interval between weather reports |
| `assigned_gates` | `dict[str, str]` | `flight_id → gate_name` |
| `_last_qos_speed` | `float` | Last sim speed used for QoS scaling |

### 3.3  DDS Entities

| Attribute | Type | Description |
|---|---|---|
| `participant` | `dds.DomainParticipant` | Single participant |
| `wx_writer` | `dds.DataWriter` | Writes `WeatherReport` (speed-scaled QoS) |
| `rwy_writer` | `dds.DataWriter` | Writes `RunwayStatus` |
| `gate_replier` | `rti.rpc.Replier` | Gate assignment replier |

---

## 4  DDS Initialisation

### 4.1  DP Partitions

- `OPS/AIRPORT/<airport_code>` — matches towers and aircraft
- `OPS/TERMINAL/<serving_tracon>` — matches TRACON

### 4.2  Weather QoS Scaling

The weather writer is created with `writer_qos_for_speed()` to scale
deadline duration by current sim speed. QoS is re-applied at runtime
when speed changes.

### 4.3  Gate Replier

```python
Replier(
    request_type=GateRequest,
    reply_type=GateAssignmentReply,
    participant=participant,
    service_name="GateAssignmentService",
)
```

---

## 5  Weather Publishing (`publish_weather`)

Publishes a `WeatherReport` with randomized:
- Wind direction (0–359°), speed (0–25 kt), gust (15–40 kt, 30% chance)
- Visibility (200–10,000 m), ceiling (200–25,000 ft)
- Temperature (−10–40°C), altimeter (980–1040 hPa)
- Random `WeatherCondition` enum value

---

## 6  Gate Assignment (`handle_gate_requests`)

1. Call `replier.receive_requests(Duration=0)` (non-blocking).
2. For each valid request:
   - If `flight_id` already assigned → reuse gate.
   - Otherwise → pick next available gate from `GATE_NAMES` (first unused).
   - If no gates available → reply with `REJECTED`.
   - Reply with `GateAssignmentReply` containing `GateAssignment`.

### Gate Selection (`_next_gate`)

Iterates `GATE_NAMES` (A1–C10), returns first gate not in
`assigned_gates.values()`. Returns `None` if all 30 are assigned.

---

## 7  Main Run Loop (`run`)

1. Publish initial runway status for all runways.
2. Loop at 0.5 Hz until `shutdown_flag` or `duration_s`:
   - Scale weather interval by sim speed: `wall_interval = weather_interval_s / speed`.
   - Re-apply QoS when speed changes.
   - Publish weather when interval elapses.
   - Handle gate requests.

---

## 8  Thread Summary

| Thread | Description |
|---|---|
| Main | `run()` — loop at 2 Hz (0.5s sleep) |

Single-threaded application.

---

## 9  File Structure

Single file: `app_airport.py`

### Imports from `air_traffic_types.py`

`GateAssignment`, `GateAssignmentReply`, `GateAssignmentStatusKind`,
`GateRequest`, `RunwayOperationalStatus`, `RunwayStatus`, `WeatherCondition`,
`WeatherReport`, `Wind`

### Imports from `common.py`

`create_participant`, `create_publisher`, `create_subscriber`,
`load_airport_config`, `load_qos_provider`, `now_ms`,
`read_sim_speed_from_discovery`, `reader_qos`, `setup_logging`, `writer_qos`,
`writer_qos_for_speed`
