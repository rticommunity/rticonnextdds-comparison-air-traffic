#!/usr/bin/env bash
#
# stop_scenario.sh — Stop all running ATC demo applications.
#
# Usage:
#   ./stop_scenario.sh
#
set -uo pipefail

APP_PATTERNS=(
    "flightplan_service/flightplan_service.py"
    "airport_app/airport.py"
    "tower_app/tower.py"
    "tracon_app/tracon.py"
    "center_app/center.py"
    "airplane_app/airplane.py"
    "dashboard_app/dashboard.py"
)

killed=0

for pattern in "${APP_PATTERNS[@]}"; do
    pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    if [[ -n "$pids" ]]; then
        for pid in $pids; do
            echo "Stopping $(basename "$pattern" .py) (PID $pid)..."
            kill "$pid" 2>/dev/null || true
            ((killed++))
        done
    fi
done

if (( killed == 0 )); then
    echo "No running ATC demo processes found."
else
    echo "Stopped $killed process(es)."
fi
