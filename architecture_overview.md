# National Air-Traffic Control System — Architecture Overview

> **Purpose:** Technology-agnostic description of the components, data elements, and interactions required to implement the national air-traffic control demo scenario. Specific designs for RTI Connext DDS, gRPC, Kafka, and other middleware technologies will be developed separately.

---

## 1. System Scope

A simulated national air-traffic control system spanning multiple airports. The system coordinates airplanes in flight, during approach, landing, and takeoff, while air-traffic controllers manage traffic flow and ensure safe separation.

---

## 2. Core Components

### 2.1 Airplane

Represents an individual aircraft in the system.

| Attribute | Description |
|---|---|
| `tail_number` | Unique identifier (e.g., N-number) |
| `callsign` | Flight callsign (e.g., AAL100) |
| `position` | Current 3-D position (latitude, longitude, altitude) |
| `velocity` | Speed and heading (ground speed, vertical speed, bearing) |
| `status` | Current phase: `preflight`, `taxi_out`, `takeoff`, `climb`, `cruise`, `descent`, `approach`, `landing`, `taxi_in`, `parked`, `holding` |
| `origin_airport` | Departure airport code |
| `destination_airport` | Arrival airport code |
| `fuel_level` | Remaining fuel (percentage) |
| `assigned_runway` | Runway assigned for landing or takeoff |
| `nav_status` | Navigation status: `normal`, `weather_deviation`, `holding`, `emergency` |

**Behaviors:**
- Periodically publish its position and status.
- Receive and acknowledge instructions from controllers.
- Transition through flight phases autonomously and in response to controller clearances.
- File flight plans via request/reply before departure.
- Request gate assignment via request/reply upon arrival.

### 2.2 Airport

Represents a physical airport with associated infrastructure.

| Attribute | Description |
|---|---|
| `airport_code` | ICAO/IATA code (e.g., KJFK, EGLL) |
| `name` | Human-readable airport name |
| `location` | Geographic coordinates |
| `runways` | List of runways with orientation, length, and current status (open/closed/occupied) |
| `gates` | Available gates and their occupancy status |
| `weather` | Current weather conditions (wind, visibility, ceiling) |
| `serving_tracon` | The TRACON facility serving this airport |

**Behaviors:**
- Publish weather and runway status updates.
- Handle gate assignment requests (request/reply).

### 2.3 Control Tower

The air-traffic control facility at each airport, responsible for terminal-area traffic.

| Attribute | Description |
|---|---|
| `controller_id` | Tower controller identifier (e.g., `TWR-KJFK`) |
| `airport_code` | The airport this tower manages |
| `serving_tracon` | The TRACON this tower hands off to |
| `managed_airspace` | Below ~3,000 ft AGL at the airport |

**Behaviors:**
- Monitor local traffic (departures originating here, arrivals below tower ceiling).
- Issue approach and landing clearances.
- Publish runway status updates.
- Detect separation violations and publish alerts.
- Manage runway sequencing and separation.
- Hand off departing aircraft to TRACON and accept arriving aircraft from TRACON.

### 2.4 TRACON (Terminal Radar Approach Control)

Manages terminal-area aircraft between local tower and en-route center.

| Attribute | Description |
|---|---|
| `tracon_id` | Unique terminal facility identifier |
| `served_airports` | Airports covered by this TRACON |
| `altitude_band` | Typical terminal control band (approx. 500 ft to 18,000 ft) |
| `serving_center` | En-route center paired with this TRACON |

**Behaviors:**
- Sequence arrivals and departures in terminal airspace.
- Issue speed/clearance instructions for approach and climb transitions.
- Accept handoffs from towers and centers.
- Hand off departures to center and arrivals to tower.

### 2.5 Air-Traffic Controller

An individual controller managing a set of aircraft.

| Attribute | Description |
|---|---|
| `controller_id` | Unique identifier |
| `tower_id` | Tower or center they are assigned to |
| `sector` | Airspace sector under their responsibility |
| `assigned_aircraft` | List of aircraft currently under their control |

