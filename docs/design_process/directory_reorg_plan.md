# Plan: Restructure air-traffic repo for GitHub publication

## Goal
Prepare rticonnextdds-comparison-air-traffic for GitHub under rticommunity. Support multiple programming languages (Python first, C++ next).

## Decisions
- Keep directory name `connext_dds/` (not `dds/`)
- Per-language dirs for source code: `connext_dds/python/`, `connext_dds/cpp/`
- `connext_dds/scripts/` for demo/collector scripts and demo_cli.py (discoverable, not buried in language dirs)
- When C++ is added, rename to `demo_python_start.sh` / `demo_cpp_start.sh` etc.
- Design-process artifacts → `docs/design_process/` on main (not separate branch)
- `docs/design_process/README.md` narrates reading order; top-level README links to it ("How We Built This")
- Reference material (atc_systems.md, *.webp) → `docs/reference/`
- Language-agnostic artifacts (IDL, QoS XML, DESIGN.md, diagrams) shared at connext_dds/ level
- `connext_dds/DESIGN.md` for architecture/design (not README — README is "how to use")
- Per-component specs are language-specific → go inside language dirs (`python/spec/`, `cpp/spec/`)
- Diagrams (mermaid, svg) go in `connext_dds/diagrams/`
- IDL file named `air_traffic_types.idl` (clarifies it defines types)
- Python app files use `app_` prefix (e.g., `app_airplane.py`) to distinguish from support files
- Demo chain uses `demo_` prefix: `demo_cli.py` (parser), `demo_start.sh`/`demo_stop.sh` (launchers)
- Scenario config named `air_traffic_scenario.json` (matches `air_traffic_types.idl`, `air_traffic_qos.xml`) and lives at `connext_dds/` level (not in scripts/) because it defines the simulation topology consumed by all apps via `common.py`
- `types_generate.sh` stays per-language (calls rtiddsgen with language-specific flags, output goes into language dir)
- `common.py` does not hardcode file paths — apps receive config/qos paths via CLI args; demo_start.sh passes them when launching

## Doc structure rationale
- README.md = "what is this, how do I run it" (auto-rendered by GitHub)
- DESIGN.md = "why is the DDS architecture designed this way" (teaching doc, language-agnostic)
- `<lang>/spec/` = per-component implementation specs (language-specific)
- `docs/design_process/` = how we built this (learning resource)
- `docs/reference/` = external knowledge and reference material used during design

## Content classification
| Content type | Language-agnostic? | Location |
|---|---|---|
| DDS architecture (domains, partitions, topics, QoS, CFTs, data flows, fault tolerance) | Yes | `connext_dds/DESIGN.md` |
| Design diagrams (partition graphs, data flow diagrams) | Yes | `connext_dds/diagrams/` |
| IDL, QoS XML | Yes | `connext_dds/` |
| Demo scenario config | Yes (shared across languages) | `connext_dds/air_traffic_scenario.json` |
| Demo/collector scripts, demo_cli.py | Cross-cutting | `connext_dds/scripts/` |
| Type generation scripts | No (language-specific flags) | `connext_dds/<lang>/` |
| Component implementation specs | No | `connext_dds/<lang>/spec/` |
| Source code | No | `connext_dds/<lang>/` |
| Design-process artifacts | N/A | `docs/design_process/` |
| Reference material | N/A | `docs/reference/` |

