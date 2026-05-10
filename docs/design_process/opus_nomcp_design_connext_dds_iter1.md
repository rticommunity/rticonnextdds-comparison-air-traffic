# RTI Connext DDS Design — National Air-Traffic Control System

> **Purpose:** Map the technology-agnostic [architecture overview](architecture_overview.md) onto RTI Connext DDS concepts: domains, topics, IDL data types, QoS profiles, content-filtered topics, DDS participants, and request/reply patterns.

---

## 1. DDS Domain Architecture

| Domain ID | Name | Purpose |
|---|---|---|
| `0` | **AirTraffic** | All air-traffic data: position reports, instructions, acknowledgments, runway status, weather, alerts, handoffs, and flight plans |

A single domain keeps discovery simple for the demo. Logical separation is achieved through **partitions** and **topics** (see §2 and §4).

### 1.1 Partitions

Partitions isolate traffic within the domain so that subscribers only discover and match publishers relevant to their scope.

| Partition Expression | Used By |
|---|---|
| `airport/<airport_code>` | Tower publishers/subscribers and aircraft at that airport (e.g., `airport/KJFK`) |
| `enroute/<center_id>` | En-route center publishers/subscribers (e.g., `enroute/CENTER_A`) |
| `national` | System-wide data visible to all participants (alerts, flight plans) |

A DomainParticipant can join multiple partitions. For example, an en-route center subscribes to `enroute/CENTER_A` **and** `national`.

---

## 2. IDL Data Types

All types are defined in a single IDL module. Connext Code Generator (`rtiddsgen`) produces language-specific type support.

```idl
module atc {

    // ─── Common types ──────────────────────────────────────

    struct GeoPosition {
        double latitude;
        double longitude;
        float  altitude_ft;
    };

    struct Velocity {
        float ground_speed_kts;
        float vertical_speed_fpm;
        float heading_deg;
    };

    enum FlightPhase {
        EN_ROUTE,
        APPROACHING,
        LANDING,
        ON_GROUND,
        TAXIING,
        TAKING_OFF,
        DEPARTED
    };

    enum InstructionType {
        HEADING,
        ALTITUDE,
        SPEED,
        CLEARANCE,
        HOLD,
        GO_AROUND,
        TAXI,
        PUSHBACK
    };

    enum AckStatus {
        WILCO,
        UNABLE,
        REQUEST_REPEAT
    };

    enum RunwayStatusKind {
        OPEN,
        CLOSED,
        OCCUPIED
    };

    enum WeatherCondition {
        VFR,
        MVFR,
        IFR,
        LIFR
    };

    enum FlightPlanStatus {
        FILED,
        ACTIVE,
        COMPLETED,
        CANCELLED
    };

    enum AlertType {
        SEPARATION_VIOLATION,
        RUNWAY_INCURSION,
        EMERGENCY
    };

    enum AlertSeverity {
        LOW,
        MEDIUM,
        HIGH,
        CRITICAL
    };

    enum HandoffStatus {
        REQUESTED,
        ACCEPTED,
        REJECTED
    };

    // ─── Waypoint ──────────────────────────────────────────

    struct Waypoint {
        string<32> name;
        double latitude;
        double longitude;
    };

    // ─── Topic data types ──────────────────────────────────

    // Keyed by aircraft_id — each aircraft is an independent instance
    @topic
    struct AircraftPosition {
        @key string<16> aircraft_id;
        int64            timestamp;       // epoch millis
        GeoPosition      position;
        Velocity         velocity;
        FlightPhase      status;
        string<8>        origin_airport;
        string<8>        destination_airport;
        float            fuel_level_pct;
        string<8>        assigned_runway;
    };

    @topic
    struct ControllerInstruction {
        @key string<32> instruction_id;
        string<16>      controller_id;
        string<16>      aircraft_id;
        int64           timestamp;
        InstructionType instruction_type;
        string<128>     parameters;       // JSON or structured string for flexibility
    };

    @topic
    struct PilotAcknowledgment {
        @key string<32> ack_id;
        string<32>      instruction_id;
        string<16>      aircraft_id;
        int64           timestamp;
        AckStatus       status;
    };

    @topic
    struct FlightPlan {
        @key string<32>      flight_plan_id;
        string<16>           aircraft_id;
        string<8>            departure_airport;
        string<8>            arrival_airport;
        sequence<Waypoint,64> route;
        int64                planned_departure_time;
        int64                planned_arrival_time;
        float                cruising_altitude_ft;
        FlightPlanStatus     status;
    };

    @topic
    struct FlightPlanUpdate {
        @key string<32> flight_plan_id;
        string<64>      amendment_type;
        string<256>     updated_fields;   // serialized key-value pairs
        string<16>      issued_by;
        int64           timestamp;
    };

    @topic
    struct RunwayStatus {
        @key string<8>  airport_code;
        @key string<8>  runway_id;
        RunwayStatusKind status;
        string<16>       occupying_aircraft_id;
        int64            timestamp;
    };

    @topic
    struct WeatherReport {
        @key string<8>   airport_code;
        int64            timestamp;
        float            wind_direction_deg;
        float            wind_speed_kts;
        float            visibility_sm;
        float            ceiling_ft;
        float            temperature_c;
        float            altimeter_inhg;
        WeatherCondition conditions;
    };

    @topic
    struct Handoff {
        @key string<32> handoff_id;
        string<16>      from_controller_id;
        string<16>      to_controller_id;
        string<16>      aircraft_id;
        int64           timestamp;
        HandoffStatus   status;
    };

    @topic
    struct Alert {
        @key string<32>          alert_id;
        AlertType                alert_type;
        sequence<string<16>, 8>  involved_aircraft;
        int64                    timestamp;
        AlertSeverity            severity;
        string<256>              description;
    };

    // ─── Request/Reply types ───────────────────────────────

    struct FlightPlanRequest {
        FlightPlan plan;
    };

    struct FlightPlanReply {
        string<32>       flight_plan_id;
        boolean          accepted;
        string<256>      reason;
    };

    struct GateAssignmentRequest {
        string<16> aircraft_id;
        string<8>  airport_code;
    };

    struct GateAssignmentReply {
        string<16> aircraft_id;
        string<8>  airport_code;
        string<8>  gate_id;
        boolean    assigned;
        string<128> reason;
    };

};
```

