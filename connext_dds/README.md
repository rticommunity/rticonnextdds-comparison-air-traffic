# National Air-Traffic Control — RTI Connext DDS Demo

A multi-application DDS-based simulation of a national air-traffic control
system using **RTI Connext DDS 7.7.0 Pro** (Python API).

## Architecture

| Application | Role | Count |
|---|---|---|
| `airplane_app` | Aircraft position reporting, flight plan filing, gate requests | 1 per aircraft |
| `tower_app` | Terminal-area control: clearances, runway management, handoffs to TRACON | 1 per airport |
| `tracon_app` | Terminal radar approach control: arrival sequencing, handoffs to center/tower | 1 per TRACON |
| `center_app` | En-route control: separation monitoring, weather rerouting, sector handoffs | 1 per center |
| `airport_app` | Weather reports, runway status, gate assignment service | 1 per airport |
| `flightplan_service` | Central flight plan validation and publishing | 1 |
| `weather_service` | Convective weather cell generation for en-route hazards | 1 |
| `dashboard_app` | Web-based real-time map and monitoring (Flask + Leaflet) | 1 |

## Project Structure

```
connext_dds/
├── idl/air_traffic.idl           # IDL4 type definitions
├── qos/USER_QOS_PROFILES.xml     # QoS profile library
├── src/
│   ├── air_traffic.py            # Auto-generated Python types (from IDL)
│   ├── common/__init__.py        # Shared utilities
│   ├── airplane_app/airplane.py
│   ├── tower_app/tower.py
│   ├── tracon_app/tracon.py
│   ├── center_app/center.py
│   ├── airport_app/airport.py
│   ├── flightplan_service/flightplan_service.py
│   ├── weather_service/weather_service.py
│   └── dashboard_app/dashboard.py
├── scripts/run_scenario.sh       # Launch script
├── config/scenario_default.json  # Demo scenario configuration
└── README.md
```

## Prerequisites

- RTI Connext DDS 7.7.0 Pro installed
- Python 3.10+
- `rti.connextdds` and `rti.rpc` Python packages (bundled with Connext)

Set up the Connext environment:

```bash
source /path/to/rti_connext_dds-7.7.0/resource/scripts/rtisetenv_arm64Darwin23clang16.0.bash
```

## Quick Start

```bash
cd connext_dds
chmod +x scripts/run_scenario.sh
./scripts/run_scenario.sh all --duration 120
```

This launches all airports, towers, TRACONs, en-route centers, aircraft,
the flight plan service, weather service, and a web dashboard based on
the scenario defined in `config/scenario_default.json` (7 airports by default).

## Running Individual Applications

Each application can be run standalone:

```bash
# Flight plan service
python3 src/flightplan_service/flightplan_service.py --duration 120

# Airport
python3 src/airport_app/airport.py --airport-code KJFK --wx-interval 25

# Tower
python3 src/tower_app/tower.py --airport-code KJFK --serving-tracon N90

# TRACON
python3 src/tracon_app/tracon.py --tracon-id N90 --airports KJFK --serving-center ZNY

# En-route center
python3 src/center_app/center.py --center-id ZNY --min-alt 18000 --max-alt 60000

# Weather service (convective cells)
python3 src/weather_service/weather_service.py --spawn-interval 30 --max-cells 5

# Aircraft
python3 src/airplane_app/airplane.py --callsign AAL100 --origin KJFK --destination KLAX

# Dashboard (web UI on http://localhost:8050)
python3 src/dashboard_app/dashboard.py --port 8050
```

## DDS Design Highlights

- **Single domain** (ID 0) with partition-based logical separation
- **Content-Filtered Topics** for aircraft-specific instructions, sector-filtered
  positions, and airport-scoped weather
- **Request/Reply** for flight plan filing and gate assignment
- **8 QoS profiles** inheriting from Connext BuiltinQosLib patterns
- **`@mutable`** topic types for schema evolution; **`@appendable`** enums
- **Writer-side CFT filtering** for bandwidth efficiency
- **Exclusive ownership** for controller redundancy
- **DomainParticipant partitions** for discovery isolation between facilities

See [design_connext_dds.md](design_connext_dds.md) for the full design document.