## Proposed structure
```
rticonnextdds-comparison-air-traffic/
├── README.md                      # Scenario, data flows, quick start, series table
├── LICENSE                        # Apache-2.0
├── setup.sourceme                 # Environment setup (source, not execute)
├── .gitignore
│
├── connext_dds/                   # Pure Connext DDS approach
│   ├── README.md                  # Approach overview, file inventory, quick start
│   ├── DESIGN.md                  # DDS architecture: partitions, QoS, CFTs, data flows
│   ├── diagrams/                  # Design diagrams (referenced by DESIGN.md)
│   │   ├── ATC_Partitions.mermaid
│   │   └── ATC_Partitions.svg
│   ├── air_traffic_types.idl      # Shared IDL (source of truth, all languages)
│   ├── air_traffic_qos.xml        # Shared QoS profiles (all languages)
│   ├── air_traffic_scenario.json  # Scenario config: airports, aircraft, centers, duration
│   │
│   ├── scripts/                   # Demo & operational scripts (first thing users find)
│   │   ├── demo_start.sh          # Launch all apps (rename to demo_python_start.sh when C++ added)
│   │   ├── demo_stop.sh           # Stop all apps
│   │   ├── demo_cli.py            # Parses air_traffic_scenario.json (used by demo_start.sh)
│   │   ├── collector_start.sh     # Start data collector
│   │   └── collector_stop.sh      # Stop data collector
│   │
│   ├── python/                    # Python implementation (pure source code)
│   │   ├── README.md              # Python-specific setup & run instructions
│   │   ├── types_generate.sh      # rtiddsgen -language Python
│   │   ├── spec/                  # Python-specific component specs (future)
│   │   ├── air_traffic.py         # Generated types (rtiddsgen output)
│   │   ├── common.py              # Shared utilities (constants, scenario loaders, geometry, etc.)
│   │   ├── app_airplane.py        # Application: airplane
│   │   ├── app_airport.py         # Application: airport
│   │   ├── app_tower.py           # Application: tower
│   │   ├── app_tracon.py          # Application: TRACON
│   │   ├── app_center.py          # Application: center
│   │   ├── app_flightplan_service.py  # Application: flight plan service
│   │   ├── app_weather_service.py     # Application: weather service
│   │   └── app_dashboard.py       # Application: dashboard
│   │
│   └── cpp/                       # C++ implementation (future)
│       ├── README.md
│       ├── types_generate.sh      # rtiddsgen -language C++11
│       ├── spec/
│       └── CMakeLists.txt
│
├── requirements/
│   ├── common.txt
│   └── connext_dds.txt
│
├── shared/                        # Assets shared across approaches
│
└── docs/
    ├── design_process/            # How we built this (learning resource)
    │   ├── README.md              # Reading guide: journey overview, tools used, reading order
    │   ├── high_level_scenario.md # Original scenario description (historical)
    │   ├── architecture_overview.md # Original architecture sketch (historical)
    │   ├── prompts.md             # Prompts used with AI tools
    │   ├── initial_connext_issues.md
    │   ├── opus_mcp_design_connext_dds_iter1.md
    │   ├── opus_nomcp_design_connext_dds_iter1.md
    │   └── use_of_connext_mcp.md  # MCP vs no-MCP comparison
    │
    └── reference/                 # Domain knowledge used during design
        ├── atc_systems.md
        └── *.webp
```

## File mapping (every file)

### Files staying on main branch

| Current path | New path | Action |
|---|---|---|
| `.gitignore` | `.gitignore` | Update (add venv/, __pycache__/, *.pyc) |
| `architecture_overview.md` | `README.md` + `docs/design_process/architecture_overview.md` | Merge into README; keep original in design_process |
| `high_level_scenario.md` | `README.md` + `docs/design_process/high_level_scenario.md` | Merge into README; keep original in design_process |
| `requirements.txt` | `requirements/connext_dds.txt` | Move + split common deps into requirements/common.txt |
| `setup_env.sh` | `setup.sourceme` | Rename |
| `gateway_1.xml` | `connext_dds/gateway_1.xml` | Move (Routing Service config) |
| — | `LICENSE` | New (Apache-2.0) |
| `connext_dds/README.md` | `connext_dds/README.md` | Rewrite (approach overview, file inventory, quick start) |
| `connext_dds/design/design_connext_dds.md` | `connext_dds/DESIGN.md` | Move + rename |
| `connext_dds/design/ATC_Partitions.mermaid` | `connext_dds/diagrams/ATC_Partitions.mermaid` | Move |
| `connext_dds/design/ATC_Partitions.svg` | `connext_dds/diagrams/ATC_Partitions.svg` | Move |
| `connext_dds/idl/air_traffic.idl` | `connext_dds/air_traffic_types.idl` | Move up + rename |
| `connext_dds/qos/USER_QOS_PROFILES.xml` | `connext_dds/air_traffic_qos.xml` | Move up + rename |
| `connext_dds/config/scenario_default.json` | `connext_dds/air_traffic_scenario.json` | Move + rename |
| `connext_dds/src/air_traffic.py` | `connext_dds/python/air_traffic.py` | Move (generated types) |
| `connext_dds/src/common/scenario_cli.py` | `connext_dds/scripts/demo_cli.py` | Move + rename |
| `connext_dds/src/common/__init__.py` | `connext_dds/python/common.py` | Move + rename (shared utilities) |
| `connext_dds/src/airplane_app/airplane.py` | `connext_dds/python/app_airplane.py` | Move + rename |
| `connext_dds/src/airport_app/airport.py` | `connext_dds/python/app_airport.py` | Move + rename |
| `connext_dds/src/tower_app/tower.py` | `connext_dds/python/app_tower.py` | Move + rename |
| `connext_dds/src/tracon_app/tracon.py` | `connext_dds/python/app_tracon.py` | Move + rename |
| `connext_dds/src/center_app/center.py` | `connext_dds/python/app_center.py` | Move + rename |
| `connext_dds/src/flightplan_service/flightplan_service.py` | `connext_dds/python/app_flightplan_service.py` | Move + rename |
| `connext_dds/src/weather_service/weather_service.py` | `connext_dds/python/app_weather_service.py` | Move + rename |
| `connext_dds/src/weather_service/__init__.py` | — | Remove (check if exports needed; fold into app_weather_service.py) |
| `connext_dds/src/dashboard_app/dashboard.py` | `connext_dds/python/app_dashboard.py` | Move + rename |
| `connext_dds/scripts/run_scenario.sh` | `connext_dds/scripts/demo_start.sh` | Rename (stays in scripts/) |
| `connext_dds/scripts/stop_scenario.sh` | `connext_dds/scripts/demo_stop.sh` | Rename |
| `connext_dds/scripts/generate_types.sh` | `connext_dds/python/types_generate.sh` | Move to python/ + rename |
| `connext_dds/scripts/run_collector.sh` | `connext_dds/scripts/collector_start.sh` | Rename |
| `connext_dds/scripts/stop_collector.sh` | `connext_dds/scripts/collector_stop.sh` | Rename |
| — | `connext_dds/python/README.md` | New (Python setup/build/run) |
| — | `connext_dds/cpp/README.md` | New (placeholder) |
| — | `connext_dds/cpp/CMakeLists.txt` | New (skeleton) |
| — | `connext_dds/cpp/types_generate.sh` | New (rtiddsgen -language C++11) |
| `docs/atc_systems.md` | `docs/reference/atc_systems.md` | Move |
| `docs/*.webp` (2 files) | `docs/reference/*.webp` | Move |

