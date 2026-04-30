#!/usr/bin/env bash
#
# setup_env.sh — Create a project-local Python virtual environment and install
#                all dependencies for the ATC DDS demo.
#
# Usage:
#   ./setup_env.sh
#
# The virtual environment is created at venv
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
VENV_DIR="$PROJECT_DIR/venv"
REQUIREMENTS="$PROJECT_DIR/requirements.txt"

# ── Connext installation path ───────────────────────────────────────────────
CONNEXT_HOME="${CONNEXT_HOME:-/Applications/rti_connext_dds-7.7.0}"
WHEEL_DIR="$CONNEXT_HOME/resource/python_api"

if [[ ! -d "$CONNEXT_HOME" ]]; then
    echo "ERROR: RTI Connext DDS not found at $CONNEXT_HOME"
    echo "       Set CONNEXT_HOME to your installation directory."
    exit 1
fi

# ── Determine Python version ───────────────────────────────────────────────
PYTHON="${PYTHON:-python3}"
PY_VERSION=$("$PYTHON" -c "import sys; print(f'cp{sys.version_info.major}{sys.version_info.minor}')")
echo "Python: $("$PYTHON" --version)  (tag: $PY_VERSION)"

# ── Find the matching wheel ────────────────────────────────────────────────
WHEEL=$(find "$WHEEL_DIR" -name "rti_connext-*-${PY_VERSION}-*.whl" 2>/dev/null | head -1)
if [[ -z "$WHEEL" ]]; then
    echo "ERROR: No rti_connext wheel found for $PY_VERSION in $WHEEL_DIR"
    echo "       Available wheels:"
    ls "$WHEEL_DIR"/*.whl 2>/dev/null || echo "       (none)"
    exit 1
fi
echo "Connext wheel: $(basename "$WHEEL")"

# ── Create virtual environment ──────────────────────────────────────────────
if [[ -d "$VENV_DIR" ]]; then
    echo "Virtual environment already exists at $VENV_DIR"
    echo "To recreate, remove it first:  rm -rf $VENV_DIR"
else
    echo "Creating virtual environment at $VENV_DIR ..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

# ── Activate and install ───────────────────────────────────────────────────
source "$VENV_DIR/bin/activate"

echo "Upgrading pip..."
pip install --upgrade pip --quiet

echo "Installing requirements..."
pip install -r "$REQUIREMENTS" --quiet

echo "Installing RTI Connext Python API..."
pip install "$WHEEL" --quiet

echo ""
echo "============================================"
echo "  Environment ready!"
echo "  Activate with:  source $VENV_DIR/bin/activate"
echo "============================================"
