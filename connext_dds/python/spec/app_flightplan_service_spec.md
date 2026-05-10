# Flight Plan Filing Service — Specification

> This document fully specifies `app_flightplan_service.py` so that an AI
> agent or developer can re-create it from scratch.

---

## 1  Purpose

A central replier service that validates incoming flight plan requests,
accepts or rejects them, and publishes accepted plans on the `FlightPlan`
topic so that towers, TRACONs, and centers can subscribe.

---

## 2  Command-Line Interface

```
python app_flightplan_service.py --config CONFIG --qos-file QOS_XML [options]
```

| Argument | Type | Default | Description |
|---|---|---|---|
| `--config` | str (required) | — | Path to `air_traffic_scenario.json` |
| `--qos-file` | str (required) | — | Path to `air_traffic_qos.xml` |
| `--service-name` | str | `main` | FPS instance name (partition: `OPS/FPS/<name>`) |
| `--duration` | float | `300.0` | Duration in wall-clock seconds |

---

## 3  `FlightPlanService` Class — State & Attributes

| Attribute | Type | Description |
|---|---|---|
| `filed_plans` | `dict[str, FlightPlan]` | Accepted plans by `flight_plan_id` |

### DDS Entities

| Attribute | Type | Description |
|---|---|---|
| `participant` | `dds.DomainParticipant` | Single participant |
| `fp_writer` | `dds.DataWriter` | Writes accepted `FlightPlan` |
| `replier` | `rti.rpc.Replier` | `FlightPlanFilingService` replier |

---

## 4  DDS Initialisation

### 4.1  DP Partitions

- `OPS/FPS/<service_name>` — concrete partition; consumers match via `OPS/FPS/*`

### 4.2  Replier

```python
Replier(
    request_type=FlightPlanRequest,
    reply_type=FlightPlanResponse,
    participant=participant,
    service_name="FlightPlanFilingService",
)
```

---

## 5  Validation (`validate_plan`)

| Check | Failure Message |
|---|---|
| `tail_number` empty | "Missing tail_number" |
| `departure_airport` empty | "Missing departure_airport" |
| `arrival_airport` empty | "Missing arrival_airport" |
| departure == arrival | "Departure and arrival airports must differ" |
| `scheduled_departure_time` ≤ 0 | "Invalid scheduled departure time" |

Returns `(accepted: bool, message: str)`.

---

## 6  Request Handling (`handle_requests`)

1. Call `replier.receive_requests(Duration=0)` (non-blocking).
2. For each valid request:
   a. Validate the plan.
   b. If accepted: set status to `ACTIVE`, update `last_updated`,
      store in `filed_plans`, publish on `FlightPlan` topic.
   c. Reply with `FlightPlanResponse(flight_plan_id, accepted, message)`.

---

## 7  Main Run Loop (`run`)

Loop at 5 Hz (0.2s sleep) until `shutdown_flag` or `duration_s` elapsed.
Calls `handle_requests()` each tick.

---

## 8  Thread Summary

| Thread | Description |
|---|---|
| Main | `run()` — loop at 5 Hz |

Single-threaded application.
