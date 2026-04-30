#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────────────
# generate_types.sh — Generate Python type-support from IDL using rtiddsgen
# ────────────────────────────────────────────────────────────────────────────
#
# Usage:
#   ./scripts/generate_types.sh
#
# Requires:
#   NDDSHOME set (or defaults to /Applications/rti_connext_dds-7.7.0)
# ────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
IDL_DIR="$PROJECT_DIR/idl"
SRC_DIR="$PROJECT_DIR/src"

NDDSHOME="${NDDSHOME:-/Applications/rti_connext_dds-7.7.0}"
RTIDDSGEN="$NDDSHOME/bin/rtiddsgen"

if [[ ! -x "$RTIDDSGEN" ]]; then
    echo "ERROR: rtiddsgen not found at $RTIDDSGEN"
    echo "Set NDDSHOME to your Connext installation directory."
    exit 1
fi

IDL_FILE="$IDL_DIR/air_traffic.idl"
if [[ ! -f "$IDL_FILE" ]]; then
    echo "ERROR: IDL file not found: $IDL_FILE"
    exit 1
fi

echo "Generating Python types from: $IDL_FILE"
echo "Output directory: $SRC_DIR"
echo "Using rtiddsgen: $RTIDDSGEN"

"$RTIDDSGEN" \
    -language Python \
    -d "$SRC_DIR" \
    -replace \
    "$IDL_FILE"

echo ""
echo "Generated: $SRC_DIR/air_traffic.py"
echo "Done."
