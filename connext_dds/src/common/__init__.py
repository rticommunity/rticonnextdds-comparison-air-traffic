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
SIM_SPEED_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "config", ".sim_speed")
SCENARIO_CONFIG = os.path.join(os.path.dirname(__file__), "..", "..", "config", "scenario_default.json")


def load_airport_coords(config_path: str = SCENARIO_CONFIG) -> dict[str, tuple[float, float]]:
    """Load airport (code → (lat, lon)) mapping from scenario config JSON."""
    with open(config_path) as f:
        data = json.load(f)
    return {
        a["code"]: (a["latitude"], a["longitude"])
        for a in data["airports"]
    }


def read_sim_speed() -> float:
    """Read simulation speed multiplier from shared file. Returns 1.0 on error."""
    try:
        with open(SIM_SPEED_FILE) as f:
            return max(0.1, min(50.0, float(f.read().strip())))
    except (FileNotFoundError, ValueError):
        return 1.0


def write_sim_speed(speed: float) -> None:
    """Write simulation speed multiplier to shared file."""
    speed = max(0.1, min(50.0, speed))
    with open(SIM_SPEED_FILE, "w") as f:
        f.write(str(speed))


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
) -> dds.DomainParticipant:
    participant_qos = qos_provider.participant_qos_from_profile(
        f"{QOS_LIB}::AtcParticipantProfile"
    )
    if dp_partitions:
        participant_qos.partition.name = dp_partitions
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
