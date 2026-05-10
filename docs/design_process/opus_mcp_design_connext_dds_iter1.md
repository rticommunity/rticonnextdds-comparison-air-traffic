# RTI Connext DDS Design — National Air-Traffic Control System

> **Purpose:** Map the technology-agnostic [architecture overview](architecture_overview.md) onto RTI Connext DDS 7.7.0 Pro concepts: domains, partitions, IDL4 data types, QoS profiles, content-filtered topics, participants, and the request/reply API.
>
> **Design guidance sourced from:** RTI Connext AI (MCP) and official RTI documentation.

---

## 1. Domain Architecture

### 1.1 Single Operational Domain

A single DDS domain is recommended for core ATC operations. This is the best fit because:

- Simplest topology — no Routing Service needed to exchange operational data.
- Aircraft move dynamically between airport-local and en-route scopes; a single domain avoids multiple participants or routed data paths.
- Partitions + Content-Filtered Topics provide sufficient logical separation.

| Domain ID | Name | Purpose |
|---|---|---|
| `0` | **ATC Operations** | All real-time air-traffic data |

Additional domains should only be added for hard isolation boundaries:

| Domain ID | Purpose |
|---|---|
| `1` | Training / Simulation |
| `2` | Analytics / Cloud backhaul |
| `3` | Administration / Monitoring |

### 1.2 Partition Strategy

Partitions control **who can match and communicate**. They are lightweight, dynamically changeable, and reduce unnecessary discovery overhead.

**Rule of thumb:**
- **Partitions** = coarse routing / visibility ("should these entities even match?")
- **CFTs** = fine-grained data selection ("they match, but each wants different samples")

#### DomainParticipant Partitions (Coarse Scope)

Participants without matching partitions do not exchange endpoint discovery information.

| Partition Expression | Used By |
|---|---|
| `OPS/AIRPORT/<code>` | Tower and airport apps at that airport (e.g., `OPS/AIRPORT/KJFK`) |
| `OPS/ENROUTE/<center_id>` | En-route center apps (e.g., `OPS/ENROUTE/ZNY`) |
| `OPS/NATIONAL` | System-wide participants (flight plan service, dashboard) |

A participant can join **multiple partitions**. For example, an aircraft at JFK under ZNY:
- `OPS/AIRPORT/KJFK`, `OPS/ENROUTE/ZNY`

#### Publisher/Subscriber Partitions (Logical Channels)

| Partition Expression | Purpose |
|---|---|
| `AIRPORT/<code>/TRACK` | Aircraft position data at an airport |
| `AIRPORT/<code>/CLEARANCE` | Controller instructions at an airport |
| `ENROUTE/<center>/TRACK` | En-route position data |
| `ENROUTE/<center>/HANDOFF` | Handoff coordination |
| `NATIONAL/FLOW` | Flight plans, system-wide alerts |
| `NATIONAL/WEATHER` | Weather reports |

---

## 2. IDL Data Types (Modern IDL4)

The data model uses modern OMG IDL 4 syntax as recommended for Connext 7.7.0:

- **`@appendable`** extensibility on all types (default; allows future evolution by appending fields)
- **`@key`** annotations for DDS instance identity
- **`@nested`** on reusable helper structs (prevents code generation of unnecessary reader/writer APIs)
- **`@topic`** on top-level publishable types (explicitly marks them for code generation)
- **`@optional`** where field absence is semantically meaningful
- **Bounded strings and sequences** for predictable memory usage and wire size

