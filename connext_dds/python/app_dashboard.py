# SPDX-FileCopyrightText: 2026 Real-Time Innovations, Inc.
# SPDX-License-Identifier: Apache-2.0
"""
ATC Web Dashboard — Flask + SSE + Leaflet.js real-time map.

Full-screen dark map with animated aircraft icons, flight trails,
airport markers with weather popups, route lines, and a collapsible
data panel.

Run with:
    python dashboard.py [--port 8050]
"""

import argparse
import atexit
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections import defaultdict, deque


from flask import Flask, Response, render_template_string, request

import rti.connextdds as dds
from air_traffic_types import NationalAirTrafficControl as ATC

AircraftPosition = ATC.AircraftPosition
Alert = ATC.Alert
ControllerInstruction = ATC.ControllerInstruction
ConvectiveCell = ATC.ConvectiveCell
ConvectiveSeverity = ATC.ConvectiveSeverity
FlightPlan = ATC.FlightPlan
Handoff = ATC.Handoff
PilotAcknowledgment = ATC.PilotAcknowledgment
RunwayStatus = ATC.RunwayStatus
WeatherReport = ATC.WeatherReport
AircraftTracking = ATC.AircraftTracking
FacilityStatus = ATC.FacilityStatus
from common import (
    create_participant,
    create_publisher,
    create_subscriber,
    load_qos_provider,
    make_id,
    now_ms,
    reader_qos,
    writer_qos,
)
import common

# ── Topic → (type, qos profile) ────────────────────────────────────────────

TOPIC_MAP = {
    "AircraftPosition": (AircraftPosition, "AircraftPositionProfile"),
    "ControllerInstruction": (ControllerInstruction, "ControllerInstructionProfile"),
    "PilotAcknowledgment": (PilotAcknowledgment, "PilotAcknowledgmentProfile"),
    "FlightPlan": (FlightPlan, "FlightPlanProfile"),
    "RunwayStatus": (RunwayStatus, "RunwayStatusProfile"),
    "WeatherReport": (WeatherReport, "WeatherReportProfile"),
    "Handoff": (Handoff, "HandoffProfile"),
    "Alert": (Alert, "AlertProfile"),
    "AircraftTracking": (AircraftTracking, "AircraftTrackingProfile"),
    "FacilityStatus": (FacilityStatus, "FacilityStatusProfile"),
    "ConvectiveCell": (ConvectiveCell, "ConvectiveCellProfile"),
}

MAX_TRAIL_POINTS = 60  # ~60s of trail at 1 position/sec

# ── Scenario config (loaded lazily in main) ────────────────────────────────

_centers_js = '[]'
_tracons_js = '[]'
_airports_js = '{}'

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
    "counters": defaultdict(int),
    "tracking": {},
    "handoff_log": deque(maxlen=50),
    "pending_pulses": [],
    "facility_status": {},  # facility_id → {facility_id, facility_type, status, tracked}
    "convective_cells": {},  # cell_id → {cell_id, lat, lon, radius_nm, severity, ...}
}

# publication_handle → facility_id  (built from FacilityStatus samples)
_pub_to_facility: dict = {}

# ── Spawned aircraft processes ──────────────────────────────────────────────

_spawned_procs: dict[str, subprocess.Popen] = {}  # callsign → Popen
_spawned_lock = threading.Lock()

# ── Dashboard-injected weather cells ────────────────────────────────────────
_injected_cells: set[str] = set()          # cell_ids we published
_cell_cancel: dict[str, threading.Event] = {}  # cell_id → cancel event
_cell_lock = threading.Lock()

_AIRPLANE_SCRIPT = os.path.join(
    os.path.dirname(__file__), "app_airplane.py"
)
_AIRPORT_CODES = []  # populated in main()


def _cleanup_spawned():
    """Kill all spawned aircraft subprocesses."""
    with _spawned_lock:
        for cs, proc in _spawned_procs.items():
            try:
                proc.terminate()
            except OSError:
                pass
        _spawned_procs.clear()


atexit.register(_cleanup_spawned)


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
        "nav_status": s.nav_status.name if s.nav_status is not None else "NORMAL",
        "gate": s.assigned_gate or "",
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
        "ts": s.timestamp,
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
        "ts": s.initiated_at,
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


def tracking_dict(s):
    return {
        "tail_number": s.tail_number,
        "controller_id": s.controller_id,
        "facility_id": s.facility_id,
        "facility_type": s.facility_type.name,
    }


def convective_cell_dict(s):
    return {
        "cell_id": s.cell_id,
        "lat": round(s.center_latitude, 4),
        "lon": round(s.center_longitude, 4),
        "radius_nm": round(s.radius_nm, 1),
        "top_alt": s.top_altitude_ft,
        "base_alt": s.base_altitude_ft,
        "severity": s.severity.name,
        "heading": round(s.movement_heading_deg, 1),
        "speed_kt": round(s.movement_speed_knots, 1),
    }


# ── DDS polling thread ─────────────────────────────────────────────────────

