#!/usr/bin/env bash
#
# stop_scenario.sh — Stop all running ATC demo applications.
#
# Usage:
#   ./stop_collectorsh
#
set -uo pipefail

APP_PATTERNS=(
    "rticollectorservicelite"
)

killed=0

for pattern in "${APP_PATTERNS[@]}"; do
    pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    if [[ -n "$pids" ]]; then
        for pid in $pids; do
            echo "Stopping $pattern (PID $pid)..."
            kill "$pid" 2>/dev/null || true
            ((killed++))
        done
    fi
done

if (( killed == 0 )); then
    echo "No running rticollectorservice processes found."
else
    echo "Stopped $killed rticollectorservice process(es)."
fi