```idl
module NationalAirTrafficControl {

    // ─── Constants ─────────────────────────────────────────

    const uint32 MAX_ID_LEN = 64;
    const uint32 MAX_CALLSIGN_LEN = 16;
    const uint32 MAX_AIRPORT_CODE_LEN = 8;
    const uint32 MAX_RUNWAY_ID_LEN = 16;
    const uint32 MAX_WAYPOINT_NAME_LEN = 16;
    const uint32 MAX_TEXT_LEN = 256;
    const uint32 MAX_ROUTE_POINTS = 128;
    const uint32 MAX_INVOLVED_AIRCRAFT = 16;

    // ─── Type Aliases ──────────────────────────────────────

    typedef string<MAX_ID_LEN> IdString;
    typedef string<MAX_CALLSIGN_LEN> Callsign;
    typedef string<MAX_AIRPORT_CODE_LEN> AirportCode;
    typedef string<MAX_RUNWAY_ID_LEN> RunwayId;
    typedef string<MAX_WAYPOINT_NAME_LEN> WaypointName;
    typedef string<MAX_TEXT_LEN> ShortText;
    typedef int64 Timestamp;

    // ─── Nested Helper Types ───────────────────────────────

    @nested
    @appendable
    struct GeoPosition {
        double latitude;
        double longitude;
        double altitude_feet;
    };

    @nested
    @appendable
    struct Wind {
        uint16 direction_degrees;
        float speed_knots;
        @optional float gust_knots;
    };

    @nested
    @appendable
    struct Waypoint {
        WaypointName name;
        GeoPosition position;
        @optional Timestamp estimated_time;
    };

    // ─── Enumerations ──────────────────────────────────────

    @appendable
    enum FlightPhase {
        PREFLIGHT,
        TAXI_OUT,
        TAKEOFF,
        CLIMB,
        CRUISE,
        DESCENT,
        APPROACH,
        LANDING,
        TAXI_IN,
        PARKED,
        HOLDING
    };

    @appendable
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

    @appendable
    enum AcknowledgmentStatus {
        RECEIVED,
        WILCO,
        UNABLE,
        READBACK_CORRECT,
        READBACK_INCORRECT
    };

    @appendable
    enum FlightPlanStatus {
        FILED,
        ACTIVE,
        AMENDED,
        DELAYED,
        CANCELLED,
        COMPLETED
    };

    @appendable
    enum RunwayOperationalStatus {
        OPEN,
        CLOSED,
        OCCUPIED
    };

    @appendable
    enum WeatherCondition {
        VMC,
        IMC,
        RAIN,
        SNOW,
        FOG,
        THUNDERSTORM,
        WIND_SHEAR,
        ICE
    };

    @appendable
    enum HandoffStatus {
        INITIATED,
        ACCEPTED,
        REJECTED,
        COMPLETED,
        CANCELLED
    };

    @appendable
    enum AlertSeverity {
        INFO,
        CAUTION,
        WARNING,
        CRITICAL
    };

    @appendable
    enum AlertType {
        EMERGENCY,
        TRAFFIC_CONFLICT,
        WEATHER_HAZARD,
        RUNWAY_INCURSION,
        COMMUNICATION_LOSS,
        SYSTEM_FAILURE
    };

    @appendable
    enum GateAssignmentStatusKind {
        PENDING,
        ASSIGNED,
        REJECTED,
        RELEASED
    };

    // ─── Pub/Sub Topic Types ───────────────────────────────

    @topic
    @appendable
    struct AircraftPosition {
        @key IdString aircraft_id;
        Callsign callsign;
        GeoPosition position;
        float ground_speed_knots;
        float vertical_speed_fpm;
        float heading_degrees;
        FlightPhase flight_phase;
        AirportCode origin_airport;
        AirportCode destination_airport;
        float fuel_level_percent;
        @optional RunwayId assigned_runway;
        Timestamp timestamp;
    };

    @topic
    @appendable
    struct ControllerInstruction {
        @key IdString instruction_id;
        IdString controller_id;
        IdString aircraft_id;
        InstructionType instruction_type;
        @optional float assigned_heading_degrees;
        @optional int32 assigned_altitude_feet;
        @optional float assigned_speed_knots;
        @optional ShortText clearance_text;
        @optional ShortText taxi_route;
        @optional ShortText hold_reason;
        Timestamp issued_at;
    };

    @topic
    @appendable
    struct PilotAcknowledgment {
        @key IdString acknowledgment_id;
        IdString instruction_id;
        IdString aircraft_id;
        AcknowledgmentStatus status;
        @optional ShortText response_text;
        Timestamp acknowledged_at;
    };

    @topic
    @appendable
    struct FlightPlan {
        @key IdString flight_plan_id;
        IdString aircraft_id;
        Callsign callsign;
        AirportCode departure_airport;
        AirportCode arrival_airport;
        sequence<Waypoint, MAX_ROUTE_POINTS> waypoints;
        Timestamp scheduled_departure_time;
        @optional Timestamp estimated_departure_time;
        @optional Timestamp scheduled_arrival_time;
        @optional Timestamp estimated_arrival_time;
        FlightPlanStatus status;
        Timestamp last_updated;
    };

    @topic
    @appendable
    struct RunwayStatus {
        @key AirportCode airport_code;
        @key RunwayId runway_id;
        RunwayOperationalStatus status;
        @optional ShortText remarks;
        Timestamp timestamp;
    };

    @topic
    @appendable
    struct WeatherReport {
        @key AirportCode airport_code;
        Wind wind;
        float visibility_meters;
        int32 ceiling_feet;
        float temperature_celsius;
        float altimeter_hpa;
        WeatherCondition conditions;
        Timestamp observation_time;
    };

    @topic
    @appendable
    struct Handoff {
        @key IdString handoff_id;
        IdString aircraft_id;
        IdString from_controller_id;
        IdString to_controller_id;
        HandoffStatus status;
        @optional ShortText sector;
        @optional ShortText frequency;
        Timestamp initiated_at;
        @optional Timestamp completed_at;
    };

    @topic
    @appendable
    struct Alert {
        @key IdString alert_id;
        AlertType alert_type;
        AlertSeverity severity;
        sequence<IdString, MAX_INVOLVED_AIRCRAFT> involved_aircraft;
        @optional AirportCode airport_code;
        @optional RunwayId runway_id;
        ShortText message;
        Timestamp timestamp;
    };

    // ─── Request/Reply Types ───────────────────────────────
    // No special annotations required for Connext Request/Reply.
    // Connext handles correlation metadata internally.

    @appendable
    struct FlightPlanRequest {
        FlightPlan plan;
    };

    @appendable
    struct FlightPlanResponse {
        @key IdString flight_plan_id;
        boolean accepted;
        @optional ShortText message;
        Timestamp response_timestamp;
    };

    @appendable
    struct GateRequest {
        @key IdString flight_id;
        AirportCode aerodrome_id;
        Timestamp requested_timestamp;
        boolean requires_assignment;
    };

    @nested
    @appendable
    struct GateAssignment {
        IdString flight_id;
        string<16> gate_name;
        GateAssignmentStatusKind status;
        Timestamp assignment_timestamp;
        @optional ShortText message;
    };

    @appendable
    struct GateAssignmentReply {
        @key IdString flight_id;
        GateAssignment assignment;
    };

};
```

### IDL Design Notes

| Decision | Rationale |
|---|---|
| `@appendable` everywhere | Allows schema evolution by appending fields without breaking compatibility |
| Bounded strings (`string<N>`) | Predictable memory allocation; avoids unbounded-type code generation issues |
| Bounded sequences | `sequence<Waypoint, 128>`, `sequence<IdString, 16>` — preallocated to max size |
| Composite key on `RunwayStatus` | `@key airport_code` + `@key runway_id` — natural compound identity |
| `@optional` on `ControllerInstruction` params | Type-safe instruction parameters instead of a generic blob |
| `@nested` on helpers | `GeoPosition`, `Wind`, `Waypoint`, `GateAssignment` — no reader/writer generated |
| `@topic` on pub/sub types | Explicitly marks top-level types for code generation |

