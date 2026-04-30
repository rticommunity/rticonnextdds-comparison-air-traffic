#!/usr/bin/env bash
#
# run_scenario.sh — Launch ATC demo applications individually or all at once.
#
# Usage:
#   ./run_scenario.sh <command> [options]
#
# Commands:
#   all            Start the full scenario (all applications)
#   flightplan     Start the Flight Plan Filing Service
#   airport        Start an Airport infrastructure app
#   tower          Start a Control Tower app
#   tracon         Start a TRACON app
#   center         Start an En-Route Center app
#   airplane       Start an Aircraft simulator
#   dashboard      Start the Dashboard monitor
#   help           Show this help message
#
# Global options:
#   --duration N   Run duration in seconds (default: 60)
#
# Examples:
#   ./run_scenario.sh all
#   ./run_scenario.sh all --duration 120
#   ./run_scenario.sh all --config config/my_scenario.json
#   ./run_scenario.sh flightplan
#   ./run_scenario.sh airport --airport-code KJFK --runways "04L/22R 04R/22L"
#   ./run_scenario.sh tower --airport-code KLAX
#   ./run_scenario.sh center --center-id ZNY --min-alt 18000 --max-alt 60000
#   ./run_scenario.sh airplane --callsign AAL100 --origin KJFK --destination KLAX
#   ./run_scenario.sh dashboard --summary-interval 5
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_DIR="$(cd "$PROJECT_DIR/.." && pwd)"
SRC_DIR="$PROJECT_DIR/src"

# ── Connext license ────────────────────────────────────────────────────────
export NDDSHOME="${NDDSHOME:-/Applications/rti_connext_dds-7.7.0}"
export RTI_LICENSE_FILE="${RTI_LICENSE_FILE:-$NDDSHOME/rti_license.dat}"

# ── Python from project venv ───────────────────────────────────────────────
PYTHON="${PYTHON:-$REPO_DIR/venv/bin/python3}"
if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: Python not found at $PYTHON"
    echo "       Run setup_env.sh first, or set PYTHON env var."
    exit 1
fi

DURATION=10000
NUM_AIRCRAFT=4
SCENARIO_CONFIG="$PROJECT_DIR/config/scenario_default.json"

# ── Helpers ─────────────────────────────────────────────────────────────────

# Lightweight JSON value extractor using Python (already available via venv).
# Usage: json_query '.duration_seconds' "$file"
json_query() {
    "$PYTHON" -c "
import json, sys
data = json.load(open(sys.argv[2]))
result = eval('data' + sys.argv[1])
if isinstance(result, list):
    for item in result:
        if isinstance(item, dict):
            print(json.dumps(item))
        else:
            print(item)
else:
    print(result)
" "$1" "$2"
}

usage() {
    sed -n '3,/^$/{ s/^# \?//; p }' "$0"
    exit 0
}

PIDS=()

cleanup() {
    echo ""
    echo "=== Shutting down all processes ==="
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    wait 2>/dev/null
    echo "All processes stopped."
}

wait_for_procs() {
    trap cleanup EXIT INT TERM
    echo ""
    echo "Press Ctrl+C to stop."
    wait
}

# ── Individual launch functions ─────────────────────────────────────────────

start_flightplan() {
    local dur="$DURATION"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --duration) dur="$2"; shift 2 ;;
            *) echo "Unknown flightplan option: $1"; exit 1 ;;
        esac
    done
    echo "Starting Flight Plan Service (duration=${dur}s)..."
    "$PYTHON" "$SRC_DIR/flightplan_service/flightplan_service.py" --duration "$dur" &
    PIDS+=($!)
}

start_airport() {
    local code="KJFK" runways="" dur="$DURATION" wx_interval="25" serving_tracon=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --airport-code)    code="$2"; shift 2 ;;
            --runways)         runways="$2"; shift 2 ;;
            --serving-tracon)  serving_tracon="$2"; shift 2 ;;
            --duration)        dur="$2"; shift 2 ;;
            --wx-interval)     wx_interval="$2"; shift 2 ;;
            *) echo "Unknown airport option: $1"; exit 1 ;;
        esac
    done
    if [[ -z "$runways" ]]; then
        case "$code" in
            KJFK) runways="04L/22R 04R/22L 13L/31R 13R/31L" ;;
            KLAX) runways="06L/24R 06R/24L 07L/25R 07R/25L" ;;
            KORD) runways="09L/27R 09R/27L 10L/28R 10R/28L" ;;
            KATL) runways="08L/26R 08R/26L 09L/27R 09R/27L 10/28" ;;
            KDFW) runways="13L/31R 13R/31L 17C/35C 17L/35R 17R/35L 18L/36R 18R/36L" ;;
            KDEN) runways="07/25 08/26 16L/34R 16R/34L 17L/35R 17R/35L" ;;
            KSFO) runways="01L/19R 01R/19L 10L/28R 10R/28L" ;;
            *)    runways="09/27" ;;
        esac
    fi
    local st_args=()
    if [[ -n "$serving_tracon" ]]; then
        st_args=(--serving-tracon "$serving_tracon")
    fi
    echo "Starting Airport $code (TRACON: ${serving_tracon:-none}, duration=${dur}s)..."
    "$PYTHON" "$SRC_DIR/airport_app/airport.py" \
        --airport-code "$code" --runways $runways "${st_args[@]}" \
        --duration "$dur" --wx-interval "$wx_interval" &
    PIDS+=($!)
}

