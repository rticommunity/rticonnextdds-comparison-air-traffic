#!/usr/bin/env bash
#
# demo_start.sh — Launch ATC demo applications individually or all at once.
#
# Usage:
#   ./demo_start.sh <command> [options]
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
#   weather        Start the Weather Service (ConvectiveCell)
#   help           Show this help message
#
# Global options:
#   --duration N   Run duration in seconds (default: 60)
#
# Examples:
#   ./demo_start.sh all
#   ./demo_start.sh all --duration 120
#   ./demo_start.sh all --config air_traffic_scenario.json
#   ./demo_start.sh flightplan
#   ./demo_start.sh airport --airport-code KJFK
#   ./demo_start.sh tower --airport-code KLAX
#   ./demo_start.sh center --center-id ZNY
#   ./demo_start.sh airplane --callsign AAL100
#   ./demo_start.sh tracon --tracon-id N90
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_DIR="$(cd "$PROJECT_DIR/.." && pwd)"
PYTHON_DIR="$PROJECT_DIR/python"

# ── Connext license ────────────────────────────────────────────────────────
export NDDSHOME="${NDDSHOME:-/Applications/rti_connext_dds-7.7.0}"
export RTI_LICENSE_FILE="${RTI_LICENSE_FILE:-$NDDSHOME/rti_license.dat}"
export DYLD_LIBRARY_PATH="$NDDSHOME/lib/arm64Darwin23clang16.0"

# ── Python from project venv ───────────────────────────────────────────────
PYTHON="${PYTHON:-$REPO_DIR/venv/bin/python3}"
if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: Python not found at $PYTHON"
    echo "       Run setup.sourceme first, or set PYTHON env var."
    exit 1
fi

DURATION=""
SCENARIO_CONFIG="$PROJECT_DIR/air_traffic_scenario.json"

# ── Helpers ─────────────────────────────────────────────────────────────────

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
            *) shift ;;  # pass-through
        esac
    done
    echo "Starting Flight Plan Service (duration=${dur}s)..."
    "$PYTHON" "$PYTHON_DIR/app_flightplan_service.py" --config "$SCENARIO_CONFIG" --qos-file "$PROJECT_DIR/air_traffic_qos.xml" --duration "$dur" &
    PIDS+=($!)
}

start_airport() {
    local code="KJFK" dur="$DURATION" extra_args=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --airport-code)    code="$2"; shift 2 ;;
            --duration)        dur="$2"; shift 2 ;;
            *)                 extra_args+=("$1"); shift ;;
        esac
    done
    echo "Starting Airport $code (duration=${dur}s)..."
    "$PYTHON" "$PYTHON_DIR/app_airport.py" \
        --config "$SCENARIO_CONFIG" --qos-file "$PROJECT_DIR/air_traffic_qos.xml" \
        --airport-code "$code" --duration "$dur" "${extra_args[@]}" &
    PIDS+=($!)
}

start_tower() {
    local code="KJFK" dur="$DURATION" extra_args=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --airport-code)    code="$2"; shift 2 ;;
            --duration)        dur="$2"; shift 2 ;;
            *)                 extra_args+=("$1"); shift ;;
        esac
    done
    echo "Starting Tower $code (duration=${dur}s)..."
    "$PYTHON" "$PYTHON_DIR/app_tower.py" \
        --config "$SCENARIO_CONFIG" --qos-file "$PROJECT_DIR/air_traffic_qos.xml" \
        --airport-code "$code" --duration "$dur" "${extra_args[@]}" &
    PIDS+=($!)
}

start_center() {
    local cid="ZNY" dur="$DURATION" extra_args=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --center-id) cid="$2"; shift 2 ;;
            --duration)  dur="$2"; shift 2 ;;
            *)           extra_args+=("$1"); shift ;;
        esac
    done
    echo "Starting Center $cid (duration=${dur}s)..."
    "$PYTHON" "$PYTHON_DIR/app_center.py" \
        --config "$SCENARIO_CONFIG" --qos-file "$PROJECT_DIR/air_traffic_qos.xml" \
        --center-id "$cid" --duration "$dur" "${extra_args[@]}" &
    PIDS+=($!)
}

start_airplane() {
    local callsign="AAL123" dur="$DURATION" extra_args=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --callsign)     callsign="$2"; shift 2 ;;
            --duration)     dur="$2"; shift 2 ;;
            *)              extra_args+=("$1"); shift ;;
        esac
    done
    echo "Starting Aircraft $callsign (duration=${dur}s)..."
    "$PYTHON" "$PYTHON_DIR/app_airplane.py" \
        --config "$SCENARIO_CONFIG" --qos-file "$PROJECT_DIR/air_traffic_qos.xml" \
        --callsign "$callsign" --duration "$dur" "${extra_args[@]}" &
    PIDS+=($!)
}

