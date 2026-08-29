#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Real-Time Innovations, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Docker entrypoint for the ATC demo.
#
# Pass .env.local with --env-file. For DDS, also mount your RTI license file
# into the container at /tmp/rti_license.dat.
#
# Usage:
#   docker run --env-file .env.local -v ./rti_license.dat:/tmp/rti_license.dat -p 8050:8050 atc-demo dds
#   docker run --env-file .env.local -p 8050:8050 atc-demo grpc
#   docker run --env-file .env.local -v ./rti_license.dat:/tmp/rti_license.dat -p 8050:8050 atc-demo dds dashboard
#   docker run --env-file .env.local -p 8050:8050 atc-demo grpc dashboard
set -euo pipefail

# ── Select implementation ─────────────────────────────────────────────────
IMPLEMENTATION="${ATC_IMPLEMENTATION:-dds}"
case "${1:-}" in
    dds|grpc)
        IMPLEMENTATION="$1"
        shift
        ;;
esac

case "$IMPLEMENTATION" in
    dds)
        # Prefer the standard container mount. This intentionally replaces a
        # host-only RTI_LICENSE_FILE path loaded from .env.local.
        if [[ -f /tmp/rti_license.dat ]]; then
            export RTI_LICENSE_FILE=/tmp/rti_license.dat
        elif [[ -z "${RTI_LICENSE_FILE:-}" ]]; then
            echo "ERROR: RTI license file not found."
            echo "  Mount it with: -v ./rti_license.dat:/tmp/rti_license.dat"
            exit 1
        fi
        LAUNCHER=/app/connext_dds/scripts/demo_start.sh
        ;;
    grpc)
        LAUNCHER=/app/grpc/scripts/demo_start.sh
        ;;
    *)
        echo "ERROR: Unknown implementation '$IMPLEMENTATION'; use 'dds' or 'grpc'."
        exit 1
        ;;
esac

# ── Delegate to the selected launcher ─────────────────────────────────────
export PYTHON="${PYTHON:-$(command -v python3)}"
exec "$LAUNCHER" "$@"
