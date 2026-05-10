# Impact of RTI Connext MCP on DDS Design Quality

> Comparison of two first-iteration designs for the same ATC system prompt:
> - **MCP-assisted** (`opus_mcp_design_connext_dds_iter1.md`) — Claude Opus with RTI Connext AI (MCP) tool access
> - **No-MCP** (`opus_nomcp_design_connext_dds_iter1.md`) — Claude Opus with no MCP access

---

## Summary of Differences

### 1. Partition Architecture

| Aspect | MCP | No-MCP |
|---|---|---|
| DP partitions | `OPS/AIRPORT/<code>`, `OPS/ENROUTE/<id>`, `OPS/NATIONAL` — hierarchical, Connext-aware | `airport/<code>`, `enroute/<center_id>`, `national` — flat, generic naming |
| Pub/Sub partitions | Yes — logical channels like `AIRPORT/<code>/TRACK`, `ENROUTE/<center>/HANDOFF` | None |
| Partition layers | Two (DP + Pub/Sub), clear separation of discovery vs. data routing | One (unspecified level), no distinction between discovery isolation and data routing |
| Wildcard usage | Dashboard uses `OPS/*` to observe all scopes | Not discussed |

**Verdict:** MCP design uses Connext's DP-level partition extension correctly to control discovery isolation, and adds a Pub/Sub partition layer for logical data channels. No-MCP treats partitions generically without leveraging Connext-specific DP partition behavior.

### 2. IDL Data Model

| Aspect | MCP | No-MCP |
|---|---|---|
| IDL syntax | Modern IDL4 with `@appendable`, `@nested`, `@topic`, `@optional`, `@key` | Legacy IDL3-style — no extensibility annotations, no `@nested`, no `@optional` |
| Type aliases | `IdString`, `Callsign`, `AirportCode`, `RunwayId`, `WaypointName`, `ShortText`, `Timestamp` | None — raw `string<N>` throughout |
| Bounded constants | Named constants (`MAX_ID_LEN`, `MAX_ROUTE_POINTS`) | Magic numbers inline |
| String bounds | All strings bounded via typedefs | All strings bounded but with hardcoded sizes |
| Extensibility | `@appendable` on all types and enums — future-proof schema evolution | None — any field change breaks wire compatibility |
| Nested helpers | `@nested` on `GeoPosition`, `Wind`, `Waypoint`, `GateAssignment` — no unnecessary code gen | Plain structs — code generator produces reader/writer APIs for helpers |
| Optional fields | `@optional` on `ControllerInstruction` parameters, `Handoff.sector`/`frequency`, timestamps | None — every field is mandatory, semantically incorrect for sparse types |
| FlightPhase enum | 11 values (PREFLIGHT through HOLDING) — realistic flight lifecycle | 7 values — missing PREFLIGHT, CLIMB, CRUISE, DESCENT, HOLDING |
| AcknowledgmentStatus | 5 values (RECEIVED, WILCO, UNABLE, READBACK_CORRECT, READBACK_INCORRECT) | 3 values (WILCO, UNABLE, REQUEST_REPEAT) |
| HandoffStatus | 5 values (INITIATED, ACCEPTED, REJECTED, COMPLETED, CANCELLED) | 3 values (REQUESTED, ACCEPTED, REJECTED) |
| AlertType | 6 values (adds COMMUNICATION_LOSS, SYSTEM_FAILURE, WEATHER_HAZARD) | 3 values (SEPARATION_VIOLATION, RUNWAY_INCURSION, EMERGENCY) |
| WeatherCondition | 8 values (VMC, IMC, RAIN, SNOW, FOG, THUNDERSTORM, WIND_SHEAR, ICE) | 4 values (VFR, MVFR, IFR, LIFR) |
| ControllerInstruction params | Type-safe `@optional` fields per instruction type | Generic `string<128> parameters` blob |
| Extra types | `Wind` struct, `GateAssignment` struct, `GateAssignmentStatusKind` enum | `Velocity` struct, `FlightPlanUpdate` topic (not in MCP) |
| Request/Reply types | `@appendable`, `@optional` on response fields, `GateAssignment` nested struct | Plain structs, simpler field sets |
| Topic count | 8 pub/sub + 2 services | 9 pub/sub + 2 services (has `FlightPlanUpdate` topic) |

