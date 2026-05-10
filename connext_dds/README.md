# RTI Connext DDS — Air Traffic Control

Implementation of the national ATC simulation using **RTI Connext DDS 7.7.0 Pro**.

## Architecture

| Application | Role | Count |
|---|---|---|
| `app_airplane.py` | Aircraft position reporting, flight plan filing, gate requests | 1 per aircraft |
| `app_airport.py` | Weather reports, runway status, gate assignment service | 1 per airport |
| `app_tower.py` | Terminal-area control: clearances, runway management, handoffs | 1 per airport |
| `app_tracon.py` | Terminal radar approach control: arrival sequencing, handoffs | 1 per TRACON |
| `app_center.py` | En-route control: separation, weather rerouting, sector handoffs | 1 per center |
| `app_flightplan_service.py` | Central flight plan validation and publishing | 1 |
| `app_weather_service.py` | Convective weather cell generation | 1 |
| `app_dashboard.py` | Web-based real-time map (Flask + Leaflet) | 1 |

## File Inventory

```
connext_dds/
├── README.md                      # This file
├── DESIGN.md                      # DDS architecture deep dive
├── air_traffic_types.idl          # IDL4 type definitions (source of truth)
├── air_traffic_qos.xml            # QoS profile library
├── air_traffic_scenario.json      # Scenario config: airports, aircraft, centers
├── diagrams/                      # Design diagrams (referenced by DESIGN.md)
├── scripts/
│   ├── demo_start.sh              # Launch all apps
│   ├── demo_stop.sh               # Stop all apps
│   ├── demo_cli.py                # Scenario config parser (used by demo_start.sh)
│   ├── collector_start.sh         # Start data collector
│   └── collector_stop.sh          # Stop data collector
├── python/                        # Python implementation
│   ├── README.md                  # Python-specific setup
│   ├── types_generate.sh          # rtiddsgen -language Python
│   ├── common.py                  # Shared utilities
│   ├── air_traffic.py             # Generated types (DO NOT HAND-EDIT)
│   └── app_*.py                   # Application files (8 apps)
└── cpp/                           # C++ implementation (planned)
```

## Quick Start

### Prerequisites

- [RTI Connext DDS 7.7.0 Professional](https://community.rti.com/static/documentation/developers/)
- Python 3.10+
- Virtual environment set up via `source ../setup.sourceme`

### Generate Types

```bash
cd python
./types_generate.sh
cd ..
```

### Run

```bash
./scripts/demo_start.sh
```

Open http://localhost:8050 for the real-time dashboard.

### Stop

```bash
./scripts/demo_stop.sh
```

## DDS Design Highlights

- **Single domain** (ID 0) with partition-based logical separation
- **Content-Filtered Topics** for aircraft-specific instructions and sector-filtered positions
- **Request/Reply** for flight plan filing and gate assignment
- **8 QoS profiles** inheriting from Connext BuiltinQosLib patterns
- **`@mutable`** topic types for schema evolution
- **DomainParticipant partitions** for discovery isolation between facilities

See [DESIGN.md](DESIGN.md) for the full architecture document.
