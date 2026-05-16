# SPDX-FileCopyrightText: 2026 Real-Time Innovations, Inc.
# SPDX-License-Identifier: Apache-2.0
"""
Weather Service (gRPC) — Publishes ConvectiveCell (storm cells) for en-route
weather hazards.

Serves: WeatherService (StreamConvectiveCells)
"""

import argparse
import math
import random
import threading
import time

import air_traffic_types_pb2 as pb
import air_traffic_types_pb2_grpc as pb_grpc
from common import (
    StreamBroadcaster,
    ZeroconfRegistrar,
    create_grpc_server,
    get_sim_speed,
    initial_sim_speed,
    install_signal_handlers,
    make_id,
    now_ts,
    serve_stream,
    set_sim_speed,
    setup_logging,
    shutdown_event,
)

log = setup_logging("weather_service")

# CONUS bounding box
SPAWN_LAT_MIN, SPAWN_LAT_MAX = 28.0, 45.0
SPAWN_LON_MIN, SPAWN_LON_MAX = -115.0, -75.0


class ActiveCell:
    """Tracks a live convective cell with its remaining lifetime."""

    def __init__(self, cell_id: str, lat: float, lon: float,
                 radius_nm: float, base_alt: int, top_alt: int,
                 severity: int, heading_deg: float, speed_kt: float,
                 lifetime_s: float):
        self.cell_id = cell_id
        self.lat = lat
        self.lon = lon
        self.radius_nm = radius_nm
        self.base_alt = base_alt
        self.top_alt = top_alt
        self.severity = severity
        self.heading_deg = heading_deg
        self.speed_kt = speed_kt
        self.lifetime_s = lifetime_s
        self.age_s = 0.0

    def advance(self, dt_s: float):
        self.age_s += dt_s
        nm = self.speed_kt / 3600.0 * dt_s
        self.lat += (nm * math.cos(math.radians(self.heading_deg))) / 60.0
        self.lon += (nm * math.sin(math.radians(self.heading_deg))) / (
            60.0 * max(math.cos(math.radians(self.lat)), 0.01)
        )

    @property
    def expired(self) -> bool:
        return self.age_s >= self.lifetime_s

    def to_proto(self) -> pb.ConvectiveCell:
        return pb.ConvectiveCell(
            cell_id=self.cell_id,
            center_latitude=self.lat,
            center_longitude=self.lon,
            radius_nm=self.radius_nm,
            top_altitude_ft=self.top_alt,
            base_altitude_ft=self.base_alt,
            severity=self.severity,
            movement_heading_deg=self.heading_deg,
            movement_speed_knots=self.speed_kt,
            observation_time=now_ts(),
        )