---

## 3. Topics

| Topic Name | IDL Type | Key Fields | Pattern |
|---|---|---|---|
| `AircraftPosition` | `atc::AircraftPosition` | `aircraft_id` | Pub/Sub |
| `ControllerInstruction` | `atc::ControllerInstruction` | `instruction_id` | Pub/Sub (directed) |
| `PilotAcknowledgment` | `atc::PilotAcknowledgment` | `ack_id` | Pub/Sub (directed) |
| `FlightPlan` | `atc::FlightPlan` | `flight_plan_id` | Pub/Sub + State |
| `FlightPlanUpdate` | `atc::FlightPlanUpdate` | `flight_plan_id` | Pub/Sub |
| `RunwayStatus` | `atc::RunwayStatus` | `airport_code`, `runway_id` | Pub/Sub + State |
| `WeatherReport` | `atc::WeatherReport` | `airport_code` | Pub/Sub + State |
| `Handoff` | `atc::Handoff` | `handoff_id` | Pub/Sub (directed) |
| `Alert` | `atc::Alert` | `alert_id` | Pub/Sub (broadcast) |

### Request/Reply Services (built on DDS Topics)

| Service | Request Type | Reply Type | Implementation |
|---|---|---|---|
| Flight Plan Filing | `atc::FlightPlanRequest` | `atc::FlightPlanReply` | Connext Request/Reply API |
| Gate Assignment | `atc::GateAssignmentRequest` | `atc::GateAssignmentReply` | Connext Request/Reply API |

---

## 4. DDS Participants and Their Data Flows

### 4.1 Airplane Participant

Each aircraft runs one DomainParticipant.

| Direction | Topic | Role |
|---|---|---|
| **Publish** | `AircraftPosition` | Periodic position and state updates |
| **Publish** | `PilotAcknowledgment` | Respond to controller instructions |
| **Subscribe** | `ControllerInstruction` | Receive instructions (content-filtered by `aircraft_id`) |
| **Subscribe** | `WeatherReport` | Receive weather for destination airport |
| **Client** | Flight Plan Filing service | File/amend flight plans |
| **Client** | Gate Assignment service | Request gate on arrival |

**Content Filter:**
```
ControllerInstruction WHERE aircraft_id = 'MY_AIRCRAFT_ID'
```

