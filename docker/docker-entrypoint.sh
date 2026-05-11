#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Real-Time Innovations, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Docker entrypoint for the ATC demo.
#
# Mount your RTI license file into the container at /tmp/rti_license.dat.
#
# Usage:
#   docker run -v ./rti_license.dat:/tmp/rti_license.dat -p 8050:8050 atc-demo
#   docker run -v ./rti_license.dat:/tmp/rti_license.dat -p 8050:8050 atc-demo dashboard
set -euo pipefail

# ── Verify license file ────────────────────────────────────────────────────
if [[ -z "${RTI_LICENSE_FILE:-}" ]]; then
    if [[ -f /tmp/rti_license.dat ]]; then
        export RTI_LICENSE_FILE=/tmp/rti_license.dat
    else
        echo "ERROR: RTI license file not found."
        echo "  Mount it with: -v ./rti_license.dat:/tmp/rti_license.dat"
        exit 1
    fi
fi

# ── Delegate to demo_start.sh ──────────────────────────────────────────────
export PYTHON="${PYTHON:-$(command -v python3)}"
exec /app/connext_dds/scripts/demo_start.sh "$@"
