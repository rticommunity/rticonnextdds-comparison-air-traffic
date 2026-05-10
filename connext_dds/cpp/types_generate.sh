#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────────────
# types_generate.sh — Generate C++11 type-support from IDL using rtiddsgen
# ────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="$SCRIPT_DIR"

NDDSHOME="${NDDSHOME:-/Applications/rti_connext_dds-7.7.0}"
RTIDDSGEN="$NDDSHOME/bin/rtiddsgen"

if [[ ! -x "$RTIDDSGEN" ]]; then
    echo "ERROR: rtiddsgen not found at $RTIDDSGEN"
    echo "Set NDDSHOME to your Connext installation directory."
    exit 1
fi

IDL_FILE="$PROJECT_DIR/air_traffic_types.idl"
if [[ ! -f "$IDL_FILE" ]]; then
    echo "ERROR: IDL file not found: $IDL_FILE"
    exit 1
fi

echo "Generating C++11 types from: $IDL_FILE"
echo "Output directory: $OUTPUT_DIR"

"$RTIDDSGEN" \
    -language C++11 \
    -d "$OUTPUT_DIR" \
    -replace \
    "$IDL_FILE"

echo "Done."