def dds_poll_loop(readers, interval=0.25):
    """Background thread: take samples and update shared state."""
    facility_reader = readers["FacilityStatus"]
    cell_reader = readers["ConvectiveCell"]
    while True:
        with state_lock:
            for topic_name, rdr in readers.items():
                if topic_name in ("FacilityStatus", "ConvectiveCell"):
                    continue  # handled separately below
                for sample in rdr.take_data():
                    state["counters"][topic_name] += 1
                    if topic_name == "AircraftPosition":
                        state["positions"][sample.tail_number] = position_dict(sample)
                        state["trails"][sample.tail_number].append(
                            [round(sample.position.latitude, 4),
                             round(sample.position.longitude, 4)]
                        )
                    elif topic_name == "WeatherReport":
                        state["weather"][sample.airport_code] = weather_dict(sample)
                    elif topic_name == "RunwayStatus":
                        key = f"{sample.airport_code}/{sample.runway_id}"
                        state["runways"][key] = runway_dict(sample)
                    elif topic_name == "FlightPlan":
                        state["flight_plans"][sample.flight_plan_id] = flightplan_dict(sample)
                    elif topic_name == "Alert":
                        state["alerts"].append(alert_dict(sample))
                    elif topic_name == "Handoff":
                        hd = handoff_dict(sample)
                        state["handoffs"].append(hd)
                        state["handoff_log"].append(hd)
                        if sample.status == ATC.HandoffStatus.ACCEPTED and sample.to_facility_type is not None:
                            if sample.to_facility_type == ATC.FacilityType.CENTER:
                                state["pending_pulses"].append(
                                    sample.to_controller_id.replace("CTR-", "", 1))
                    elif topic_name == "ControllerInstruction":
                        state["instructions"].append(instruction_dict(sample))
                    elif topic_name == "PilotAcknowledgment":
                        state["acks"].append(ack_dict(sample))
                    elif topic_name == "AircraftTracking":
                        state["tracking"][sample.tail_number] = tracking_dict(sample)

            # FacilityStatus: use take() to capture publication_handle
            # and instance_state for liveliness detection
            for sample in facility_reader.take():
                fid = None
                if sample.info.valid:
                    data = sample.data
                    state["counters"]["FacilityStatus"] += 1
                    fid = data.facility_id
                    _pub_to_facility[sample.info.publication_handle] = fid
                    state["facility_status"][fid] = {
                        "facility_id": fid,
                        "facility_type": data.facility_type.name,
                        "status": "ONLINE",
                        "tracked": data.tracked_aircraft_count,
                    }
                else:
                    # Invalid sample — writer liveliness lost or instance disposed
                    fid = _pub_to_facility.get(sample.info.publication_handle)

                # Check instance state for NOT_ALIVE
                if fid and fid in state["facility_status"]:
                    ist = sample.info.state.instance_state
                    if ist != dds.InstanceState.ALIVE:
                        state["facility_status"][fid]["status"] = "OFFLINE"

            # ConvectiveCell: use take() to detect disposed cells (dissipated)
            for sample in cell_reader.take():
                if sample.info.valid:
                    data = sample.data
                    state["counters"]["ConvectiveCell"] += 1
                    state["convective_cells"][data.cell_id] = convective_cell_dict(data)
                else:
                    # Disposed or not-alive — remove cell from map
                    ist = sample.info.state.instance_state
                    if ist != dds.InstanceState.ALIVE:
                        ih = sample.info.instance_handle
                        to_remove = [
                            cid for cid in state["convective_cells"]
                            if cell_reader.lookup_instance(
                                ConvectiveCell(cell_id=cid)) == ih
                        ]
                        for cid in to_remove:
                            del state["convective_cells"][cid]
        time.sleep(interval)


# ── Flask app ───────────────────────────────────────────────────────────────

app = Flask(__name__)


def _snapshot():
    """Return a JSON-serialisable snapshot of the current state."""
    with state_lock:
        trails = {aid: list(pts) for aid, pts in state["trails"].items()}
        pulses = list(state["pending_pulses"])
        state["pending_pulses"].clear()

        # Facility status — tracked count comes directly from FacilityStatus topic
        facility_status = []
        for fid, fs in state["facility_status"].items():
            facility_status.append({
                "facility_id": fid,
                "facility_type": fs["facility_type"],
                "status": fs["status"],
                "tracked": fs["tracked"],
            })
        # Sort: centers first, then TRACONs, then towers; alphabetically within type
        type_order = {"CENTER": 0, "TRACON": 1, "TOWER": 2, "NATIONAL": 3}
        facility_status.sort(key=lambda f: (type_order.get(f["facility_type"], 9), f["facility_id"]))

        return {
            "positions": list(state["positions"].values()),
            "trails": trails,
            "weather": list(state["weather"].values()),
            "flight_plans": list(state["flight_plans"].values()),
            "alerts": state["alerts"][-200:],
            "counters": dict(state["counters"]),
            "tracking": dict(state["tracking"]),
            "handoff_log": list(state["handoff_log"]),
            "pulse_centers": pulses,
            "facility_status": facility_status,
            "convective_cells": [
                {**cc, "injected": cc["cell_id"] in _injected_cells}
                for cc in state["convective_cells"].values()
            ],
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
    from common import set_sim_speed, get_sim_speed, write_sim_speed
    participant = app.config["dds_participant"]
    data = request.get_json(silent=True)
    if data and "speed" in data:
        speed = float(data["speed"])
        set_sim_speed(participant, speed)
        write_sim_speed(speed, app.config["scenario_config"])  # persist for restarts
    return {"speed": get_sim_speed(participant)}


@app.route("/speed")
def get_speed():
    from common import get_sim_speed
    participant = app.config["dds_participant"]
    return {"speed": get_sim_speed(participant)}


@app.route("/airports")
def list_airports():
    return {"airports": _AIRPORT_CODES}


@app.route("/weather_cell", methods=["POST"])
def create_weather_cell():
    """Publish a manually-created ConvectiveCell via DDS."""
    from common import get_sim_speed
    data = request.get_json(silent=True) or {}
    try:
        lat = float(data.get("lat", 0))
        lon = float(data.get("lon", 0))
        radius = float(data.get("radius", 20))
        severity = data.get("severity", "MODERATE").upper()
        top_alt = int(data.get("top_alt", 45000))
        base_alt = int(data.get("base_alt", 5000))
        hdg = float(data.get("heading", 0))
        spd = float(data.get("speed", 0))
        duration_min = float(data.get("duration_min", 30))
    except (TypeError, ValueError) as exc:
        return {"error": f"Invalid parameter: {exc}"}, 400

    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return {"error": "lat must be -90..90, lon -180..180"}, 400
    if radius <= 0 or radius > 200:
        return {"error": "radius must be 1..200 nm"}, 400
    if duration_min <= 0 or duration_min > 600:
        return {"error": "duration must be 1..600 sim-minutes"}, 400
    sev_map = {"MODERATE": ConvectiveSeverity.MODERATE,
               "SEVERE": ConvectiveSeverity.SEVERE,
               "EXTREME": ConvectiveSeverity.EXTREME}
    if severity not in sev_map:
        return {"error": f"severity must be one of {list(sev_map)}"}, 400

    cell_id = make_id("WX-")
    sample = ConvectiveCell(
        cell_id=cell_id,
        center_latitude=lat,
        center_longitude=lon,
        radius_nm=radius,
        top_altitude_ft=top_alt,
        base_altitude_ft=base_alt,
        severity=sev_map[severity],
        movement_heading_deg=hdg,
        movement_speed_knots=spd,
        observation_time=now_ms(),
    )
    wx_writer = app.config["wx_writer"]
    wx_writer.write(sample)

    cancel_evt = threading.Event()
    with _cell_lock:
        _injected_cells.add(cell_id)
        _cell_cancel[cell_id] = cancel_evt

    # Schedule dispose after duration_min sim-minutes
    participant = app.config["dds_participant"]
    def _dispose_cell():
        sim_seconds = duration_min * 60
        elapsed = 0.0
        while elapsed < sim_seconds:
            if cancel_evt.is_set():
                return  # manually removed
            spd_mult = max(get_sim_speed(participant), 1)
            time.sleep(1.0)
            elapsed += spd_mult
        if not cancel_evt.is_set():
            ih = wx_writer.lookup_instance(ConvectiveCell(cell_id=cell_id))
            if ih is not None:
                wx_writer.dispose_instance(ih)
        with _cell_lock:
            _injected_cells.discard(cell_id)
            _cell_cancel.pop(cell_id, None)
    threading.Thread(target=_dispose_cell, daemon=True).start()

    return {"cell_id": cell_id, "lat": lat, "lon": lon, "radius": radius,
            "severity": severity, "duration_min": duration_min}


@app.route("/weather_cell/<cell_id>", methods=["DELETE"])
def remove_weather_cell(cell_id):
    """Dispose a dashboard-injected ConvectiveCell."""
    with _cell_lock:
        if cell_id not in _injected_cells:
            return {"error": "Cell not found or not dashboard-injected"}, 404
        evt = _cell_cancel.pop(cell_id, None)
        _injected_cells.discard(cell_id)
    if evt:
        evt.set()  # cancel the timer thread
    wx_writer = app.config["wx_writer"]
    ih = wx_writer.lookup_instance(ConvectiveCell(cell_id=cell_id))
    if ih is not None:
        wx_writer.dispose_instance(ih)
    return {"removed": cell_id}


@app.route("/aircraft", methods=["POST"])
def spawn_aircraft():
    """Spawn a new airplane subprocess on the fly."""
    data = request.get_json(silent=True) or {}
    callsign = data.get("callsign", "").strip().upper()
    origin = data.get("origin", "").strip().upper()
    destination = data.get("destination", "").strip().upper()

    if not callsign or not origin or not destination:
        return {"error": "callsign, origin, and destination are required"}, 400
    if origin == destination:
        return {"error": "origin and destination must differ"}, 400
    if origin not in _AIRPORT_CODES or destination not in _AIRPORT_CODES:
        return {"error": f"unknown airport code"}, 400

    with _spawned_lock:
        if callsign in _spawned_procs:
            proc = _spawned_procs[callsign]
            if proc.poll() is None:
                return {"error": f"{callsign} is already running"}, 409

    python = sys.executable
    cmd = [
        python, _AIRPLANE_SCRIPT,
        "--config", app.config["scenario_config"],
        "--qos-file", common.QOS_FILE,
        "--callsign", callsign,
        "--origin", origin,
        "--destination", destination,
        "--duration", "3600",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    with _spawned_lock:
        _spawned_procs[callsign] = proc

    return {"callsign": callsign, "origin": origin, "destination": destination, "pid": proc.pid}


@app.route("/aircraft")
def list_spawned():
    """List dynamically spawned aircraft and their status."""
    with _spawned_lock:
        result = []
        for cs, proc in _spawned_procs.items():
            result.append({
                "callsign": cs,
                "pid": proc.pid,
                "running": proc.poll() is None,
            })
    return {"spawned": result}


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
#mouse-coords { cursor: pointer; margin-left: 12px; font-family: monospace;
  color: var(--dim); border-left: 1px solid var(--border); padding-left: 10px; }
#mouse-coords:hover { color: var(--accent); }

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
               display: flex; align-items: center; gap: 6px;
               cursor: pointer; user-select: none; }
