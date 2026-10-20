"""SITL reachability smoke test."""
import os
import shutil
import socket
import subprocess
import time

import pytest
from pymavlink import mavutil

from app.comms.sitl_manager import terminate as _terminate_sitl

ARDUPILOT_ROOT = os.environ.get("ARDUPILOT_ROOT") or os.path.expanduser("~/ardupilot")
SIM_VEHICLE = os.path.join(ARDUPILOT_ROOT, "Tools/autotest/sim_vehicle.py")

SITL_PYTHON = os.environ.get("SITL_PYTHON") or shutil.which("python3", path="/usr/bin") or "/usr/bin/python3"

VEHICLES = {
    "copter": "ArduCopter",
    "plane": "ArduPlane",
}

TCP_PORT = 5760
PORT_WAIT_DEADLINE_S = 180
HEARTBEAT_WAIT_S = 30


def _wait_for_port(host: str, port: int, deadline: float) -> None:
    last_err = None
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                return
        except OSError as e:
            last_err = e
            time.sleep(2)
    raise TimeoutError(f"port {host}:{port} never became connectable: {last_err}")


def _sitl_env() -> dict:
    env = dict(os.environ)
    for var in ("DISPLAY", "TMUX", "STY", "ZELLIJ", "SITL_RITW_TERMINAL"):
        env.pop(var, None)
    return env


@pytest.mark.parametrize("vehicle,frame", [("copter", "quad"), ("plane", "plane")])
def test_sitl_heartbeat(vehicle, frame):
    if not os.path.exists(SIM_VEHICLE):
        pytest.skip(f"ArduPilot checkout not found at {ARDUPILOT_ROOT}")

    vtype = VEHICLES[vehicle]
    proc = subprocess.Popen(
        [
            SITL_PYTHON,
            SIM_VEHICLE,
            "-v", vtype,
            "-f", frame,
            "--no-mavproxy",
            "--no-rebuild",
            "-w",
        ],
        cwd=ARDUPILOT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=_sitl_env(),
    )
    try:
        deadline = time.time() + PORT_WAIT_DEADLINE_S
        _wait_for_port("127.0.0.1", TCP_PORT, deadline)

        conn = mavutil.mavlink_connection(f"tcp:127.0.0.1:{TCP_PORT}")
        try:
            msg = conn.wait_heartbeat(timeout=HEARTBEAT_WAIT_S)
            assert msg is not None, "no HEARTBEAT received within timeout"
            assert msg.get_type() == "HEARTBEAT"
        finally:
            conn.close()
    finally:
        _terminate_sitl(proc)