### 4.2 Control Tower Participant

One DomainParticipant per airport control tower.

| Direction | Topic | Role |
|---|---|---|
| **Subscribe** | `AircraftPosition` | Monitor traffic in terminal airspace (content-filtered) |
| **Publish** | `ControllerInstruction` | Issue approach, landing, takeoff, taxi clearances |
| **Subscribe** | `PilotAcknowledgment` | Receive pilot responses |
| **Publish** | `RunwayStatus` | Publish runway state changes |
| **Publish** | `Handoff` | Initiate/accept handoff with en-route centers |
| **Subscribe** | `Handoff` | Receive handoff requests from en-route centers |
| **Publish** | `Alert` | Broadcast alerts for terminal-area conflicts |
| **Subscribe** | `WeatherReport` | Monitor local weather |
| **Subscribe** | `FlightPlan` | View flight plans for aircraft arriving/departing |

**Content Filter (AircraftPosition):**
```
AircraftPosition WHERE destination_airport = 'KJFK' OR origin_airport = 'KJFK'
```

### 4.3 En-Route Center Participant

One DomainParticipant per en-route control center.

| Direction | Topic | Role |
|---|---|---|
| **Subscribe** | `AircraftPosition` | Monitor all en-route aircraft in region (content-filtered by position or partition) |
| **Publish** | `ControllerInstruction` | Issue heading/altitude amendments |
| **Subscribe** | `PilotAcknowledgment` | Receive pilot responses |
| **Publish** | `Handoff` | Initiate/accept handoffs |
| **Subscribe** | `Handoff` | Receive handoff requests |
| **Publish** | `Alert` | Broadcast separation violation alerts |
| **Subscribe** | `FlightPlan` | View active flight plans |

### 4.4 Airport Participant

Publishes environmental and infrastructure state.

| Direction | Topic | Role |
|---|---|---|
| **Publish** | `WeatherReport` | Periodic weather updates |
| **Publish** | `RunwayStatus` | Runway state changes |
| **Server** | Gate Assignment service | Respond to gate requests |

### 4.5 Flight Plan Service Participant

Central service that validates and stores flight plans.

| Direction | Topic | Role |
|---|---|---|
| **Server** | Flight Plan Filing service | Validate and accept/reject flight plans |
| **Publish** | `FlightPlan` | Publish accepted flight plans for all subscribers |
| **Publish** | `FlightPlanUpdate` | Publish amendments |

---

## 5. QoS Profiles

All QoS settings are defined in an XML QoS profile file (`air_traffic_qos.xml`) loaded at startup.

### 5.1 QoS Profile Library: `AirTrafficLibrary`

#### Profile: `PositionReporting`
For high-frequency, best-effort position data.

| QoS Policy | Setting | Rationale |
|---|---|---|
| Reliability | `BEST_EFFORT` | Acceptable to lose an occasional sample; latency is paramount |
| History | `KEEP_LAST(1)` | Only the latest position matters |
| Durability | `VOLATILE` | No need to persist old positions |
| Deadline | `200 ms` | Position must be updated at least every 200 ms |
| Latency Budget | `50 ms` | Hint to transport for batching/optimization |
| Ownership | `EXCLUSIVE` | Only one source per aircraft instance |
| Ownership Strength | `100` | Default strength; can override for redundant sensors |
| Lifespan | `1 s` | Discard stale positions older than 1 second |
| Transport Priority | `0` | Normal priority |

#### Profile: `ReliableCommand`
For controller instructions and pilot acknowledgments that must not be lost.

| QoS Policy | Setting | Rationale |
|---|---|---|
| Reliability | `RELIABLE` | Every instruction must be delivered |
| History | `KEEP_ALL` | Retain all instructions until acknowledged by reader |
| Durability | `TRANSIENT_LOCAL` | Late-joining aircraft receives recent pending instructions |
| Deadline | `5 s` | Instruction should be delivered within 5 seconds |
| Liveliness | `AUTOMATIC, lease = 10 s` | Detect controller failure |
| Transport Priority | `5` | Higher priority than position data |

#### Profile: `StateData`
For runway status, weather, and flight plans — state that should be available to late joiners.