---

## 3. Topics

| Topic Name | IDL Type | Key Fields | Pattern | QoS Profile |
|---|---|---|---|---|
| `AircraftPosition` | `AircraftPosition` | `aircraft_id` | Pub/Sub (periodic) | `PositionReportingProfile` |
| `ControllerInstruction` | `ControllerInstruction` | `instruction_id` | Pub/Sub (directed) | `ReliableCommandProfile` |
| `PilotAcknowledgment` | `PilotAcknowledgment` | `acknowledgment_id` | Pub/Sub (directed) | `ReliableCommandProfile` |
| `FlightPlan` | `FlightPlan` | `flight_plan_id` | Pub/Sub (state) | `StateDataProfile` |
| `RunwayStatus` | `RunwayStatus` | `airport_code` + `runway_id` | Pub/Sub (state) | `StateDataProfile` |
| `WeatherReport` | `WeatherReport` | `airport_code` | Pub/Sub (state) | `StateDataProfile` |
| `Handoff` | `Handoff` | `handoff_id` | Pub/Sub (directed) | `HandoffProfile` |
| `Alert` | `Alert` | `alert_id` | Pub/Sub (broadcast) | `AlertBroadcastProfile` |

### Request/Reply Services

| Service Name | Request Type | Reply Type | QoS Profile |
|---|---|---|---|
| `FlightPlanFilingService` | `FlightPlanRequest` | `FlightPlanResponse` | `FlightPlanRequestReplyProfile` |
| `GateAssignmentService` | `GateRequest` | `GateAssignmentReply` | `GateAssignmentRequestReplyProfile` |

---

## 4. QoS Profiles

