# gRPC Design — National Air-Traffic Control System

> **Purpose:** Map the technology-agnostic [architecture overview](../docs/design_process/architecture_overview.md) onto gRPC + Protocol Buffers, producing the same ATC demo as the [Connext DDS implementation](../connext_dds/DESIGN.md) but using gRPC's client-server paradigm.
>
> **Language:** Python (grpcio + protobuf)

---

## 1. Architectural Approach

### 1.1 DDS vs gRPC — Fundamental Differences

The DDS implementation uses **anonymous, peer-to-peer publish/subscribe** with automatic discovery. gRPC uses **explicit client-server connections** with service definitions. This creates fundamental mapping challenges:

| DDS Concept | gRPC Equivalent | Trade-offs |
|---|---|---|
| Topic pub/sub (1-to-N) | Server-streaming RPC; each producer is a server | Consumers must know and connect to every producer |
| Content-Filtered Topics | Server-side filtering in streaming RPCs | Filter logic moves into application code |
| Automatic discovery | Zeroconf mDNS/DNS-SD (separate protocol) | Requires additional library and ~30 lines of code |
| DomainParticipant partitions | N/A — clients choose which servers to connect to | No discovery isolation; explicit wiring |
| QoS (deadline, liveliness, durability) | Application-level keepalives, retries, caching | Must be implemented manually |
| Request/Reply | Unary or bidirectional streaming RPC | Native gRPC strength |
| Late-join state recovery | Server caches state; replays on new stream | Must be implemented in application |
| Ownership / instance lifecycle | Application-level conflict resolution | No built-in equivalent |
| Multicast (1 write → N readers) | N point-to-point streams (1 write → N connections) | O(N) bandwidth per producer |

### 1.2 Direct-Connection Architecture

Each application that **produces data** runs a gRPC server. Applications that **consume data** connect directly to the servers they need via server-streaming RPCs. This mirrors the peer-to-peer nature of DDS as closely as gRPC allows.

There is no central hub or broker — consumers connect to each data source directly, just as DDS readers match directly with writers.

```
 ┌──────────┐  StreamPositions()   ┌──────────┐  StreamPositions()   ┌──────────┐
 │  Tower   │◄─────────────────────│ Airplane │─────────────────────►│  TRACON  │
 │  (KJFK)  │                      │  (✈)     │                      │  (N90)   │
 │  :auto   │ StreamInstructions() │  :auto   │  StreamInstructions()│  :auto   │
 │  server  │─────────────────────►│  server  │◄─────────────────────│  server  │
 └──────────┘                      └──────────┘                      └──────────┘
```

**Key characteristics:**
- **Each application is both a gRPC server and a gRPC client.** It serves data it produces and connects to servers for data it consumes.
- **Connection fan-out is explicit.** A tower watching 10 aircraft opens 10 position streams. In DDS, one reader receives from all matching writers automatically.
- **No single point of failure.** Unlike a hub architecture, losing one application only affects its direct consumers.
- **Service discovery uses Zeroconf (mDNS/DNS-SD).** Each server binds to port 0 (OS auto-assigns), registers its actual port and metadata via mDNS, and clients discover endpoints dynamically. No static configuration needed.

### 1.3 Connection Fan-Out Problem

This is the fundamental cost of gRPC for pub/sub workloads. In DDS, a writer publishes once and multicast/UDP delivers to all matched readers. In gRPC, each consumer opens a separate stream:

| Scenario (demo scale) | DDS | gRPC |
|---|---|---|
| 10 aircraft → 1 tower | 10 writers, 1 reader, multicast | Tower opens 10 `StreamPositions` connections |
| 10 aircraft → 7 towers + 7 TRACONs + 20 centers | Same 10 writers; readers match by partition/CFT | Each of 34 facilities opens streams to relevant aircraft |
| 1 tower publishes instruction → 1 aircraft | 1 writer, 1 CFT reader | Aircraft opens parallel `StreamInstructions` to all controllers |

The gRPC version requires **explicit connection management**: as aircraft move between sectors, clients must open new streams to new facility servers and close old ones. DDS handles this through discovery and Content-Filtered Topics.

---

## 2. Service Definitions

Each application exposes a gRPC service for the data it **produces**. Consumers call server-streaming RPCs to receive updates.

### 2.1 AircraftService (Airplane)

Each airplane runs a gRPC server with this service.