start_tower() {
    local code="KJFK" dur="$DURATION" serving_tracon=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --airport-code)    code="$2"; shift 2 ;;
            --serving-tracon)  serving_tracon="$2"; shift 2 ;;
            --duration)        dur="$2"; shift 2 ;;
            *) echo "Unknown tower option: $1"; exit 1 ;;
        esac
    done
    local st_args=()
    if [[ -n "$serving_tracon" ]]; then
        st_args=(--serving-tracon "$serving_tracon")
    fi
    echo "Starting Tower $code (TRACON: ${serving_tracon:-none}, duration=${dur}s)..."
    "$PYTHON" "$SRC_DIR/tower_app/tower.py" \
        --airport-code "$code" "${st_args[@]}" --duration "$dur" &
    PIDS+=($!)
}

start_center() {
    local cid="ZNY" dur="$DURATION" min_alt="18000" max_alt="60000"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --center-id) cid="$2"; shift 2 ;;
            --duration)  dur="$2"; shift 2 ;;
            --min-alt)   min_alt="$2"; shift 2 ;;
            --max-alt)   max_alt="$2"; shift 2 ;;
            *) echo "Unknown center option: $1"; exit 1 ;;
        esac
    done
    echo "Starting Center $cid FL${min_alt}-FL${max_alt} (duration=${dur}s)..."
    "$PYTHON" "$SRC_DIR/center_app/center.py" \
        --center-id "$cid" --min-alt "$min_alt" --max-alt "$max_alt" \
        --duration "$dur" &
    PIDS+=($!)
}

start_airplane() {
    local callsign="SIM001" origin="KJFK" dest="KLAX" dur="$DURATION" tail=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --callsign)     callsign="$2"; shift 2 ;;
            --tail-number)  tail="$2"; shift 2 ;;
            --origin)       origin="$2"; shift 2 ;;
            --destination)  dest="$2"; shift 2 ;;
            --duration)     dur="$2"; shift 2 ;;
            *) echo "Unknown airplane option: $1"; exit 1 ;;
        esac
    done
    local tail_args=()
    if [[ -n "$tail" ]]; then
        tail_args=(--tail-number "$tail")
    fi
    echo "Starting Aircraft $callsign ($tail) $origin -> $dest (duration=${dur}s)..."
    "$PYTHON" "$SRC_DIR/airplane_app/airplane.py" \
        "${tail_args[@]}" --callsign "$callsign" --origin "$origin" --destination "$dest" \
        --duration "$dur" &
    PIDS+=($!)
}

start_tracon() {
    local tid="N90" dur="$DURATION" airports="" serving_center=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --tracon-id)       tid="$2"; shift 2 ;;
            --airports)        airports="$2"; shift 2 ;;
            --serving-center)  serving_center="$2"; shift 2 ;;
            --duration)        dur="$2"; shift 2 ;;
            *) echo "Unknown tracon option: $1"; exit 1 ;;
        esac
    done
    echo "Starting TRACON $tid — airports: ${airports:-none}, center: ${serving_center:-none} (duration=${dur}s)..."
    local sc_args=()
    if [[ -n "$serving_center" ]]; then
        sc_args=(--serving-center "$serving_center")
    fi
    local ap_args=()
    if [[ -n "$airports" ]]; then
        # shellcheck disable=SC2086
        ap_args=(--airports $airports)
    fi
    "$PYTHON" "$SRC_DIR/tracon_app/tracon.py" \
        --tracon-id "$tid" "${ap_args[@]}" "${sc_args[@]}" --duration "$dur" &
    PIDS+=($!)
}

start_dashboard() {
    local port="8050"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --port) port="$2"; shift 2 ;;
            *) echo "Unknown dashboard option: $1"; exit 1 ;;
        esac
    done
    echo "Starting Dashboard (Flask on http://localhost:${port})..."
    "$PYTHON" "$SRC_DIR/dashboard_app/dashboard.py" --port "$port" &
    PIDS+=($!)
}

# ── "all" — full scenario ──────────────────────────────────────────────────

