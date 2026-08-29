#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Real-Time Innovations, Inc.
# SPDX-License-Identifier: Apache-2.0
# ────────────────────────────────────────────────────────────────────────────
# types_generate.sh — Generate Python type-support from IDL using rtiddsgen
# ────────────────────────────────────────────────────────────────────────────
#
# Usage:
#   ./types_generate.sh
#
# Requires:
#   NDDSHOME set (or defaults to /Applications/rti_connext_dds-7.7.0)
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

echo "Generating Python types from: $IDL_FILE"
echo "Output directory: $OUTPUT_DIR"
echo "Using rtiddsgen: $RTIDDSGEN"

"$RTIDDSGEN" \
    -language Python \
    -d "$OUTPUT_DIR" \
    -replace \
    "$IDL_FILE"

echo ""
echo "Generated: $OUTPUT_DIR/air_traffic_types.py"
echo "Done."
