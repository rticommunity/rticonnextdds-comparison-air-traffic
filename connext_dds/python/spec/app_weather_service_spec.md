# Weather Service Application — Specification

> This document fully specifies `app_weather_service.py` so that an AI
> agent or developer can re-create it from scratch.

---

## 1  Purpose

Mirrors the real-world Center Weather Service Unit (CWSU).  Periodically
spawns convective weather cells within CONUS, advances their positions
along a heading/speed vector, disposes cells when they expire, and
publishes all active cells on the `ConvectiveCell` topic.

Centers subscribe to reroute aircraft.  The Dashboard subscribes to
visualise cells on the map.

---

## 2  Command-Line Interface

```
python app_weather_service.py --config CONFIG --qos-file QOS_XML [options]
```

| Argument | Type | Default | Description |
|---|---|---|---|
| `--config` | str (required) | — | Path to `air_traffic_scenario.json` |
| `--qos-file` | str (required) | — | Path to `air_traffic_qos.xml` |
| `--duration` | float | `120.0` | Run duration in wall-clock seconds |
| `--spawn-interval` | float | `30.0` | Sim-time seconds between cell spawns |
| `--publish-interval` | float | `300.0` | Sim-time seconds between cell publications (5 min) |
| `--max-cells` | int | `5` | Max concurrent cells |

---

## 3  `ActiveCell` Helper Class

Tracks a live convective cell with remaining lifetime.

| Attribute | Type | Description |
|---|---|---|
| `cell_id` | `str` | Unique ID |
| `lat`, `lon` | `float` | Current center position |
| `radius_nm` | `float` | Cell radius in nautical miles |
| `base_alt`, `top_alt` | `int` | Altitude extent in feet |
| `severity` | `ConvectiveSeverity` | MODERATE, SEVERE, or EXTREME |
| `heading_deg` | `float` | Movement heading |
| `speed_kt` | `float` | Movement speed in knots |
| `lifetime_s` | `float` | Total lifetime in sim-seconds |
| `age_s` | `float` | Accumulated sim-time age |

### Methods

- `advance(dt_s)` — Move cell by `dt_s` of sim-time along heading/speed vector.
- `expired` — Property: `True` when `age_s >= lifetime_s`.
- `to_sample()` — Returns a `ConvectiveCell` DDS sample.

---

## 4  `WeatherService` Class — State & Attributes

| Attribute | Type | Description |
|---|---|---|
| `spawn_interval_s` | `float` | Sim-time between spawns |
| `max_cells` | `int` | Max concurrent cells |
| `publish_interval_s` | `float` | Sim-time between publications |
| `config_path` | `str` | Scenario config path |
| `cells` | `dict[str, ActiveCell]` | Active cells by ID |
| `_time_since_spawn` | `float` | Sim-time accumulator for spawning |
| `_time_since_publish` | `float` | Sim-time accumulator for publishing |
| `_last_qos_speed` | `float` | Last sim speed for QoS scaling |

### DDS Entities

| Attribute | Type | Description |
|---|---|---|
| `participant` | `dds.DomainParticipant` | Single participant |
| `cell_writer` | `dds.DataWriter` | Writes `ConvectiveCell` (speed-scaled QoS) |

---

## 5  DDS Initialisation

### 5.1  DP Partitions

- `OPS/WEATHER/*` — weather service scope
- `OPS/ENROUTE/*` — ensures centers discover the cell writer

### 5.2  Writer QoS

Created with `writer_qos_for_speed()`. Re-applied at runtime when speed changes.

---

## 6  Cell Spawning (`_spawn_cell`)

Random parameters within CONUS bounds:

| Parameter | Range | Description |
|---|---|---|
| Latitude | 28°–45° N | CONUS bounding box |
| Longitude | 115°–75° W | CONUS bounding box |
| Radius | 8–30 nm | Cell size |
| Base altitude | 10,000 / 15,000 / 18,000 ft | Cell base |
| Top altitude | 35,000 / 40,000 / 45,000 ft | Cell top |
| Severity | MODERATE (50%), SEVERE (25%), EXTREME (25%) | |
| Heading | 30°–120° | Generally SW→NE movement |
| Speed | 15–45 kt | Movement speed |
| Lifetime | 1,800–3,600 s | 30–60 min of sim-time |

---

## 7  Cell Disposal (`_dispose_cell`)

Looks up instance handle, calls `cell_writer.dispose_instance()`.
This signals to all subscribers that the cell has dissipated.

---

## 8  Main Run Loop (`run`)

Loop at 1 Hz wall-clock. Each tick:

1. Read `sim_speed` via `read_sim_speed_from_discovery()`.
2. Compute `dt = TICK × sim_speed` (sim-time elapsed).
3. Re-apply QoS if speed changed.
4. Advance all cells by `dt`.
5. Remove expired cells (dispose instance, delete from dict).
6. If spawn interval elapsed and below max → spawn new cell, publish immediately.
7. Otherwise, publish all cells at `publish_interval_s` cadence.

On shutdown: dispose all remaining cells.

---

## 9  Thread Summary

| Thread | Description |
|---|---|
| Main | `run()` — loop at 1 Hz |

Single-threaded application.
