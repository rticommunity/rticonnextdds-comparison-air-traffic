# SPDX-FileCopyrightText: 2026 Real-Time Innovations, Inc.
# SPDX-License-Identifier: Apache-2.0
# ── Connext license ────────────────────────────────────────────────────────
export NDDSHOME="${NDDSHOME:-/Applications/rti_connext_dds-7.7.0}"
export RTI_LICENSE_FILE="${RTI_LICENSE_FILE:-$NDDSHOME/rti_license.dat}"
echo "Starting rticollectorservice..."
echo "Connect at  ws://localhost:19098/rti/collector_service/v1/observables"
${NDDSHOME}/bin/rticollectorservicelite -cfgName NonSecureRemoteDebuggingLAN -verbosity 4