All profiles are defined in `USER_QOS_PROFILES.xml` and inherit from Connext built-in QoS profiles where appropriate.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<dds xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xsi:noNamespaceSchemaLocation=
       "https://community.rti.com/schema/7.7.0/rti_dds_qos_profiles.xsd"
     version="7.7.0">

    <qos_library name="AirTrafficControl_QosLib">

        <!--
            PositionReportingProfile
            Topics: AircraftPosition
            High-rate periodic data (~5 Hz), best-effort, volatile
        -->
        <qos_profile name="PositionReportingProfile"
                     base_name="BuiltinQosLib::Pattern.PeriodicData"
                     is_default_qos="false">

            <datawriter_qos>
                <deadline>
                    <period>
                        <sec>0</sec>
                        <nanosec>200000000</nanosec>
                    </period>
                </deadline>
                <latency_budget>
                    <duration>
                        <sec>0</sec>
                        <nanosec>50000000</nanosec>
                    </duration>
                </latency_budget>
                <lifespan>
                    <duration>
                        <sec>1</sec>
                        <nanosec>0</nanosec>
                    </duration>
                </lifespan>
                <reliability>
                    <kind>BEST_EFFORT_RELIABILITY_QOS</kind>
                </reliability>
                <history>
                    <kind>KEEP_LAST_HISTORY_QOS</kind>
                    <depth>1</depth>
                </history>
                <durability>
                    <kind>VOLATILE_DURABILITY_QOS</kind>
                </durability>
                <ownership>
                    <kind>EXCLUSIVE_OWNERSHIP_QOS</kind>
                </ownership>
            </datawriter_qos>

            <datareader_qos>
                <deadline>
                    <period>
                        <sec>0</sec>
                        <nanosec>200000000</nanosec>
                    </period>
                </deadline>
                <latency_budget>
                    <duration>
                        <sec>0</sec>
                        <nanosec>50000000</nanosec>
                    </duration>
                </latency_budget>
                <lifespan>
                    <duration>
                        <sec>1</sec>
                        <nanosec>0</nanosec>
                    </duration>
                </lifespan>
                <reliability>
                    <kind>BEST_EFFORT_RELIABILITY_QOS</kind>
                </reliability>
                <history>
                    <kind>KEEP_LAST_HISTORY_QOS</kind>
                    <depth>1</depth>
                </history>
                <durability>
                    <kind>VOLATILE_DURABILITY_QOS</kind>
                </durability>
                <ownership>
                    <kind>EXCLUSIVE_OWNERSHIP_QOS</kind>
                </ownership>
            </datareader_qos>
        </qos_profile>


        <!--
            ReliableCommandProfile
            Topics: ControllerInstruction, PilotAcknowledgment
            Reliable, keep-all, transient-local, priority 5
        -->
        <qos_profile name="ReliableCommandProfile"
                     base_name="BuiltinQosLib::Generic.StrictReliable"
                     is_default_qos="false">

            <base_name>
                <element>BuiltinQosSnippetLib::QosPolicy.Durability.TransientLocal</element>
            </base_name>

            <datawriter_qos>
                <deadline>
                    <period>
                        <sec>5</sec>
                        <nanosec>0</nanosec>
                    </period>
                </deadline>
                <liveliness>
                    <kind>AUTOMATIC_LIVELINESS_QOS</kind>
                    <lease_duration>
                        <sec>10</sec>
                        <nanosec>0</nanosec>
                    </lease_duration>
                </liveliness>
                <transport_priority>
                    <value>5</value>
                </transport_priority>
                <reliability>
                    <kind>RELIABLE_RELIABILITY_QOS</kind>
                    <max_blocking_time>
                        <sec>5</sec>
                        <nanosec>0</nanosec>
                    </max_blocking_time>
                </reliability>
                <history>
                    <kind>KEEP_ALL_HISTORY_QOS</kind>
                </history>
                <durability>
                    <kind>TRANSIENT_LOCAL_DURABILITY_QOS</kind>
                </durability>
            </datawriter_qos>

            <datareader_qos>
                <deadline>
                    <period>
                        <sec>5</sec>
                        <nanosec>0</nanosec>
                    </period>
                </deadline>
                <liveliness>
                    <kind>AUTOMATIC_LIVELINESS_QOS</kind>
                    <lease_duration>
                        <sec>10</sec>
                        <nanosec>0</nanosec>
                    </lease_duration>
                </liveliness>
                <transport_priority>
                    <value>5</value>
                </transport_priority>
                <reliability>
                    <kind>RELIABLE_RELIABILITY_QOS</kind>
                </reliability>
                <history>
                    <kind>KEEP_ALL_HISTORY_QOS</kind>
                </history>
                <durability>
                    <kind>TRANSIENT_LOCAL_DURABILITY_QOS</kind>
                </durability>
            </datareader_qos>
        </qos_profile>


        <!--
            StateDataProfile
            Topics: RunwayStatus, WeatherReport, FlightPlan
            Reliable, keep-last-1, transient-local, exclusive ownership
            WeatherReport gets a 30s deadline via topic_filter override
        -->
        <qos_profile name="StateDataProfile"
                     base_name="BuiltinQosLib::Pattern.Status"
                     is_default_qos="false">

            <datawriter_qos>
                <reliability>
                    <kind>RELIABLE_RELIABILITY_QOS</kind>
                    <max_blocking_time>
                        <sec>5</sec>
                        <nanosec>0</nanosec>
                    </max_blocking_time>
                </reliability>
                <history>
                    <kind>KEEP_LAST_HISTORY_QOS</kind>
                    <depth>1</depth>
                </history>
                <durability>
                    <kind>TRANSIENT_LOCAL_DURABILITY_QOS</kind>
                </durability>
                <ownership>
                    <kind>EXCLUSIVE_OWNERSHIP_QOS</kind>
                </ownership>
            </datawriter_qos>

            <datareader_qos>
                <reliability>
                    <kind>RELIABLE_RELIABILITY_QOS</kind>
                </reliability>
                <history>
                    <kind>KEEP_LAST_HISTORY_QOS</kind>
                    <depth>1</depth>
                </history>
                <durability>
                    <kind>TRANSIENT_LOCAL_DURABILITY_QOS</kind>
                </durability>
                <ownership>
                    <kind>EXCLUSIVE_OWNERSHIP_QOS</kind>
                </ownership>
            </datareader_qos>

            <!-- WeatherReport-specific deadline override -->
            <datawriter_qos topic_filter="WeatherReport">
                <deadline>
                    <period>
                        <sec>30</sec>
                        <nanosec>0</nanosec>
                    </period>
                </deadline>
            </datawriter_qos>

            <datareader_qos topic_filter="WeatherReport">
                <deadline>
                    <period>
                        <sec>30</sec>
                        <nanosec>0</nanosec>
                    </period>
                </deadline>
            </datareader_qos>
        </qos_profile>


        <!--
            AlertBroadcastProfile
            Topics: Alert
            Reliable, keep-all, transient-local, lifespan 60s, priority 10
        -->
        <qos_profile name="AlertBroadcastProfile"
                     base_name="BuiltinQosLib::Pattern.Event"
                     is_default_qos="false">

            <base_name>
                <element>BuiltinQosSnippetLib::QosPolicy.Durability.TransientLocal</element>
            </base_name>

            <datawriter_qos>
                <lifespan>
                    <duration>
                        <sec>60</sec>
                        <nanosec>0</nanosec>
                    </duration>
                </lifespan>
                <transport_priority>
                    <value>10</value>
                </transport_priority>
                <reliability>
                    <kind>RELIABLE_RELIABILITY_QOS</kind>
                    <max_blocking_time>
                        <sec>5</sec>
                        <nanosec>0</nanosec>
                    </max_blocking_time>
                </reliability>
                <history>
                    <kind>KEEP_ALL_HISTORY_QOS</kind>
                </history>
                <durability>
                    <kind>TRANSIENT_LOCAL_DURABILITY_QOS</kind>
                </durability>
            </datawriter_qos>

            <datareader_qos>
                <time_based_filter>
                    <minimum_separation>
                        <sec>0</sec>
                        <nanosec>0</nanosec>
                    </minimum_separation>
                </time_based_filter>
                <transport_priority>
                    <value>10</value>
                </transport_priority>
                <reliability>
                    <kind>RELIABLE_RELIABILITY_QOS</kind>
                </reliability>
                <history>
                    <kind>KEEP_ALL_HISTORY_QOS</kind>
                </history>
                <durability>
                    <kind>TRANSIENT_LOCAL_DURABILITY_QOS</kind>
                </durability>
            </datareader_qos>
        </qos_profile>


        <!--
            HandoffProfile
            Topics: Handoff
            Reliable, keep-last-5, transient-local, manual-by-topic liveliness
        -->
        <qos_profile name="HandoffProfile"
                     base_name="BuiltinQosLib::Generic.KeepLastReliable.TransientLocal"
                     is_default_qos="false">

            <datawriter_qos>
                <reliability>
                    <kind>RELIABLE_RELIABILITY_QOS</kind>
                    <max_blocking_time>
                        <sec>5</sec>
                        <nanosec>0</nanosec>
                    </max_blocking_time>
                </reliability>
                <history>
                    <kind>KEEP_LAST_HISTORY_QOS</kind>
                    <depth>5</depth>
                </history>
                <durability>
                    <kind>TRANSIENT_LOCAL_DURABILITY_QOS</kind>
                </durability>
                <liveliness>
                    <kind>MANUAL_BY_TOPIC_LIVELINESS_QOS</kind>
                    <lease_duration>
                        <sec>15</sec>
                        <nanosec>0</nanosec>
                    </lease_duration>
                </liveliness>
            </datawriter_qos>

            <datareader_qos>
                <reliability>
                    <kind>RELIABLE_RELIABILITY_QOS</kind>
                </reliability>
                <history>
                    <kind>KEEP_LAST_HISTORY_QOS</kind>
                    <depth>5</depth>
                </history>
                <durability>
                    <kind>TRANSIENT_LOCAL_DURABILITY_QOS</kind>
                </durability>
                <liveliness>
                    <kind>MANUAL_BY_TOPIC_LIVELINESS_QOS</kind>
                    <lease_duration>
                        <sec>15</sec>
                        <nanosec>0</nanosec>
                    </lease_duration>
                </liveliness>
            </datareader_qos>
        </qos_profile>


        <!--
            Request/Reply Profiles
            Based on BuiltinQosLib::Pattern.RPC (reliable, keep-all, tuned for RPC)
        -->
        <qos_profile name="FlightPlanRequestReplyProfile"
                     base_name="BuiltinQosLib::Pattern.RPC"
                     is_default_qos="false">
            <datawriter_qos>
                <reliability>
                    <max_blocking_time>
                        <sec>2</sec>
                        <nanosec>0</nanosec>
                    </max_blocking_time>
                </reliability>
            </datawriter_qos>
        </qos_profile>

        <qos_profile name="GateAssignmentRequestReplyProfile"
                     base_name="BuiltinQosLib::Pattern.RPC"
                     is_default_qos="false">
            <datawriter_qos>
                <reliability>
                    <max_blocking_time>
                        <sec>2</sec>
                        <nanosec>0</nanosec>
                    </max_blocking_time>
                </reliability>
            </datawriter_qos>
        </qos_profile>

    </qos_library>
