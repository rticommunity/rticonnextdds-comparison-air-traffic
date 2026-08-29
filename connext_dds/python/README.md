# Python Implementation

Python implementation of the Air Traffic Control simulation using RTI Connext DDS 7.7.0.

## Prerequisites

- Python 3.10+
- RTI Connext DDS 7.7.0 Professional
- Virtual environment set up via `source ../../setup.sourceme`
- `CARTO_BASEMAP_API_KEY` set to your own
    [CARTO basemap key](https://carto.com/basemaps/apikey/), which is free within
    CARTO's fair-use limit, in the repository's ignored `.env.local` file before
    running the dashboard. Create it by copying `.env.example` at the repository
    root. Do not commit the key; it is visible to dashboard users in browser tile
    requests and should be restricted to the domains where it is used.

## Generate Types

```bash
./types_generate.sh
```

This runs `rtiddsgen -language Python` on `../air_traffic_types.idl` and generates `air_traffic_types.py`.

## Application Files

| File | Description |
|---|---|
| `common.py` | Shared utilities: DDS helpers, scenario loaders, geometry, sim speed |
| `air_traffic_types.py` | Generated types from IDL (DO NOT HAND-EDIT) |
| `app_airplane.py` | Aircraft simulator |
| `app_airport.py` | Airport infrastructure (weather, runways, gates) |
| `app_tower.py` | Control tower |
| `app_tracon.py` | TRACON approach control |
| `app_center.py` | En-route center |
| `app_flightplan_service.py` | Flight plan filing service |
| `app_weather_service.py` | Convective weather cell publisher |
| `app_dashboard.py` | Web dashboard (Flask + Leaflet) |

## Running Individual Apps

All apps require `--config` and `--qos-file` arguments:

```bash
python app_airport.py \
    --config ../../air_traffic_scenario.json \
    --qos-file ../air_traffic_qos.xml \
    --airport-code KJFK
```

Use `../scripts/demo_start.sh` to launch the full scenario with all arguments pre-configured.
