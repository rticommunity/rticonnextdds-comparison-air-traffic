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
| `aircraft_id` | Unique identifier (e.g., tail number or callsign) |
| `aircraft_type` | Model/type of aircraft (e.g., B737, A320) |
| `position` | Current 3-D position (latitude, longitude, altitude) |
| `velocity` | Speed and heading (ground speed, vertical speed, bearing) |
| `status` | Current phase: `en_route`, `approaching`, `landing`, `on_ground`, `taxiing`, `taking_off`, `departed` |
| `origin_airport` | Departure airport code |
| `destination_airport` | Arrival airport code |
| `fuel_level` | Remaining fuel (percentage or time-to-empty) |
| `assigned_runway` | Runway assigned for landing or takeoff |

**Behaviors:**
- Periodically publish its position and status.
- Receive and acknowledge instructions from controllers.
- Transition through flight phases based on controller clearances.
- Declare emergencies (e.g., low fuel, mechanical issue).

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

**Behaviors:**
- Publish weather and runway status updates.
- Report gate availability changes.

### 2.3 Control Tower

The air-traffic control facility at each airport, responsible for terminal-area traffic.

| Attribute | Description |
|---|---|
| `tower_id` | Unique identifier |
| `airport_code` | The airport this tower manages |
| `active_controllers` | List of controllers currently on duty |
| `managed_airspace` | Defined region of responsibility (radius, altitude range) |

**Behaviors:**
- Monitor all aircraft within its managed airspace.
- Issue approach, landing, takeoff, and taxi clearances.
- Manage runway sequencing and separation.
- Hand off aircraft to/from en-route controllers.

### 2.4 Air-Traffic Controller

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

### 2.5 Flight Plan

Describes the intended route and schedule of a flight.

| Attribute | Description |
|---|---|
| `flight_plan_id` | Unique identifier |
| `aircraft_id` | Associated aircraft |
| `departure_airport` | Origin airport code |
| `arrival_airport` | Destination airport code |
| `route` | Ordered list of waypoints |
| `planned_departure_time` | Scheduled departure |
| `planned_arrival_time` | Estimated arrival |
| `cruising_altitude` | Requested cruise altitude |
| `status` | `filed`, `active`, `completed`, `cancelled` |

**Behaviors:**
- Filed before departure and activated on takeoff.
- Updated in-flight if route amendments are issued.
- Closed upon landing or cancellation.

### 2.6 En-Route Control Center

Manages aircraft in transit between airports (high-altitude, non-terminal airspace).

| Attribute | Description |
|---|---|
| `center_id` | Unique identifier |
| `region` | Geographic region covered |
| `sectors` | Subdivisions of the airspace |
| `active_controllers` | Controllers on duty |

**Behaviors:**
- Monitor en-route traffic within its region.
- Issue routing and altitude instructions.
- Hand off aircraft to adjacent centers or to approach controllers.

---

## 3. Key Data Elements

### 3.1 Position Report
Published periodically by each airplane.

```
aircraft_id, timestamp, latitude, longitude, altitude,
ground_speed, vertical_speed, heading
```

### 3.2 Controller Instruction
Issued by a controller to a specific aircraft.

```
instruction_id, controller_id, aircraft_id, timestamp,
instruction_type (heading | altitude | speed | clearance | hold | go_around),
parameters (target_value, runway, waypoint, etc.)
```

### 3.3 Pilot Acknowledgment
Sent by the aircraft in response to an instruction.

```
ack_id, instruction_id, aircraft_id, timestamp,
status (wilco | unable | request_repeat)
```

### 3.4 Flight Plan Update
Amendments to an active flight plan.

```
flight_plan_id, amendment_type, updated_fields, issued_by, timestamp
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
conditions (VFR | MVFR | IFR | LIFR)
```

### 3.7 Handoff Request / Accept
Coordination between controllers when an aircraft transitions between sectors.

```
handoff_id, from_controller_id, to_controller_id,
aircraft_id, timestamp, status (requested | accepted | rejected)
```

### 3.8 Alert / Conflict Notification
Generated when safety thresholds are breached.

```
alert_id, alert_type (separation_violation | runway_incursion | emergency),
involved_aircraft[], timestamp, severity, description
```

---

## 4. Interaction Patterns

### 4.1 Publish / Subscribe (One-to-Many)
- **Position Reports:** Every airplane publishes; control towers and en-route centers subscribe to aircraft within their airspace.
- **Weather Reports:** Airports publish; all aircraft and controllers subscribe.
- **Runway Status:** Airports publish; controllers and approaching aircraft subscribe.
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
1. Flight plan is filed and approved.
2. Aircraft requests pushback and taxi clearance.
3. Control tower assigns a runway and taxi route.
4. Aircraft taxis to the assigned runway.
5. Tower issues takeoff clearance.
6. Aircraft takes off and transitions to en-route control.
7. Handoff from tower controller to en-route controller.

### 5.2 En-Route Flight
1. En-route center monitors aircraft position reports.
2. Controller issues heading/altitude amendments as needed.
3. When approaching sector boundary, handoff to adjacent center.
4. When approaching destination, handoff to approach/tower controller.

### 5.3 Arrival Sequence
1. Approach controller sequences inbound aircraft.
2. Controller issues approach clearance and assigns runway.
3. Aircraft follows approach procedure, publishing position.
4. Tower issues landing clearance.
5. Aircraft lands and reports on ground.
6. Tower issues taxi instructions to gate.
7. Flight plan is closed.

### 5.4 Emergency Handling
1. Aircraft declares emergency (fuel, mechanical, medical).
2. Alert is broadcast to all relevant controllers.
3. Priority handling: aircraft gets immediate clearance.
4. Other aircraft are re-routed or put in holding patterns.

---

## 6. Simulation Elements

| Element | Description |
|---|---|
| **Time model** | Simulated clock with configurable speed (real-time, accelerated) |
| **Aircraft generator** | Creates aircraft with randomized or scripted flight plans |
| **Position simulator** | Advances aircraft positions based on speed, heading, and flight phase |
| **Weather generator** | Produces changing weather conditions per airport on a schedule |
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
┌──────────────────────────────────────────────────────┐
│                  National Airspace                    │
│                                                      │
│   ┌─────────────┐         ┌─────────────┐           │
│   │ En-Route     │◄───────►│ En-Route     │          │
│   │ Center A     │         │ Center B     │          │
│   └──────┬──────┘         └──────┬──────┘           │
│          │    handoffs           │                    │
│     ┌────▼────┐            ┌────▼────┐              │
│     │ Tower 1  │            │ Tower 2  │             │
│     │(Airport 1)│           │(Airport 2)│            │
│     └────┬────┘            └────┬────┘              │
│          │                      │                    │
│    ✈ ✈ ✈ ✈                ✈ ✈ ✈ ✈                 │
│   Aircraft at               Aircraft at              │
│   Airport 1                 Airport 2                │
│                                                      │
│          ✈  ✈  ✈  ✈  ✈  (en-route aircraft)        │
└──────────────────────────────────────────────────────┘
```

Each airport has a local control tower instance. En-route centers manage aircraft between airports. All components communicate through the selected middleware.

---

## 9. Next Steps

Technology-specific design documents will map these components and interactions onto:

- **RTI Connext DDS** — Topics, data types, QoS profiles, domains, partitions
- **gRPC** — Service definitions, streaming RPCs, proto messages
- **Kafka** — Topics, producers/consumers, schemas, partitioning strategies

Each design will implement the same scenario to enable a direct comparison of developer experience, performance characteristics, and architectural fit.
