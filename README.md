# National Air-Traffic Control System — RTI Connext DDS vs gRPC

A multi-application simulation of a national air-traffic control system implemented **twice** — once with [RTI Connext DDS](https://www.rti.com/products/connext) and once with [gRPC](https://grpc.io/) — to compare a **data-centric** publish/subscribe architecture against a **client-server** RPC architecture for the same real-time distributed scenario.

Both implementations share the same scenario configuration, application roles, and data flows. Aircraft fly between airports while control towers, TRACON facilities, and en-route centers coordinate traffic. The key difference is **how** applications communicate:

| | Connext DDS | gRPC |
|---|---|---|
| **Paradigm** | Peer-to-peer pub/sub with automatic discovery | Explicit client-server with mDNS discovery |
| **Data model** | Shared distributed state (Topics + QoS) | RPC service definitions (Protocol Buffers) |
| **Multicast** | Native (1 write → N readers) | N point-to-point streams |
| **Late-join** | Built-in (transient-local durability) | Application-level state replay |
| **QoS** | Declarative (deadline, liveliness, ownership) | Must be implemented manually |

This repository is part of the [RTI Connext comparison series](https://github.com/rticommunity) alongside the [tractor-fleet demo](https://github.com/rticommunity/rticonnextdds-comparison-tractor-fleet).

## Scenario

A simulated national air-traffic control system spanning multiple airports. 

![ATC Dashboard showing aircraft flying, control centers, airports, etc.](docs/air_traffic_ui.png)

Aircraft fly between airports while control towers, TRACON facilities, and en-route centers coordinate traffic flow, issue instructions, and manage handoffs — just like the real national airspace system.

### Components

| Component | Role | Instances |
|---|---|---|
| **Airplane** | Position reporting, flight plan filing, gate requests | 1 per aircraft |
| **Airport** | Weather reports, runway status, gate assignment | 1 per airport |
| **Control Tower** | Terminal-area clearances, runway management | 1 per airport |
| **TRACON** | Arrival sequencing, departure handoffs | 1 per TRACON |
| **En-Route Center** | Separation monitoring, weather rerouting, sector handoffs | 1 per center |
| **Flight Plan Service** | Central plan validation and publishing | 1 |
| **Weather Service** | Convective cell generation for en-route hazards | 1 |
| **Dashboard** | Web-based real-time map and monitoring | 1 |

### Data Flows

```
┌──────────────┐    handoffs   ┌──────────────┐
│ En-Route     │◄─────────────►│ En-Route     │
│ Center A     │               │ Center B     │
└──────┬───────┘               └───────┬──────┘
       │                               │
  ┌────▼─────┐                   ┌─────▼────┐
  │ TRACON 1 │                   │ TRACON 2 │
  └────┬─────┘                   └─────┬────┘
       │                               │
  ┌────▼──────┐                  ┌─────▼─────┐
  │ Tower 1   │                  │ Tower 2   │
  │(Airport 1)│                  │(Airport 2)│
  └────┬────-─┘                  └─────┬──-──┘
       │                               │
  ✈ ✈ ✈ ✈                         ✈ ✈ ✈ ✈
 Aircraft at                      Aircraft at
 Airport 1                        Airport 2

       ✈  ✈  ✈  ✈  ✈  (en-route aircraft)

┌─────────────────────┐   ┌───────────────────┐
│ Flight Plan Service │   │ Weather Service   │
└─────────────────-───┘   └───────────────────┘

┌─────────────────────┐
│ Dashboard (observer)│
└─────────────────────┘
```

### Interaction Patterns

- **Publish/Subscribe:** Position reports, weather, runway status, alerts, tracking state
- **Command/Response:** Controller instructions → pilot acknowledgments, handoff initiation → acceptance
- **Request/Reply:** Flight plan filing, gate assignment

## Implementations

### Connext DDS

Built with RTI Connext DDS (Python). See [`connext_dds/`](connext_dds/) for the full implementation.

### gRPC

Built with gRPC + Protocol Buffers (Python). See [`grpc/`](grpc/) for the full implementation.

## Comparison: What the Resulting Applications Can Do

Both implementations produce the same ATC demo with the same 8 application roles — but the resulting systems differ significantly in what they deliver out of the box. The code can be written by AI in either case; what matters is the **capabilities, robustness, and scalability** of the running application.

### Discovery: How Do Applications Find Each Other?

| | Connext DDS | gRPC |
|---|---|---|
| **Mechanism** | Automatic — UDP multicast discovery built into the middleware | Manual — Zeroconf/mDNS with application-level service registration |
| **New app starts** | All existing apps discover it automatically within seconds | Zeroconf callback fires; each consumer must open a new stream |
| **App restarts after crash** | Re-discovered automatically; readers resume receiving data | Must re-register with Zeroconf; consumers detect stream error, reconnect |
| **WAN / cloud** | Unicast locator configuration | Requires external service registry (Consul, etcd, Kubernetes DNS) |

**Impact:** With DDS, you can start and stop applications in any order and they just find each other. With gRPC, every consumer must implement a discovery-browse-connect loop (~50 lines per app).

### Fault Tolerance: What Happens When a Facility Crashes?

| | Connext DDS | gRPC |
|---|---|---|
| **Detection** | Middleware liveliness lease (5s) — automatic callback | Stream error caught in try/except — manual retry with backoff |
| **Dashboard awareness** | Liveliness violation triggers status change to "offline" within 5s | Must detect gRPC stream reset, then update UI |
| **Handoff in progress** | Deadline violation detected; can trigger alert | RPC timeout after configurable wait; exception handling |
| **Recovery** | Automatic re-discovery when facility restarts | Manual reconnection in each consumer |

**Impact:** DDS provides deterministic failure detection timers as declarative policy. gRPC requires each app to implement its own retry/reconnect/timeout logic.

### Late Join: What If Dashboard Starts After Aircraft Are Already Flying?

| | Connext DDS | gRPC |
|---|---|---|
| **Mechanism** | Transient-local durability — middleware caches last state per instance | Application-level cache — server replays from in-memory `StreamBroadcaster` |
| **What dashboard sees** | All current flight plans, latest position per aircraft, runway status, tracking state — delivered automatically by middleware | Cached messages replayed by each server on stream open — limited by cache size and TTL |
| **Implementation** | Zero code — QoS policy in XML | ~50 lines per data type (`StreamBroadcaster` with `key_fn`, `max_cache`, `ttl_s`) |

**Impact:** With DDS, any reader joining late automatically receives the current state of the world — a fundamental middleware guarantee. With gRPC, each server must implement and maintain its own cache, and the behavior varies by how the cache is configured.

### Scalability: What Happens When You Add 100 More Aircraft?

| | Connext DDS | gRPC |
|---|---|---|
| **Network topology** | 1 multicast packet per position update — all readers receive the same packet | 1 TCP stream per consumer — each reader gets a separate copy |
| **10 aircraft → 34 facilities** | ~10 KB/s total (multicast) | ~340 KB/s total (10 × 34 point-to-point streams) |
| **100 aircraft → 34 facilities** | ~100 KB/s total (multicast) | ~3,400 KB/s total (100 × 34 streams) |
| **Connections per facility** | 1 reader (receives from all aircraft) | N streams (1 per aircraft) |
| **Adding aircraft** | Zero configuration — new aircraft discovered, positions received | Each facility's discovery loop spawns a new connection thread |

**Impact:** DDS bandwidth scales with the number of *producers* (multicast). gRPC bandwidth scales with *producers × consumers* (point-to-point). At demo scale this is negligible; at production scale (thousands of aircraft) the difference is orders of magnitude.

### Data Filtering: How Does a Tower Receive Only Its Own Traffic?

| | Connext DDS | gRPC |
|---|---|---|
| **Mechanism** | Content-Filtered Topics — subscriber specifies a SQL expression (e.g., `"tail_number = 'N738WN'"`) at runtime; the middleware evaluates it at the *publisher* and only sends matching data over the network | Server-side Python closures — the server must anticipate every filter a client might need and hard-code the logic; client passes filter parameters defined in the `.proto` contract |
| **Who defines the filter** | The *subscriber*, at runtime, using any SQL expression over the topic's fields — no server changes needed | The *server developer*, at build time — adding a new filter field requires changing the `.proto`, regenerating stubs, and redeploying the server |
| **Bandwidth** | Writer-side filtering: unmatched data never leaves the publisher | Server sends matching data per TCP stream; each consumer is a separate connection regardless of filter |
| **Extensibility** | Any new subscriber can define its own filter without touching existing code | New filter requirements require coordinated server + client changes |
| **Discovery isolation** | DomainParticipant partitions prevent unrelated apps from even discovering each other | No equivalent — all consumers see all Zeroconf registrations |

**Impact:** DDS filtering is decoupled — any subscriber can filter any field without the publisher knowing or caring. gRPC filtering is monolithic — the server and client must agree on which fields are filterable at compile time, and adding a new filter means redeploying the server.

### QoS: How Are Real-Time Guarantees Enforced?

DDS provides declarative QoS policies applied per topic profile — deadline, liveliness, reliability, ownership, durability, lifespan — all configured in a single XML file and enforced by the middleware:

| QoS Policy | DDS (built-in) | gRPC (must implement) |
|---|---|---|
| **Deadline** | 200ms for positions, 5s for commands — violation callback | Manual timeout on stream read |
| **Liveliness** | Manual-by-topic with 5s lease — automatic detection | Manual heartbeat publishing |
| **Reliability** | Best-effort for positions, reliable for commands | Always TCP (reliable), no best-effort option |
| **Durability** | Transient-local — last state cached by middleware | Manual in-memory cache per server |
| **Ownership** | Shared ownership + by-source-timestamp for handoffs | No equivalent — application coordination |
| **Lifespan** | 1s for positions (auto-expire stale data), 60s for alerts | Manual TTL in cache |

**Impact:** With DDS, QoS is a configuration concern — change the XML, not the code. With gRPC, every QoS guarantee becomes application logic that must be written, tested, and maintained.

### Data Consistency: How Do Handoffs Work?

When an aircraft transitions from one controller to another (Tower → TRACON → Center), both implementations use a multi-step handoff protocol — but the guarantees differ:

| | Connext DDS | gRPC |
|---|---|---|
| **Protocol** | Shared `Handoff` topic — both controllers write to the same keyed instance | Direct unary RPC between facilities |
| **Ordering** | `BY_SOURCE_TIMESTAMP` destination ordering ensures all readers converge on the newest update | RPC request/response enforces ordering for each pair |
| **Concurrent updates** | `SHARED_OWNERSHIP` QoS allows both controllers to update tracking state during transition — middleware resolves | Application must coordinate — no built-in conflict resolution |
| **Crash during handoff** | Liveliness violation detects crashed controller within 5s; remaining controller retains tracking | RPC timeout detects failure; manual fallback logic required |

### Operational Overhead

| | Connext DDS | gRPC |
|---|---|---|
| **External infrastructure** | None (peer-to-peer, no broker) | None (peer-to-peer with Zeroconf) |
| **Per-app connection code** | ~0 lines (middleware handles discovery + connection) | ~100-150 lines (discovery + connection threads + retry logic) |
| **Configuration** | QoS XML file (declarative) | Scattered across Python code |
| **Monitoring** | Built-in observability (Monitoring Library 2.0) + RTI tools | Manual logging + gRPC channel state |
| **License** | Commercial (free evaluation available) | Open-source, no license cost |

### Summary

Both approaches produce a working ATC demo. The fundamental trade-off:

- **Connext DDS** handles discovery, filtering, fault detection, late-join state, data consistency, and QoS enforcement **in the middleware**. The application code focuses purely on domain logic. The trade-off is a commercial license requirement.

- **gRPC** requires the application to implement all of those concerns explicitly. The resulting system works but carries more application-level complexity and fewer built-in guarantees. The trade-off is zero licensing cost and a widely-known API.

For safety-critical or high-scale real-time systems, the middleware-level guarantees of DDS are difficult to replicate reliably in application code. For simpler request/reply services or systems where explicit control over every connection is preferred, gRPC's transparency is an advantage.

## Prerequisites

### Connext DDS

- **RTI Connext DDS license file** (no Connext installation required — the Python
  package is installed automatically from PyPI).
  A free evaluation license is available at [rti.com/free-trial](https://www.rti.com/free-trial).
  Set `RTI_LICENSE_FILE` to point to your license file before running the demo.
- Python 3.10+

### gRPC

- Python 3.10+
- No license required

## Quick Start

### Connext DDS

```bash
# Clone the repository
git clone https://github.com/rticommunity/rticonnextdds-comparison-air-traffic.git
cd rticonnextdds-comparison-air-traffic

# Set up virtual environment and install dependencies
source setup.sourceme

# Run the demo (defaults to all apps, 60 min)
./connext_dds/scripts/demo_start.sh
```

Open http://localhost:8050 for the real-time dashboard.

### gRPC

```bash
# Set up virtual environment and install dependencies
source setup.sourceme

# Run the demo
./grpc/scripts/demo_start.sh
```

### Docker

```bash
# Build the image (from repo root)
docker build -f docker/Dockerfile -t atc-demo .

# Run the full demo (all components)
docker run -v ./rti_license.dat:/tmp/rti_license.dat -p 8050:8050 atc-demo

# Run a single component
docker run -v ./rti_license.dat:/tmp/rti_license.dat -p 8050:8050 atc-demo dashboard
```

`--network host` is recommended so DDS multicast discovery works between containers. Pass any component name (`dashboard`, `center`, `tower`, `tracon`, `airport`, `airplane`, `flightplan`, `weather`) or `all` (default). On Linux, add `--network host` for DDS discovery across multiple containers.

See [`connext_dds/README.md`](connext_dds/README.md) for prerequisites, installation, detailed options, and design notes.

## Repository Structure

```
├── README.md                      # This file
├── air_traffic_scenario.json      # Shared scenario config (both implementations)
├── setup.sourceme                 # Environment setup (source, not execute)
├── requirements/
│   └── connext_dds.txt            # Python dependencies (Connext DDS)
├── connext_dds/                   # RTI Connext DDS implementation
│   ├── README.md                  # Approach overview & quick start
│   ├── DESIGN.md                  # DDS architecture deep dive
│   ├── air_traffic_types.idl      # Shared IDL type definitions
│   ├── air_traffic_qos.xml        # Shared QoS profiles
│   ├── diagrams/                  # Design diagrams
│   ├── scripts/                   # Demo launcher
│   ├── python/                    # Python implementation
│   └── cpp/                       # C++ implementation (planned)
├── grpc/                          # gRPC implementation
│   ├── DESIGN.md                  # gRPC architecture deep dive
│   ├── air_traffic_types.proto    # Shared Protocol Buffer definitions
│   ├── scripts/                   # Demo launcher
│   ├── python/                    # Python implementation
│   └── specs/                     # App specifications
└── docs/
    ├── design_process/            # How we built this (AI-assisted design journey)
    └── reference/                 # ATC domain reference material
```

## How We Built This

This project was designed iteratively using AI tools with and without [RTI's Connext AI Design Expert (Connext MCP server)](https://chatbot.rti.com/docs/getting-started). The [`docs/design_process/`](docs/design_process/) directory documents this journey, including prompts, design iterations, and a comparison of using Connext AI Design Expert vs no Expert approaches.

## License

Apache-2.0 — see [LICENSE](LICENSE).