</dds>
```

### QoS Profile Summary

| Profile | Base Built-in Profile | Topics | Key Policies |
|---|---|---|---|
| `PositionReportingProfile` | `BuiltinQosLib::Pattern.PeriodicData` | AircraftPosition | Best-effort, keep-last-1, volatile, deadline 200ms, lifespan 1s, exclusive ownership |
| `ReliableCommandProfile` | `BuiltinQosLib::Generic.StrictReliable` | ControllerInstruction, PilotAcknowledgment | Reliable, keep-all, transient-local, deadline 5s, liveliness 10s, priority 5 |
| `StateDataProfile` | `BuiltinQosLib::Pattern.Status` | RunwayStatus, WeatherReport, FlightPlan | Reliable, keep-last-1, transient-local, exclusive ownership, 30s deadline (weather only) |
| `AlertBroadcastProfile` | `BuiltinQosLib::Pattern.Event` | Alert | Reliable, keep-all, transient-local, lifespan 60s, priority 10 (highest) |
| `HandoffProfile` | `BuiltinQosLib::Generic.KeepLastReliable.TransientLocal` | Handoff | Reliable, keep-last-5, transient-local, manual-by-topic liveliness 15s |
| `FlightPlanRequestReplyProfile` | `BuiltinQosLib::Pattern.RPC` | FlightPlanFilingService | Reliable, keep-all, RPC-tuned protocol |
| `GateAssignmentRequestReplyProfile` | `BuiltinQosLib::Pattern.RPC` | GateAssignmentService | Reliable, keep-all, RPC-tuned protocol |

---

## 5. Content-Filtered Topics

Content-Filtered Topics (CFTs) reduce data volume per subscriber. In Connext, **writer-side filtering is applied automatically** when possible — the publisher evaluates filters and sends only matching data, saving network bandwidth.

### Writer-Side Filtering Conditions

Writer-side filtering is applied unless one of these conditions is present:
- `PublishMode.kind = ASYNCHRONOUS`
- `Liveliness.lease_duration != INFINITE`
- `Batch.enable = true`
- Multicast subscription

**Recommendation for maximum CFT efficiency:**
- Use synchronous publishing on filtered topics
- Avoid batching on command/control topics
- Use unicast delivery for CFT-filtered readers

### CFT Definitions

| CFT Name | Base Topic | SQL Filter | Used By |
|---|---|---|---|
| `MyInstructions` | `ControllerInstruction` | `aircraft_id = %0` | Airplane (receives only its own instructions) |
| `LocalTraffic` | `AircraftPosition` | `(origin_airport = %0) OR (destination_airport = %0)` | Control Tower (sees only local traffic) |
| `SectorTraffic` | `AircraftPosition` | `(position.altitude_feet >= %0) AND (position.altitude_feet < %1)` | En-Route Center (altitude band filtering) |
| `MyHandoffs` | `Handoff` | `(to_controller_id = %0) OR (from_controller_id = %0)` | Controller (receives relevant handoffs) |
| `DestinationWeather` | `WeatherReport` | `airport_code = %0` | Airplane (weather at destination) |
| `LocalRunways` | `RunwayStatus` | `airport_code = %0` | Tower, Airplane (runways at one airport) |

### CFT Python Example

```python
import rti.connextdds as dds

# Aircraft receives only its own instructions
topic = dds.Topic(participant, "ControllerInstruction", ControllerInstruction)

