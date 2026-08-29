# SPDX-FileCopyrightText: 2026 Real-Time Innovations, Inc.
# SPDX-License-Identifier: Apache-2.0
"""
Common utilities for ATC gRPC applications.

Provides:
  - Scenario config loading (airports, TRACONs, centers, aircraft)
  - Geographic math (haversine, bearing, point-in-polygon)
  - Zeroconf (mDNS/DNS-SD) service registration and discovery
  - gRPC server-streaming broadcast helpers
  - Simulation speed management
  - Logging, ID generation, timestamp helpers
"""

import json
import logging
import math
import os
import signal
import socket
import threading
import time
import uuid
from collections import defaultdict
from concurrent import futures
from typing import Any

import grpc
from google.protobuf.timestamp_pb2 import Timestamp
from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf

# ── Scenario config loading ────────────────────────────────────────────


def _load_scenario(config_path: str) -> dict:
    with open(config_path) as f:
        return json.load(f)


def load_airport_coords(config_path: str) -> dict[str, tuple[float, float]]:
    data = _load_scenario(config_path)
    return {a["code"]: (a["latitude"], a["longitude"]) for a in data["airports"]}


def load_center_boundaries(config_path: str) -> dict[str, list[list[float]]]:
    data = _load_scenario(config_path)
    return {c["id"]: c["boundary"] for c in data["centers"]}


def load_tracon_for_airport(config_path: str) -> dict[str, str]:
    data = _load_scenario(config_path)
    return {a["code"]: a["serving_tracon"] for a in data["airports"] if "serving_tracon" in a}


def load_airport_config(airport_code: str, config_path: str) -> dict:
    data = _load_scenario(config_path)
    for a in data["airports"]:
        if a["code"] == airport_code:
            return a
    raise KeyError(f"Airport '{airport_code}' not found in scenario config")


def load_tracon_config(tracon_id: str, config_path: str) -> dict:
    data = _load_scenario(config_path)
    for t in data.get("tracons", []):
        if t["id"] == tracon_id:
            t["airports"] = [
                a["code"] for a in data["airports"]
                if a.get("serving_tracon") == tracon_id
            ]
            return t
    raise KeyError(f"TRACON '{tracon_id}' not found in scenario config")


def load_center_config(center_id: str, config_path: str) -> dict:
    data = _load_scenario(config_path)
    for c in data["centers"]:
        if c["id"] == center_id:
            return c
    raise KeyError(f"Center '{center_id}' not found in scenario config")


def load_aircraft_config(callsign: str, config_path: str) -> dict | None:
    data = _load_scenario(config_path)
    for ac in data.get("aircraft", []):
        if ac["callsign"] == callsign:
            return ac
    return None


def load_scenario_info(config_path: str) -> dict:
    data = _load_scenario(config_path)
    return {
        "scenario": data.get("scenario", "unnamed"),
        "duration_seconds": data.get("duration_seconds", 120),
        "airports": [a["code"] for a in data.get("airports", [])],
        "tracons": [t["id"] for t in data.get("tracons", [])],
        "centers": [c["id"] for c in data.get("centers", [])],
        "aircraft": [ac["callsign"] for ac in data.get("aircraft", [])],
    }


# ── Geographic math ────────────────────────────────────────────────────


def point_in_polygon(lat: float, lon: float, polygon: list[list[float]]) -> bool:
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
    lats = [p[0] for p in polygon]
    lons = [p[1] for p in polygon]
    return min(lats), max(lats), min(lons), max(lons)


def find_center_for_position(
    lat: float, lon: float, center_boundaries: dict[str, list[list[float]]], exclude: str = ""
) -> str | None:
    for cid, boundary in center_boundaries.items():
        if cid == exclude:
            continue
        if point_in_polygon(lat, lon, boundary):
            return cid
    return None


def distance_nm(lat1, lon1, lat2, lon2) -> float:
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = rlat2 - rlat1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * 3440.065 * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(rlat2)
    y = math.cos(rlat1) * math.sin(rlat2) - math.sin(rlat1) * math.cos(rlat2) * math.cos(dlon)
    return math.degrees(math.atan2(x, y)) % 360


# ── Simulation speed ───────────────────────────────────────────────────

_sim_speed_lock = threading.Lock()
_sim_speed = 1.0