### Files moving to docs/design_process/
| Current path | New path |
|---|---|
| `iterations/initial_connext_issues.md` | `docs/design_process/initial_connext_issues.md` |
| `iterations/opus_mcp_design_connext_dds_iter1.md` | `docs/design_process/opus_mcp_design_connext_dds_iter1.md` |
| `iterations/opus_nomcp_design_connext_dds_iter1.md` | `docs/design_process/opus_nomcp_design_connext_dds_iter1.md` |
| `iterations/use_of_connext_mcp.md` | `docs/design_process/use_of_connext_mcp.md` |
| `prompts.md` | `docs/design_process/prompts.md` |
| `architecture_overview.md` | `docs/design_process/architecture_overview.md` (copy — original also merged into README) |
| `high_level_scenario.md` | `docs/design_process/high_level_scenario.md` (copy — original also merged into README) |
| — | `docs/design_process/README.md` (new — reading guide) |

### Directories removed (empty after moves)
`connext_dds/design/`, `connext_dds/idl/`, `connext_dds/qos/`, `connext_dds/config/`, `connext_dds/src/` and all subdirs, `iterations/`

Note: `connext_dds/scripts/` is RETAINED (demo/collector scripts stay there, only generate_types.sh moves out to python/)

## Implementation notes
- All file moves/renames use `git mv` to preserve history (`git log --follow` works on relocated files)
- Create new directories implicitly via `git mv` targets or `mkdir -p` before populating
- New files (README.md, LICENSE, etc.) use plain `git add`

## Steps

