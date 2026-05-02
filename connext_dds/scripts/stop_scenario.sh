#!/usr/bin/env bash
#
# stop_scenario.sh — Stop running ATC demo applications.
#
# Usage:
#   ./stop_scenario.sh                  # stop all apps
#   ./stop_scenario.sh dashboard        # stop only the dashboard
#   ./stop_scenario.sh airplane         # stop only airplanes
#   ./stop_scenario.sh center           # stop all centers
#   ./stop_scenario.sh center ZNY       # stop only center ZNY
#   ./stop_scenario.sh tower KJFK       # stop only the KJFK tower
#   ./stop_scenario.sh center tower     # stop all centers and towers
#
set -uo pipefail

declare -A APP_MAP=(
    [flightplan]="flightplan_service/flightplan_service.py"
    [airport]="airport_app/airport.py"
    [tower]="tower_app/tower.py"
    [tracon]="tracon_app/tracon.py"
    [center]="center_app/center.py"
    [airplane]="airplane_app/airplane.py"
    [dashboard]="dashboard_app/dashboard.py"
)

# Build list of (pattern, instance_filter) pairs
searches=()

if (( $# > 0 )); then
    while (( $# > 0 )); do
        key="${1,,}"  # lowercase
        if [[ -z "${APP_MAP[$key]+_}" ]]; then
            echo "Unknown app: $1 (valid: ${!APP_MAP[*]})"
            exit 1
        fi
        pattern="${APP_MAP[$key]}"
        shift
        # Check if next arg is an instance ID (not an app name)
        instance=""
        if (( $# > 0 )); then
            next="${1,,}"
            if [[ -z "${APP_MAP[$next]+_}" ]]; then
                instance="$1"
                shift
            fi
        fi
        searches+=("$pattern|$instance")
    done
else
    for pattern in "${APP_MAP[@]}"; do
        searches+=("$pattern|")
    done
fi

killed=0

for entry in "${searches[@]}"; do
    pattern="${entry%%|*}"
    instance="${entry#*|}"
    if [[ -n "$instance" ]]; then
        # Match processes whose command line contains both the script and the instance ID
        pids=$(pgrep -f "$pattern" 2>/dev/null | while read -r pid; do
            if ps -p "$pid" -o args= 2>/dev/null | grep -q "$instance"; then
                echo "$pid"
            fi
        done)
    else
        pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    fi
    if [[ -n "$pids" ]]; then
        for pid in $pids; do
            cmdline=$(ps -p "$pid" -o args= 2>/dev/null || true)
            echo "Stopping PID $pid: $cmdline"
            kill "$pid" 2>/dev/null || true
            ((killed++))
        done
    fi
done

if (( killed == 0 )); then
    echo "No matching ATC demo processes found."
else
    echo "Stopped $killed process(es)."
fi
