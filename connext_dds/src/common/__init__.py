"""
Common utilities for ATC DDS applications.
"""

import json
import logging
import os
import time
import uuid

import rti.connextdds as dds

DOMAIN_ID = 0
QOS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "qos", "USER_QOS_PROFILES.xml")
QOS_LIB = "AirTrafficControl_QosLib"
SCENARIO_CONFIG = os.path.join(os.path.dirname(__file__), "..", "..", "config", "scenario_default.json")


def _load_scenario(config_path: str = SCENARIO_CONFIG) -> dict:
    """Load the scenario JSON from disk."""
    with open(config_path) as f:
        return json.load(f)


def load_airport_coords(config_path: str = SCENARIO_CONFIG) -> dict[str, tuple[float, float]]:
    """Load airport (code → (lat, lon)) mapping from scenario config JSON."""
    data = _load_scenario(config_path)
    return {
        a["code"]: (a["latitude"], a["longitude"])
        for a in data["airports"]
    }


def load_center_boundaries(config_path: str = SCENARIO_CONFIG) -> dict[str, list[list[float]]]:
    """Load center boundary polygons as dict[center_id → list of [lat, lon]]."""
    data = _load_scenario(config_path)
    return {c["id"]: c["boundary"] for c in data["centers"]}


def load_tracon_for_airport(config_path: str = SCENARIO_CONFIG) -> dict[str, str]:
    """Load mapping from airport code → TRACON id."""
    data = _load_scenario(config_path)
    return {a["code"]: a["serving_tracon"] for a in data["airports"] if "serving_tracon" in a}


def load_tracon_serving_center(config_path: str = SCENARIO_CONFIG) -> dict[str, str]:
    """Load mapping from TRACON id → serving center id."""
    data = _load_scenario(config_path)
    return {t["id"]: t["serving_center"] for t in data.get("tracons", []) if "serving_center" in t}


# ── Per-entity config lookups ──────────────────────────────────────────


def load_airport_config(airport_code: str, config_path: str = SCENARIO_CONFIG) -> dict:
    """Look up a single airport's full config entry by code.

    Returns dict with keys: code, name, latitude, longitude, runways, serving_tracon.
    Raises KeyError if not found.
    """
    data = _load_scenario(config_path)
    for a in data["airports"]:
        if a["code"] == airport_code:
            return a
    raise KeyError(f"Airport '{airport_code}' not found in scenario config")


def load_tracon_config(tracon_id: str, config_path: str = SCENARIO_CONFIG) -> dict:
    """Look up a TRACON config entry by ID.

    Returns dict with keys from the config (id, serving_center, ...)
    plus a derived 'airports' list of airport codes served by this TRACON.
    Raises KeyError if not found.
    """
    data = _load_scenario(config_path)
    for t in data.get("tracons", []):
        if t["id"] == tracon_id:
            # Derive served airports by reverse-lookup
            t["airports"] = [
                a["code"] for a in data["airports"]
                if a.get("serving_tracon") == tracon_id
            ]
            return t
    raise KeyError(f"TRACON '{tracon_id}' not found in scenario config")


def load_center_config(center_id: str, config_path: str = SCENARIO_CONFIG) -> dict:
    """Look up a center config entry by ID.

    Returns dict with keys: id, boundary, min_altitude_ft, max_altitude_ft.
    Raises KeyError if not found.
    """
    data = _load_scenario(config_path)
    for c in data["centers"]:
        if c["id"] == center_id:
            return c
    raise KeyError(f"Center '{center_id}' not found in scenario config")


def load_aircraft_config(callsign: str, config_path: str = SCENARIO_CONFIG) -> dict | None:
    """Look up an aircraft config entry by callsign.

    Returns dict with keys: callsign, tail_number, origin, destination.
    Returns None if not found (aircraft may be ad-hoc).
    """
    data = _load_scenario(config_path)
    for ac in data.get("aircraft", []):
        if ac["callsign"] == callsign:
            return ac
    return None


def load_scenario_info(config_path: str = SCENARIO_CONFIG) -> dict:
    """Return scenario metadata + all entity IDs as a flat dict.

    Keys:
        scenario, duration_seconds,
        airports (list), tracons (list), centers (list), aircraft (list)
    """
    data = _load_scenario(config_path)
    return {
        "scenario": data.get("scenario", "unnamed"),
        "duration_seconds": data.get("duration_seconds", 120),
        "airports": [a["code"] for a in data.get("airports", [])],
        "tracons": [t["id"] for t in data.get("tracons", [])],
        "centers": [c["id"] for c in data.get("centers", [])],
        "aircraft": [ac["callsign"] for ac in data.get("aircraft", [])],
    }


