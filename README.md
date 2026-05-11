# National Air-Traffic Control System with RTI Connext DDS

A multi-application simulation of a national air-traffic control system built with [RTI Connext DDS](https://www.rti.com/products/connext). The system uses a **data-centric** architecture where applications share state through a common data space rather than exchanging point-to-point messages — aircraft positions, facility status, weather cells, and flight plans are all modeled as distributed shared state that any participant can read, filter, and react to in real time.

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

## Implementation

Built with RTI Connext DDS (Python). See [`connext_dds/`](connext_dds/) for the full implementation.

## Quick Start

```bash
# Set up virtual environment and install dependencies
source setup.sourceme

# Generate Python types from IDL
cd connext_dds/python && ./types_generate.sh && cd ../..

# Run the demo (defaults to all apps, 120s)
./connext_dds/scripts/demo_start.sh
```

Open http://localhost:8050 for the real-time dashboard.

See [`connext_dds/README.md`](connext_dds/README.md) for prerequisites, detailed options, and design notes.

## Repository Structure

```
├── README.md                      # This file
├── setup.sourceme                 # Environment setup (source, not execute)
├── requirements/
│   └── connext_dds.txt            # Python dependencies
├── connext_dds/                   # RTI Connext DDS implementation
│   ├── README.md                  # Approach overview & quick start
│   ├── DESIGN.md                  # DDS architecture deep dive
│   ├── air_traffic_types.idl      # Shared IDL type definitions
│   ├── air_traffic_qos.xml        # Shared QoS profiles
│   ├── diagrams/                  # Design diagrams
│   ├── scripts/                   # Demo launcher, scenario config
│   ├── python/                    # Python implementation
│   └── cpp/                       # C++ implementation (planned)
└── docs/
    ├── design_process/            # How we built this (AI-assisted design journey)
    └── reference/                 # ATC domain reference material
```

## How We Built This

This project was designed iteratively using AI tools with and without [RTI's Connext AI Design Expert (Connext MCP server)](https://chatbot.rti.com/docs/getting-started). The [`docs/design_process/`](docs/design_process/) directory documents this journey, including prompts, design iterations, and a comparison of using Connext AI Design Expert vs no Expert approaches.

## License

Apache-2.0 — see [LICENSE](LICENSE).
