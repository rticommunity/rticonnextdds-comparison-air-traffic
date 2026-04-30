"""
ATC Web Dashboard — Flask + SSE + Leaflet.js real-time map.

Full-screen dark map with animated aircraft icons, flight trails,
airport markers with weather popups, route lines, and a collapsible
data panel.

Run with:
    python dashboard.py [--port 8050]
"""

import argparse
import json
import os
import sys
import threading
import time
from collections import defaultdict, deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, Response, render_template_string, request

import rti.connextdds as dds
from air_traffic import NationalAirTrafficControl as ATC

AircraftPosition = ATC.AircraftPosition
Alert = ATC.Alert
ControllerInstruction = ATC.ControllerInstruction
FlightPlan = ATC.FlightPlan
Handoff = ATC.Handoff
PilotAcknowledgment = ATC.PilotAcknowledgment
RunwayStatus = ATC.RunwayStatus
WeatherReport = ATC.WeatherReport
from common import (
    create_participant,
    create_subscriber,
    load_qos_provider,
    reader_qos,
)

# ── Topic → (type, qos profile) ────────────────────────────────────────────

TOPIC_MAP = {
    "AircraftPosition": (AircraftPosition, "PositionReportingProfile"),
    "ControllerInstruction": (ControllerInstruction, "ReliableCommandProfile"),
    "PilotAcknowledgment": (PilotAcknowledgment, "ReliableCommandProfile"),
    "FlightPlan": (FlightPlan, "StateDataProfile"),
    "RunwayStatus": (RunwayStatus, "StateDataProfile"),
    "WeatherReport": (WeatherReport, "StateDataProfile"),
    "Handoff": (Handoff, "HandoffProfile"),
    "Alert": (Alert, "AlertBroadcastProfile"),
}

MAX_EVENTS = 100
MAX_TRAIL_POINTS = 60  # ~60s of trail at 1 position/sec

# ── Load scenario config for airspace boundaries ───────────────────────────

_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "scenario_default.json"
)
with open(_CONFIG_PATH) as _f:
    _scenario_cfg = json.load(_f)

_centers_js = json.dumps([
    {"id": c["id"], "name": c["name"], "boundary": c["boundary"]}
    for c in _scenario_cfg["centers"] if "boundary" in c
])
_tracons_js = json.dumps([
    {"id": t["id"], "name": t["name"],
     "lat": t["center_lat"], "lon": t["center_lon"], "radius_nm": t["radius_nm"]}
    for t in _scenario_cfg["tracons"] if "center_lat" in t
])

_airports_js = json.dumps({
    a["code"]: {"lat": a["latitude"], "lon": a["longitude"], "name": a["name"]}
    for a in _scenario_cfg["airports"]
})

# ── Shared state (written by DDS thread, read by SSE) ──────────────────────

state_lock = threading.Lock()
state = {
    "positions": {},
    "trails": defaultdict(lambda: deque(maxlen=MAX_TRAIL_POINTS)),
    "weather": {},
    "runways": {},
    "flight_plans": {},
    "alerts": [],
    "handoffs": [],
    "instructions": [],
    "acks": [],
    "events": [],
    "counters": defaultdict(int),
}


# ── DDS → dict helpers ─────────────────────────────────────────────────────

def position_dict(s):
    return {
        "tail_number": s.tail_number, "callsign": s.callsign,
        "lat": round(s.position.latitude, 4),
        "lon": round(s.position.longitude, 4),
        "alt_ft": int(s.position.altitude_feet),
        "speed_kt": int(s.ground_speed_knots),
        "heading": int(s.heading_degrees),
        "phase": s.flight_phase.name,
        "origin": s.origin_airport, "dest": s.destination_airport,
        "fuel_pct": int(s.fuel_level_percent),
    }

def weather_dict(s):
    return {
        "airport": s.airport_code, "condition": s.conditions.name,
        "wind": f"{s.wind.direction_degrees:03d}\u00b0/{s.wind.speed_knots:.0f}kt",
        "vis_m": int(s.visibility_meters), "ceiling_ft": s.ceiling_feet,
        "temp_c": round(s.temperature_celsius, 1),
        "altimeter_hpa": round(s.altimeter_hpa, 1),
    }

def runway_dict(s):
    return {
        "airport": s.airport_code, "runway": s.runway_id,
        "status": s.status.name, "remarks": s.remarks or "",
    }

def flightplan_dict(s):
    wpts = []
    for w in s.waypoints:
        wpts.append({
            "name": w.name,
            "lat": round(w.position.latitude, 4),
            "lon": round(w.position.longitude, 4),
        })
    return {
        "plan_id": s.flight_plan_id, "tail_number": s.tail_number,
        "callsign": s.callsign, "from": s.departure_airport,
        "to": s.arrival_airport, "status": s.status.name,
        "waypoints": wpts,
    }

def alert_dict(s):
    return {
        "alert_id": s.alert_id, "type": s.alert_type.name,
        "severity": s.severity.name,
        "aircraft": ", ".join(s.involved_aircraft) if s.involved_aircraft else "",
        "airport": s.airport_code or "", "message": s.message,
    }

def handoff_dict(s):
    from_type = ""
    to_type = ""
    if s.from_facility_type is not None:
        from_type = s.from_facility_type.name
    if s.to_facility_type is not None:
        to_type = s.to_facility_type.name
    return {
        "handoff_id": s.handoff_id, "tail_number": s.tail_number,
        "from": s.from_controller_id, "to": s.to_controller_id,
        "status": s.status.name,
        "from_facility": from_type, "to_facility": to_type,
    }