| RPC | Type | Output | Purpose |
|---|---|---|---|
| `StreamPositions` | Server-streaming | `AircraftPosition` | Continuous 5 Hz position telemetry |
| `StreamAcknowledgments` | Server-streaming | `PilotAcknowledgment` | Pilot readback of instructions |

### 2.2 TowerService (Control Tower)

Each tower runs a gRPC server.

| RPC | Type | Output | Purpose |
|---|---|---|---|
| `StreamInstructions` | Server-streaming | `ControllerInstruction` | Commands filtered by `tail_number` |
| `StreamHandoffs` | Server-streaming | `Handoff` | Handoff initiation/acceptance filtered by `controller_id` |
| `StreamAlerts` | Server-streaming | `Alert` | Safety alerts |
| `StreamTracking` | Server-streaming | `AircraftTracking` | Controller-of-record updates |
| `StreamFacilityStatus` | Server-streaming | `FacilityStatus` | Facility heartbeat |
| `StreamRunwayStatus` | Server-streaming | `RunwayStatus` | Runway state changes |
| `SendHandoff` | Unary | `HandoffAck` | Receive a handoff from another facility |

### 2.3 TraconService (TRACON)

Each TRACON runs a gRPC server. Same RPCs as TowerService (minus `StreamRunwayStatus`).

| RPC | Type | Output | Purpose |
|---|---|---|---|
| `StreamInstructions` | Server-streaming | `ControllerInstruction` | Commands filtered by `tail_number` |
| `StreamHandoffs` | Server-streaming | `Handoff` | Handoff coordination |
| `StreamAlerts` | Server-streaming | `Alert` | Separation violations |
| `StreamTracking` | Server-streaming | `AircraftTracking` | Controller-of-record updates |
| `StreamFacilityStatus` | Server-streaming | `FacilityStatus` | Facility heartbeat |
| `SendHandoff` | Unary | `HandoffAck` | Receive a handoff from tower or center |

### 2.4 CenterService (En-Route Center)

Each center runs a gRPC server.

| RPC | Type | Output | Purpose |
|---|---|---|---|
| `StreamInstructions` | Server-streaming | `ControllerInstruction` | Routing/altitude commands |
| `StreamHandoffs` | Server-streaming | `Handoff` | Inter-facility handoff coordination |
| `StreamAlerts` | Server-streaming | `Alert` | Separation violations |
| `StreamTracking` | Server-streaming | `AircraftTracking` | Controller-of-record updates |
| `StreamFacilityStatus` | Server-streaming | `FacilityStatus` | Facility heartbeat |
| `SendHandoff` | Unary | `HandoffAck` | Receive a handoff from TRACON or adjacent center |

### 2.5 AirportService (Airport)

Each airport runs a gRPC server.

| RPC | Type | Output | Purpose |
|---|---|---|---|
| `StreamWeatherReports` | Server-streaming | `WeatherReport` | METAR observations |
| `StreamRunwayStatus` | Server-streaming | `RunwayStatus` | Runway state |
| `RequestGate` | Server-streaming | `GateAssignmentReply` | Gate assignment (PENDING → ASSIGNED) |

### 2.6 FlightPlanService (Standalone)

Single server instance.

| RPC | Type | Output | Purpose |
|---|---|---|---|
| `FileFlightPlan` | Unary | `FlightPlanResponse` | File/validate a flight plan |
| `StreamFlightPlans` | Server-streaming | `FlightPlan` | Accepted plans broadcast to all subscribers |

### 2.7 WeatherService (Weather)

Single server instance.

| RPC | Type | Output | Purpose |
|---|---|---|---|
| `StreamConvectiveCells` | Server-streaming | `ConvectiveCell` | En-route weather cells |
| `InjectCell` | Unary | `CellInjectionAck` | Inject a cell from external source (e.g., dashboard) |

---

## 3. Data Types (Protocol Buffers)

All types are defined in [`air_traffic_types.proto`](air_traffic_types.proto) using proto3 syntax. The protobuf messages mirror the DDS IDL types field-for-field to keep the two implementations comparable.

### Mapping Conventions

| IDL Concept | Protobuf Equivalent |
|---|---|
| `@key` fields | No direct equivalent; application-level identity |
| `@optional` fields | `optional` keyword (proto3) |
| Bounded `string<N>` | `string` (unbounded; length enforced in application) |
| `typedef` aliases | Direct type usage (proto3 has no typedefs) |
| `@appendable enum` | `enum` with `UNKNOWN = 0` reserved value |
| `@nested struct` | Regular `message` (no behavioral difference in proto3) |
| `@mutable struct` | Regular `message` (proto3 is inherently wire-compatible) |
| `sequence<T, N>` | `repeated T` (unbounded; max enforced in application) |
| `int64 Timestamp` | `google.protobuf.Timestamp` for idiomatic proto |