| QoS Policy | Setting | Rationale |
|---|---|---|
| Reliability | `RELIABLE` | State changes must not be lost |
| History | `KEEP_LAST(1)` | Only latest state per instance |
| Durability | `TRANSIENT_LOCAL` | Late joiners get current state |
| Ownership | `EXCLUSIVE` | Single authoritative source per instance |
| Deadline | `30 s` (weather), `none` (others) | Weather must be refreshed periodically |

#### Profile: `AlertBroadcast`
For emergency alerts and conflict notifications.

| QoS Policy | Setting | Rationale |
|---|---|---|
| Reliability | `RELIABLE` | Alerts must not be lost |
| History | `KEEP_ALL` | All alerts preserved for audit |
| Durability | `TRANSIENT_LOCAL` | Late joiners see recent alerts |
| Lifespan | `60 s` | Alerts expire after 1 minute |
| Transport Priority | `10` | Highest priority — preempts all other traffic |

#### Profile: `HandoffCoordination`
For controller-to-controller handoff messages.

| QoS Policy | Setting | Rationale |
|---|---|---|
| Reliability | `RELIABLE` | Handoff must complete |
| History | `KEEP_LAST(5)` | Retain recent handoff history per instance |
| Durability | `TRANSIENT_LOCAL` | Recovering controller sees pending handoffs |
| Liveliness | `MANUAL_BY_TOPIC, lease = 15 s` | Detect controller disconnect |

---

## 6. Content-Filtered Topics

Content-filtered topics reduce the data each participant processes by filtering at the subscriber side (or, with Connext, pushed to the writer side for further optimization).

| CFT Name | Base Topic | SQL Filter | Used By |
|---|---|---|---|
| `MyInstructions` | `ControllerInstruction` | `aircraft_id = %0` (parameter: own aircraft ID) | Airplane |
| `LocalTraffic` | `AircraftPosition` | `destination_airport = %0 OR origin_airport = %0` | Control Tower |
| `SectorTraffic` | `AircraftPosition` | `position.altitude_ft >= %0 AND position.altitude_ft <= %1` | En-Route Center |
| `MyHandoffs` | `Handoff` | `to_controller_id = %0 OR from_controller_id = %0` | Controller |
| `DestinationWeather` | `WeatherReport` | `airport_code = %0` | Airplane |
| `LocalRunways` | `RunwayStatus` | `airport_code = %0` | Control Tower, Airplane |

---

## 7. DDS Participant Mapping to Applications

Each application (OS process) contains one DomainParticipant.

| Application | Participant | Count in Demo |
|---|---|---|
| `airplane_app` | Airplane Participant | One per simulated aircraft (N) |
| `tower_app` | Control Tower Participant | One per airport (M) |
| `center_app` | En-Route Center Participant | One per en-route region (K) |
| `airport_app` | Airport Participant | One per airport (M) |
| `flightplan_service` | Flight Plan Service Participant | 1 (centralized) |
| `dashboard_app` | Read-only subscriber to all topics | 1 (monitoring/visualization) |

---

## 8. Request/Reply Implementation

RTI Connext provides the **Request/Reply** API built on top of regular DDS topics.

### Flight Plan Filing
```
Requester<FlightPlanRequest, FlightPlanReply>  →  airplane_app
Replier<FlightPlanRequest, FlightPlanReply>    →  flightplan_service
```

- The requester sends a `FlightPlanRequest` containing the full `FlightPlan`.
- The replier validates the plan, publishes it on the `FlightPlan` topic if accepted, and returns a `FlightPlanReply`.

### Gate Assignment
```
Requester<GateAssignmentRequest, GateAssignmentReply>  →  airplane_app
Replier<GateAssignmentRequest, GateAssignmentReply>    →  airport_app
```

- The requester sends a `GateAssignmentRequest` upon approach.
- The airport replier checks availability and responds with a gate assignment.

---

## 9. Discovery and Participant Configuration

| Setting | Value | Notes |
|---|---|---|
| **Discovery Protocol** | DPDE (default) | Simple Participant Discovery for demos; switch to DPDEv2 or Discovery Service for larger scale |
| **Initial Peers** | `builtin.udpv4://239.255.0.1` | Multicast for LAN demo; replace with unicast peer list or Discovery Service for WAN |
| **Max Participants per Domain** | 128 | Covers dozens of airports + hundreds of aircraft |
| **Type Registration** | Static (code-generated types) | Generated once from IDL; no dynamic types needed |

---

## 10. Fault Tolerance and Liveliness

