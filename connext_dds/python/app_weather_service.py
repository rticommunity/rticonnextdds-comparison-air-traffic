# SPDX-FileCopyrightText: 2026 Real-Time Innovations, Inc.
# SPDX-License-Identifier: Apache-2.0
"""
Weather Service — Publishes ConvectiveCell (storm cells) for en-route weather hazards.

Mirrors the real-world Center Weather Service Unit (CWSU).  Periodically spawns
convective cells within CONUS, moves them along their heading, and disposes
instances when cells dissipate.

Centers subscribe to ConvectiveCell to reroute aircraft around weather.
The Dashboard subscribes to visualise cells on the map.
"""

import argparse
import math
import os
import random
import signal
import sys
import time


import rti.connextdds as dds
from air_traffic_types import NationalAirTrafficControl as ATC

ConvectiveCell = ATC.ConvectiveCell
ConvectiveSeverity = ATC.ConvectiveSeverity
from common import (
    create_participant,
    create_publisher,
    load_qos_provider,
    make_id,
    now_ms,
    read_sim_speed_from_discovery,
    setup_logging,
    writer_qos,
    writer_qos_for_speed,
)
import common

log = setup_logging("weather_service")

shutdown_flag = False


def signal_handler(_sig, _frame):
    global shutdown_flag
    shutdown_flag = True


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# CONUS bounding box for random cell spawning
SPAWN_LAT_MIN, SPAWN_LAT_MAX = 28.0, 45.0
SPAWN_LON_MIN, SPAWN_LON_MAX = -115.0, -75.0