### Type Categories

**Enums (13):** Same set as IDL — `FlightPhase`, `InstructionType`, `AcknowledgmentStatus`, `FlightPlanStatus`, `RunwayOperationalStatus`, `WeatherCondition`, `HandoffStatus`, `AlertSeverity`, `AlertType`, `ConvectiveSeverity`, `FacilityType`, `GateAssignmentStatusKind`, `NavStatus`

**Helper Messages (4):** `GeoPosition`, `Wind`, `Waypoint`, `GateAssignment`

**Topic Messages (11):** `AircraftPosition`, `ControllerInstruction`, `PilotAcknowledgment`, `FlightPlan`, `RunwayStatus`, `WeatherReport`, `Handoff`, `Alert`, `AircraftTracking`, `FacilityStatus`, `ConvectiveCell`

**Request/Reply Messages (4):** `FlightPlanRequest`, `FlightPlanResponse`, `GateRequest`, `GateAssignmentReply`

**Subscription Filter Messages:** Per-topic filter messages used as request parameters for server-streaming RPCs (e.g., `ControllerInstructionFilter`, `HandoffFilter`, `WeatherReportFilter`)

---

## 4. Application Components

Each application is **both a gRPC server and a gRPC client**. It serves data it produces and opens streaming connections to servers for data it consumes.

### 4.1 Airplane (`app_airplane.py`)

**Serves:** `AircraftService` on port 0 (OS auto-assigns). Registers via Zeroconf as `_atc-aircraft._tcp.local.`.

| Direction | Connects To | RPC | Filter |
|---|---|---|---|
| **Serves** | (own server) | `StreamPositions`, `StreamAcknowledgments` | — |
| **Subscribes** | Tower/TRACON/Center servers | `StreamInstructions` | `tail_number` |
| **Subscribes** | Airport server (destination) | `StreamWeatherReports` | `airport_code` |
| **Requests** | FlightPlanService server | `FileFlightPlan` | — |
| **Requests** | Airport server (destination) | `RequestGate` | — |

> **Parallel instruction subscription:** The airplane discovers all controller services (tower, TRACON, center) via Zeroconf and opens a persistent `StreamInstructions` connection to **each** in a dedicated thread. This ensures instructions are received immediately regardless of which controller is active. In DDS, one content-filtered reader on the instruction topic achieves the same result automatically.

### 4.2 Control Tower (`app_tower.py`)

**Serves:** `TowerService` on port 0 (OS auto-assigns). Registers via Zeroconf as `_atc-tower._tcp.local.`.

| Direction | Connects To | RPC | Notes |
|---|---|---|---|
| **Serves** | (own server) | `StreamInstructions`, `StreamHandoffs`, `StreamAlerts`, `StreamTracking`, `StreamFacilityStatus`, `StreamRunwayStatus`, `SendHandoff` | — |
| **Subscribes** | Each tracked airplane's `AircraftService` | `StreamPositions` | Opens/closes streams as aircraft arrive/depart |
| **Subscribes** | TRACON server | `StreamHandoffs` | Receives inbound handoffs |
| **Subscribes** | Airport server | `StreamWeatherReports` | Own airport weather |
| **Subscribes** | FlightPlanService | `StreamFlightPlans` | Active flight plans |
| **Sends** | TRACON server | `SendHandoff` | Initiates departure handoff |

### 4.3 TRACON (`app_tracon.py`)

**Serves:** `TraconService` on port 0 (OS auto-assigns). Registers via Zeroconf as `_atc-tracon._tcp.local.`.

| Direction | Connects To | RPC | Notes |
|---|---|---|---|
| **Serves** | (own server) | `StreamInstructions`, `StreamHandoffs`, `StreamAlerts`, `StreamTracking`, `StreamFacilityStatus`, `SendHandoff` | — |
| **Subscribes** | Each tracked airplane's `AircraftService` | `StreamPositions` | Altitude band 500–18,000 ft |
| **Subscribes** | Tower servers (served airports) | `StreamHandoffs` | Inbound departure handoffs |
| **Subscribes** | Center server | `StreamHandoffs` | Inbound arrival handoffs |
| **Subscribes** | Airport servers | `StreamWeatherReports` | Weather at served airports |
| **Subscribes** | FlightPlanService | `StreamFlightPlans` | Active flight plans |
| **Sends** | Tower server | `SendHandoff` | Arrival handoff to tower |
| **Sends** | Center server | `SendHandoff` | Departure handoff to center |