def instruction_dict(s):
    return {
        "instruction_id": s.instruction_id, "controller": s.controller_id,
        "tail_number": s.tail_number, "type": s.instruction_type.name,
    }

def ack_dict(s):
    return {
        "ack_id": s.acknowledgment_id, "tail_number": s.tail_number,
        "instruction_id": s.instruction_id, "status": s.status.name,
    }


# ── DDS polling thread ─────────────────────────────────────────────────────

def dds_poll_loop(readers, interval=0.25):
    """Background thread: take samples and update shared state."""
    while True:
        with state_lock:
            for topic_name, rdr in readers.items():
                for sample in rdr.take_data():
                    state["counters"][topic_name] += 1
                    if topic_name == "AircraftPosition":
                        state["positions"][sample.tail_number] = position_dict(sample)
                        state["trails"][sample.tail_number].append(
                            [round(sample.position.latitude, 4),
                             round(sample.position.longitude, 4)]
                        )
                        _event(f"\u2708\ufe0f {sample.callsign} "
                               f"{sample.flight_phase.name} "
                               f"FL{int(sample.position.altitude_feet/100):03d} "
                               f"{int(sample.ground_speed_knots)}kt")
                    elif topic_name == "WeatherReport":
                        state["weather"][sample.airport_code] = weather_dict(sample)
                        _event(f"\U0001f324 {sample.airport_code} "
                               f"{sample.conditions.name} vis {int(sample.visibility_meters)}m")
                    elif topic_name == "RunwayStatus":
                        key = f"{sample.airport_code}/{sample.runway_id}"
                        state["runways"][key] = runway_dict(sample)
                        _event(f"\U0001f6ec {key} \u2192 {sample.status.name}")
                    elif topic_name == "FlightPlan":
                        state["flight_plans"][sample.flight_plan_id] = flightplan_dict(sample)
                        _event(f"\U0001f4cb FP {sample.flight_plan_id} "
                               f"{sample.departure_airport}\u2192{sample.arrival_airport} "
                               f"{sample.status.name}")
                    elif topic_name == "Alert":
                        state["alerts"].append(alert_dict(sample))
                        _event(f"\U0001f6a8 {sample.severity.name} "
                               f"{sample.alert_type.name}: {sample.message}")
                    elif topic_name == "Handoff":
                        state["handoffs"].append(handoff_dict(sample))
                        ft = ""
                        if sample.from_facility_type is not None and sample.to_facility_type is not None:
                            ft = f" [{sample.from_facility_type.name}→{sample.to_facility_type.name}]"
                        _event(f"\U0001f504 Handoff {sample.tail_number} "
                               f"{sample.from_controller_id}→{sample.to_controller_id}{ft}")
                    elif topic_name == "ControllerInstruction":
                        state["instructions"].append(instruction_dict(sample))
                        _event(f"\U0001f4e1 Instr \u2192 {sample.tail_number} "
                               f"{sample.instruction_type.name}")
                    elif topic_name == "PilotAcknowledgment":
                        state["acks"].append(ack_dict(sample))
                        _event(f"\u2705 ACK {sample.tail_number} {sample.status.name}")
        time.sleep(interval)


def _event(text):
    state["events"].insert(0, text)
    if len(state["events"]) > MAX_EVENTS:
        state["events"] = state["events"][:MAX_EVENTS]


# ── Flask app ───────────────────────────────────────────────────────────────

app = Flask(__name__)


def _snapshot():
    """Return a JSON-serialisable snapshot of the current state."""
    with state_lock:
        trails = {aid: list(pts) for aid, pts in state["trails"].items()}
        return {
            "positions": list(state["positions"].values()),
            "trails": trails,
            "weather": list(state["weather"].values()),
            "runways": list(state["runways"].values()),
            "flight_plans": list(state["flight_plans"].values()),
            "alerts": state["alerts"][-20:],
            "events": state["events"][:50],
            "counters": dict(state["counters"]),
            "kpi": {
                "aircraft": len(state["positions"]),
                "flight_plans": len(state["flight_plans"]),
                "airports": len(state["weather"]),
                "total_alerts": len(state["alerts"]),
            },
        }


@app.route("/")
def index():
    return render_template_string(
        HTML_PAGE,
        airports_json=_airports_js,
        centers_json=_centers_js,
        tracons_json=_tracons_js,
    )


@app.route("/speed", methods=["POST"])
def set_speed():
    from common import write_sim_speed, read_sim_speed
    data = request.get_json(silent=True)
    if data and "speed" in data:
        write_sim_speed(float(data["speed"]))
    return {"speed": read_sim_speed()}


@app.route("/speed")
def get_speed():
    from common import read_sim_speed
    return {"speed": read_sim_speed()}


@app.route("/stream")
def stream():
    def generate():
        while True:
            data = json.dumps(_snapshot())
            yield f"data: {data}\n\n"
            time.sleep(1.0)
    return Response(generate(), mimetype="text/event-stream")


# ── Inline HTML / CSS / JS ──────────────────────────────────────────────────

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ATC Dashboard</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root {
  --bg: #0f1117; --surface: #1a1d27; --surface2: #232736; --border: #2d3140;
  --text: #e0e0e0; --dim: #888; --accent: #4ea8de;
  --green: #4caf50; --yellow: #ff9800; --red: #f44336; --cyan: #00e5ff;
  --panel-w: 380px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       background: var(--bg); color: var(--text); overflow: hidden; height: 100vh; }