def point_in_polygon(lat: float, lon: float, polygon: list[list[float]]) -> bool:
    """Ray-casting point-in-polygon test. Polygon is list of [lat, lon]."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        lat_i, lon_i = polygon[i]
        lat_j, lon_j = polygon[j]
        if ((lat_i > lat) != (lat_j > lat)) and \
           (lon < (lon_j - lon_i) * (lat - lat_i) / (lat_j - lat_i) + lon_i):
            inside = not inside
        j = i
    return inside


def polygon_bbox(polygon: list[list[float]]) -> tuple[float, float, float, float]:
    """Return (min_lat, max_lat, min_lon, max_lon) for a polygon of [lat, lon] points."""
    lats = [p[0] for p in polygon]
    lons = [p[1] for p in polygon]
    return min(lats), max(lats), min(lons), max(lons)


def find_center_for_position(
    lat: float, lon: float, center_boundaries: dict[str, list[list[float]]], exclude: str = ""
) -> str | None:
    """Find which center contains the given position. Optionally exclude one center."""
    for cid, boundary in center_boundaries.items():
        if cid == exclude:
            continue
        if point_in_polygon(lat, lon, boundary):
            return cid
    return None


SIM_SPEED_PROP = "sim_speed"


def initial_sim_speed() -> float:
    """Read initial_speed from scenario config JSON (used at participant creation)."""
    try:
        return max(0.1, min(50.0, float(_load_scenario().get("initial_speed", 1.0))))
    except (FileNotFoundError, ValueError):
        return 1.0


def set_sim_speed(participant: dds.DomainParticipant, speed: float) -> None:
    """Update the propagated sim_speed participant property."""
    speed = max(0.1, min(50.0, speed))
    qos = participant.qos
    qos.property.set({SIM_SPEED_PROP: str(speed)}, propagate=True)
    participant.qos = qos


def get_sim_speed(participant: dds.DomainParticipant) -> float:
    """Read sim_speed from the local participant's own property."""
    try:
        return float(participant.qos.property.get(SIM_SPEED_PROP))
    except (KeyError, ValueError):
        return 1.0


def read_sim_speed_from_discovery(participant: dds.DomainParticipant) -> float:
    """Read sim_speed from discovered participants via builtin reader.

    Only returns a value if a discovered participant actually has the
    sim_speed property set.  Falls back to initial_speed from config.
    """
    reader = participant.participant_reader
    for sample in reader.read():
        if sample.info.valid:
            try:
                val = sample.data.property.try_get(SIM_SPEED_PROP)
                if val is not None:
                    return max(0.1, min(50.0, float(val)))
            except (ValueError, AttributeError):
                continue
    return initial_sim_speed()


def write_sim_speed(speed: float) -> None:
    """Update initial_speed in scenario config JSON (for persistence across restarts)."""
    speed = max(0.1, min(50.0, speed))
    with open(SCENARIO_CONFIG) as f:
        data = json.load(f)
    data["initial_speed"] = speed
    with open(SCENARIO_CONFIG, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def now_ms() -> int:
    return int(time.time() * 1000)


def make_id(prefix: str = "") -> str:
    short = uuid.uuid4().hex[:12]
    return f"{prefix}{short}" if prefix else short


def setup_logging(name: str) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s [{name}] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger(name)


def load_qos_provider() -> dds.QosProvider:
    return dds.QosProvider(QOS_FILE)


def create_participant(
    qos_provider: dds.QosProvider,
    domain_id: int = DOMAIN_ID,
    dp_partitions: list[str] | None = None,
    participant_name: str | None = None,
    app_name: str | None = None,
) -> dds.DomainParticipant:
    participant_qos = qos_provider.participant_qos_from_profile(
        f"{QOS_LIB}::AtcParticipantProfile"
    )
    if dp_partitions:
        participant_qos.partition.name = dp_partitions
    if participant_name:
        participant_qos.participant_name.name = participant_name
    if app_name:
        participant_qos.participant_name.role_name = app_name
    # Disable shared memory — use only UDPv4
    participant_qos.transport_builtin.mask = dds.TransportBuiltinMask.UDPv4
    # Allow longer CFT filter parameter strings (default 256 is too short for geo bboxes)
    participant_qos.resource_limits.contentfilter_property_max_length = 512
    return dds.DomainParticipant(domain_id, participant_qos)


def create_publisher(
    participant: dds.DomainParticipant,
    partitions: list[str] | None = None,
) -> dds.Publisher:
    if partitions:
        pub_qos = participant.default_publisher_qos
        pub_qos.partition.name = partitions
        return dds.Publisher(participant, pub_qos)
    return dds.Publisher(participant)


def create_subscriber(
    participant: dds.DomainParticipant,
    partitions: list[str] | None = None,
) -> dds.Subscriber:
    if partitions:
        sub_qos = participant.default_subscriber_qos
        sub_qos.partition.name = partitions
        return dds.Subscriber(participant, sub_qos)
    return dds.Subscriber(participant)


def writer_qos(qos_provider: dds.QosProvider, profile: str) -> dds.DataWriterQos:
    return qos_provider.datawriter_qos_from_profile(f"{QOS_LIB}::{profile}")


def reader_qos(qos_provider: dds.QosProvider, profile: str) -> dds.DataReaderQos:
    return qos_provider.datareader_qos_from_profile(f"{QOS_LIB}::{profile}")