### 4.4 En-Route Center (`app_center.py`)

**Serves:** `CenterService` on port 0 (OS auto-assigns). Registers via Zeroconf as `_atc-center._tcp.local.`.

| Direction | Connects To | RPC | Notes |
|---|---|---|---|
| **Serves** | (own server) | `StreamInstructions`, `StreamHandoffs`, `StreamAlerts`, `StreamTracking`, `StreamFacilityStatus`, `SendHandoff` | — |
| **Subscribes** | Each tracked airplane's `AircraftService` | `StreamPositions` | Altitude band 18,000–60,000 ft |
| **Subscribes** | TRACON servers | `StreamHandoffs` | Inbound departure handoffs |
| **Subscribes** | Adjacent center servers | `StreamHandoffs` | Inter-center handoffs |
| **Subscribes** | FlightPlanService | `StreamFlightPlans` | Active flight plans |
| **Subscribes** | WeatherService | `StreamConvectiveCells` | En-route weather hazards |
| **Sends** | TRACON server | `SendHandoff` | Descent handoff to TRACON |
| **Sends** | Adjacent center server | `SendHandoff` | Boundary exit handoff |

### 4.5 Airport (`app_airport.py`)

**Serves:** `AirportService` on port 0 (OS auto-assigns). Registers via Zeroconf as `_atc-airport._tcp.local.`.

| Direction | Connects To | RPC | Notes |
|---|---|---|---|
| **Serves** | (own server) | `StreamWeatherReports`, `StreamRunwayStatus`, `RequestGate` | — |

The Airport is a pure server — it does not subscribe to any other service.

### 4.6 Flight Plan Service (`app_flightplan_service.py`)

**Serves:** `FlightPlanService` on port 0 (OS auto-assigns). Registers via Zeroconf as `_atc-fps._tcp.local.`.

| Direction | Connects To | RPC | Notes |
|---|---|---|---|
| **Serves** | (own server) | `FileFlightPlan`, `StreamFlightPlans` | — |

### 4.7 Weather Service (`app_weather_service.py`)

**Serves:** `WeatherService` on port 0 (OS auto-assigns). Registers via Zeroconf as `_atc-weather._tcp.local.`.

| Direction | Connects To | RPC | Notes |
|---|---|---|---|
| **Serves** | (own server) | `StreamConvectiveCells`, `InjectCell` | `InjectCell` allows external injection of weather cells (e.g., from the dashboard) |

### 4.8 Dashboard (`app_dashboard.py`)

The Dashboard is a **pure client** (no gRPC server) — it connects to every other application's server to subscribe to all data streams. It also serves a Flask HTTP/SSE web UI on port 8050.

| Direction | Connects To | RPC | Notes |
|---|---|---|---|
| **Subscribes** | All airplane servers | `StreamPositions`, `StreamAcknowledgments` | All aircraft |
| **Subscribes** | All tower servers | `StreamInstructions`, `StreamHandoffs`, `StreamAlerts`, `StreamTracking`, `StreamFacilityStatus`, `StreamRunwayStatus` | — |
| **Subscribes** | All TRACON servers | `StreamInstructions`, `StreamHandoffs`, `StreamAlerts`, `StreamTracking`, `StreamFacilityStatus` | — |
| **Subscribes** | All center servers | `StreamInstructions`, `StreamHandoffs`, `StreamAlerts`, `StreamTracking`, `StreamFacilityStatus` | — |
| **Subscribes** | All airport servers | `StreamWeatherReports`, `StreamRunwayStatus` | — |
| **Subscribes** | FlightPlanService | `StreamFlightPlans` | — |
| **Subscribes** | WeatherService | `StreamConvectiveCells` | — |
| **Sends** | WeatherService | `InjectCell` | Dashboard-injected cells forwarded to WeatherService for broadcast |

> **Fan-out cost:** With 10 aircraft + 7 airports + 7 towers + 7 TRACONs + 20 centers + 2 services, the dashboard opens **~53+ streaming connections**. In DDS, this is one participant subscribing to 11 topics with wildcard partition `OPS/*`.

---

## 5. State Management and Late-Join