**Verdict:** MCP design is significantly more Connext-idiomatic. The IDL4 annotations (`@appendable`, `@nested`, `@optional`, `@topic`) enable schema evolution, reduce unnecessary code generation, and model real-world optionality. No-MCP produces valid but legacy-style IDL that would break on any schema change.

### 3. QoS Profiles

| Aspect | MCP | No-MCP |
|---|---|---|
| Built-in base profiles | Every profile inherits from a specific Connext built-in (`Pattern.PeriodicData`, `Pattern.Status`, `Pattern.Event`, `Pattern.RPC`, `Generic.StrictReliable`, `Generic.KeepLastReliable.TransientLocal`) | No built-in inheritance — all QoS policies specified from scratch |
| QoS snippets | Uses `BuiltinQosSnippetLib::QosPolicy.Durability.TransientLocal` for composition | Not used |
| Profile count | 7 data profiles + 1 participant profile | 5 data profiles (no participant profile) |
| XML provided | Full inline XML with all profiles | Described in tables only — no XML |
| topic_filter | `topic_filter="WeatherReport"` for per-topic QoS within `StateDataProfile` | Not used |
| Discovery optimization | `Optimization.Discovery.Common`, `Optimization.Discovery.Endpoint.Fast`, `Optimization.ReliabilityProtocol.Common` | Mentioned in settings table but not configured |
| Monitoring | `Feature.Monitoring2.Enable` on all participants | Not mentioned |
| Lifespan | 1s on positions, 60s on alerts (writer-side stale data expiry) | 1s on positions, 60s on alerts (same) |
| Latency budget | 50ms on positions | 50ms on positions (same) |
| Transport priority | Alerts=10, Commands=5, Positions=0 | Alerts=10, Commands=5, Positions=0 (same) |

**Verdict:** MCP design leverages Connext's built-in QoS profile inheritance system — the single most important Connext-specific QoS feature. This reduces configuration to only the deltas from well-tested baselines. No-MCP specifies every policy from scratch, duplicating what the built-in profiles already provide and risking misconfiguration.

### 4. Content-Filtered Topics

| Aspect | MCP | No-MCP |
|---|---|---|
| CFT count | 6 | 6 (same) |
| Filter syntax | `%0` parameter syntax (correct for Connext) | `%0` parameter syntax (same) |
| Writer-side filtering | Detailed section on conditions that enable/disable writer-side filtering | Not discussed |
| Efficiency recommendations | Synchronous publishing, no batching, unicast for CFT readers | Not discussed |
| Python example | Full code example with `dds.Filter` and parameterized query | Not provided |
| Partitions + CFTs combined | Explicit example showing layered filtering (partition first, then CFT) | Not discussed |

**Verdict:** MCP design includes Connext-specific writer-side filtering guidance that directly affects system performance. This is advanced Connext knowledge not available in generic DDS documentation.

### 5. Request/Reply

| Aspect | MCP | No-MCP |
|---|---|---|
| Code examples | Full Python code for Requester, Replier, multi-reply pattern, XML+Python hybrid | Described textually only — no code |
| Multi-reply | `final=False` for intermediate PENDING replies | Not discussed |
| wait_for_service | Explicit `wait_for_service()` before first request | Not discussed |
| QoS integration | Shows XML QoS loading into Requester/Replier constructors | Not discussed |
| Service naming | Explains automatic topic name derivation from service name | Not discussed |

**Verdict:** MCP design provides production-ready code patterns. No-MCP describes the pattern conceptually but provides no implementation guidance.

### 6. Fault Tolerance