**Behaviors:**
- Issue instructions (heading, altitude, speed changes, clearances).
- Receive acknowledgments from aircraft.
- Transfer control of aircraft to another controller (handoff).
- Declare alerts when separation minimums are violated.

### 2.6 Flight Plan

Describes the intended route and schedule of a flight.

| Attribute | Description |
|---|---|
| `flight_plan_id` | Unique identifier |
| `tail_number` | Associated aircraft tail number |
| `callsign` | Flight callsign |
| `departure_airport` | Origin airport code |
| `arrival_airport` | Destination airport code |
| `route` | Ordered list of waypoints |
| `planned_departure_time` | Scheduled departure |
| `status` | `filed`, `active`, `amended`, `delayed`, `cancelled`, `completed` |

**Behaviors:**
- Filed before departure and activated on takeoff.
- Updated in-flight if route amendments are issued.
- Closed upon landing or cancellation.

### 2.7 En-Route Control Center

Manages aircraft in transit between airports (high-altitude, non-terminal airspace).

| Attribute | Description |
|---|---|
| `center_id` | Unique identifier |
| `region` | Geographic region covered (boundary polygon) |
| `altitude_band` | Min/max altitude of jurisdiction (typically FL180–FL600) |
| `controller_id` | Controller on duty |

**Behaviors:**
- Monitor en-route traffic within its boundary polygon using position filtering.
- Detect and alert on separation violations between controlled aircraft.
- Issue routing, altitude, and weather-deviation instructions.
- Reroute aircraft around convective weather cells.
- Hand off aircraft to adjacent centers or to TRACON for arrivals.

### 2.8 Flight Plan Service

Central service that validates and accepts/rejects filed flight plans.

| Attribute | Description |
|---|---|
| `service_id` | Unique service instance identifier |
| `validation_rules` | Business rules for plan acceptance/rejection |
| `published_plans` | Accepted plans distributed to operational components |

**Behaviors:**
- Receive flight plan filing requests.
- Validate and respond with acceptance/rejection.
- Publish accepted plans as state data.

### 2.9 Weather Service (En-Route Convective Hazards)

Publishes moving storm-cell style hazards used by en-route controllers.

| Attribute | Description |
|---|---|
| `cell_id` | Unique weather cell identifier |
| `center` | Cell center position (lat/lon) |
| `radius_nm` | Affected radius in nautical miles |
| `altitude_band` | Base/top altitude of hazard |
| `severity` | Hazard severity level |

**Behaviors:**
- Generate and publish convective-cell updates.
- Move cells over time and retire dissipated cells.
- Support rerouting/deviation decisions by controllers.

### 2.10 Operational Dashboard

Read-only observer for end-to-end system state.

| Attribute | Description |
|---|---|
| `observed_topics` | Position, plans, weather, handoffs, alerts, status |
| `airspace_views` | Airport, TRACON, and center situational views |

**Behaviors:**
- Subscribe to all operational streams.
- Present current aircraft, facility, and weather-hazard state.
- Visualize handoffs and safety alerts in near real time.

---

## 3. Key Data Elements

### 3.1 Position Report
Published periodically by each airplane.

```
tail_number, timestamp, latitude, longitude, altitude,
ground_speed, vertical_speed, heading
```

### 3.2 Controller Instruction
Issued by a controller to a specific aircraft.

```
instruction_id, controller_id, tail_number, timestamp,
instruction_type (heading | altitude | speed | clearance | hold | go_around | taxi | pushback),
parameters (target_value, runway, waypoint, etc.)
```

### 3.3 Pilot Acknowledgment
Sent by the aircraft in response to an instruction.

```
ack_id, instruction_id, tail_number, timestamp,
status (received | wilco | unable | readback_correct | readback_incorrect)
```

### 3.4 Flight Plan State
Published by the Flight Plan Service when a plan is filed or its status changes.

```
flight_plan_id, tail_number, callsign, departure_airport, arrival_airport,
waypoints[], scheduled_departure_time, status, last_updated
```