Each server that produces state data must maintain an in-memory cache and replay it to new subscribers. This replicates DDS `TRANSIENT_LOCAL` durability.

| Data Type | Cache (at server) | DDS Equivalent |
|---|---|---|
| `AircraftPosition` | Latest per aircraft (at airplane server) | Keep-last-1 + Volatile |
| `FlightPlan` | Latest per `flight_plan_id` (at FPS server) | Keep-last-1 + Transient-local |
| `RunwayStatus` | Latest per runway (at airport server) | Keep-last-1 + Transient-local |
| `WeatherReport` | Latest per airport (at airport server) | Keep-last-1 + Transient-local |
| `AircraftTracking` | Latest per `tail_number` (at facility server) | Keep-last-1 + Transient-local |
| `FacilityStatus` | Latest (at facility server) | Keep-last-1 + Transient-local |
| `ConvectiveCell` | Latest per `cell_id` (at weather server) | Keep-last-1 + Transient-local |
| `Handoff` | Last 5 per `handoff_id` (at facility server) | Keep-last-5 + Transient-local |
| `Alert` | All with 60s TTL (at facility server) | Keep-all + Lifespan 60s |

When a new streaming subscriber connects, the server first replays cached state, then continues with live updates. This must be explicitly implemented in every server.

### 5.1 Liveliness Detection

DDS liveliness QoS is replaced by:

- **gRPC keepalives:** Detect transport-level disconnects
- **Application heartbeats:** `FacilityStatus` messages serve as application-level heartbeats (same as in DDS)
- **Stream cancellation:** gRPC detects when a client stream is cancelled/disconnected

### 5.2 Data Expiry

DDS lifespan QoS is replaced by TTL-based eviction in the server's state cache:

| Data Type | TTL | DDS Equivalent |
|---|---|---|
| `AircraftPosition` | 1s | Lifespan 1s |
| `Alert` | 60s | Lifespan 60s |
| Others | No expiry | No lifespan set |

---

## 6. Service Discovery and Connection Management

gRPC has no built-in discovery — clients must know server addresses before connecting. In DDS, this is handled by the middleware's discovery protocol. Production gRPC deployments typically use a service registry (etcd, Consul, Kubernetes DNS). For this demo, we use **Zeroconf (mDNS/DNS-SD)** — a zero-infrastructure, multicast-based discovery protocol that runs entirely peer-to-peer.

### 6.1 Why Zeroconf

Zeroconf (via mDNS + DNS-SD, RFC 6762/6763) is the discovery mechanism behind AirPlay, Chromecast, and network printers. Each service announces itself on the local network via multicast; interested parties listen for announcements. No central server needed.

The irony is instructive: **Zeroconf uses multicast for peer-to-peer service discovery — which is exactly what DDS's Simple Participant Discovery Protocol (SPDP) does.** To make gRPC behave like DDS, we end up reimplementing a subset of DDS discovery on top of a separate multicast protocol.

| Approach | Infrastructure | Latency | Failure Detection | Complexity |
|---|---|---|---|---|
| **etcd / Consul** | Requires deploying + operating a server | Watch interval (~1s) | TTL lease expiry | High for a demo |
| **Kubernetes DNS** | Requires a K8s cluster | DNS TTL | Pod health checks | Overkill for local dev |
| **Zeroconf (mDNS)** | None — pure multicast | Sub-second | Service deregistration + TTL | `pip install zeroconf` |
| **DDS (for reference)** | None — built into middleware | Sub-second | Liveliness QoS | Zero application code |

### 6.2 Service Registration via DNS-SD

Each application registers a DNS-SD service on startup using the Python `zeroconf` library. Service types follow the naming convention `_atc-<role>._tcp.local.`:

| Application | DNS-SD Service Type | Service Name (example) |
|---|---|---|
| Airplane | `_atc-aircraft._tcp.local.` | `AAL100._atc-aircraft._tcp.local.` |
| Tower | `_atc-tower._tcp.local.` | `KJFK._atc-tower._tcp.local.` |
| TRACON | `_atc-tracon._tcp.local.` | `N90._atc-tracon._tcp.local.` |
| Center | `_atc-center._tcp.local.` | `ZNY._atc-center._tcp.local.` |
| Airport | `_atc-airport._tcp.local.` | `KJFK._atc-airport._tcp.local.` |
| FlightPlanService | `_atc-fps._tcp.local.` | `fps._atc-fps._tcp.local.` |
| WeatherService | `_atc-weather._tcp.local.` | `weather._atc-weather._tcp.local.` |