start_tracon() {
    local tid="N90" dur="$DURATION" extra_args=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --tracon-id)       tid="$2"; shift 2 ;;
            --duration)        dur="$2"; shift 2 ;;
            *)                 extra_args+=("$1"); shift ;;
        esac
    done
    echo "Starting TRACON $tid (duration=${dur}s)..."
    "$PYTHON" "$PYTHON_DIR/app_tracon.py" \
        --config "$SCENARIO_CONFIG" --qos-file "$PROJECT_DIR/air_traffic_qos.xml" \
        --tracon-id "$tid" --duration "$dur" "${extra_args[@]}" &
    PIDS+=($!)
}

start_dashboard() {
    local port="8050"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --port) port="$2"; shift 2 ;;
            *) shift ;;
        esac
    done
    echo "Starting Dashboard (Flask on http://localhost:${port})..."
    "$PYTHON" "$PYTHON_DIR/app_dashboard.py" --config "$SCENARIO_CONFIG" --qos-file "$PROJECT_DIR/air_traffic_qos.xml" --port "$port" &
    PIDS+=($!)
}

start_weather() {
    local dur="$DURATION" spawn_interval="30" max_cells="5"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --duration)        dur="$2"; shift 2 ;;
            --spawn-interval)  spawn_interval="$2"; shift 2 ;;
            --max-cells)       max_cells="$2"; shift 2 ;;
            *) shift ;;
        esac
    done
    echo "Starting Weather Service (spawn=${spawn_interval}s, max=${max_cells}, duration=${dur}s)..."
    "$PYTHON" "$PYTHON_DIR/app_weather_service.py" \
        --config "$SCENARIO_CONFIG" --qos-file "$PROJECT_DIR/air_traffic_qos.xml" \
        --duration "$dur" --spawn-interval "$spawn_interval" --max-cells "$max_cells" &
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

    # Query a single field from scenario config
    scenario_query() { "$PYTHON" "$SCRIPT_DIR/demo_cli.py" "$SCENARIO_CONFIG" "$1"; }

    local SCENARIO_NAME=$(scenario_query scenario)
    local CONFIG_DURATION=$(scenario_query duration)
    local AIRPORT_CODES=$(scenario_query airports)
    local TRACON_IDS=$(scenario_query tracons)
    local CENTER_IDS=$(scenario_query centers)
    local CALLSIGNS=$(scenario_query aircraft)

    if [[ -z "$DURATION" ]]; then
        DURATION="$CONFIG_DURATION"
    fi

    echo "============================================"
    echo "  $SCENARIO_NAME"
    echo "  Config: $(basename "$SCENARIO_CONFIG")"
    echo "  Duration: ${DURATION}s"
    echo "============================================"
    echo ""

    # 1. Flight Plan Service
    start_flightplan
    sleep 1

    # 2. Airports
    for code in $AIRPORT_CODES; do
        start_airport --airport-code "$code"
    done
    sleep 1

    # 3. Control Towers — one per airport
    for code in $AIRPORT_CODES; do
        start_tower --airport-code "$code"
    done
    sleep 1

    # 4. TRACONs
    for tid in $TRACON_IDS; do
        start_tracon --tracon-id "$tid"
    done
    sleep 1

    # 5. En-Route Centers
    for cid in $CENTER_IDS; do
        start_center --center-id "$cid"
    done
    sleep 1

    # 6. Weather Service
    start_weather
    sleep 1

    # 7. Aircraft
    for cs in $CALLSIGNS; do
        start_airplane --callsign "$cs"
        sleep 0.3
    done

    # 8. Dashboard
    sleep 2
    start_dashboard

    echo ""
    echo "=== All processes launched. Running for ${DURATION}s ==="
}

# ── Main dispatch ───────────────────────────────────────────────────────────

CMD="${1:-help}"
shift || true

case "$CMD" in
    all)         start_all "$@";               wait_for_procs ;;
    flightplan)  start_flightplan "$@";         wait_for_procs ;;
    airport)     start_airport "$@";            wait_for_procs ;;
    tower)       start_tower "$@";              wait_for_procs ;;
    tracon)      start_tracon "$@";             wait_for_procs ;;
    center)      start_center "$@";             wait_for_procs ;;
    airplane)    start_airplane "$@";           wait_for_procs ;;
    dashboard)   start_dashboard "$@";          wait_for_procs ;;
    weather)     start_weather "$@";            wait_for_procs ;;
    help|-h|--help) usage ;;
    *) echo "Unknown command: $CMD"; echo "Run '$0 help' for usage."; exit 1 ;;
esac