start_all() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --duration) DURATION="$2"; shift 2 ;;
            --config)   SCENARIO_CONFIG="$2"; shift 2 ;;
            *) echo "Unknown option: $1"; exit 1 ;;
        esac
    done

    if [[ ! -f "$SCENARIO_CONFIG" ]]; then
        echo "ERROR: Scenario config not found: $SCENARIO_CONFIG"
        exit 1
    fi

    # Read scenario metadata
    SCENARIO_NAME=$(json_query '["scenario"]' "$SCENARIO_CONFIG")
    CONFIG_DURATION=$(json_query '["duration_seconds"]' "$SCENARIO_CONFIG")
    # Use config duration unless overridden via --duration
    if [[ "$DURATION" == "10000" ]]; then
        DURATION="$CONFIG_DURATION"
    fi

    echo "============================================"
    echo "  $SCENARIO_NAME"
    echo "  Config: $(basename "$SCENARIO_CONFIG")"
    echo "  Duration: ${DURATION}s"
    echo "============================================"
    echo ""

    # 1. Flight Plan Service (must start first for request/reply discovery)
    start_flightplan
    sleep 1

    # 2. Airport infrastructure — read from config (includes serving_tracon)
    while IFS= read -r airport_json; do
        code=$("$PYTHON" -c "import json,sys; print(json.loads(sys.argv[1])['code'])" "$airport_json")
        runways=$("$PYTHON" -c "import json,sys; print(' '.join(json.loads(sys.argv[1])['runways']))" "$airport_json")
        st=$("$PYTHON" -c "import json,sys; print(json.loads(sys.argv[1]).get('serving_tracon',''))" "$airport_json")
        start_airport --airport-code "$code" --runways "$runways" --serving-tracon "$st"
    done < <(json_query '["airports"]' "$SCENARIO_CONFIG")
    sleep 1

    # 3. Control Towers — one per airport (includes serving_tracon)
    while IFS= read -r airport_json; do
        code=$("$PYTHON" -c "import json,sys; print(json.loads(sys.argv[1])['code'])" "$airport_json")
        st=$("$PYTHON" -c "import json,sys; print(json.loads(sys.argv[1]).get('serving_tracon',''))" "$airport_json")
        start_tower --airport-code "$code" --serving-tracon "$st"
    done < <(json_query '["airports"]' "$SCENARIO_CONFIG")
    sleep 1

    # 4. TRACONs — derive airport list from airports with matching serving_tracon
    while IFS= read -r tracon_json; do
        tid=$("$PYTHON" -c "import json,sys; d=json.loads(sys.argv[1]); print(d['id'])" "$tracon_json")
        sc=$("$PYTHON" -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('serving_center',''))" "$tracon_json")
        airports=$("$PYTHON" -c "
import json,sys
cfg=json.load(open(sys.argv[1]))
tid=sys.argv[2]
print(' '.join(a['code'] for a in cfg['airports'] if a.get('serving_tracon')==tid))
" "$SCENARIO_CONFIG" "$tid")
        start_tracon --tracon-id "$tid" --airports "$airports" --serving-center "$sc"
    done < <(json_query '["tracons"]' "$SCENARIO_CONFIG")
    sleep 1

    # 5. En-Route Centers — read from config
    while IFS= read -r center_json; do
        cid=$("$PYTHON" -c "import json,sys; d=json.loads(sys.argv[1]); print(d['id'])" "$center_json")
        min_alt=$("$PYTHON" -c "import json,sys; d=json.loads(sys.argv[1]); print(d['min_altitude_ft'])" "$center_json")
        max_alt=$("$PYTHON" -c "import json,sys; d=json.loads(sys.argv[1]); print(d['max_altitude_ft'])" "$center_json")
        start_center --center-id "$cid" --min-alt "$min_alt" --max-alt "$max_alt"
    done < <(json_query '["centers"]' "$SCENARIO_CONFIG")
    sleep 1

    # 6. Aircraft — read from config
    while IFS= read -r ac_json; do
        cs=$("$PYTHON" -c "import json,sys; d=json.loads(sys.argv[1]); print(d['callsign'])" "$ac_json")
        tail=$("$PYTHON" -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('tail_number',''))" "$ac_json")
        orig=$("$PYTHON" -c "import json,sys; d=json.loads(sys.argv[1]); print(d['origin'])" "$ac_json")
        dest=$("$PYTHON" -c "import json,sys; d=json.loads(sys.argv[1]); print(d['destination'])" "$ac_json")
        start_airplane --callsign "$cs" --tail-number "$tail" --origin "$orig" --destination "$dest"
        sleep 0.3
    done < <(json_query '["aircraft"]' "$SCENARIO_CONFIG")

    # 7. Dashboard (last — all other participants should be discovered)
    sleep 2
    start_dashboard

    echo ""
    echo "=== All processes launched. Running for ${DURATION}s ==="
}

# ── Main dispatch ───────────────────────────────────────────────────────────

CMD="${1:-help}"
shift || true

case "$CMD" in
    all)         start_all "$@";         wait_for_procs ;;
    flightplan)  start_flightplan "$@";  wait_for_procs ;;
    airport)     start_airport "$@";     wait_for_procs ;;
    tower)       start_tower "$@";       wait_for_procs ;;
    tracon)      start_tracon "$@";      wait_for_procs ;;
    center)      start_center "$@";      wait_for_procs ;;
    airplane)    start_airplane "$@";    wait_for_procs ;;
    dashboard)   start_dashboard "$@";   wait_for_procs ;;
    help|-h|--help) usage ;;
    *) echo "Unknown command: $CMD"; echo "Run '$0 help' for usage."; exit 1 ;;
esac