def initial_sim_speed(config_path: str) -> float:
    try:
        return max(0.1, min(50.0, float(_load_scenario(config_path).get("initial_speed", 1.0))))
    except (FileNotFoundError, ValueError):
        return 1.0


def set_sim_speed(speed: float) -> None:
    global _sim_speed
    with _sim_speed_lock:
        _sim_speed = max(0.1, min(50.0, speed))


def get_sim_speed() -> float:
    with _sim_speed_lock:
        return _sim_speed


def start_sim_speed_listener() -> None:
    """Follow live speed updates from the dashboard's control service."""
    def listen():
        # Import lazily to keep this shared module independent of generated
        # bindings during type generation and other utility-only use.
        import air_traffic_types_pb2 as pb
        import air_traffic_types_pb2_grpc as pb_grpc

        discovery = DiscoveryManager(browse_roles=["control"])
        try:
            while not shutdown_event.is_set():
                endpoint = discovery.get_endpoint("control", "dashboard")
                if endpoint is None:
                    shutdown_event.wait(1.0)
                    continue

                channel = grpc.insecure_channel(f"{endpoint[0]}:{endpoint[1]}")
                try:
                    stub = pb_grpc.SimulationControlServiceStub(channel)
                    for update in stub.WatchSimulationSpeed(
                        pb.EmptyFilter(), timeout=600,
                    ):
                        set_sim_speed(update.multiplier)
                        if shutdown_event.is_set():
                            break
                except grpc.RpcError:
                    if not shutdown_event.is_set():
                        shutdown_event.wait(1.0)
                finally:
                    channel.close()
        finally:
            discovery.close()

    threading.Thread(target=listen, name="sim-speed-listener", daemon=True).start()


def write_sim_speed(speed: float, config_path: str) -> None:
    """Persist sim speed into the scenario config JSON for restarts."""
    try:
        data = _load_scenario(config_path)
        data["initial_speed"] = speed
        with open(config_path, "w") as f:
            json.dump(data, f, indent=2)
    except (FileNotFoundError, OSError):
        pass


# ── Timestamps and IDs ─────────────────────────────────────────────────


def now_ts() -> Timestamp:
    """Return current time as a protobuf Timestamp."""
    ts = Timestamp()
    ts.GetCurrentTime()
    return ts


def now_ms() -> int:
    return int(time.time() * 1000)


def make_id(prefix: str = "") -> str:
    short = uuid.uuid4().hex[:12]
    return f"{prefix}{short}" if prefix else short


# ── Logging ────────────────────────────────────────────────────────────


def setup_logging(name: str) -> logging.Logger:
    fmt = f"%(asctime)s [{name}] %(levelname)s: %(message)s"
    datefmt = "%H:%M:%S"
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO, format=fmt, datefmt=datefmt)
    else:
        for h in root.handlers:
            h.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    return logger


# ── Zeroconf service discovery ─────────────────────────────────────────

# DNS-SD service type naming convention
SERVICE_TYPES = {
    "aircraft": "_atc-aircraft._tcp.local.",
    "tower": "_atc-tower._tcp.local.",
    "tracon": "_atc-tracon._tcp.local.",
    "center": "_atc-center._tcp.local.",
    "airport": "_atc-airport._tcp.local.",
    "fps": "_atc-fps._tcp.local.",
    "weather": "_atc-weather._tcp.local.",
    "control": "_atc-control._tcp.local.",
}


