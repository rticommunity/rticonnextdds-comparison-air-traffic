"""Print a single scenario field as a space-separated string.

Usage:  python scenario_cli.py <config.json> <key>

Keys:
    scenario       - Scenario name
    duration       - Duration in seconds
    airports       - Space-separated airport codes
    tracons        - Space-separated TRACON IDs
    centers        - Space-separated center IDs
    aircraft       - Space-separated callsigns
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))

from common import load_scenario_info

if len(sys.argv) < 3:
    print(f"Usage: {sys.argv[0]} <config.json> <key>", file=sys.stderr)
    sys.exit(1)

config_path = sys.argv[1]
key = sys.argv[2]

info = load_scenario_info(config_path)

if key == "scenario":
    print(info["scenario"])
elif key == "duration":
    print(info["duration_seconds"])
elif key in ("airports", "tracons", "centers", "aircraft"):
    print(" ".join(info[key]))
else:
    print(f"Unknown key: {key}", file=sys.stderr)
    sys.exit(1)