cft = dds.ContentFilteredTopic(
    topic,
    "MyInstructions",
    dds.Filter("aircraft_id = %0", ["'AAL123'"])
)

reader = dds.DataReader(subscriber, cft)
```

### Partitions + CFTs Combined

For maximum efficiency, combine both. Example for a JFK tower:

1. **Partition:** `AIRPORT/KJFK/TRACK` — only matches writers in the JFK track channel
2. **CFT:** `(origin_airport = 'KJFK') OR (destination_airport = 'KJFK')` — further filters to JFK-relevant flights

This way the reader:
- Only discovers and matches endpoints in its partition
- Only receives data passing the content filter

---

## 6. DDS Participants and Data Flows

### 6.1 Airplane Participant

Each aircraft runs one DomainParticipant.

**Partitions:** `OPS/AIRPORT/<origin>`, `OPS/ENROUTE/<center>` (dynamic as flight progresses)

| Direction | Topic / Service | QoS Profile | Notes |
|---|---|---|---|
| **Publish** | `AircraftPosition` | `PositionReportingProfile` | Periodic ~5 Hz |
| **Publish** | `PilotAcknowledgment` | `ReliableCommandProfile` | Response to instructions |
| **Subscribe (CFT)** | `ControllerInstruction` | `ReliableCommandProfile` | Filter: `aircraft_id = %0` |
| **Subscribe (CFT)** | `WeatherReport` | `StateDataProfile` | Filter: `airport_code = %0` (destination) |
| **Requester** | `FlightPlanFilingService` | `FlightPlanRequestReplyProfile` | File/amend flight plans |
| **Requester** | `GateAssignmentService` | `GateAssignmentRequestReplyProfile` | Request gate on arrival |

### 6.2 Control Tower Participant

One DomainParticipant per airport.

**Partitions:** `OPS/AIRPORT/<code>`, `OPS/NATIONAL`

| Direction | Topic / Service | QoS Profile | Notes |
|---|---|---|---|
| **Subscribe (CFT)** | `AircraftPosition` | `PositionReportingProfile` | Filter: `origin/destination = %0` |
| **Publish** | `ControllerInstruction` | `ReliableCommandProfile` | Clearances and commands |
| **Subscribe** | `PilotAcknowledgment` | `ReliableCommandProfile` | Pilot responses |
| **Publish** | `RunwayStatus` | `StateDataProfile` | Runway state changes |
| **Publish/Subscribe (CFT)** | `Handoff` | `HandoffProfile` | Filter: `to/from_controller_id = %0` |
| **Publish** | `Alert` | `AlertBroadcastProfile` | Terminal-area conflicts |
| **Subscribe (CFT)** | `WeatherReport` | `StateDataProfile` | Filter: own airport |
| **Subscribe** | `FlightPlan` | `StateDataProfile` | Active flight plans |

### 6.3 En-Route Center Participant

One DomainParticipant per center.

**Partitions:** `OPS/ENROUTE/<center_id>`, `OPS/NATIONAL`

| Direction | Topic / Service | QoS Profile | Notes |
|---|---|---|---|
| **Subscribe (CFT)** | `AircraftPosition` | `PositionReportingProfile` | Filter: altitude band |
| **Publish** | `ControllerInstruction` | `ReliableCommandProfile` | Routing/altitude amendments |
| **Subscribe** | `PilotAcknowledgment` | `ReliableCommandProfile` | Pilot responses |
| **Publish/Subscribe (CFT)** | `Handoff` | `HandoffProfile` | Sector handoffs |
| **Publish** | `Alert` | `AlertBroadcastProfile` | Separation violations |
| **Subscribe** | `FlightPlan` | `StateDataProfile` | Active flight plans |

### 6.4 Airport Participant

Publishes infrastructure and environmental state.

**Partitions:** `OPS/AIRPORT/<code>`, `OPS/NATIONAL`

| Direction | Topic / Service | QoS Profile | Notes |
|---|---|---|---|
| **Publish** | `WeatherReport` | `StateDataProfile` | Periodic weather (≤30s) |
| **Publish** | `RunwayStatus` | `StateDataProfile` | Runway changes |
| **Replier** | `GateAssignmentService` | `GateAssignmentRequestReplyProfile` | Gate allocation |

### 6.5 Flight Plan Service Participant

Central service for flight plan validation.

**Partitions:** `OPS/NATIONAL`

| Direction | Topic / Service | QoS Profile | Notes |
|---|---|---|---|
| **Replier** | `FlightPlanFilingService` | `FlightPlanRequestReplyProfile` | Validate and accept/reject |
| **Publish** | `FlightPlan` | `StateDataProfile` | Publish accepted plans |

### 6.6 Dashboard Participant

Read-only monitoring and visualization.

**Partitions:** `OPS/*` (wildcard — subscribes to all)

| Direction | Topic | QoS Profile | Notes |
|---|---|---|---|
| **Subscribe** | All topics | Matching profiles | Read-only observation |

---

## 7. Request/Reply Implementation

The Connext **Request/Reply API** is built on correlated DDS topics. No special IDL annotations are needed — Connext handles correlation metadata internally. The default QoS is `BuiltinQosLib::Pattern.RPC` (reliable, keep-all).

### Key API Patterns

- Always call `wait_for_service()` before sending requests (endpoint discovery must complete)
- Supports **single-request / multiple-replies** (useful for `PENDING → ASSIGNED` gate workflow)
- Service name derives topic names automatically (`FlightPlanFilingService` → request/reply topics)

### Flight Plan Filing — Requester (Aircraft Side)

```python
import rti.connextdds as dds
from rti.rpc import Requester

requester = Requester(
    request_type=FlightPlanRequest,
    reply_type=FlightPlanResponse,
    participant=participant,
    service_name="FlightPlanFilingService"
)

if not requester.wait_for_service(dds.Duration(seconds=10)):
    raise RuntimeError("FlightPlanFilingService not discovered")

request_id = requester.send_request(request)
replies = requester.receive_replies(
    dds.Duration(seconds=10),
    related_request_id=request_id
)
```

### Flight Plan Filing — Replier (Service Side)

```python
import rti.connextdds as dds
from rti.rpc import Replier

replier = Replier(
    request_type=FlightPlanRequest,
    reply_type=FlightPlanResponse,
    participant=participant,
    service_name="FlightPlanFilingService"
)

while True:
    requests = replier.receive_requests(dds.Duration(seconds=20))
    for request, info in requests:
        if not info.valid:
            continue
        reply = validate_and_respond(request)
        replier.send_reply(reply, info)
```

### Gate Assignment — Multi-Reply Pattern

Connext supports multiple replies per request. The replier sends intermediate replies with `final=False`:

```python
# Send intermediate "PENDING" reply
replier.send_reply(pending_reply, info, final=False)

# Later, send final "ASSIGNED" reply
replier.send_reply(assigned_reply, info)  # final=True (default)
```

### XML + Python Hybrid Pattern

QoS is defined in XML; Requester/Replier instantiated in Python:

```python
qos_provider = dds.QosProvider("USER_QOS_PROFILES.xml")
participant = qos_provider.create_participant_from_config(
    "AtcParticipantLibrary::AircraftParticipant"
)

writer_qos = qos_provider.datawriter_qos_from_profile(
    "AirTrafficControl_QosLib::FlightPlanRequestReplyProfile"
)
reader_qos = qos_provider.datareader_qos_from_profile(
    "AirTrafficControl_QosLib::FlightPlanRequestReplyProfile"
)

requester = Requester(
    request_type=FlightPlanRequest,
    reply_type=FlightPlanResponse,
    participant=participant,
    service_name="FlightPlanFilingService",
    datawriter_qos=writer_qos,
    datareader_qos=reader_qos
)
```

---

## 8. Fault Tolerance and Liveliness

| Mechanism | DDS Feature | Application |
|---|---|---|
| **Controller failure detection** | Liveliness QoS (`AUTOMATIC`, 10s lease on commands) | Towers/centers detect silent controllers |
| **Aircraft loss detection** | Deadline QoS (200ms on `AircraftPosition` reader) | Tower notified if aircraft stops reporting |
| **Redundant controllers** | Ownership QoS (`EXCLUSIVE`) with strength | Backup takes over; highest-strength writer wins |
| **Late-join state recovery** | Durability (`TRANSIENT_LOCAL`) on state topics | New participant gets current runway, weather, flight plan state |
| **Controller disconnect** | Liveliness (`MANUAL_BY_TOPIC`, 15s on handoffs) | Detect controller disconnect during handoff |
| **Stale data expiry** | Lifespan (1s positions, 60s alerts) | Automatic removal of outdated samples |

---

## 9. Discovery Configuration

| Setting | Value | Notes |
|---|---|---|
| **Discovery Protocol** | DPDE (default) | Sufficient for demo; use Discovery Service for larger scale |
| **Initial Peers** | `builtin.udpv4://239.255.0.1` | Multicast for LAN; unicast list or Discovery Service for WAN |
| **Discovery Optimization** | `BuiltinQosSnippetLib::Optimization.Discovery.Common` + `Optimization.Discovery.Endpoint.Fast` | Reduces discovery latency |
| **Monitoring** | `BuiltinQosSnippetLib::Feature.Monitoring2.Enable` | Observability for all participants |

### Participant QoS with Optimizations

```xml
<qos_profile name="AtcParticipantProfile"
             base_name="BuiltinQosLib::Generic.Common">
    <domain_participant_qos>
        <base_name>
            <element>BuiltinQosSnippetLib::Optimization.Discovery.Common</element>
            <element>BuiltinQosSnippetLib::Optimization.Discovery.Endpoint.Fast</element>
            <element>BuiltinQosSnippetLib::Optimization.ReliabilityProtocol.Common</element>
            <element>BuiltinQosSnippetLib::Feature.Monitoring2.Enable</element>
        </base_name>
    </domain_participant_qos>
</qos_profile>
```

---

## 10. Deployment Diagram (DDS View)

```
┌───────────────────────── Domain 0: ATC Operations ─────────────────────────┐
│                                                                             │
│  Partition: OPS/NATIONAL                                                    │
│  ┌──────────────────────┐     ┌──────────────────┐                         │
│  │ flightplan_service    │     │  dashboard_app   │                         │
│  │ (Replier)             │     │  (all-topic sub) │                         │
│  └──────────────────────┘     └──────────────────┘                         │
│                                                                             │
│  Partition: OPS/AIRPORT/KJFK              Partition: OPS/AIRPORT/EGLL      │
│  ┌────────────┐ ┌───────────┐            ┌────────────┐ ┌───────────┐     │
│  │ tower_app  │ │airport_app│            │ tower_app  │ │airport_app│     │
│  │  (KJFK)   │ │  (KJFK)   │            │  (EGLL)   │ │  (EGLL)   │     │
│  └────────────┘ └───────────┘            └────────────┘ └───────────┘     │
│        ▲ CFT                                    ▲ CFT                      │
│        │                                        │                          │
│  Partition: OPS/ENROUTE/ZNY             Partition: OPS/ENROUTE/ZLA        │
│  ┌──────────────────┐                  ┌──────────────────┐               │
│  │   center_app     │◄── Handoff ────►│   center_app     │               │
│  │  (ZNY)           │    Topic        │  (ZLA)           │               │
│  └──────────────────┘                  └──────────────────┘               │
│        ▲ CFT                                  ▲ CFT                       │
│        │                                      │                           │
│   ✈ airplane_app (N instances)                                            │
│     Partitions: dynamic as flight progresses                              │
│     Publishes: AircraftPosition (periodic 5Hz)                            │
│     Subscribes: ControllerInstruction (CFT by aircraft_id)                │
│     Request/Reply: FlightPlanFilingService, GateAssignmentService         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 11. Application-to-Participant Mapping

| Application | Participant | Count | Language |
|---|---|---|---|
| `airplane_app` | Airplane Participant | N (per aircraft) | Python |
| `tower_app` | Control Tower Participant | M (per airport) | Python |
| `center_app` | En-Route Center Participant | K (per region) | Python |
| `airport_app` | Airport Participant | M (per airport) | Python |
| `flightplan_service` | Flight Plan Service | 1 | Python |
| `dashboard_app` | Dashboard (read-only) | 1 | Python |

---

## 12. Project Structure

```
air-traffic-dds/
├── idl/
│   └── air_traffic.idl              # All type definitions (IDL4)
├── qos/
│   └── USER_QOS_PROFILES.xml        # QoS profile library
├── src/
│   ├── atc_types.py                 # Python type definitions (@idl.struct)
│   ├── airplane_app/
│   │   └── airplane.py              # Aircraft simulator + requester
│   ├── tower_app/
│   │   └── tower.py                 # Control tower logic
│   ├── center_app/
│   │   └── center.py                # En-route center logic
│   ├── airport_app/
│   │   └── airport.py               # Weather, runways, gate replier
│   ├── flightplan_service/
│   │   └── flightplan_service.py    # Flight plan filing replier
│   ├── dashboard_app/
│   │   └── dashboard.py             # Visualization / monitoring
│   └── common/
│       └── utils.py                 # Shared utilities (time, logging)
├── scripts/
│   ├── run_scenario.sh              # Launch multi-process demo
│   └── generate_types.sh            # Run rtiddsgen on IDL
├── config/
│   └── scenario_default.json        # Airports, routes, aircraft counts
└── README.md
```

---

## 13. Connext 7.7.0 Features to Leverage

| Feature | Usage in ATC System |
|---|---|
| **XML-Based Application Creation** | Centralize domain/topic/QoS definitions; share same XML across all apps |
| **Modern Python API** | `@idl.struct`/`@idl.enum` typed dataclasses; `Requester`/`Replier` from `rti.rpc` |
| **Built-in QoS Profiles** | Inherit from `Pattern.PeriodicData`, `Pattern.Status`, `Pattern.RPC`, etc. |
| **QoS Snippets** | Compose with `QosSnippetLib` for discovery optimization, monitoring |
| **Monitoring 2.0 / Observability** | `Feature.Monitoring2.Enable` on all participants for operational insight |
| **Content-Filtered Topics** | Writer-side filtering for reduced bandwidth |
| **Request/Reply with multi-reply** | Gate assignment `PENDING → ASSIGNED` workflow |
| **`wait_for_service()`** | Robust discovery for Request/Reply before first request |
| **Topic filter overrides** | `topic_filter="WeatherReport"` for per-topic QoS within a shared profile |
| **Zero Copy** | Reserved for future large-data flows (radar tiles, maps); not needed for current types |

---

## 14. Architecture-to-DDS Mapping Summary

| Architecture Concept | DDS Realization |
|---|---|
| Publish/Subscribe | DDS Topics with DataWriters and DataReaders |
| Command/Response | Directed topic samples + CFTs filtered by `aircraft_id` / `controller_id` |
| Request/Reply | Connext Request/Reply API (`Requester` / `Replier`) via `rti.rpc` |
| Timeliness | Deadline (200ms), Latency Budget (50ms), Transport Priority QoS |
| Reliability | `RELIABLE` vs `BEST_EFFORT` per topic class |
| Late-join state | `TRANSIENT_LOCAL` durability + `KEEP_LAST(1)` history |
| Data filtering | Content-Filtered Topics (per-reader) + Partitions (per-scope) |
| Priority | Transport Priority: alerts (10) > commands (5) > positions (0) |
| Fault detection | Liveliness QoS + Deadline QoS |
| Redundancy | Exclusive Ownership QoS with strength for failover |
| Logical isolation | DomainParticipant and Publisher/Subscriber partitions |
| Observability | Monitoring 2.0 enabled on all participants |

---

## References

- [RTI Connext Built-in QoS Profiles](https://community.rti.com/static/documentation/connext-dds/current/resource/xml/BuiltinProfiles.documentationONLY.xml)
- [Content-Filtered Topics Guide](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/manuals/connext_dds_professional/getting_started_guide/csharp/intro_content_filters.html)
- [Request-Reply Pattern](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/manuals/connext_dds_professional/users_manual/users_manual/The_Request_Reply_Pattern.htm)
- [PARTITION QoS Policy](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/manuals/connext_dds_professional/users_manual/users_manual/PARTITION_QosPolicy.htm)
- [XML Application Creation](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/api/connext_dds/api_python/xmlapp.html)
- [Multi-Channel DataWriters](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/manuals/connext_dds_professional/users_manual/users_manual/MultichannelDatawriters.htm)
- [Extensible Types Guide](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/manuals/connext_dds_professional/extensible_types_guide/extensible_types/Defining_Extensible_Types.htm)