.section-hdr::before { content: '\25BE'; font-size: 1.1rem; transition: transform 0.15s;
                      min-width: 1rem; text-align: center; }
.section.collapsed .section-hdr::before { transform: rotate(-90deg); }
.section.collapsed .section-body { display: none; }
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
.nav-wx { display:inline-block; padding:1px 4px; border-radius:3px; font-size:0.6rem;
          font-weight:700; background:#ff9800; color:#000; margin-left:4px; animation:wxpulse 1.5s infinite; }
@keyframes wxpulse { 0%,100%{opacity:1} 50%{opacity:0.5} }

/* Alerts */
.alert-card { padding: 6px 8px; border-radius: 5px; margin-bottom: 5px; font-size: 0.75rem; }
.alert-card .ts, .ho .ts { color: var(--dim); font-size: 0.68rem; margin-right: 4px; }
.alert-CRITICAL { background: rgba(244,67,54,0.18); border-left: 3px solid var(--red); }
.alert-WARNING  { background: rgba(255,152,0,0.15); border-left: 3px solid var(--yellow); }
.alert-CAUTION  { background: rgba(255,152,0,0.10); border-left: 3px solid var(--yellow); }
.alert-INFO     { background: rgba(78,168,222,0.10); border-left: 3px solid var(--accent); }
#alerts-box { max-height: 200px; overflow-y: auto; }



/* Counters */
.counters td { padding: 1px 6px; border: none; font-size: 0.72rem; }
.counters td:last-child { text-align: right; font-family: monospace; color: var(--accent); }

/* Facility status */
.fac-table td { padding: 2px 6px; border-bottom: 1px solid var(--border); font-size: 0.72rem; }
.fac-table td:nth-child(3) { text-align: center; }
.fac-table td:nth-child(4) { text-align: right; font-family: monospace; color: var(--accent); }
.fac-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }
.fac-dot-ONLINE  { background: var(--green); box-shadow: 0 0 4px var(--green); }
.fac-dot-OFFLINE { background: var(--red); box-shadow: 0 0 4px var(--red); }
.fac-type { font-size: 0.6rem; color: var(--dim); text-transform: uppercase; }

.empty { color: var(--dim); font-style: italic; padding: 8px; text-align: center; font-size: 0.78rem; }

/* ── Spawn aircraft form ─────────────────────────────────────────── */
.spawn-form { display: flex; flex-direction: column; gap: 6px; }
.form-row { display: flex; align-items: center; gap: 8px; }
.form-row label { font-size: 0.72rem; color: var(--dim); min-width: 70px; text-transform: uppercase;
                  letter-spacing: 0.4px; }
.form-row input, .form-row select {
  flex: 1; background: var(--surface2); color: var(--text); border: 1px solid var(--border);
  border-radius: 4px; padding: 5px 8px; font-size: 0.78rem; font-family: inherit;
}
.form-row input:focus, .form-row select:focus { outline: none; border-color: var(--accent); }
#spawn-btn {
  margin-top: 4px; padding: 6px 0; border: none; border-radius: 5px;
  background: var(--accent); color: #000; font-weight: 700; font-size: 0.8rem;
  cursor: pointer; letter-spacing: 0.4px;
}
#spawn-btn:hover { background: #6bc0f0; }
#spawn-btn:disabled { opacity: 0.5; cursor: not-allowed; }
#spawn-msg { font-size: 0.72rem; min-height: 1.2em; }
#spawn-msg.ok { color: var(--green); }
#spawn-msg.err { color: var(--red); }