| Aspect | MCP | No-MCP |
|---|---|---|
| Mechanisms | 6 (adds controller disconnect detection via MANUAL_BY_TOPIC liveliness, stale data expiry via Lifespan) | 4 (basic liveliness, deadline, ownership, durability) |

### 7. Discovery & Deployment

| Aspect | MCP | No-MCP |
|---|---|---|
| Discovery settings | Optimization snippets configured in participant QoS XML | Settings described in a table |
| Monitoring | Monitoring 2.0 enabled | Not mentioned |
| Participant QoS XML | Provided with `base_name` composition | Not provided |
| Connext features table | §13 — 10 features with usage descriptions | Not present |
| References | §14 — 7 links to official RTI documentation | Not present |

---

## Verdict: MCP Design Is Better

The **MCP-assisted design** (`opus_mcp_design_connext_dds_iter1.md`) is the clearly superior design.

---

## Top Reasons the MCP Design Is Better

### 1. Connext-Idiomatic IDL4 Annotations
The MCP design uses `@appendable`, `@nested`, `@optional`, and `@topic` annotations throughout. These are not cosmetic — they control schema evolution (wire compatibility on field additions), code generation scope (no unnecessary reader/writer APIs for helper types), and semantic correctness (optional fields for sparse instruction parameters). The no-MCP design produces valid but legacy-style IDL that would break on any schema change and generates unnecessary API surface.

### 2. Built-In QoS Profile Inheritance
The MCP design inherits every QoS profile from a specific Connext built-in base (`Pattern.PeriodicData`, `Pattern.Status`, `Pattern.Event`, `Pattern.RPC`, etc.) and overrides only the deltas. This is the recommended Connext practice — it ensures correct defaults for dozens of policies not explicitly set, and makes the intent of each profile immediately clear. The no-MCP design specifies all policies manually, duplicating what built-ins already provide and creating risk of subtle misconfiguration.

### 3. Writer-Side CFT Filtering Guidance
The MCP design includes the specific conditions under which Connext applies writer-side filtering for CFTs (synchronous publishing, infinite liveliness lease, no batching, unicast). This is critical performance knowledge — writer-side filtering avoids sending data across the network that will just be dropped at the reader. The no-MCP design doesn't mention this at all.

### 4. DP-Level Partition Awareness
The MCP design correctly identifies DomainParticipant partitions as a Connext extension that controls discovery isolation (not just data routing), and uses a two-layer partition strategy (DP for discovery, Pub/Sub for logical channels). The no-MCP design uses partitions generically without distinguishing their Connext-specific discovery behavior.

### 5. Production-Ready Code Patterns
The MCP design provides complete Python code for the Request/Reply pattern including `wait_for_service()`, multi-reply workflows (`final=False`), and XML+Python QoS integration. These are patterns a developer can use directly. The no-MCP design describes patterns conceptually but provides no implementation.

### 6. Richer Domain Model
The MCP design has more complete enumerations (11 FlightPhase values vs. 7, 5 HandoffStatus values vs. 3, 6 AlertType values vs. 3), type-safe instruction parameters via `@optional` fields instead of a generic string blob, and a `Wind` struct for weather that no-MCP lacks. The domain model is more realistic and extensible.

---

## What the No-MCP Design Does Well

- Includes a `FlightPlanUpdate` topic for amendments (MCP design rolls this into `FlightPlan` status changes)
- Has a `Velocity` struct (MCP inlines speed/heading/vertical-speed directly into `AircraftPosition`)
- Simpler to read for someone unfamiliar with Connext — fewer annotations and layers
- The flat partition scheme is easier to reason about for a demo

---

## Conclusion

Access to the RTI Connext MCP tool resulted in a design that is measurably more Connext-idiomatic across every dimension: IDL annotations, QoS inheritance, partition strategy, CFT optimization, and implementation patterns. The no-MCP design is a competent generic DDS design, but it misses the Connext-specific features and best practices that distinguish a well-engineered Connext system from a portable but suboptimal one.
