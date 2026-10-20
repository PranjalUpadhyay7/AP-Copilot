"""Serial-port discovery, labels and contention checks for flight controllers."""

from __future__ import annotations

import glob
import logging
import os
import re
import time

from pymavlink import mavutil

logger = logging.getLogger(__name__)

_KNOWN_FC = re.compile(
    r"ArduPilot|CubePilot|Cube|Hex|Holybro|mRo|3D_Robotics|PX4|CUAV|Radiolink|Matek|SpeedyBee|Pixhawk|Pixracer|Durandal|Kakute",
    re.IGNORECASE,
)


def friendly_label(by_id_name: str) -> str:
    name = re.sub(r"-if\d+(-port\d+)?$", "", re.sub(r"^usb-", "", by_id_name))
    parts = name.split("_")
    if len(parts) > 2 and re.fullmatch(r"[0-9A-Fa-f]{6,}|\d+", parts[-1]):
        parts = parts[:-1]
    return " ".join(parts)


def board_label_for(connection_string: str, simulation: bool = False) -> str | None:
    """Human name of the hardware behind a connection, for the UI header."""
    if simulation:
        return "Simulator (SITL)"
    device = connection_string.split(",")[0]
    if device.startswith("/dev/serial/by-id/"):
        return friendly_label(os.path.basename(device))
    if device.startswith(("/dev/ttyACM", "/dev/ttyUSB")):
        real = os.path.realpath(device)
        for alias in glob.glob("/dev/serial/by-id/*"):
            if os.path.realpath(alias) == real:
                return friendly_label(os.path.basename(alias))
    return None


def list_ports() -> list[dict]:
    entries: list[dict] = []
    seen: set[str] = set()
    for path in sorted(glob.glob("/dev/serial/by-id/*")):
        seen.add(os.path.realpath(path))
        name = os.path.basename(path)
        label = friendly_label(name)
        entries.append({"path": path, "label": label, "likely_fc": bool(_KNOWN_FC.search(name))})
    for path in sorted(glob.glob("/dev/ttyACM*")) + sorted(glob.glob("/dev/ttyUSB*")):
        if os.path.realpath(path) in seen:
            continue
        entries.append({"path": path, "label": os.path.basename(path), "likely_fc": "ttyACM" in path})
    return entries


def stable_port_path(connection_string: str) -> str:
    """Prefer the stable /dev/serial/by-id alias of a raw serial device."""
    device, sep, baud = connection_string.partition(",")
    if not device.startswith(("/dev/ttyACM", "/dev/ttyUSB")):
        return connection_string
    real = os.path.realpath(device)
    for alias in sorted(glob.glob("/dev/serial/by-id/*")):
        if os.path.realpath(alias) == real:
            return alias + sep + baud
    return connection_string


def port_holders(path: str) -> list[tuple[int, str]]:
    """Other processes that have the device open (Linux /proc scan)."""
    device = os.path.realpath(path.split(",")[0])
    me = os.getpid()
    holders: list[tuple[int, str]] = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or int(entry) == me:
            continue
        try:
            for fd in os.listdir(f"/proc/{entry}/fd"):
                # readlink, not realpath: realpath over every process's descriptors took ~20 s
                if os.readlink(f"/proc/{entry}/fd/{fd}") == device:
                    with open(f"/proc/{entry}/cmdline", "rb") as f:
                        cmd = f.read().replace(b"\0", b" ").decode(errors="ignore").strip()
                    holders.append((int(entry), cmd[:80]))
                    break
        except OSError:
            continue
    return holders


def find_flight_controller(timeout_per_port: float = 4.0) -> str | None:
    """First serial port that answers with a MAVLink HEARTBEAT."""
    for entry in sorted(list_ports(), key=lambda e: not e["likely_fc"]):
        if port_holders(entry["path"]):
            logger.info("skipping %s while auto-detecting: already open in another process", entry["path"])
            continue
        try:
            conn = mavutil.mavlink_connection(entry["path"])
        except Exception as e:  # noqa: BLE001 -- busy/permission-denied port: just try the next one
            logger.info("skipping %s while auto-detecting: %s", entry["path"], e)
            continue
        try:
            deadline = time.time() + timeout_per_port
            while time.time() < deadline:
                conn.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_GCS, mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0,
                    mavutil.mavlink.MAV_STATE_ACTIVE,
                )
                if conn.wait_heartbeat(timeout=1) is not None:
                    return entry["path"]
        except OSError as e:  # device vanished mid-probe; try the next one
            logger.info("lost %s while auto-detecting: %s", entry["path"], e)
        finally:
            conn.close()
    return None