/* ── Aircraft label on map ───────────────────────────────────────────── */
.aircraft-label {
  color: #e0e0e0; padding: 1px 3px;
  font-size: 11px; font-weight: 600; white-space: nowrap;
  font-family: "Courier New", Courier, monospace;
  text-shadow: 0 0 4px #000, 0 0 4px #000; pointer-events: none;
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

/* ── Handoff log ───────────────────────────────────────────────────────── */
#handoff-log { max-height: 200px; overflow-y: auto; font-size: 0.72rem;
              background: var(--surface); border: 1px solid var(--border);
              border-radius: 6px; padding: 6px; }
.ho { padding: 3px 0; border-bottom: 1px solid rgba(45,49,64,0.5);
     display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.ho-status { font-size: 0.65rem; font-weight: 700; padding: 1px 5px;
            border-radius: 3px; text-transform: uppercase; }
.ho-INITIATED { background: rgba(78,168,222,0.2); color: var(--accent); }
.ho-ACCEPTED  { background: rgba(76,175,80,0.2); color: var(--green); }
.ho-REJECTED  { background: rgba(244,67,54,0.2); color: var(--red); }
.ho-COMPLETED { background: rgba(0,229,255,0.2); color: var(--cyan); }
.ho-CANCELLED { background: rgba(136,136,136,0.2); color: var(--dim); }
.ho-tail { font-weight: 700; color: var(--text); min-width: 60px; }
.ho-flow { color: var(--dim); font-family: monospace; font-size: 0.68rem; }
.ho-facility { font-size: 0.6rem; color: var(--dim); }

/* ── Weather cell severity colours on map ─────────────────────── */
.wx-cell-tooltip {
  background: rgba(30,30,40,0.92) !important; color: #e0e0e0 !important;
  border: 1px solid rgba(255,100,100,0.4) !important; border-radius: 4px !important;
  font-size: 11px !important; padding: 3px 7px !important;
}

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
    <input type="range" id="speed-slider" min="0.1" max="50" step="0.1" value="1">
    <span id="speed-value">1x</span>
  </div>
</div>
<div id="status"><span class="dot"></span>Connected<span id="mouse-coords" title="Click to fill WX form">---, ---</span></div>

<!-- Map -->
<div id="map"></div>

<!-- Side panel toggle -->
<button id="panel-toggle" onclick="togglePanel()">&lsaquo;</button>

<!-- Side panel -->
<div id="panel">
  <!-- Add Weather Cell -->
  <div class="section collapsed">
    <div class="section-hdr" onclick="toggleSection(this)">&#9928; Add Weather Cell</div>
    <div class="section-body">
    <div class="spawn-form">
      <div class="form-row">
        <label for="wx-lat">Latitude</label>
        <input id="wx-lat" type="number" step="0.1" min="-90" max="90" value="36.0">
      </div>
      <div class="form-row">
        <label for="wx-lon">Longitude</label>
        <input id="wx-lon" type="number" step="0.1" min="-180" max="180" value="-95.0">
      </div>
      <div class="form-row">
        <label for="wx-radius">Radius (nm)</label>
        <input id="wx-radius" type="number" step="1" min="1" max="200" value="20">
      </div>
      <div class="form-row">
        <label for="wx-sev">Severity</label>
        <select id="wx-sev">
          <option value="MODERATE">Moderate</option>
          <option value="SEVERE" selected>Severe</option>
          <option value="EXTREME">Extreme</option>
        </select>
      </div>
      <div class="form-row">
        <label for="wx-hdg">Move Hdg</label>
        <input id="wx-hdg" type="number" step="1" min="0" max="360" value="90">
      </div>
      <div class="form-row">
        <label for="wx-spd">Move Spd (kt)</label>
        <input id="wx-spd" type="number" step="1" min="0" max="100" value="15">
      </div>
      <div class="form-row">
        <label for="wx-dur">Duration (sim-min)</label>
        <input id="wx-dur" type="number" step="5" min="1" max="600" value="30">
      </div>
      <button id="wx-btn" onclick="spawnWeatherCell()">Inject Cell</button>
      <div id="wx-msg"></div>
    </div>
    </div>
  </div>

  <!-- Add Aircraft -->
  <div class="section collapsed">
    <div class="section-hdr" onclick="toggleSection(this)">&#128747; Add Aircraft</div>
    <div class="section-body">
    <div class="spawn-form">
      <div class="form-row">
        <label for="spawn-cs">Callsign</label>
        <input id="spawn-cs" type="text" maxlength="10" placeholder="e.g. UAL999">
      </div>
      <div class="form-row">
        <label for="spawn-orig">Origin</label>
        <select id="spawn-orig"></select>
      </div>
      <div class="form-row">
        <label for="spawn-dest">Destination</label>
        <select id="spawn-dest"></select>
      </div>
      <button id="spawn-btn" onclick="spawnAircraft()">Launch</button>
      <div id="spawn-msg"></div>
    </div>
    </div>
  </div>

  <!-- Aircraft table -->
  <div class="section">
    <div class="section-hdr" onclick="toggleSection(this)">Aircraft <span class="badge" id="ac-count">0</span></div>
    <div class="section-body">
    <div class="table-wrap">
      <table><thead><tr><th>Callsign</th><th>Tail</th><th>Phase</th><th>Alt</th><th>Spd</th><th>Fuel</th><th>Lat</th><th>Lon</th></tr></thead>
      <tbody id="ac-body"></tbody></table>
    </div>
    </div>
  </div>

  <!-- Facility Status -->
  <div class="section">
    <div class="section-hdr" onclick="toggleSection(this)">&#127959;&#65039; Facility Status <span class="badge" id="fac-online">0</span></div>
    <div class="section-body">
    <div class="table-wrap">
      <table class="fac-table"><thead><tr><th>Facility</th><th>Type</th><th>Status</th><th>Flights</th></tr></thead>
      <tbody id="fac-body"></tbody></table>
    </div>
    </div>
  </div>

  <!-- Alerts -->
  <div class="section collapsed">
    <div class="section-hdr" onclick="toggleSection(this)">&#128680; Alerts <span class="badge" id="alert-count">0</span></div>
    <div class="section-body">
    <div id="alerts-box"></div>
    </div>
  </div>

  <!-- Flight Plans -->
  <div class="section collapsed">
    <div class="section-hdr" onclick="toggleSection(this)">Flight Plans <span class="badge" id="fp-count">0</span></div>
    <div class="section-body">
    <div class="table-wrap">
      <table><thead><tr><th>Callsign</th><th>Route</th><th>Wpts</th><th>Status</th></tr></thead>
      <tbody id="fp-body"></tbody></table>
    </div>
    </div>
  </div>

  <!-- Weather -->
  <div class="section collapsed">
    <div class="section-hdr" onclick="toggleSection(this)">Weather</div>
    <div class="section-body">
    <div class="table-wrap">
      <table><thead><tr><th>Airport</th><th>Cond</th><th>Wind</th><th>Vis</th><th>Ceil</th></tr></thead>
      <tbody id="wx-body"></tbody></table>
    </div>
    </div>
  </div>

  <!-- Convective Cells -->
  <div class="section collapsed">
    <div class="section-hdr" onclick="toggleSection(this)">&#9889; Convective Cells <span class="badge" id="cc-count">0</span></div>
    <div class="section-body">
    <div class="table-wrap">
      <table><thead><tr><th>Cell</th><th>Severity</th><th>Radius</th><th>Alt</th><th>Move</th></tr></thead>
      <tbody id="cc-body"></tbody></table>
    </div>
    </div>
  </div>

  <!-- Handoff Log -->
  <div class="section collapsed">
    <div class="section-hdr" onclick="toggleSection(this)">&#128260; Handoff Log <span class="badge" id="ho-count">0</span></div>
    <div class="section-body">
    <div id="handoff-log"><div class="empty">No handoffs yet</div></div>
    </div>
  </div>

  <!-- Message Counts -->
  <div class="section collapsed">
    <div class="section-hdr" onclick="toggleSection(this)">Message Counts <span class="badge" id="msg-total">0</span></div>
    <div class="section-body">
    <table class="counters" id="counters-table"></table>
    </div>
  </div>
</div>

<script>
/* ── Known airports (injected from scenario config) ──────────────── */
var AIRPORTS = {{ airports_json | safe }};

/* ── Timestamp formatter (epoch ms → HH:MM:SS) ──────────────────── */
function fmtTs(ms) {
  if (!ms) return "";
  var d = new Date(ms);
  return d.toTimeString().slice(0, 8);
}

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

// Mouse coordinate display
var _lastMouseLatLng = null;
map.on("mousemove", function(e) {
  _lastMouseLatLng = e.latlng;
  document.getElementById("mouse-coords").textContent =
    e.latlng.lat.toFixed(2) + ", " + e.latlng.lng.toFixed(2);
});
document.getElementById("mouse-coords").addEventListener("click", function() {
  if (_lastMouseLatLng) {
    var latInput = document.getElementById("wx-lat");
    var lonInput = document.getElementById("wx-lon");
    if (latInput) latInput.value = _lastMouseLatLng.lat.toFixed(2);
    if (lonInput) lonInput.value = _lastMouseLatLng.lng.toFixed(2);
  }
});

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

/* ── Center colour palette ─────────────────────────────────────── */
var CENTER_COLORS = {};
var _centerPalette = [
  "#FF6B6B","#4ECDC4","#45B7D1","#96CEB4","#FFEAA7",
  "#DDA0DD","#98D8C8","#F7DC6F","#BB8FCE","#85C1E9",
  "#F8C471","#82E0AA","#F1948A","#AED6F1","#D7BDE2",
  "#A3E4D7","#FAD7A0","#ABEBC6","#D2B4DE","#AEB6BF"
];
CENTERS.forEach(function(c, i) {
  CENTER_COLORS[c.id] = _centerPalette[i % _centerPalette.length];
});

var centerPolygons = {};

CENTERS.forEach(function(c) {
  var color = CENTER_COLORS[c.id] || "#4fc3f7";
  var poly = L.polygon(c.boundary, {
    color: color, weight: 1.5, opacity: 0.6,
    fillColor: color, fillOpacity: 0.04,
    dashArray: "6 4", bubblingMouseEvents: true
  });
  poly.bindTooltip("", { sticky: true, className: "airspace-tooltip" });
  (function(cid, name) {
    poly.on("tooltipopen", function() {
      var aircraft = [];
      Object.keys(lastTracking).forEach(function(tail) {
        if (lastTracking[tail].facility_id === cid) aircraft.push(tail);
      });
      var lines = aircraft.map(function(tail) {
        var ac = lastPositions.find(function(a) { return a.tail_number === tail; });
        return ac ? ac.callsign + " (" + tail + ")" : tail;
      });
      var html = "<strong>" + cid + "</strong> — " + name +
        "<br>Tracking: <strong>" + aircraft.length + "</strong> aircraft";
      if (lines.length > 0) html += "<br><span style='font-size:0.85em'>" + lines.join(", ") + "</span>";
      poly.getTooltip().setContent(html);
    });
  })(c.id, c.name);
  centerLayer.addLayer(poly);
  centerPolygons[c.id] = poly;
});

var traconCircles = {};
TRACONS.forEach(function(t) {
  var circle = L.circle([t.lat, t.lon], {
    radius: t.radius_nm * NM_TO_METERS,
    color: "#ffb74d", weight: 1.5, opacity: 0.7,
    fillColor: "#ffb74d", fillOpacity: 0.06,
    dashArray: "4 3"
  });
  circle.bindTooltip(t.id + " — " + t.name, { sticky: true, className: "airspace-tooltip" });
  traconLayer.addLayer(circle);
  traconCircles[t.id] = circle;
});

centerLayer.addTo(map);
traconLayer.addTo(map);

// Weather cell layer
var weatherLayer = L.layerGroup().addTo(map);
var weatherCircles = {};  // cell_id → L.circle

var WX_SEVERITY_COLOR = {
  MODERATE: { color: "#ff9800", fill: "#ff9800" },
  SEVERE:   { color: "#f44336", fill: "#f44336" },
  EXTREME:  { color: "#d50000", fill: "#d50000" }
};

function renderWeatherCells(cells) {
  var seen = {};
  cells.forEach(function(c) {
    seen[c.cell_id] = true;
    var sc = WX_SEVERITY_COLOR[c.severity] || WX_SEVERITY_COLOR.MODERATE;
    var radiusM = c.radius_nm * NM_TO_METERS;
    if (weatherCircles[c.cell_id]) {
      weatherCircles[c.cell_id].setLatLng([c.lat, c.lon]);
      weatherCircles[c.cell_id].setRadius(radiusM);
      weatherCircles[c.cell_id].setStyle({ color: sc.color, fillColor: sc.fill });
    } else {
      var circle = L.circle([c.lat, c.lon], {
        radius: radiusM, color: sc.color, weight: 2, opacity: 0.7,
        fillColor: sc.fill, fillOpacity: 0.18, dashArray: "4 3"
      });
      circle.bindTooltip(
        "<strong>" + c.severity + "</strong> cell " + c.cell_id +
        "<br>FL" + Math.round(c.base_alt/100) + "-FL" + Math.round(c.top_alt/100) +
        "<br>r=" + c.radius_nm + "nm &bull; " + c.speed_kt + "kt HDG" + Math.round(c.heading),
        { sticky: true, className: "wx-cell-tooltip" }
      );
      circle.bindPopup(
        "<strong>" + c.severity + "</strong> " + c.cell_id +
        "<br>r=" + c.radius_nm + "nm FL" + Math.round(c.base_alt/100) + "-FL" + Math.round(c.top_alt/100) +
        (c.injected ? '<br><button onclick="removeWeatherCell(\'' + c.cell_id + '\')" style="margin-top:4px;padding:3px 10px;' +
        'background:#f44336;color:#fff;border:none;border-radius:3px;cursor:pointer;font-size:12px">Remove Cell</button>' : '')
      );
      weatherLayer.addLayer(circle);
      weatherCircles[c.cell_id] = circle;
    }
  });
  // Remove dissipated cells
  Object.keys(weatherCircles).forEach(function(cid) {
    if (!seen[cid]) {
      weatherLayer.removeLayer(weatherCircles[cid]);
      delete weatherCircles[cid];
    }
  });
}

L.control.layers(null, {
  "ARTCC (Centers)": centerLayer,
  "TRACON": traconLayer,
  "Weather Cells": weatherLayer
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
function toggleAirportPopup(code) {
  ensureAirportMarker(code);
  var m = airportMarkers[code];
  if (!m) return;
  if (m.isPopupOpen()) m.closePopup();
  else m.openPopup();
}

function toggleFacilityPopup(facId, facType) {
  var layer = null;
  if (facType === 'CENTER') layer = centerPolygons[facId];
  else if (facType === 'TRACON') layer = traconCircles[facId];
  else if (facType === 'TOWER') {
    // Tower facility IDs match airport codes
    var code = facId.replace(/^TWR-/, '');
    toggleAirportPopup(code);
    return;
  }
  if (!layer) return;
  if (layer.isPopupOpen()) { layer.closePopup(); return; }
  // Build aircraft list from tracking data
  var aircraft = [];
  Object.keys(lastTracking).forEach(function(tail) {
    if (lastTracking[tail].facility_id === facId) aircraft.push(tail);
  });
  // Find callsigns from lastPositions
  var lines = aircraft.map(function(tail) {
    var ac = lastPositions.find(function(a) { return a.tail_number === tail; });
    return ac ? ac.callsign + ' (' + tail + ')' : tail;
  });
  var nameInfo = '';
  if (facType === 'CENTER') {
    var ci = CENTERS.find(function(c) { return c.id === facId; });
    if (ci) nameInfo = '<br><span style="color:#aaa">' + ci.name + '</span>';
  } else if (facType === 'TRACON') {
    var ti = TRACONS.find(function(t) { return t.id === facId; });
    if (ti) nameInfo = '<br><span style="color:#aaa">' + ti.name + '</span>';
  }
  var html = '<strong>' + facId + '</strong>' + nameInfo +
    '<br>Tracking: <strong>' + aircraft.length + '</strong> aircraft';
  if (lines.length > 0) html += '<br><span style="font-size:0.85em;color:#ccc">' + lines.join('<br>') + '</span>';
  layer.unbindPopup();
  layer.bindPopup(html, { maxHeight: 200 });
  layer.openPopup();
}

function toggleWeatherCellPopup(cellId) {
  var circle = weatherCircles[cellId];
  if (!circle) return;
  if (circle.isPopupOpen()) circle.closePopup();
  else circle.openPopup();
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

function makeAircraftIcon(heading, color) {
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
var lastTracking = {};      // cache for facility popup lookup

/* ── Panel toggle ────────────────────────────────────────────────── */
function togglePanel() {
  var p = document.getElementById("panel");
  var t = document.getElementById("panel-toggle");
  p.classList.toggle("collapsed");
  t.classList.toggle("collapsed");
  t.innerHTML = p.classList.contains("collapsed") ? "&rsaquo;" : "&lsaquo;";
  setTimeout(function() { map.invalidateSize(); }, 350);
}

function toggleSection(hdr) {
  hdr.parentElement.classList.toggle("collapsed");
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

/* ── Center pulse ────────────────────────────────────────────────── */
function pulseCenter(centerId) {
  var poly = centerPolygons[centerId];
  if (!poly) return;
  var c = CENTER_COLORS[centerId] || "#4fc3f7";
  poly.setStyle({ fillColor: c, fillOpacity: 0.30, color: c, weight: 3, opacity: 1.0 });
  setTimeout(function() {
    poly.setStyle({ fillColor: c, fillOpacity: 0.04, color: c, weight: 1.5, opacity: 0.6 });
  }, 1500);
}

/* ── Handoff log renderer ────────────────────────────────────────── */
function renderHandoffLog(entries) {
  var el = document.getElementById("handoff-log");
  document.getElementById("ho-count").textContent = entries.length;
  if (!entries.length) { el.innerHTML = '<div class="empty">No handoffs yet</div>'; return; }
  var rows = entries.slice(-30).reverse().map(function(h) {
    return '<div class="ho">' +
      '<span class="ts">' + fmtTs(h.ts) + '</span>' +
      '<span class="ho-tail">' + h.tail_number + '</span>' +
      '<span class="ho-flow">' + h.from + ' &rarr; ' + h.to + '</span>' +
      '<span class="ho-status ho-' + h.status + '">' + h.status + '</span>' +
      '</div>';
  }).join("");
  el.innerHTML = rows;
}

/* ── Render helpers ──────────────────────────────────────────────── */
function renderAircraft(positions, trails, tracking) {
  var seen = {};
  tracking = tracking || {};
  positions.forEach(function(ac) {
    seen[ac.tail_number] = true;
    var ll = [ac.lat, ac.lon];
    var trk = tracking[ac.tail_number];
    var color;
    if (trk && trk.facility_type === "CENTER" && CENTER_COLORS[trk.facility_id]) {
      color = CENTER_COLORS[trk.facility_id];
    } else if (trk && trk.facility_type === "TRACON") {
      color = "#ffb74d";
    } else if (trk && trk.facility_type === "TOWER") {
      color = "#4caf50";
    } else {
      color = PHASE_COLOR[ac.phase] || "#4ea8de";
    }

    // Ensure origin/dest airport markers exist
    ensureAirportMarker(ac.origin);
    ensureAirportMarker(ac.dest);

    // Marker
    if (aircraftMarkers[ac.tail_number]) {
      aircraftMarkers[ac.tail_number].setLatLng(ll);
      aircraftMarkers[ac.tail_number].setIcon(makeAircraftIcon(ac.heading, color));
    } else {
      var m = L.marker(ll, { icon: makeAircraftIcon(ac.heading, color), zIndexOffset: 200 }).addTo(map);
      m.bindPopup("");
      (function(aid) { m.on("click", function() { selectAircraft(aid); }); })(ac.tail_number);
      aircraftMarkers[ac.tail_number] = m;
    }
    // Update popup lazily
    var ctrlLine = trk ? "<br><strong style='color:" + color + "'>" + trk.controller_id + "</strong> (" + trk.facility_type + ")" : "";
    aircraftMarkers[ac.tail_number].getPopup().setContent(
      "<strong>" + ac.callsign + "</strong> (" + ac.tail_number + ")<br>" +
      '<span class="phase phase-' + ac.phase + '">' + ac.phase + "</span>" + (ac.gate ? ' Gate ' + ac.gate : '') + (ac.nav_status === 'WEATHER_DEVIATION' ? ' <span class="nav-wx">⚡WX DEV</span>' : '') + ctrlLine + "<br>" +
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
    // Update label text (callsign + FL + controller)
    var ctrlTag = '';
    if (trk) {
      if (trk.facility_type === 'CENTER') {
        ctrlTag = ' \u00b7 ' + trk.facility_id;
      } else if (trk.facility_type === 'TRACON') {
        ctrlTag = ' \u00b7 APP-' + trk.facility_id;
      } else if (trk.facility_type === 'TOWER') {
        ctrlTag = ' \u00b7 TWR-' + trk.facility_id;
      } else {
        ctrlTag = ' \u00b7 ' + trk.facility_id;
      }
    }
    var wxBadge = ac.nav_status === 'WEATHER_DEVIATION' ? ' <span class="nav-wx">⚡WX</span>' : '';
    aircraftLabels[ac.tail_number].setIcon(L.divIcon({
      className: "",
      html: '<div class="aircraft-label" style="border-color:' + color + '80">' + ac.callsign + ' FL' + String(Math.round(ac.alt_ft/100)).padStart(3,'0') + ctrlTag + wxBadge + '</div>',
      iconSize: [160, 18],
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
  renderAircraft(d.positions, d.trails, d.tracking);
  updateAirportWeather(d.weather);
  if (d.convective_cells) {
    renderWeatherCells(d.convective_cells);
    document.getElementById("cc-count").textContent = d.convective_cells.length;
    renderTable("cc-body", d.convective_cells.map(function(c) {
      var sc = WX_SEVERITY_COLOR[c.severity] || WX_SEVERITY_COLOR.MODERATE;
      return '<tr onclick="toggleWeatherCellPopup(\'' + c.cell_id + '\')">' +
             '<td>' + c.cell_id + '</td>' +
             '<td><span style="color:' + sc.color + '">' + c.severity + '</span></td>' +
             '<td>' + c.radius_nm + ' nm</td>' +
             '<td>FL' + Math.round(c.base_alt/100) + '-' + Math.round(c.top_alt/100) + '</td>' +
             '<td>' + Math.round(c.heading) + '&deg; ' + c.speed_kt + 'kt</td></tr>';
    }).join(""));
  }

  // Aircraft table
  lastPositions = d.positions;
  document.getElementById("ac-count").textContent = d.positions.length;
  renderTable("ac-body", d.positions.map(function(ac) {
    var sel = ac.tail_number === selectedAircraftId ? ' class="selected"' : '';
    return '<tr' + sel + ' onclick="selectAircraft(\'' + ac.tail_number + '\')"><td>' + ac.callsign + "</td>" +
           "<td>" + ac.tail_number + "</td>" +
           '<td><span class="phase phase-' + ac.phase + '">' + ac.phase + "</span>" + (ac.gate ? ' ' + ac.gate : '') + (ac.nav_status === 'WEATHER_DEVIATION' ? ' <span class="nav-wx">⚡WX</span>' : '') + "</td>" +
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
    return '<tr onclick="toggleAirportPopup(\'' + w.airport + '\')">' +
           "<td>" + w.airport + "</td><td>" + w.condition + "</td>" +
           "<td>" + w.wind + "</td><td>" + w.vis_m + "</td><td>" + w.ceiling_ft + "</td></tr>";
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
      return '<div class="alert-card alert-' + a.severity + '"><span class="ts">' + fmtTs(a.ts) + '</span> <strong>' + a.type +
             "</strong> &mdash; " + a.message + (a.aircraft ? " (" + a.aircraft + ")" : "") + "</div>";
    }).join("");
  } else { ab.innerHTML = '<div class="empty">No alerts</div>'; }

  // Handoff log
  if (d.handoff_log) renderHandoffLog(d.handoff_log);

  // Pulse centers on handoff accept
  if (d.pulse_centers) d.pulse_centers.forEach(function(cid) { pulseCenter(cid); });

  // Counters
  var ct = document.getElementById("counters-table");
  var names = ["AircraftPosition","ControllerInstruction","PilotAcknowledgment",
               "FlightPlan","RunwayStatus","WeatherReport","Handoff","Alert","AircraftTracking","FacilityStatus","ConvectiveCell"];
  var msgTotal = 0;
  ct.innerHTML = names.map(function(n) {
    var v = d.counters[n] || 0; msgTotal += v;
    return "<tr><td>" + n + "</td><td>" + v + "</td></tr>";
  }).join("");
  document.getElementById("msg-total").textContent = msgTotal.toLocaleString();

  // Facility Status
  lastTracking = d.tracking || lastTracking;
  if (d.facility_status) {
    var fb = document.getElementById("fac-body");
    var onlineCount = 0;
    fb.innerHTML = d.facility_status.map(function(f) {
      if (f.status === "ONLINE") onlineCount++;
      var dot = '<span class="fac-dot fac-dot-' + f.status + '"></span>';
      var swatch = '';
      if (f.facility_type === 'CENTER') {
        var col = CENTER_COLORS[f.facility_id] || '#4fc3f7';
        swatch = '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + col + ';margin-right:4px;vertical-align:middle"></span>';
      }
      return '<tr onclick="toggleFacilityPopup(\'' + f.facility_id + '\', \'' + f.facility_type + '\')">' +
             '<td>' + swatch + f.facility_id + '</td><td><span class="fac-type">' +
             f.facility_type + '</span></td><td>' + dot + '</td><td>' +
             f.tracked + '</td></tr>';
    }).join("");
    document.getElementById("fac-online").textContent =
      onlineCount + "/" + d.facility_status.length;
  }
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

/* ── Add Aircraft form ───────────────────────────────────────────── */
(function() {
  var codes = Object.keys(AIRPORTS).sort();
  var origSel = document.getElementById("spawn-orig");
  var destSel = document.getElementById("spawn-dest");
  codes.forEach(function(c) {
    origSel.add(new Option(c + " — " + AIRPORTS[c].name, c));
    destSel.add(new Option(c + " — " + AIRPORTS[c].name, c));
  });
  if (codes.length > 1) destSel.selectedIndex = 1;
})();

function removeWeatherCell(cellId) {
  fetch("/weather_cell/" + encodeURIComponent(cellId), { method: "DELETE" })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (d.error) { console.warn("Remove cell:", d.error); }
      else { map.closePopup(); }
    }).catch(function(e) { console.error("Remove cell error:", e); });
}

function spawnWeatherCell() {
  var msg = document.getElementById("wx-msg");
  var btn = document.getElementById("wx-btn");
  msg.textContent = ""; msg.className = "";
  var lat = parseFloat(document.getElementById("wx-lat").value);
  var lon = parseFloat(document.getElementById("wx-lon").value);
  if (isNaN(lat) || isNaN(lon)) { msg.textContent = "Enter valid coordinates"; msg.className = "err"; return; }
  btn.disabled = true;
  fetch("/weather_cell", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      lat: lat, lon: lon,
      radius: parseFloat(document.getElementById("wx-radius").value) || 20,
      severity: document.getElementById("wx-sev").value,
      heading: parseFloat(document.getElementById("wx-hdg").value) || 0,
      speed: parseFloat(document.getElementById("wx-spd").value) || 0,
      duration_min: parseFloat(document.getElementById("wx-dur").value) || 30,
      top_alt: 45000, base_alt: 5000
    })
  }).then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
    .then(function(res) {
      btn.disabled = false;
      if (res.ok) {
        msg.textContent = res.data.severity + " cell at " + res.data.lat.toFixed(1) + ", " + res.data.lon.toFixed(1) + " (" + res.data.duration_min + " sim-min)";
        msg.className = "ok";
      } else {
        msg.textContent = res.data.error || "Failed";
        msg.className = "err";
      }
    }).catch(function(e) { btn.disabled = false; msg.textContent = "Network error"; msg.className = "err"; });
}

function spawnAircraft() {
  var cs = document.getElementById("spawn-cs").value.trim().toUpperCase();
  var orig = document.getElementById("spawn-orig").value;
  var dest = document.getElementById("spawn-dest").value;
  var msg = document.getElementById("spawn-msg");
  var btn = document.getElementById("spawn-btn");
  msg.textContent = ""; msg.className = "";
  if (!cs) { msg.textContent = "Enter a callsign"; msg.className = "err"; return; }
  if (orig === dest) { msg.textContent = "Select different airports"; msg.className = "err"; return; }
  btn.disabled = true;
  fetch("/aircraft", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({callsign: cs, origin: orig, destination: dest})
  }).then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
    .then(function(res) {
      btn.disabled = false;
      if (res.ok) {
        msg.textContent = res.data.callsign + " launched: " + res.data.origin + " → " + res.data.destination;
        msg.className = "ok";
        document.getElementById("spawn-cs").value = "";
      } else {
        msg.textContent = res.data.error || "Failed";
        msg.className = "err";
      }
    }).catch(function(e) { btn.disabled = false; msg.textContent = "Network error"; msg.className = "err"; });
}

// Map click → fill WX form coordinates
map.on("click", function(e) {
  var latInput = document.getElementById("wx-lat");
  var lonInput = document.getElementById("wx-lon");
  if (latInput && lonInput) {
    latInput.value = e.latlng.lat.toFixed(2);
    lonInput.value = e.latlng.lng.toFixed(2);
    var mc = document.getElementById("mouse-coords");
    if (mc) { mc.style.color = "#00e5ff"; setTimeout(function(){ mc.style.color = ""; }, 400); }
  }
});
</script>
</body>
</html>"""


# ── Main ────────────────────────────────────────────────────────────────────

def init_dds():
    from common import initial_sim_speed, set_sim_speed
    qos_provider = load_qos_provider()
    dp_partitions = ["OPS/*"]
    participant = create_participant(
        qos_provider,
        dp_partitions=dp_partitions,
        participant_name="Dashboard",
        app_name="ATC_Dashboard",
    )
    # Set initial sim speed as a propagated participant property
    set_sim_speed(participant, initial_sim_speed(app.config["scenario_config"]))
    subscriber = create_subscriber(participant)
    readers = {}
    for topic_name, (type_cls, profile) in TOPIC_MAP.items():
        topic = dds.Topic(participant, topic_name, type_cls)
        readers[topic_name] = dds.DataReader(
            subscriber, topic,
            reader_qos(qos_provider, profile),
        )
    # ConvectiveCell writer for manual weather injection (reuse existing topic)
    publisher = create_publisher(participant)
    wx_topic = dds.Topic.find(participant, "ConvectiveCell")
    wx_writer = dds.DataWriter(
        publisher, wx_topic,
        writer_qos(qos_provider, "ConvectiveCellProfile"),
    )
    return participant, readers, wx_writer


def main():
    global _centers_js, _tracons_js, _airports_js, _AIRPORT_CODES
    parser = argparse.ArgumentParser(description="ATC Web Dashboard")
    parser.add_argument("--config", required=True, help="Path to scenario config JSON")
    parser.add_argument("--qos-file", required=True, help="Path to QoS XML file")
    parser.add_argument("--port", type=int, default=8050, help="HTTP port")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    args = parser.parse_args()

    common.QOS_FILE = args.qos_file
    app.config["scenario_config"] = args.config

    # Load scenario config for airspace boundaries
    with open(args.config) as f:
        _scenario_cfg = json.load(f)

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
    _AIRPORT_CODES = [a["code"] for a in _scenario_cfg["airports"]]

    participant, readers, wx_writer = init_dds()
    app.config["dds_participant"] = participant
    app.config["wx_writer"] = wx_writer
    t = threading.Thread(target=dds_poll_loop, args=(readers,), daemon=True)
    t.start()

    print(f"Dashboard running at http://localhost:{args.port}")
    app.run(host=args.host, port=args.port, threaded=True)
    participant.close()


if __name__ == "__main__":
    main()