class ActiveCell:
    """Tracks a live convective cell with its remaining lifetime."""

    def __init__(self, cell_id: str, lat: float, lon: float,
                 radius_nm: float, base_alt: int, top_alt: int,
                 severity: ConvectiveSeverity,
                 heading_deg: float, speed_kt: float,
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
        """Move cell by dt_s of sim-time."""
        self.age_s += dt_s
        nm = self.speed_kt / 3600.0 * dt_s
        self.lat += (nm * math.cos(math.radians(self.heading_deg))) / 60.0
        self.lon += (nm * math.sin(math.radians(self.heading_deg))) / (
            60.0 * max(math.cos(math.radians(self.lat)), 0.01)
        )

    @property
    def expired(self) -> bool:
        return self.age_s >= self.lifetime_s

    def to_sample(self) -> ConvectiveCell:
        return ConvectiveCell(
            cell_id=self.cell_id,
            center_latitude=self.lat,
            center_longitude=self.lon,
            radius_nm=self.radius_nm,
            top_altitude_ft=self.top_alt,
            base_altitude_ft=self.base_alt,
            severity=self.severity,
            movement_heading_deg=self.heading_deg,
            movement_speed_knots=self.speed_kt,
            observation_time=now_ms(),
        )


class WeatherService:
    """Publishes and manages convective cells over DDS."""

    def __init__(
        self,
        config_path: str,
        spawn_interval_s: float = 30.0,
        max_cells: int = 5,
        publish_interval_s: float = 300.0,
    ):
        self.spawn_interval_s = spawn_interval_s
        self.max_cells = max_cells
        self.publish_interval_s = publish_interval_s
        self.config_path = config_path
        self.cells: dict[str, ActiveCell] = {}
        self._time_since_spawn = 0.0
        self._time_since_publish = 0.0

        # DDS
        self.qos_provider = load_qos_provider()
        dp_partitions = [
            "OPS/WEATHER/*",
            "OPS/ENROUTE/*",
        ]
        self.participant = create_participant(
            self.qos_provider,
            dp_partitions=dp_partitions,
            participant_name="WeatherService",
            app_name="ATC_WeatherService",
        )
        self.publisher = create_publisher(self.participant)

        cell_topic = dds.Topic(self.participant, "ConvectiveCell", ConvectiveCell)
        speed = read_sim_speed_from_discovery(self.participant, self.config_path)
        self.cell_writer = dds.DataWriter(
            self.publisher, cell_topic,
            writer_qos_for_speed(self.qos_provider, "ConvectiveCellProfile", speed),
        )
        self._last_qos_speed = speed

        log.info(
            "WeatherService initialized — spawn every %.0fs, publish every %.0fs, max %d cells",
            spawn_interval_s, publish_interval_s, max_cells,
        )

    def _spawn_cell(self):
        """Create a new random convective cell."""
        cell_id = make_id("WX-")
        lat = random.uniform(SPAWN_LAT_MIN, SPAWN_LAT_MAX)
        lon = random.uniform(SPAWN_LON_MIN, SPAWN_LON_MAX)
        radius = random.uniform(8.0, 30.0)
        base_alt = random.choice([10000, 15000, 18000])
        top_alt = random.choice([35000, 40000, 45000])
        severity = random.choice([
            ConvectiveSeverity.MODERATE,
            ConvectiveSeverity.MODERATE,
            ConvectiveSeverity.SEVERE,
            ConvectiveSeverity.EXTREME,
        ])
        heading = random.uniform(30, 120)   # generally SW→NE movement
        speed = random.uniform(15.0, 45.0)
        # Real single-cell storms last 30-60 min; at 450 kt cruise that's
        # 225-450 nm — the distance scale that makes reroutes meaningful.
        lifetime = random.uniform(1800, 3600)  # 30–60 minutes of sim-time

        cell = ActiveCell(
            cell_id=cell_id, lat=lat, lon=lon,
            radius_nm=radius, base_alt=base_alt, top_alt=top_alt,
            severity=severity, heading_deg=heading, speed_kt=speed,
            lifetime_s=lifetime,
        )
        self.cells[cell_id] = cell
        log.info(
            "Spawned cell %s at (%.1f, %.1f) r=%.0fnm %s — lifetime %.0fs",
            cell_id, lat, lon, radius, severity.name, lifetime,
        )

    def _publish_cells(self):
        """Publish all active cells."""
        for cell in self.cells.values():
            self.cell_writer.write(cell.to_sample())

    def _dispose_cell(self, cell_id: str):
        """Dispose (remove) a dissipated cell."""
        sample = ConvectiveCell(cell_id=cell_id)
        handle = self.cell_writer.lookup_instance(sample)
        if handle is not None and not handle.is_nil:
            self.cell_writer.dispose_instance(handle)
            log.info("Disposed cell %s (dissipated)", cell_id)

    def run(self, duration_s: float = 120.0):
        """Main loop — advance cells every wall-tick, publish at sim-time interval."""
        log.info("WeatherService running")
        start = time.time()
        TICK = 1.0  # wall-clock seconds between iterations

        while not shutdown_flag and (time.time() - start) < duration_s:
            sim_speed = read_sim_speed_from_discovery(self.participant, self.config_path)
            dt = TICK * sim_speed
            if sim_speed != self._last_qos_speed:
                self._last_qos_speed = sim_speed
                self.cell_writer.qos = writer_qos_for_speed(
                    self.qos_provider, "ConvectiveCellProfile", sim_speed,
                )
                log.info("Cell QoS rescaled for speed=%.1fx", sim_speed)

            # Advance all cells
            for cell in list(self.cells.values()):
                cell.advance(dt)

            # Remove expired cells
            expired = [cid for cid, c in self.cells.items() if c.expired]
            for cid in expired:
                self._dispose_cell(cid)
                del self.cells[cid]

            # Spawn new cell periodically
            self._time_since_spawn += dt
            if self._time_since_spawn >= self.spawn_interval_s and len(self.cells) < self.max_cells:
                self._spawn_cell()
                self._time_since_spawn = 0.0
                # Publish immediately on spawn so subscribers see the new cell
                self._publish_cells()
                self._time_since_publish = 0.0
            else:
                # Publish at realistic radar interval (default 5 min sim-time)
                self._time_since_publish += dt
                if self._time_since_publish >= self.publish_interval_s:
                    self._publish_cells()
                    self._time_since_publish = 0.0

            time.sleep(TICK)

        # Clean up — dispose all remaining cells
        for cid in list(self.cells):
            self._dispose_cell(cid)
        log.info("WeatherService shutdown — disposed %d cells", len(self.cells))


def main():
    parser = argparse.ArgumentParser(description="ATC Weather Service (ConvectiveCell)")
    parser.add_argument("--config", required=True, help="Path to scenario config JSON")
    parser.add_argument("--qos-file", required=True, help="Path to QoS XML file")
    parser.add_argument("--duration", type=float, default=120.0, help="Run duration in seconds")
    parser.add_argument("--spawn-interval", type=float, default=30.0, help="Seconds between cell spawns (sim-time)")
    parser.add_argument("--publish-interval", type=float, default=300.0,
                        help="Cell publication interval in sim-time seconds (default: 300 = 5 min)")
    parser.add_argument("--max-cells", type=int, default=5, help="Max concurrent cells")
    args = parser.parse_args()

    common.QOS_FILE = args.qos_file

    svc = WeatherService(
        config_path=args.config,
        spawn_interval_s=args.spawn_interval,
        max_cells=args.max_cells,
        publish_interval_s=args.publish_interval,
    )
    svc.run(duration_s=args.duration)


if __name__ == "__main__":
    main()
