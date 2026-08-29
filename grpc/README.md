# gRPC — Air Traffic Control

Implementation of the national ATC simulation using **gRPC, Protocol Buffers,
and Zeroconf service discovery**.

## Architecture

| Application | Role | Count |
|---|---|---|
| `app_airplane.py` | Aircraft position reporting and instruction acknowledgments | 1 per aircraft |
| `app_airport.py` | Weather reports, runway status, and gate assignment | 1 per airport |
| `app_tower.py` | Terminal-area control, runway management, and handoffs | 1 per airport |
| `app_tracon.py` | Arrival sequencing and terminal handoffs | 1 per TRACON |
| `app_center.py` | En-route separation, weather rerouting, and handoffs | 1 per center |
| `app_flightplan_service.py` | Central flight-plan validation and streaming | 1 |
| `app_weather_service.py` | Convective weather-cell generation | 1 |
| `app_dashboard.py` | Web-based real-time map (Flask + Leaflet) | 1 |

## File Inventory

```
(repository root)
├── .env.example                   # Template for local credentials and settings
├── .env.local                     # User-created local settings (Git-ignored)
└── grpc/
    ├── README.md                  # This file
    ├── DESIGN.md                  # gRPC architecture deep dive
    ├── air_traffic_types.proto    # Protocol Buffer messages and services
    ├── scripts/
    │   ├── demo_start.sh          # Launch all or selected applications
    │   ├── demo_stop.sh           # Stop all or selected applications
    │   └── demo_cli.py            # Scenario configuration parser
    ├── python/
    │   ├── types_generate.sh      # Generate Python protobuf/gRPC modules
    │   ├── common.py              # Shared gRPC and simulation utilities
    │   ├── air_traffic_types_pb2.py
    │   ├── air_traffic_types_pb2_grpc.py
    │   └── app_*.py               # Application files
    └── specs/                     # Implementation notes and specifications
```

## Quick Start

### Prerequisites

- Python 3.10+
- Virtual environment set up via `source ../setup.sourceme`
- A personal [CARTO basemap API key](https://carto.com/basemaps/apikey/) for the
  dashboard. Keys are free within CARTO's fair-use limit of five million tile
  requests per calendar month. Authorize `localhost`, then create the ignored
  local configuration file from the repository root:

  ```bash
  cp .env.example .env.local
  ```

  Replace the `CARTO_BASEMAP_API_KEY` placeholder. The demo launcher loads this
  file automatically. Each user must use their own key and comply with the
  [CARTO Basemaps Terms](https://carto.com/legal/basemap-terms/). The key is
  visible in browser tile requests, so configure domain restrictions and usage
  limits and monitor it for abuse.

### Generate Types

The generated Python modules are checked in, so regeneration is needed only
when `air_traffic_types.proto` changes:

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

## gRPC Design Highlights

- Protocol Buffers define messages and RPC service contracts.
- Server-streaming RPCs emulate publish/subscribe data flows.
- Zeroconf provides runtime service discovery.
- Application code implements state replay, retries, filtering, and fan-out.
- No RTI Connext installation or license is required.

See [DESIGN.md](DESIGN.md) for the full architecture document.