def get_local_ip() -> str:
    """Get the local IP address that can reach other hosts."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("224.0.0.251", 5353))  # mDNS multicast
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class ZeroconfRegistrar:
    """Registers a gRPC service via Zeroconf mDNS/DNS-SD."""

    def __init__(self):
        self._zc = Zeroconf()
        self._infos: list[ServiceInfo] = []

    def register(self, role: str, name: str, port: int,
                 properties: dict[str, str] | None = None):
        stype = SERVICE_TYPES[role]
        host = get_local_ip()
        props = {k: v.encode() if isinstance(v, str) else v
                 for k, v in (properties or {}).items()}
        info = ServiceInfo(
            type_=stype,
            name=f"{name}.{stype}",
            addresses=[socket.inet_aton(host)],
            port=port,
            properties=props,
        )
        # cooperating_responders=True allows re-registering after kill -9
        # where stale mDNS records from the previous instance still exist.
        self._zc.register_service(info, cooperating_responders=True)
        self._infos.append(info)

    def close(self):
        for info in self._infos:
            self._zc.unregister_service(info)
        self._zc.close()


class ServiceListener:
    """Listens for Zeroconf service announcements and tracks endpoints.

    Thread-safe: callbacks happen on Zeroconf's background thread.
    """

    def __init__(self, zc: Zeroconf):
        self._zc = zc
        self._lock = threading.Lock()
        # role -> {service_name -> (host, port, properties)}
        self._services: dict[str, dict[str, tuple[str, int, dict[str, str]]]] = defaultdict(dict)
        self._callbacks: list[Any] = []  # list of (event, callback) tuples

    def add_service(self, zc, type_: str, name: str):
        info = zc.get_service_info(type_, name)
        if info is None:
            return
        host = socket.inet_ntoa(info.addresses[0]) if info.addresses else "127.0.0.1"
        port = info.port
        props = {(k.decode() if isinstance(k, bytes) else str(k)):
                 (v.decode() if isinstance(v, bytes) else str(v))
                 for k, v in (info.properties or {}).items()}
        role = self._type_to_role(type_)
        with self._lock:
            self._services[role][name] = (host, port, props)
        self._fire_callbacks("add", role, name, host, port, props)

    def remove_service(self, zc, type_: str, name: str):
        role = self._type_to_role(type_)
        with self._lock:
            self._services[role].pop(name, None)
        self._fire_callbacks("remove", role, name, None, None, {})

    def update_service(self, zc, type_: str, name: str):
        self.add_service(zc, type_, name)

    def get_services(self, role: str) -> dict[str, tuple[str, int, dict[str, str]]]:
        with self._lock:
            return dict(self._services.get(role, {}))

    def get_endpoint(self, role: str, name_prefix: str) -> tuple[str, int] | None:
        """Get (host, port) for a service whose name starts with name_prefix."""
        with self._lock:
            for sname, (host, port, _) in self._services.get(role, {}).items():
                if sname.startswith(name_prefix + "."):
                    return (host, port)
        return None

    def on_change(self, callback):
        """Register a callback(event, role, name, host, port, props)."""
        self._callbacks.append(callback)

    def _fire_callbacks(self, event, role, name, host, port, props):
        for cb in self._callbacks:
            try:
                cb(event, role, name, host, port, props)
            except Exception:
                pass

    @staticmethod
    def _type_to_role(type_: str) -> str:
        for role, stype in SERVICE_TYPES.items():
            if stype == type_:
                return role
        return type_


class DiscoveryManager:
    """Manages Zeroconf browsing for multiple service types.

    Wraps ServiceBrowser + ServiceListener. Provides a simple API to
    query discovered services and register callbacks.
    """

    def __init__(self, browse_roles: list[str] | None = None):
        self._zc = Zeroconf()
        self.listener = ServiceListener(self._zc)
        self._browsers: list[ServiceBrowser] = []
        if browse_roles:
            for role in browse_roles:
                stype = SERVICE_TYPES.get(role)
                if stype:
                    browser = ServiceBrowser(self._zc, stype, self.listener)
                    self._browsers.append(browser)

    def get_services(self, role: str) -> dict[str, tuple[str, int, dict[str, str]]]:
        return self.listener.get_services(role)

    def get_endpoint(self, role: str, name_prefix: str) -> tuple[str, int] | None:
        return self.listener.get_endpoint(role, name_prefix)

    def get_all_endpoints(self, role: str) -> list[tuple[str, int, dict[str, str]]]:
        services = self.listener.get_services(role)
        return [(h, p, props) for h, p, props in services.values()]

    def on_change(self, callback):
        self.listener.on_change(callback)

    def close(self):
        self._zc.close()


# ── gRPC broadcast helpers ─────────────────────────────────────────────


class StreamBroadcaster:
    """Manages multiple gRPC server-streaming subscribers for a single data type.

    Servers produce data, which is broadcast to all connected subscriber streams.
    Maintains a state cache for late-join replay (TRANSIENT_LOCAL equivalent).

    Thread-safe: producers and subscriber management may happen concurrently.
    """

    def __init__(self, key_fn=None, max_cache: int = 100, ttl_s: float | None = None):
        """
        Args:
            key_fn: Function that extracts a key from a message for caching.
                    If None, all messages are cached in a list (no dedup).
            max_cache: Max cached entries.
            ttl_s: TTL in seconds for cached entries. None = no expiry.
        """
        self._lock = threading.Lock()
        self._subscribers: list[Any] = []  # list of queue objects
        self._key_fn = key_fn
        self._max_cache = max_cache
        self._ttl_s = ttl_s
        # Cache: key → (message, timestamp) if keyed, else list of (message, timestamp)
        self._cache: dict | list = {} if key_fn else []

    def add_subscriber(self, queue_obj):
        with self._lock:
            self._subscribers.append(queue_obj)
            # Replay cached state
            self._evict_expired()
            if isinstance(self._cache, dict):
                for msg, _ in self._cache.values():
                    queue_obj.put(msg)
            else:
                for msg, _ in self._cache:
                    queue_obj.put(msg)

    def remove_subscriber(self, queue_obj):
        with self._lock:
            try:
                self._subscribers.remove(queue_obj)
            except ValueError:
                pass

    def publish(self, message):
        with self._lock:
            now = time.time()
            # Update cache
            if self._key_fn:
                key = self._key_fn(message)
                self._cache[key] = (message, now)
                # Enforce max cache
                if len(self._cache) > self._max_cache:
                    oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
                    del self._cache[oldest_key]
            else:
                self._cache.append((message, now))
                if len(self._cache) > self._max_cache:
                    self._cache = self._cache[-self._max_cache:]
            self._evict_expired()
            # Broadcast to all subscribers
            dead = []
            for q in self._subscribers:
                try:
                    q.put(message)
                except Exception:
                    dead.append(q)
            for q in dead:
                try:
                    self._subscribers.remove(q)
                except ValueError:
                    pass

    def remove_key(self, key):
        """Remove a cached entry by key (instance disposal)."""
        with self._lock:
            if isinstance(self._cache, dict):
                self._cache.pop(key, None)

    def _evict_expired(self):
        if self._ttl_s is None:
            return
        cutoff = time.time() - self._ttl_s
        if isinstance(self._cache, dict):
            expired = [k for k, (_, t) in self._cache.items() if t < cutoff]
            for k in expired:
                del self._cache[k]
        else:
            self._cache = [(m, t) for m, t in self._cache if t >= cutoff]


class SubscriberQueue:
    """A thread-safe queue for a single gRPC streaming subscriber."""

    def __init__(self):
        self._queue: list = []
        self._cond = threading.Condition()
        self._closed = False

    def put(self, item):
        with self._cond:
            if not self._closed:
                self._queue.append(item)
                self._cond.notify()

    def get(self, timeout: float = 1.0):
        with self._cond:
            while not self._queue and not self._closed:
                if not self._cond.wait(timeout=timeout):
                    return None  # timeout
            if self._closed and not self._queue:
                return None
            if self._queue:
                return self._queue.pop(0)
            return None

    def close(self):
        with self._cond:
            self._closed = True
            self._cond.notify_all()


def create_grpc_server(port: int, max_workers: int = 50) -> tuple[grpc.Server, int]:
    """Create a gRPC server. Returns (server, actual_port).

    If port is 0, a free port is dynamically assigned.
    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    actual_port = server.add_insecure_port(f"0.0.0.0:{port}")
    return server, actual_port


def serve_stream(broadcaster: StreamBroadcaster, context: grpc.ServicerContext,
                 filter_fn=None):
    """Generator that serves a server-streaming RPC from a broadcaster.

    Args:
        broadcaster: The StreamBroadcaster to subscribe to.
        context: The gRPC service context (for cancellation detection).
        filter_fn: Optional function(message) -> bool. Only yield if True.
    """
    q = SubscriberQueue()
    broadcaster.add_subscriber(q)
    try:
        while context.is_active():
            msg = q.get(timeout=1.0)
            if msg is None:
                continue
            if filter_fn and not filter_fn(msg):
                continue
            yield msg
    finally:
        q.close()
        broadcaster.remove_subscriber(q)


# ── Graceful shutdown helper ───────────────────────────────────────────


shutdown_event = threading.Event()


def install_signal_handlers():
    """Install SIGINT/SIGTERM handlers that set the shutdown event.

    A second signal (or 2-second grace period) forces immediate exit,
    which is necessary for apps with long-lived gRPC streaming threads.
    """
    def handler(_sig, _frame):
        if shutdown_event.is_set():
            os._exit(1)
        shutdown_event.set()
        threading.Timer(2.0, lambda: os._exit(0)).start()
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