TXT records carry metadata (callsign, facility type, served airports, sector boundaries) that consumers use to decide whether to connect.

### 6.3 Registration and Discovery Code

```python
from zeroconf import Zeroconf, ServiceBrowser, ServiceInfo
import socket

zc = Zeroconf()

# ── Aircraft registers on startup ──────────────────────────
info = ServiceInfo(
    type_="_atc-aircraft._tcp.local.",
    name=f"{callsign}._atc-aircraft._tcp.local.",
    addresses=[socket.inet_aton(host)],
    port=grpc_port,
    properties={"callsign": callsign, "origin": "KJFK", "dest": "KLAX"},
)
zc.register_service(info)

# ── Tower discovers aircraft via listener ──────────────────
class AircraftListener:
    def add_service(self, zc, type_, name):
        info = zc.get_service_info(type_, name)
        # New aircraft — open StreamPositions if in our sector

    def remove_service(self, zc, type_, name):
        # Aircraft gone — close stream, clean up

    def update_service(self, zc, type_, name):
        pass

browser = ServiceBrowser(zc, "_atc-aircraft._tcp.local.", AircraftListener())
```

On shutdown, `zc.unregister_service(info)` sends a goodbye packet; on crash, the mDNS TTL expires and listeners are notified. This is the same pattern as DDS liveliness detection.

### 6.4 Two Tiers of Services

| Tier | Examples | Lifecycle | Discovery Pattern |
|---|---|---|---|
| **Infrastructure** (long-lived) | Towers, TRACONs, Centers, Airports, FPS, Weather | Stable — start once, run indefinitely | Announce once; rarely changes |
| **Aircraft** (ephemeral) | Each airplane process | Dynamic — appear when flight begins, disappear when parked | Announce on startup, goodbye on shutdown, mDNS TTL on crash |

Facilities browse `_atc-aircraft._tcp.local.` to discover aircraft. Aircraft browse `_atc-tower._tcp.local.`, `_atc-tracon._tcp.local.`, and `_atc-center._tcp.local.` to discover their current controller. The dashboard browses all service types.

### 6.5 Aircraft Registration Flow

When an airplane process starts:

1. **Aircraft starts its gRPC server** on a dynamically assigned port.
2. **Aircraft registers** a Zeroconf service (`_atc-aircraft._tcp.local.`) with its host, port, and metadata (callsign, origin, destination).
3. **Aircraft files a flight plan** via `FlightPlanService.FileFlightPlan`. The accepted plan is broadcast to all facilities via `StreamFlightPlans`.
4. **Facilities** receive an `add_service` callback from their `ServiceBrowser`. They inspect the TXT record metadata to decide if the aircraft is in their sector, and if so, open a `StreamPositions` connection.
5. **On shutdown**, the aircraft calls `unregister_service()`, triggering `remove_service` callbacks. On crash, the mDNS TTL expires (typically within seconds).

This is the gRPC equivalent of DDS participant discovery + endpoint matching — but built from a separate multicast protocol rather than integrated into the middleware.

### 6.6 Dynamic Connection Lifecycle

Unlike DDS (where discovery is automatic), gRPC clients must **manually manage connections** as the system evolves:

| Event | DDS Behavior | gRPC + Zeroconf |
|---|---|---|
| New aircraft enters system | Discovered automatically; CFT matches → data flows | mDNS announcement → `add_service` callback → open `StreamPositions` |
| Aircraft exits sector | CFT stops matching; no more data | Controller closes the stream |
| Handoff tower → TRACON | Handoff topic; new controller sees aircraft via CFT | TRACON receives handoff via `SendHandoff`, looks up aircraft in Zeroconf cache, opens stream |
| New facility starts | Discovered automatically | mDNS announcement → `add_service` callback → connect |
| Facility crashes | Liveliness QoS detects it | mDNS TTL expires → `remove_service` callback; gRPC stream error |

### 6.7 Aircraft Discovery During Handoff

During handoffs, the receiving controller needs to connect to the aircraft's gRPC server. Since all controllers already browse `_atc-aircraft._tcp.local.` via Zeroconf, the aircraft's endpoint is already known — the receiving controller simply opens a `StreamPositions` connection to the aircraft it now controls. No endpoint is carried in the `Handoff` message itself.

In DDS, this is unnecessary: the receiving controller already has a CFT reader on `AircraftPosition` that will automatically match the aircraft's writer once the handoff changes the filter expression.