class WeatherServiceServicer(pb_grpc.WeatherServiceServicer):
    """gRPC WeatherService implementation."""

    def __init__(self, spawn_interval_s: float = 30.0, max_cells: int = 5,
                 publish_interval_s: float = 10.0):
        self.spawn_interval_s = spawn_interval_s
        self.max_cells = max_cells
        self.publish_interval_s = publish_interval_s
        self.cells: dict[str, ActiveCell] = {}

        self.cell_bc = StreamBroadcaster(
            key_fn=lambda m: m.cell_id, max_cache=20
        )

    def StreamConvectiveCells(self, request, context):
        return serve_stream(self.cell_bc, context)

    def InjectCell(self, request, context):
        """Accept a cell injected from an external source (e.g., dashboard)."""
        cell_id = request.cell_id or make_id("WX-")
        lifetime = 1800.0  # 30 min sim-time default for injected cells
        cell = ActiveCell(
            cell_id=cell_id,
            lat=request.center_latitude,
            lon=request.center_longitude,
            radius_nm=request.radius_nm,
            base_alt=request.base_altitude_ft,
            top_alt=request.top_altitude_ft,
            severity=request.severity,
            heading_deg=request.movement_heading_deg,
            speed_kt=request.movement_speed_knots,
            lifetime_s=lifetime,
        )
        self.cells[cell_id] = cell
        self.cell_bc.publish(cell.to_proto())
        log.info("Injected cell %s at (%.1f, %.1f) r=%.0fnm %s",
                 cell_id, cell.lat, cell.lon, cell.radius_nm,
                 pb.ConvectiveSeverity.Name(cell.severity))
        return pb.CellInjectionAck(accepted=True, cell_id=cell_id)

    def _spawn_cell(self):
        cell_id = make_id("WX-")
        lat = random.uniform(SPAWN_LAT_MIN, SPAWN_LAT_MAX)
        lon = random.uniform(SPAWN_LON_MIN, SPAWN_LON_MAX)
        radius = random.uniform(8.0, 30.0)
        base_alt = random.choice([10000, 15000, 18000])
        top_alt = random.choice([35000, 40000, 45000])
        severity = random.choice([
            pb.MODERATE, pb.MODERATE, pb.SEVERE, pb.EXTREME,
        ])
        heading = random.uniform(30, 120)
        speed = random.uniform(15.0, 45.0)
        lifetime = random.uniform(1800, 3600)

        cell = ActiveCell(
            cell_id=cell_id, lat=lat, lon=lon,
            radius_nm=radius, base_alt=base_alt, top_alt=top_alt,
            severity=severity, heading_deg=heading, speed_kt=speed,
            lifetime_s=lifetime,
        )
        self.cells[cell_id] = cell
        log.info("Spawned cell %s at (%.1f, %.1f) r=%.0fnm %s — lifetime %.0fs",
                 cell_id, lat, lon, radius,
                 pb.ConvectiveSeverity.Name(severity), lifetime)

    def _publish_cells(self):
        for cell in self.cells.values():
            self.cell_bc.publish(cell.to_proto())

    def run_loop(self):
        """Main loop — advance cells every wall-tick, publish at sim-time interval."""
        log.info("WeatherService running")
        TICK = 1.0
        time_since_spawn = 0.0
        time_since_publish = 0.0

        while not shutdown_event.is_set():
            sim_speed = get_sim_speed()
            dt = TICK * sim_speed

            for cell in list(self.cells.values()):
                cell.advance(dt)

            expired = [cid for cid, c in self.cells.items() if c.expired]
            for cid in expired:
                self.cell_bc.remove_key(cid)
                del self.cells[cid]
                log.info("Disposed cell %s (dissipated)", cid)

            time_since_spawn += dt
            if time_since_spawn >= self.spawn_interval_s and len(self.cells) < self.max_cells:
                self._spawn_cell()
                time_since_spawn = 0.0
                self._publish_cells()
                time_since_publish = 0.0
            else:
                time_since_publish += dt
                if time_since_publish >= self.publish_interval_s:
                    self._publish_cells()
                    time_since_publish = 0.0

            shutdown_event.wait(TICK)

        log.info("WeatherService shutdown — %d cells remaining", len(self.cells))


def main():
    parser = argparse.ArgumentParser(description="ATC Weather Service (gRPC)")
    parser.add_argument("--config", required=True, help="Path to scenario config JSON")
    parser.add_argument("--port", type=int, default=0, help="gRPC port (0=auto)")
    parser.add_argument("--duration", type=float, default=120.0, help="Run duration in seconds")
    parser.add_argument("--spawn-interval", type=float, default=30.0,
                        help="Seconds between cell spawns (sim-time)")
    parser.add_argument("--publish-interval", type=float, default=10.0,
                        help="Cell publication interval in sim-time seconds")
    parser.add_argument("--max-cells", type=int, default=5, help="Max concurrent cells")
    args = parser.parse_args()

    install_signal_handlers()
    set_sim_speed(initial_sim_speed(args.config))

    servicer = WeatherServiceServicer(
        spawn_interval_s=args.spawn_interval,
        max_cells=args.max_cells,
        publish_interval_s=args.publish_interval,
    )

    server, actual_port = create_grpc_server(args.port)
    pb_grpc.add_WeatherServiceServicer_to_server(servicer, server)
    server.start()
    log.info("WeatherService gRPC server on port %d", actual_port)

    zc = ZeroconfRegistrar()
    zc.register("weather", "weather", actual_port)

    loop_thread = threading.Thread(target=servicer.run_loop, daemon=True)
    loop_thread.start()

    shutdown_event.wait(timeout=args.duration)
    log.info("WeatherService shutting down")
    zc.close()
    server.stop(grace=2)


if __name__ == "__main__":
    main()