### 3.5 Runway Status
Published by the airport when runway state changes.

```
airport_code, runway_id, status (open | closed | occupied),
occupying_aircraft_id, timestamp
```

### 3.6 Weather Report
Periodic publication of airport weather conditions.

```
airport_code, timestamp, wind_direction, wind_speed,
visibility, ceiling, temperature, altimeter_setting,
conditions (vmc | imc | rain | snow | fog | thunderstorm | wind_shear | ice)
```

### 3.7 Handoff Request / Accept
Coordination between controllers when an aircraft transitions between sectors.

```
handoff_id, from_controller_id, to_controller_id,
tail_number, timestamp, status (initiated | accepted | rejected | completed | cancelled)
```

### 3.8 Alert / Conflict Notification
Generated when safety thresholds are breached.

```
alert_id, alert_type (emergency | traffic_conflict | weather_hazard | runway_incursion |
communication_loss | system_failure | unauthorized_entry | weather_deviation),
involved_aircraft[], timestamp, severity, description
```

### 3.9 Convective Weather Cell
Published by the weather service for en-route hazard awareness.

```
cell_id, timestamp, center_latitude, center_longitude,
radius_nm, base_altitude_ft, top_altitude_ft,
severity, movement_heading_deg, movement_speed_knots
```

### 3.10 Aircraft Tracking State
Indicates the current controller/facility of record for an aircraft.

```
tail_number, controller_id, facility_id, facility_type, acquired_at
```

### 3.11 Facility Status
Heartbeat/workload status published by operational control facilities.

```
facility_id, facility_type, controller_id,
tracked_aircraft_count, last_updated
```

---

## 4. Interaction Patterns

### 4.1 Publish / Subscribe (One-to-Many)
- **Position Reports:** Every airplane publishes; towers, TRACONs, and en-route centers subscribe to aircraft relevant to their airspace.
- **Weather Reports:** Airports publish; all aircraft and controllers subscribe.
- **Runway Status:** Airports publish; controllers and approaching aircraft subscribe.
- **Convective Weather Cells:** Weather service publishes; en-route centers and dashboards subscribe.
- **Aircraft Tracking / Facility Status:** Operational facilities publish ownership and heartbeat state for monitoring.
- **Alerts:** Generated and broadcast to all relevant parties.

### 4.2 Command / Response (One-to-One)
- **Controller Instruction → Pilot Acknowledgment:** A controller issues a directed instruction; the specific aircraft acknowledges.
- **Handoff Request → Handoff Accept:** One controller initiates; the receiving controller responds.

### 4.3 Request / Reply
- **Flight Plan Filing:** An aircraft (or airline) submits a flight plan; the system validates and responds with acceptance or rejection.
- **Gate Assignment Request:** An inbound flight requests a gate; the airport responds with an assignment.

---

## 5. Key Workflows

### 5.1 Departure Sequence
1. Flight plan is filed and approved (request/reply with Flight Plan Service).
2. Aircraft auto-transitions through preflight, taxi-out, and takeoff phases.
3. Tower monitors departure and tracks aircraft as controller of record.
4. Aircraft takes off and transitions to terminal control (TRACON).
5. Handoff from tower controller to TRACON controller.
6. TRACON hands aircraft to en-route center when climbing to en-route airspace.

### 5.2 En-Route Flight
1. En-route center monitors aircraft position reports.
2. Controller issues heading/altitude amendments as needed.
3. Center detects convective weather cells and issues heading deviations to affected aircraft.
4. When weather clears, center issues clearance to resume own navigation.
5. When approaching sector boundary, handoff to adjacent center.
6. When approaching destination and descending, handoff to destination TRACON.

### 5.3 Arrival Sequence
1. TRACON controller sequences inbound aircraft.
2. Controller issues speed instructions for approach transitions.
3. Handoff from TRACON to tower in low-altitude terminal phase.
4. Tower issues approach/landing clearance.
5. Aircraft lands and reports on ground.
6. Aircraft requests gate assignment (request/reply with Airport).
7. Flight plan is closed.