### 6.8 Comparison: DDS Discovery vs gRPC + Zeroconf

| Aspect | DDS (built-in) | gRPC + Zeroconf |
|---|---|---|
| **Setup** | Zero config — automatic | `pip install zeroconf` — no server to deploy |
| **Protocol** | Multicast SPDP/SEDP (UDP) | Multicast mDNS/DNS-SD (UDP) |
| **Latency** | Sub-second | Sub-second |
| **Failure detection** | Liveliness QoS (configurable) | mDNS TTL expiry + gRPC stream error |
| **Filtering** | Content-Filtered Topics (middleware) | Application logic after discovery |
| **Code required** | None — middleware handles it | ~30 lines: register, browse, connect/disconnect |
| **Coupling** | Anonymous — pub/sub by topic name | Must map service types to gRPC stubs |
| **Scalability** | Peer-to-peer, no central bottleneck | Peer-to-peer; mDNS is LAN-scope only |
| **WAN support** | Discovery over UDP unicast locators | Requires DNS-SD + wide-area DNS, or switch to etcd/Consul |

> **LAN limitation:** Zeroconf is limited to the local network segment. For multi-site deployment, a centralized registry (etcd, Consul, Kubernetes DNS) would be needed. For a demo running on a single machine or LAN, Zeroconf is ideal.

---

## 7. Handoff Protocol

The handoff protocol is **identical in logic** to the DDS implementation. The transport difference is that handoffs use **direct unary RPCs** between facility servers instead of a shared topic:

1. **Initiating controller** calls `SendHandoff` on the **receiving controller's server** with `status = INITIATED`.
2. **Receiving controller** processes the handoff, opens a `StreamPositions` connection to the aircraft's server, then calls `SendHandoff` back on the **initiating controller's server** with `status = ACCEPTED`.
3. **Initiating controller** closes its `StreamPositions` connection to the aircraft and removes it from local tracking.

This is a direct RPC exchange between two known endpoints — no shared topic or broker needed. Both controllers discover each other via Zeroconf (infrastructure services are long-lived and always browsable). The receiving controller looks up the aircraft's endpoint from its Zeroconf cache (see §6.7).

---

## 8. Deployment

### 8.1 Network Topology

All gRPC servers bind to **port 0** (OS auto-assigns a free port). The actual port is advertised via Zeroconf mDNS after startup. Clients discover endpoints dynamically — no hardcoded ports.

```
  ┌────────────────────────────────────────────────────────────────┐
  │              Direct gRPC Connections (all ports dynamic)       │
  │                                                                │
  │  ┌──────────┐  ┌──────────┐  ┌──────────┐     ... (7 total)    │
  │  │ Airport  │  │ Airport  │  │ Airport  │                      │
  │  │ KJFK     │  │ KLAX     │  │ KORD     │                      │
  │  └────┬─────┘  └────┬─────┘  └────┬─────┘                      │
  │       │              │              │                          │
  │  ┌────┴─────┐  ┌────┴─────┐  ┌────┴─────┐     ... (7 total)    │
  │  │ Tower    │  │ Tower    │  │ Tower    │                      │
  │  │ KJFK     │  │ KLAX     │  │ KORD     │                      │
  │  └────┬─────┘  └────┬─────┘  └────┬─────┘                      │
  │       │              │              │                          │
  │  ┌────┴─────┐  ┌────┴─────┐  ┌────┴─────┐     ... (7 total)    │
  │  │ TRACON   │  │ TRACON   │  │ TRACON   │                      │
  │  │ N90      │  │ SCT      │  │ C90      │                      │
  │  └────┬─────┘  └────┬─────┘  └────┬─────┘                      │
  │       │              │              │                          │
  │  ┌────┴─────┐  ┌────┴─────┐  ┌────┴─────┐    ... (20 total)    │
  │  │ Center   │  │ Center   │  │ Center   │                      │
  │  │ ZNY      │◄─►│ ZLA      │◄─►│ ZAU      │                    │
  │  └──────────┘  └──────────┘  └──────────┘                      │
  │                                                                │
  │  ┌───────────────┐    ┌───────────────┐                        │
  │  │ FlightPlan    │    │ Weather       │                        │
  │  │ Service       │    │ Service       │                        │
  │  └───────────────┘    └───────────────┘                        │
  │                                                                │
  │  ✈ Airplane servers: one per aircraft (10 in demo scenario)    │
  │  📊 Dashboard: pure gRPC client + Flask HTTP on :8050          │
  │                                                                │
  │  All gRPC ports assigned dynamically via port 0.               │
  │  Endpoints discovered via Zeroconf mDNS/DNS-SD.                │
  └────────────────────────────────────────────────────────────────┘
```

