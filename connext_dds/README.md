# National Air-Traffic Control — RTI Connext DDS Demo

A multi-application DDS-based simulation of a national air-traffic control
system using **RTI Connext DDS 7.7.0 Pro** (Python API).

## Architecture

| Application | Role | Count |
|---|---|---|
| `airplane_app` | Aircraft position reporting, flight plan filing, gate requests | N per aircraft |
| `tower_app` | Terminal-area control: clearances, runway management, handoffs | 1 per airport |
| `center_app` | En-route control: separation monitoring, sector handoffs | 1 per center |
| `airport_app` | Weather reports, runway status, gate assignment service | 1 per airport |
| `flightplan_service` | Central flight plan validation and publishing | 1 |
| `dashboard_app` | Read-only monitoring of all topics | 1 |

## Project Structure

```
connext_dds/
├── idl/air_traffic.idl           # IDL4 type definitions
├── qos/USER_QOS_PROFILES.xml     # QoS profile library
├── src/
│   ├── atc_types.py              # Python type definitions
│   ├── common/__init__.py        # Shared utilities
│   ├── airplane_app/airplane.py
│   ├── tower_app/tower.py
│   ├── center_app/center.py
│   ├── airport_app/airport.py
│   ├── flightplan_service/flightplan_service.py
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
./scripts/run_scenario.sh --duration 60 --aircraft 4
```

This launches 2 airports (KJFK, KLAX), 2 towers, 2 en-route centers,
4 aircraft, the flight plan service, and a dashboard.

## Running Individual Applications

Each application can be run standalone:

```bash
# Flight plan service
python3 src/flightplan_service/flightplan_service.py --duration 120

# Airport
python3 src/airport_app/airport.py --airport-code KJFK --wx-interval 25

# Tower
python3 src/tower_app/tower.py --airport-code KJFK

# En-route center
python3 src/center_app/center.py --center-id ZNY --min-alt 18000 --max-alt 60000

# Aircraft
python3 src/airplane_app/airplane.py --callsign AAL100 --origin KJFK --destination KLAX

# Dashboard
python3 src/dashboard_app/dashboard.py --summary-interval 10
```

## DDS Design Highlights

- **Single domain** (ID 0) with partition-based logical separation
- **Content-Filtered Topics** for aircraft-specific instructions, sector-filtered
  positions, and airport-scoped weather
- **Request/Reply** for flight plan filing and gate assignment
- **7 QoS profiles** inheriting from Connext BuiltinQosLib patterns
- **`@mutable`** topic types for schema evolution; **`@appendable`** enums
- **Writer-side CFT filtering** for bandwidth efficiency
- **Exclusive ownership** for controller redundancy

See [design_connext_dds.md](design_connext_dds.md) for the full design document.