/* ── Full-screen map ─────────────────────────────────────────────────── */
#map { position: absolute; top: 0; left: 0; right: 0; bottom: 0; z-index: 0;
       background: #0a0c12; }
.leaflet-container { background: #0a0c12 !important; }

/* ── Top bar (KPIs) ──────────────────────────────────────────────────── */
#topbar {
  position: absolute; top: 0; left: 0; right: 0; z-index: 1000;
  display: flex; align-items: center; gap: 0;
  background: linear-gradient(180deg, rgba(15,17,23,0.95) 60%, rgba(15,17,23,0));
  padding: 10px 16px 20px 16px; pointer-events: none;
}
#topbar > * { pointer-events: auto; }
.logo { font-size: 1.15rem; font-weight: 700; white-space: nowrap; margin-right: 24px; }
.logo span { color: var(--accent); }
.kpi-row { display: flex; gap: 10px; flex-wrap: wrap; }
.kpi { background: var(--surface); border: 1px solid var(--border);
       border-radius: 8px; padding: 8px 16px; min-width: 130px; text-align: center; }
.kpi-value { font-size: 1.6rem; font-weight: 700; color: var(--accent); line-height: 1; }
.kpi-label { font-size: 0.7rem; color: var(--dim); margin-top: 2px; text-transform: uppercase;
             letter-spacing: 0.5px; }
.speed-control {
  display: flex; align-items: center; gap: 8px; margin-left: auto; margin-right: 80px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 6px 14px; white-space: nowrap;
}
.speed-control label { font-size: 0.7rem; color: var(--dim); text-transform: uppercase;
                       letter-spacing: 0.5px; }
.speed-control input[type="range"] { width: 100px; accent-color: var(--accent);
                                      cursor: pointer; }
#speed-value { font-size: 1rem; font-weight: 700; color: var(--accent); min-width: 36px;
               text-align: right; }

/* ── Connection status ───────────────────────────────────────────────── */
#status { position: absolute; top: 12px; right: 16px; z-index: 1001;
          font-size: 0.75rem; color: var(--dim); }
#status .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
               background: var(--green); margin-right: 4px; vertical-align: middle; }

/* ── Side panel ──────────────────────────────────────────────────────── */
#panel {
  position: absolute; top: 70px; right: 0; bottom: 0; width: var(--panel-w);
  z-index: 1000; background: rgba(15,17,23,0.92); backdrop-filter: blur(12px);
  border-left: 1px solid var(--border); overflow-y: auto;
  transition: transform 0.3s ease; padding: 12px; padding-bottom: 24px;
}
#panel.collapsed { transform: translateX(100%); }
#panel-toggle {
  position: absolute; top: 76px; z-index: 1001;
  right: var(--panel-w); width: 28px; height: 60px;
  background: rgba(15,17,23,0.85); border: 1px solid var(--border);
  border-right: none; border-radius: 6px 0 0 6px; cursor: pointer;
  color: var(--dim); font-size: 1rem; display: flex; align-items: center;
  justify-content: center; transition: right 0.3s ease;
}
#panel-toggle.collapsed { right: 0; }
#panel-toggle:hover { background: var(--surface); color: var(--text); }

/* Panel sections */
.section { margin-bottom: 14px; }
.section-hdr { font-size: 0.8rem; font-weight: 700; text-transform: uppercase;
               letter-spacing: 0.6px; color: var(--accent); margin-bottom: 6px;
               display: flex; align-items: center; gap: 6px; }
.section-hdr .badge { background: var(--accent); color: #000; border-radius: 10px;
                      padding: 0 7px; font-size: 0.7rem; font-weight: 700; }

/* Tables */
table { width: 100%; border-collapse: collapse; font-size: 0.75rem; }
th { background: var(--surface2); color: var(--dim); text-align: left;
     padding: 4px 6px; position: sticky; top: 0; }
td { padding: 3px 6px; border-bottom: 1px solid var(--border); white-space: nowrap; }
tr:hover td { background: rgba(78,168,222,0.08); cursor: pointer; }
tr.selected td { background: rgba(78,168,222,0.18); }
.table-wrap { max-height: 180px; overflow-y: auto; border: 1px solid var(--border);
              border-radius: 6px; }