### 8.2 Port Assignments

| Application | Port | Notes |
|---|---|---|
| All gRPC servers | Dynamic (port 0) | OS auto-assigns; advertised via Zeroconf |
| Dashboard HTTP | 8050 | Flask + SSE (same as DDS) |

---

## 9. What gRPC Does NOT Provide (vs DDS)

These DDS capabilities must be **manually implemented** in the gRPC version:

| DDS Feature | gRPC Workaround | Effort |
|---|---|---|
| **Automatic discovery** | Zeroconf mDNS/DNS-SD (separate protocol) | Medium — ~30 lines of registration/browsing code |
| **Peer-to-peer pub/sub (1 write → N readers)** | Each producer is a server; consumers connect directly | High — N×M connections |
| **Content-Filtered Topics** | Server-side filtering in streaming RPCs | Medium |
| **Writer-side filtering** | Server evaluates filters before sending on each stream | Medium |
| **QoS policies** (deadline, liveliness, ownership, durability) | Application-level implementation | High |
| **Instance lifecycle** (register/unregister/dispose) | Application-level cache management | Medium |
| **Exclusive ownership** | Application-level conflict resolution | Medium |
| **Transient-local durability** | Server-side state cache with replay on connect | Medium |
| **DomainParticipant partitions** | Clients choose which servers to connect to | N/A — no discovery isolation |
| **Transport priority** | gRPC priority hints (limited) | Low |
| **Multicast delivery** | One stream per subscriber (O(N) bandwidth) | Fundamental limitation |
| **Dynamic connection management** | Explicit open/close as aircraft move between sectors | High |
| **Monitoring 2.0** | Prometheus/OpenTelemetry (separate instrumentation) | Medium |

---

## 10. Application-to-Process Mapping

| Application | Process | Runs gRPC Server | Count | Language |
|---|---|---|---|---|
| `app_airplane.py` | Airplane | Yes (`AircraftService`) | N (per aircraft) | Python |
| `app_tower.py` | Tower | Yes (`TowerService`) | M (per airport) | Python |
| `app_tracon.py` | TRACON | Yes (`TraconService`) | T (per TRACON) | Python |
| `app_center.py` | Center | Yes (`CenterService`) | K (per region) | Python |
| `app_airport.py` | Airport | Yes (`AirportService`) | M (per airport) | Python |
| `app_flightplan_service.py` | FlightPlanService | Yes (`FlightPlanService`) | 1 | Python |
| `app_weather_service.py` | WeatherService | Yes (`WeatherService`) | 1 | Python |
| `app_dashboard.py` | Dashboard | No (client only + Flask HTTP) | 1 | Python |

---

## 11. Project Structure

```
grpc/
├── air_traffic_types.proto          # Protobuf + gRPC service definitions
├── DESIGN.md                        # This document
├── README.md
├── python/
│   ├── air_traffic_types_pb2.py     # Generated protobuf messages (DO NOT HAND-EDIT)
│   ├── air_traffic_types_pb2_grpc.py # Generated gRPC stubs (DO NOT HAND-EDIT)
│   ├── common.py                    # Shared utilities (sim speed, airport coords, gRPC helpers)
│   ├── app_airplane.py              # Aircraft simulator: AircraftService server + client
│   ├── app_tower.py                 # Control tower: TowerService server + client
│   ├── app_tracon.py                # TRACON: TraconService server + client
│   ├── app_center.py                # En-route center: CenterService server + client
│   ├── app_airport.py               # Airport: AirportService server
│   ├── app_flightplan_service.py    # Flight plan filing: FlightPlanService server
│   ├── app_weather_service.py       # Weather: WeatherService server
│   ├── app_dashboard.py             # Dashboard: pure client + Flask HTTP server
│   └── types_generate.sh            # Run protoc to generate Python stubs
├── scripts/
│   ├── demo_start.sh                # Multi-process launcher
│   ├── demo_stop.sh                 # Kill all processes
│   └── demo_cli.py                  # Scenario config parser
├── docker/
│   └── Dockerfile
└── requirements.txt                 # grpcio, protobuf, zeroconf, flask
```