### Phase 1: Design-process and reference documentation
1. Create `docs/design_process/` directory
2. Move iterations/* → docs/design_process/
3. Move prompts.md → docs/design_process/prompts.md
4. Copy high_level_scenario.md, architecture_overview.md → docs/design_process/ (originals removed after merge into README in Phase 5)
5. Create docs/design_process/README.md (reading guide: journey overview, tools used, suggested reading order)
6. Remove empty iterations/ directory
7. Create `docs/reference/` directory
8. Move docs/atc_systems.md → docs/reference/atc_systems.md
9. Move docs/*.webp → docs/reference/

### Phase 2: Restructure connext_dds/ shared files
10. Move shared DDS files to connext_dds/ root:
    - idl/air_traffic.idl → connext_dds/air_traffic_types.idl
    - qos/USER_QOS_PROFILES.xml → connext_dds/air_traffic_qos.xml
11. Move config/scenario_default.json → connext_dds/air_traffic_scenario.json
12. Rename design/design_connext_dds.md → connext_dds/DESIGN.md
13. Move design/ATC_Partitions.mermaid → connext_dds/diagrams/ATC_Partitions.mermaid
14. Move design/ATC_Partitions.svg → connext_dds/diagrams/ATC_Partitions.svg
15. Remove empty idl/, qos/, config/, design/ subdirs

### Phase 3: Restructure connext_dds/scripts/
15. Rename scripts in place:
    - scripts/run_scenario.sh → scripts/demo_start.sh
    - scripts/stop_scenario.sh → scripts/demo_stop.sh
    - scripts/run_collector.sh → scripts/collector_start.sh
    - scripts/stop_collector.sh → scripts/collector_stop.sh
16. Move src/common/scenario_cli.py → scripts/demo_cli.py
17. Move scripts/generate_types.sh → python/types_generate.sh (language-specific)
18. Update demo_start.sh: paths to app_ files in ../python/, path to demo_cli.py (now local ./demo_cli.py), path to ../air_traffic_scenario.json, passes --config/--qos-file to apps
19. Update demo_stop.sh similarly

### Phase 4: Create connext_dds/python/ (*parallel with Phase 3 steps 16-17*)
20. Move all Python source files flat into connext_dds/python/ with app_ prefix for applications:
    - src/airplane_app/airplane.py → connext_dds/python/app_airplane.py
    - src/airport_app/airport.py → connext_dds/python/app_airport.py
    - src/tower_app/tower.py → connext_dds/python/app_tower.py
    - src/tracon_app/tracon.py → connext_dds/python/app_tracon.py
    - src/center_app/center.py → connext_dds/python/app_center.py
    - src/flightplan_service/flightplan_service.py → connext_dds/python/app_flightplan_service.py
    - src/weather_service/weather_service.py → connext_dds/python/app_weather_service.py
    - (weather_service/__init__.py — check if needed; fold into app_weather_service.py if so)
    - src/dashboard_app/dashboard.py → connext_dds/python/app_dashboard.py
    Support files (no app_ prefix):
    - src/air_traffic.py → connext_dds/python/air_traffic.py (generated types)
    - src/common/__init__.py → connext_dds/python/common.py
21. Refactor common.py: remove hardcoded QOS_FILE and SCENARIO_CONFIG paths. Use module-level init() or require callers to pass paths explicitly. Each app already has argparse — add --config and --qos-file args. demo_start.sh passes these paths when launching apps.
22. Update all app files to pass config/qos paths to common.py functions (no more relying on hardcoded defaults)
23. Remove empty src/ and all subdirs

### Phase 5: Stub connext_dds/cpp/ (*parallel with Phase 4*)
24. Create connext_dds/cpp/README.md placeholder
25. Create connext_dds/cpp/CMakeLists.txt skeleton
26. Create connext_dds/cpp/types_generate.sh (rtiddsgen -language C++11 ../air_traffic_types.idl)

### Phase 6: Top-level files
27. Merge high_level_scenario.md + architecture_overview.md → README.md; add "How We Built This" section at bottom linking to docs/design_process/
28. Remove top-level high_level_scenario.md, architecture_overview.md (copies already in docs/design_process/ from Phase 1)
29. Rename setup_env.sh → setup.sourceme
30. Layer requirements: requirements/common.txt, requirements/connext_dds.txt
31. Move gateway_1.xml into connext_dds/ or remove
32. Add LICENSE (Apache-2.0)
33. Update .gitignore (venv/, __pycache__/, *.pyc, generated types)
34. Create connext_dds/README.md (approach overview, quick start pointing to scripts/, file inventory)
35. Create connext_dds/python/README.md (Python setup/build/run)

### Phase 7: Tractor-fleet cross-link
36. Update tractor-fleet series table to add air-traffic entry

## Tractor-fleet alignment (future)
- Tractor-fleet's `dds/spec/` contains Python-specific component specs (robot_node_spec.md etc.)
- When C++ is added to tractor-fleet, its spec/ should move to `dds/python/spec/`
- Air-traffic establishes the correct pattern from the start

## Verification
1. cd connext_dds/python && ./types_generate.sh → generates air_traffic.py from ../air_traffic_types.idl
2. cd connext_dds/scripts && ./demo_start.sh all → launches scenario (references ../python/app_*.py)
3. All Python imports resolve (no broken paths)
4. connext_dds/README.md and DESIGN.md render with correct relative links on GitHub
5. DESIGN.md references to diagrams/ATC_Partitions.svg resolve correctly
6. docs/design_process/README.md renders correctly, links to all process files work
7. docs/reference/ contains atc_systems.md and *.webp files
8. Top-level README "How We Built This" section links to docs/design_process/ correctly
9. No stale top-level files (high_level_scenario.md, architecture_overview.md, prompts.md removed; iterations/ dir removed)
10. `ls connext_dds/python/app_*.py` lists exactly 8 app files; support files (common.py, air_traffic.py) have no app_ prefix
11. demo_start.sh references `./demo_cli.py` and `../air_traffic_scenario.json` correctly
12. scripts/ contains demo_start.sh, demo_stop.sh, demo_cli.py, collector_start.sh, collector_stop.sh (no types_generate.sh — that's per-language)