| Mechanism | DDS Feature | Application |
|---|---|---|
| **Controller failure detection** | Liveliness QoS (`AUTOMATIC` or `MANUAL_BY_TOPIC`) | Towers and centers detect when a controller goes silent |
| **Aircraft loss detection** | Deadline QoS on `AircraftPosition` subscriber | Tower gets notified if an aircraft stops reporting |
| **Redundant controllers** | Ownership QoS (`EXCLUSIVE`) with strength | Backup controller takes over if primary fails; highest-strength writer wins |
| **Late-join state recovery** | Durability (`TRANSIENT_LOCAL`) | New/recovering participant gets current state of all active instances |

---

## 11. Deployment Diagram (DDS View)

```
┌─────────────────────────── Domain 0: AirTraffic ───────────────────────────┐
│                                                                             │
│  Partition: national                                                        │
│  ┌──────────────────┐     ┌──────────────────┐                             │
│  │ flightplan_service│     │  dashboard_app   │                             │
│  │ (Replier)         │     │  (all-topic sub) │                             │
│  └──────────────────┘     └──────────────────┘                             │
│                                                                             │
│  Partition: airport/KJFK                Partition: airport/EGLL             │
│  ┌────────────┐ ┌───────────┐          ┌────────────┐ ┌───────────┐       │
│  │ tower_app  │ │airport_app│          │ tower_app  │ │airport_app│       │
│  │  (KJFK)   │ │  (KJFK)   │          │  (EGLL)   │ │  (EGLL)   │       │
│  └────────────┘ └───────────┘          └────────────┘ └───────────┘       │
│        ▲ CFT                                  ▲ CFT                        │
│        │                                      │                            │
│  Partition: enroute/CENTER_EAST         Partition: enroute/CENTER_WEST     │
│  ┌──────────────────┐                  ┌──────────────────┐               │
│  │   center_app     │◄── Handoff ────►│   center_app     │               │
│  │  (CENTER_EAST)   │    Topic        │  (CENTER_WEST)   │               │
│  └──────────────────┘                  └──────────────────┘               │
│        ▲ CFT                                  ▲ CFT                        │
│        │                                      │                            │
│   ✈ airplane_app (N instances, each in relevant partition(s))              │
│     Publishes: AircraftPosition                                            │
│     Subscribes: ControllerInstruction (CFT), WeatherReport (CFT)          │
│     Request/Reply: FlightPlan, GateAssignment                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 12. File / Project Structure

```
air-traffic-dds/
├── idl/
│   └── air_traffic.idl              # All type definitions
├── qos/
│   └── air_traffic_qos.xml          # QoS profile library
├── src/
│   ├── airplane_app/                # Aircraft simulator
│   ├── tower_app/                   # Control tower logic
│   ├── center_app/                  # En-route center logic
│   ├── airport_app/                 # Airport infrastructure (weather, runways, gates)
│   ├── flightplan_service/          # Flight plan filing service
│   ├── dashboard_app/               # Visualization / monitoring
│   └── common/                      # Shared utilities (time, logging, config)
├── scripts/
│   ├── run_scenario.sh              # Launch a multi-process demo scenario
│   └── generate_types.sh            # Run rtiddsgen on the IDL
├── config/
│   └── scenario_*.json              # Scenario definitions (airports, routes, aircraft counts)
└── README.md
```

---

## 13. Summary: Architecture-to-DDS Mapping

| Architecture Concept | DDS Realization |
|---|---|
| Publish/Subscribe | DDS Topics with DataWriters and DataReaders |
| Command/Response | Directed topic samples filtered by `aircraft_id` or `controller_id` via Content-Filtered Topics |
| Request/Reply | Connext Request/Reply API (built on correlated DDS topics) |
| Timeliness | Deadline, Latency Budget, and Transport Priority QoS |
| Reliability | Reliability QoS (`RELIABLE` vs `BEST_EFFORT`) per topic |
| Late-join state | Durability (`TRANSIENT_LOCAL`) + History (`KEEP_LAST(1)`) |
| Filtering | Content-Filtered Topics and Partitions |
| Priority | Transport Priority QoS (alerts > commands > position) |
| Fault detection | Liveliness and Deadline QoS policies |
| Redundancy | Ownership QoS with strength for failover |
| Logical isolation | Partitions within a single domain |