/* Phase badge */
.phase { display: inline-block; padding: 1px 5px; border-radius: 3px;
         font-size: 0.68rem; font-weight: 600; color: #fff; }
.phase-PREFLIGHT, .phase-PARKED   { background:#555; }
.phase-TAXI_OUT, .phase-TAXI_IN   { background:#6a5acd; }
.phase-TAKEOFF                    { background:#2196f3; }
.phase-CLIMB                      { background:#03a9f4; }
.phase-CRUISE                     { background:#00bcd4; }
.phase-DESCENT                    { background:#ff9800; }
.phase-APPROACH                   { background:#ff5722; }
.phase-LANDING                    { background:#f44336; }
.phase-HOLDING                    { background:#9c27b0; }

/* Runway status */
.rwy-OPEN     { color: var(--green); font-weight: 600; }
.rwy-CLOSED   { color: var(--red); font-weight: 600; }
.rwy-OCCUPIED { color: var(--yellow); font-weight: 600; }

/* Alerts */
.alert-card { padding: 6px 8px; border-radius: 5px; margin-bottom: 5px; font-size: 0.75rem; }
.alert-CRITICAL { background: rgba(244,67,54,0.18); border-left: 3px solid var(--red); }
.alert-WARNING  { background: rgba(255,152,0,0.15); border-left: 3px solid var(--yellow); }
.alert-CAUTION  { background: rgba(255,152,0,0.10); border-left: 3px solid var(--yellow); }
.alert-INFO     { background: rgba(78,168,222,0.10); border-left: 3px solid var(--accent); }

/* Event feed */
#events { max-height: 180px; overflow-y: auto; font-size: 0.72rem;
          background: var(--surface); border: 1px solid var(--border);
          border-radius: 6px; padding: 6px; }
.ev { padding: 2px 0; border-bottom: 1px solid rgba(45,49,64,0.5); }

/* Counters */
.counters td { padding: 1px 6px; border: none; font-size: 0.72rem; }
.counters td:last-child { text-align: right; font-family: monospace; color: var(--accent); }

.empty { color: var(--dim); font-style: italic; padding: 8px; text-align: center; font-size: 0.78rem; }

/* ── Aircraft label on map ───────────────────────────────────────────── */
.aircraft-label {
  background: rgba(15,17,23,0.85); color: #fff; padding: 2px 6px;
  border-radius: 4px; font-size: 11px; font-weight: 600; white-space: nowrap;
  border: 1px solid rgba(78,168,222,0.4); pointer-events: none;
}

/* ── Airport icon on map ─────────────────────────────────────────────── */
.airport-icon {
  background: var(--surface); border: 2px solid var(--accent); border-radius: 50%;
  width: 28px; height: 28px; display: flex; align-items: center; justify-content: center;
  font-size: 14px; box-shadow: 0 0 10px rgba(78,168,222,0.4);
}
.airspace-tooltip {
  background: rgba(30,30,40,0.9) !important; color: #e0e0e0 !important;
  border: 1px solid rgba(255,255,255,0.2) !important; border-radius: 4px !important;
  font-size: 11px !important; padding: 3px 7px !important;
  box-shadow: 0 2px 8px rgba(0,0,0,0.4) !important;
}
.leaflet-control-layers {
  background: var(--surface) !important; color: var(--text) !important;
  border: 1px solid var(--border) !important; border-radius: 6px !important;
}
.leaflet-control-layers label { color: var(--text) !important; }
.leaflet-interactive:focus { outline: none !important; }

/* Leaflet popup override for dark theme */
.leaflet-popup-content-wrapper {
  background: var(--surface) !important; color: var(--text) !important;
  border-radius: 8px !important; border: 1px solid var(--border) !important;
  box-shadow: 0 4px 20px rgba(0,0,0,0.5) !important;
}
.leaflet-popup-tip { background: var(--surface) !important; }
.leaflet-popup-content { font-size: 0.8rem !important; line-height: 1.5 !important; }
.leaflet-popup-content strong { color: var(--accent); }

/* Highlight pulse animation for selected aircraft */
@keyframes pulse-ring {
  0% { opacity: 1; stroke-width: 3; }
  50% { opacity: 0.4; stroke-width: 5; }
  100% { opacity: 1; stroke-width: 3; }
}
.highlight-pulse { animation: pulse-ring 1.2s ease-in-out infinite; }
.waypoint-tooltip {
  background: rgba(0,229,255,0.85); color: #000; font-size: 10px; font-weight: 700;
  border: none; border-radius: 3px; padding: 1px 4px; box-shadow: 0 1px 4px rgba(0,0,0,0.5);
}
.waypoint-tooltip::before { border-top-color: rgba(0,229,255,0.85) !important; }
</style>
</head>
<body>

<!-- Top bar with KPIs -->
<div id="topbar">
  <div class="logo">&#9992;&#65039; <span>ATC</span> Dashboard</div>
  <div class="kpi-row">
    <div class="kpi"><div class="kpi-value" id="kpi-aircraft">0</div><div class="kpi-label">Aircraft</div></div>
    <div class="kpi"><div class="kpi-value" id="kpi-fp">0</div><div class="kpi-label">Flight Plans</div></div>
    <div class="kpi"><div class="kpi-value" id="kpi-airports">0</div><div class="kpi-label">Airports</div></div>
    <div class="kpi"><div class="kpi-value" id="kpi-alerts">0</div><div class="kpi-label">Alerts</div></div>
  </div>
  <div class="speed-control">
    <label for="speed-slider">Speed</label>
    <input type="range" id="speed-slider" min="0.1" max="20" step="0.1" value="1">
    <span id="speed-value">1x</span>
  </div>
</div>
<div id="status"><span class="dot"></span>Connected</div>

<!-- Map -->
<div id="map"></div>

<!-- Side panel toggle -->
<button id="panel-toggle" onclick="togglePanel()">&lsaquo;</button>

<!-- Side panel -->
<div id="panel">
  <!-- Aircraft table -->
  <div class="section">
    <div class="section-hdr">Aircraft <span class="badge" id="ac-count">0</span></div>
    <div class="table-wrap">
      <table><thead><tr><th>Callsign</th><th>Tail</th><th>Phase</th><th>Alt</th><th>Spd</th><th>Fuel</th><th>Lat</th><th>Lon</th></tr></thead>
      <tbody id="ac-body"></tbody></table>
    </div>
  </div>

  <!-- Weather -->
  <div class="section">
    <div class="section-hdr">Weather</div>
    <div class="table-wrap">
      <table><thead><tr><th>Airport</th><th>Cond</th><th>Wind</th><th>Vis</th><th>Ceil</th></tr></thead>
      <tbody id="wx-body"></tbody></table>
    </div>
  </div>

  <!-- Runways -->
  <div class="section">
    <div class="section-hdr">Runways</div>
    <div class="table-wrap">
      <table><thead><tr><th>Airport</th><th>Rwy</th><th>Status</th></tr></thead>
      <tbody id="rwy-body"></tbody></table>
    </div>
  </div>

  <!-- Flight Plans -->
  <div class="section">
    <div class="section-hdr">Flight Plans <span class="badge" id="fp-count">0</span></div>
    <div class="table-wrap">
      <table><thead><tr><th>Callsign</th><th>Route</th><th>Wpts</th><th>Status</th></tr></thead>
      <tbody id="fp-body"></tbody></table>
    </div>
  </div>

  <!-- Alerts -->
  <div class="section">
    <div class="section-hdr">&#128680; Alerts <span class="badge" id="alert-count">0</span></div>
    <div id="alerts-box"></div>
  </div>

  <!-- Event feed -->
  <div class="section">
    <div class="section-hdr">Live Feed</div>
    <div id="events"></div>
  </div>

  <!-- Counters -->
  <div class="section">
    <div class="section-hdr">DDS Samples</div>
    <table class="counters" id="counters-table"></table>
  </div>
</div>

<script>
/* ── Known airports (injected from scenario config) ──────────────── */
var AIRPORTS = {{ airports_json | safe }};

/* ── Phase colours ───────────────────────────────────────────────── */
var PHASE_COLOR = {
  PREFLIGHT: "#888", PARKED: "#888",
  TAXI_OUT: "#6a5acd", TAXI_IN: "#6a5acd",
  TAKEOFF: "#2196f3", CLIMB: "#03a9f4", CRUISE: "#00bcd4",
  DESCENT: "#ff9800", APPROACH: "#ff5722", LANDING: "#f44336",
  HOLDING: "#9c27b0"
};

/* ── Leaflet map setup ───────────────────────────────────────────── */
var map = L.map("map", {
  center: [38.5, -96],
  zoom: 5,
  zoomControl: false,
  attributionControl: false
});

L.control.zoom({ position: "bottomleft" }).addTo(map);
L.control.attribution({ position: "bottomleft", prefix: false }).addTo(map);

// CartoDB dark tiles — free, no API key
L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
  subdomains: "abcd",
  maxZoom: 19
}).addTo(map);

/* ── Airspace boundaries (injected from scenario config) ──────────── */
var CENTERS = {{ centers_json | safe }};
var TRACONS = {{ tracons_json | safe }};

var NM_TO_METERS = 1852;

// Layer groups for toggling
var centerLayer = L.layerGroup();
var traconLayer = L.layerGroup();

CENTERS.forEach(function(c) {
  var poly = L.polygon(c.boundary, {
    color: "#4fc3f7", weight: 1.5, opacity: 0.6,
    fillColor: "#4fc3f7", fillOpacity: 0.04,
    dashArray: "6 4", bubblingMouseEvents: false
  });
  poly.bindTooltip(c.id + " — " + c.name, { sticky: true, className: "airspace-tooltip" });
  poly.on('click', function(e) { L.DomEvent.stopPropagation(e); });
  centerLayer.addLayer(poly);
});

TRACONS.forEach(function(t) {
  var circle = L.circle([t.lat, t.lon], {
    radius: t.radius_nm * NM_TO_METERS,
    color: "#ffb74d", weight: 1.5, opacity: 0.7,
    fillColor: "#ffb74d", fillOpacity: 0.06,
    dashArray: "4 3"
  });
  circle.bindTooltip(t.id + " — " + t.name, { sticky: true, className: "airspace-tooltip" });
  traconLayer.addLayer(circle);
});

centerLayer.addTo(map);
traconLayer.addTo(map);

L.control.layers(null, {
  "ARTCC (Centers)": centerLayer,
  "TRACON": traconLayer
}, { position: "bottomleft", collapsed: false }).addTo(map);

/* ── Airport markers (created dynamically when seen in data) ─────── */
var airportMarkers = {};
function ensureAirportMarker(code) {
  if (airportMarkers[code]) return;
  var a = AIRPORTS[code];
  if (!a) return;
  var icon = L.divIcon({
    className: "",
    html: '<div class="airport-icon">&#9992;</div>',
    iconSize: [28, 28],
    iconAnchor: [14, 14]
  });
  var m = L.marker([a.lat, a.lon], { icon: icon, zIndexOffset: -100 }).addTo(map);
  m.bindPopup("<strong>" + code + "</strong><br>" + a.name + "<br><span id='wx-popup-" + code + "' style='color:#888'></span>");
  airportMarkers[code] = m;
}

/* ── Aircraft SVG icon factory ───────────────────────────────────── */
function aircraftSvg(heading, color) {
  var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">' +
    '<g transform="rotate(' + heading + ' 16 16)">' +
    '<path d="M16 4 L19 14 L28 18 L19 19 L18 28 L16 24 L14 28 L13 19 L4 18 L13 14 Z" ' +
    'fill="' + color + '" stroke="#000" stroke-width="0.5" opacity="0.95"/>' +
    '</g></svg>';
  return 'data:image/svg+xml;base64,' + btoa(svg);
}

function makeAircraftIcon(heading, phase) {
  var color = PHASE_COLOR[phase] || "#4ea8de";
  return L.icon({
    iconUrl: aircraftSvg(heading, color),
    iconSize: [32, 32],
    iconAnchor: [16, 16]
  });
}

/* ── Map layer groups ────────────────────────────────────────────── */
var aircraftMarkers = {};   // tail_number → L.marker
var aircraftLabels = {};    // tail_number → L.marker (tooltip label)
var trailLines = {};        // tail_number → L.polyline
var routeLines = {};        // origin-dest key → L.polyline
var highlightCircle = null; // pulsing ring for selected aircraft
var waypointLayer = null;   // L.layerGroup for selected aircraft waypoints
var selectedAircraftId = null;
var lastPositions = [];     // cache for click lookup
var lastFlightPlans = [];   // cache for waypoint lookup

/* ── Panel toggle ────────────────────────────────────────────────── */
function togglePanel() {
  var p = document.getElementById("panel");
  var t = document.getElementById("panel-toggle");
  p.classList.toggle("collapsed");
  t.classList.toggle("collapsed");
  t.innerHTML = p.classList.contains("collapsed") ? "&rsaquo;" : "&lsaquo;";
  setTimeout(function() { map.invalidateSize(); }, 350);
}

/* ── Waypoint route helpers ───────────────────────────────────────── */
function clearWaypointRoute() {
  if (waypointLayer) { map.removeLayer(waypointLayer); waypointLayer = null; }
}

function showWaypointRoute(aircraftId) {
  clearWaypointRoute();
  var fp = lastFlightPlans.find(function(f) { return f.tail_number === aircraftId; });
  if (!fp || !fp.waypoints || fp.waypoints.length < 1) return;
  waypointLayer = L.layerGroup().addTo(map);
  var coords = fp.waypoints.map(function(w) { return [w.lat, w.lon]; });
  // Polyline through waypoints
  L.polyline(coords, {
    color: "#00e5ff", weight: 2.5, opacity: 0.8, dashArray: "6 4"
  }).addTo(waypointLayer);
  // Dot at each waypoint with name tooltip
  fp.waypoints.forEach(function(w) {
    L.circleMarker([w.lat, w.lon], {
      radius: 5, color: "#00e5ff", fillColor: "#00e5ff",
      fillOpacity: 0.9, weight: 1
    }).bindTooltip(w.name, {
      permanent: true, direction: "top", offset: [0, -8],
      className: "waypoint-tooltip"
    }).addTo(waypointLayer);
  });
}

/* ── Select aircraft ──────────────────────────────────────────────── */
function highlightTableRows(aircraftId) {
  // Highlight matching rows in aircraft and flight-plan tables
  ["ac-body", "fp-body"].forEach(function(tbId) {
    var rows = document.getElementById(tbId).querySelectorAll("tr");
    rows.forEach(function(tr) {
      // onclick contains the tail_number string
      var match = tr.getAttribute("onclick");
      if (match && match.indexOf(aircraftId) !== -1) {
        tr.classList.add("selected");
      } else {
        tr.classList.remove("selected");
      }
    });
  });
}

function selectAircraft(aircraftId) {
  if (selectedAircraftId === aircraftId) {
    selectedAircraftId = null;
    if (highlightCircle) { map.removeLayer(highlightCircle); highlightCircle = null; }
    clearWaypointRoute();
    highlightTableRows("");
    return;
  }
  selectedAircraftId = aircraftId;
  highlightTableRows(aircraftId);
  var ac = lastPositions.find(function(a) { return a.tail_number === aircraftId; });
  if (!ac) return;
  var ll = [ac.lat, ac.lon];
  if (highlightCircle) map.removeLayer(highlightCircle);
  highlightCircle = L.circleMarker(ll, {
    radius: 22, color: "#00e5ff", weight: 3, fill: false,
    opacity: 0.9, className: "highlight-pulse"
  }).addTo(map);
  showWaypointRoute(aircraftId);
  map.panTo(ll, { animate: true, duration: 0.5 });
  if (aircraftMarkers[aircraftId]) aircraftMarkers[aircraftId].openPopup();
}

/* ── Render helpers ──────────────────────────────────────────────── */
function renderAircraft(positions, trails) {
  var seen = {};
  positions.forEach(function(ac) {
    seen[ac.tail_number] = true;
    var ll = [ac.lat, ac.lon];
    var color = PHASE_COLOR[ac.phase] || "#4ea8de";

    // Ensure origin/dest airport markers exist
    ensureAirportMarker(ac.origin);
    ensureAirportMarker(ac.dest);

    // Marker
    if (aircraftMarkers[ac.tail_number]) {
      aircraftMarkers[ac.tail_number].setLatLng(ll);
      aircraftMarkers[ac.tail_number].setIcon(makeAircraftIcon(ac.heading, ac.phase));
    } else {
      var m = L.marker(ll, { icon: makeAircraftIcon(ac.heading, ac.phase), zIndexOffset: 200 }).addTo(map);
      m.bindPopup("");
      (function(aid) { m.on("click", function() { selectAircraft(aid); }); })(ac.tail_number);
      aircraftMarkers[ac.tail_number] = m;
    }
    // Update popup lazily
    aircraftMarkers[ac.tail_number].getPopup().setContent(
      "<strong>" + ac.callsign + "</strong> (" + ac.tail_number + ")<br>" +
      '<span class="phase phase-' + ac.phase + '">' + ac.phase + "</span><br>" +
      "Alt: " + ac.alt_ft.toLocaleString() + " ft &bull; " + ac.speed_kt + " kt<br>" +
      "Hdg: " + ac.heading + "&deg; &bull; Fuel: " + ac.fuel_pct + "%<br>" +
      ac.origin + " &rarr; " + ac.dest
    );

    // Callsign label
    if (aircraftLabels[ac.tail_number]) {
      aircraftLabels[ac.tail_number].setLatLng(ll);
    } else {
      var lbl = L.marker(ll, {
        icon: L.divIcon({
          className: "",
          html: '<div class="aircraft-label">' + ac.callsign + '</div>',
          iconSize: [80, 18],
          iconAnchor: [-8, 20]
        }),
        interactive: false, zIndexOffset: 100
      }).addTo(map);
      aircraftLabels[ac.tail_number] = lbl;
    }
    // Update label text (callsign + FL)
    aircraftLabels[ac.tail_number].setIcon(L.divIcon({
      className: "",
      html: '<div class="aircraft-label">' + ac.callsign + ' FL' + String(Math.round(ac.alt_ft/100)).padStart(3,'0') + '</div>',
      iconSize: [110, 18],
      iconAnchor: [-8, 20]
    }));

    // Trail
    var pts = trails[ac.tail_number] || [];
    if (pts.length > 1) {
      if (trailLines[ac.tail_number]) {
        trailLines[ac.tail_number].setLatLngs(pts);
        trailLines[ac.tail_number].setStyle({ color: color });
      } else {
        trailLines[ac.tail_number] = L.polyline(pts, {
          color: color, weight: 2, opacity: 0.5, dashArray: "4 4"
        }).addTo(map);
      }
    }

    // Route line (dashed, dim)
    var rkey = ac.origin + "-" + ac.dest;
    if (!routeLines[rkey] && AIRPORTS[ac.origin] && AIRPORTS[ac.dest]) {
      var o = AIRPORTS[ac.origin], d = AIRPORTS[ac.dest];
      routeLines[rkey] = L.polyline([[o.lat, o.lon], [d.lat, d.lon]], {
        color: "#4ea8de", weight: 1, opacity: 0.2, dashArray: "8 12"
      }).addTo(map);
    }
  });

  // Remove stale markers
  Object.keys(aircraftMarkers).forEach(function(aid) {
    if (!seen[aid]) {
      map.removeLayer(aircraftMarkers[aid]);
      delete aircraftMarkers[aid];
      if (aircraftLabels[aid]) { map.removeLayer(aircraftLabels[aid]); delete aircraftLabels[aid]; }
      if (trailLines[aid]) { map.removeLayer(trailLines[aid]); delete trailLines[aid]; }
    }
  });
}

function updateAirportWeather(wxList) {
  wxList.forEach(function(w) {
    ensureAirportMarker(w.airport);
    var el = document.getElementById("wx-popup-" + w.airport);
    if (el) {
      el.innerHTML = w.condition + "<br>Wind: " + w.wind +
        "<br>Vis: " + w.vis_m + "m &bull; Ceil: " + w.ceiling_ft + "ft" +
        "<br>Temp: " + w.temp_c + "&deg;C &bull; QNH: " + w.altimeter_hpa;
      el.style.color = "#e0e0e0";
    }
    // Tint airport marker border by condition
    if (airportMarkers[w.airport]) {
      var cond = w.condition;
      var borderColor = (cond === "CLEAR" || cond === "FEW") ? "#4caf50" :
                        (cond === "SCATTERED" || cond === "BROKEN") ? "#ff9800" :
                        (cond === "OVERCAST") ? "#f57c00" :
                        (cond === "THUNDERSTORM" || cond === "FOG") ? "#f44336" : "#4ea8de";
      var iconEl = airportMarkers[w.airport].getElement();
      if (iconEl) {
        var inner = iconEl.querySelector('.airport-icon');
        if (inner) inner.style.borderColor = borderColor;
      }
    }
  });
}

function renderTable(bodyId, rows) {
  var el = document.getElementById(bodyId);
  if (!rows.length) { el.innerHTML = '<tr><td colspan="10" class="empty">No data</td></tr>'; return; }
  el.innerHTML = rows;
}

function update(d) {
  // KPIs
  document.getElementById("kpi-aircraft").textContent = d.kpi.aircraft;
  document.getElementById("kpi-fp").textContent = d.kpi.flight_plans;
  document.getElementById("kpi-airports").textContent = d.kpi.airports;
  document.getElementById("kpi-alerts").textContent = d.kpi.total_alerts;

  // Map
  renderAircraft(d.positions, d.trails);
  updateAirportWeather(d.weather);

  // Aircraft table
  lastPositions = d.positions;
  document.getElementById("ac-count").textContent = d.positions.length;
  renderTable("ac-body", d.positions.map(function(ac) {
    var sel = ac.tail_number === selectedAircraftId ? ' class="selected"' : '';
    return '<tr' + sel + ' onclick="selectAircraft(\'' + ac.tail_number + '\')"><td>' + ac.callsign + "</td>" +
           "<td>" + ac.tail_number + "</td>" +
           '<td><span class="phase phase-' + ac.phase + '">' + ac.phase + "</span></td>" +
           "<td>" + ac.alt_ft.toLocaleString() + "</td>" +
           "<td>" + ac.speed_kt + "</td>" +
           "<td>" + ac.fuel_pct + "%</td>" +
           "<td>" + ac.lat.toFixed(2) + "</td>" +
           "<td>" + ac.lon.toFixed(2) + "</td></tr>";
  }).join(""));

  // Update highlight circle position if aircraft is selected
  if (selectedAircraftId && highlightCircle) {
    var selAc = d.positions.find(function(a) { return a.tail_number === selectedAircraftId; });
    if (selAc) highlightCircle.setLatLng([selAc.lat, selAc.lon]);
    else { map.removeLayer(highlightCircle); highlightCircle = null; selectedAircraftId = null; }
  }

  // Weather table
  renderTable("wx-body", d.weather.map(function(w) {
    return "<tr><td>" + w.airport + "</td><td>" + w.condition + "</td>" +
           "<td>" + w.wind + "</td><td>" + w.vis_m + "</td><td>" + w.ceiling_ft + "</td></tr>";
  }).join(""));

  // Runway table
  renderTable("rwy-body", d.runways.map(function(r) {
    return "<tr><td>" + r.airport + "</td><td>" + r.runway + "</td>" +
           '<td><span class="rwy-' + r.status + '">' + r.status + "</span></td></tr>";
  }).join(""));

  // Flight plans table
  lastFlightPlans = d.flight_plans;
  document.getElementById("fp-count").textContent = d.flight_plans.length;
  renderTable("fp-body", d.flight_plans.map(function(fp) {
    var sel = fp.tail_number === selectedAircraftId ? ' class="selected"' : '';
    return '<tr' + sel + ' onclick="selectAircraft(\'' + fp.tail_number + '\')"><td>' + fp.callsign + "</td>" +
           "<td>" + fp["from"] + "&rarr;" + fp["to"] + "</td>" +
           "<td>" + fp.waypoints.length + " wpts</td>" +
           "<td>" + fp.status + "</td></tr>";
  }).join(""));
  // Refresh waypoint route if selected aircraft's plan updated
  if (selectedAircraftId) showWaypointRoute(selectedAircraftId);

  // Alerts
  document.getElementById("alert-count").textContent = d.alerts.length;
  var ab = document.getElementById("alerts-box");
  if (d.alerts.length) {
    ab.innerHTML = d.alerts.map(function(a) {
      return '<div class="alert-card alert-' + a.severity + '"><strong>' + a.type +
             "</strong> &mdash; " + a.message + (a.aircraft ? " (" + a.aircraft + ")" : "") + "</div>";
    }).join("");
  } else { ab.innerHTML = '<div class="empty">No alerts</div>'; }

  // Events
  var ev = document.getElementById("events");
  if (d.events.length) {
    ev.innerHTML = d.events.map(function(e) { return '<div class="ev">' + e + "</div>"; }).join("");
  } else { ev.innerHTML = '<div class="empty">Waiting for DDS data&hellip;</div>'; }

  // Counters
  var ct = document.getElementById("counters-table");
  var names = ["AircraftPosition","ControllerInstruction","PilotAcknowledgment",
               "FlightPlan","RunwayStatus","WeatherReport","Handoff","Alert"];
  ct.innerHTML = names.map(function(n) {
    return "<tr><td>" + n + "</td><td>" + (d.counters[n] || 0) + "</td></tr>";
  }).join("");
}

/* ── SSE connection ──────────────────────────────────────────────── */
var es = new EventSource("/stream");
es.onmessage = function(e) {
  try { update(JSON.parse(e.data)); } catch(err) { console.error(err); }
};
es.onerror = function() {
  document.querySelector("#status .dot").style.background = "#f44336";
  document.querySelector("#status").childNodes[1].textContent = " Reconnecting\u2026";
};
es.onopen = function() {
  document.querySelector("#status .dot").style.background = "#4caf50";
  document.querySelector("#status").childNodes[1].textContent = " Connected";
};

/* ── Speed slider ────────────────────────────────────────────────── */
var speedSlider = document.getElementById("speed-slider");
var speedLabel = document.getElementById("speed-value");
// Load current speed on startup
fetch("/speed").then(function(r) { return r.json(); }).then(function(d) {
  speedSlider.value = d.speed;
  speedLabel.textContent = d.speed + "x";
});
var speedTimeout = null;
speedSlider.addEventListener("input", function() {
  var v = parseFloat(this.value);
  speedLabel.textContent = (v < 10 ? v.toFixed(1) : Math.round(v)) + "x";
  clearTimeout(speedTimeout);
  speedTimeout = setTimeout(function() {
    fetch("/speed", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({speed: v})
    });
  }, 100);
});
</script>
</body>
</html>"""


# ── Main ────────────────────────────────────────────────────────────────────

def init_dds():
    qos_provider = load_qos_provider()
    dp_partitions = ["OPS/*"]
    participant = create_participant(qos_provider, dp_partitions=dp_partitions)
    subscriber = create_subscriber(participant)
    readers = {}
    for topic_name, (type_cls, profile) in TOPIC_MAP.items():
        topic = dds.Topic(participant, topic_name, type_cls)
        readers[topic_name] = dds.DataReader(
            subscriber, topic,
            reader_qos(qos_provider, profile),
        )
    return readers


def main():
    parser = argparse.ArgumentParser(description="ATC Web Dashboard")
    parser.add_argument("--port", type=int, default=8050, help="HTTP port")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    args = parser.parse_args()

    readers = init_dds()
    t = threading.Thread(target=dds_poll_loop, args=(readers,), daemon=True)
    t.start()

    print(f"Dashboard running at http://localhost:{args.port}")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