### 5.4 Emergency Handling (not yet implemented)
1. Aircraft declares emergency (fuel, mechanical, medical).
2. Alert is broadcast to all relevant controllers.
3. Priority handling: aircraft gets immediate clearance.
4. Other aircraft are re-routed or put in holding patterns.

---

## 6. Simulation Elements

| Element | Description |
|---|---|
| **Time model** | Speed multiplier broadcast via DDS discovery; all apps scale their sim-time ticks accordingly |
| **Aircraft generator** | Creates aircraft with randomized or scripted flight plans |
| **Position simulator** | Advances aircraft positions based on speed, heading, and flight phase |
| **Airport weather generator** | Produces changing METAR-style weather conditions per airport on a schedule |
| **Convective weather service** | Spawns, moves, and retires en-route storm cells consumed by centers for rerouting |
| **Scenario scripts** | Predefined scenarios (normal operations, high traffic, emergency, multi-airport coordination) |

---

## 7. Quality-of-Service Considerations

These are abstract requirements that each middleware technology must satisfy in its own way:

| Requirement | Description |
|---|---|
| **Timeliness** | Position reports must be delivered with low and bounded latency |
| **Reliability** | Controller instructions and acknowledgments must not be lost |
| **Ordering** | Messages from a single source must arrive in order |
| **Scalability** | The system must handle dozens of airports and hundreds of aircraft |
| **Filtering** | Consumers should receive only data relevant to their airspace or role |
| **Durability** | Late-joining controllers must receive the latest state of all aircraft in their sector |
| **Priority** | Emergency alerts must take precedence over routine traffic |
| **Fault tolerance** | Controller handoffs and system failures must not cause data loss |

---

## 8. Deployment Topology

```
┌───────────────────────────────────────────────────────────────────┐
│                        National Airspace                           │
│                                                                   │
│  ┌──────────────┐    handoffs    ┌──────────────┐                 │
│  │ En-Route      │◄─────────────►│ En-Route      │                │
│  │ Center A      │               │ Center B      │                │
│  └──────┬───────┘               └───────┬──────┘                 │
│         │                               │                         │
│    ┌────▼─────┐                   ┌─────▼────┐                    │
│    │ TRACON 1  │                   │ TRACON 2  │                   │
│    └────┬─────┘                   └─────┬────┘                    │
│         │                               │                         │
│    ┌────▼─────┐                   ┌─────▼────┐                    │
│    │ Tower 1   │                   │ Tower 2   │                   │
│    │(Airport 1) │                  │(Airport 2) │                  │
│    └────┬─────┘                   └─────┬────┘                    │
│         │                               │                         │
│    ✈ ✈ ✈ ✈                         ✈ ✈ ✈ ✈                      │
│   Aircraft at                      Aircraft at                    │
│   Airport 1                        Airport 2                      │
│                                                                   │
│         ✈  ✈  ✈  ✈  ✈  (en-route aircraft)                      │
│                                                                   │
│  ┌────────────────────┐   ┌───────────────────┐                   │
│  │ Flight Plan Service │   │ Weather Service    │                  │
│  └────────────────────┘   └───────────────────┘                   │
│                                                                   │
│  ┌────────────────────┐                                           │
│  │ Dashboard (observer)│                                          │
│  └────────────────────┘                                           │
└───────────────────────────────────────────────────────────────────┘
```

Each airport has a local control tower instance and a serving TRACON. En-route centers manage aircraft between TRACON regions. Flight plan and weather services provide shared operational data. A dashboard can observe the full system state. All components communicate through the selected middleware.

---

## 9. Next Steps

Technology-specific design documents will map these components and interactions onto:

- **RTI Connext DDS** — Topics, data types, QoS profiles, domains, partitions
- **gRPC** — Service definitions, streaming RPCs, proto messages
- **Kafka** — Topics, producers/consumers, schemas, partitioning strategies

Each design will implement the same scenario to enable a direct comparison of developer experience, performance characteristics, and architectural fit.
