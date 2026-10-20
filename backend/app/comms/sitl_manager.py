"""SITL process management for the "Simulation" connect mode."""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from dataclasses import dataclass

ARDUPILOT_ROOT = os.environ.get("ARDUPILOT_ROOT") or os.path.join(os.path.expanduser("~"), "ardupilot")
SITL_PYTHON = os.environ.get("SITL_PYTHON", "/usr/bin/python3")
SIM_VEHICLE_PY = os.path.join(ARDUPILOT_ROOT, "Tools/autotest/sim_vehicle.py")

_VEHICLE_TYPE_BY_KEY = {"copter": "ArduCopter", "plane": "ArduPlane"}
_DEFAULT_FRAME_BY_KEY = {"copter": "quad", "plane": "plane"}
_BINARY_NAME_BY_VEHICLE = {"ArduCopter": "arducopter", "ArduPlane": "arduplane"}


class SITLLaunchError(RuntimeError):
    pass


@dataclass
class SITLSettings:
    vehicle: str = "copter"   # "copter" | "plane"
    frame: str | None = None  # defaults per-vehicle if omitted
    instance: int = 0         # port offset: tcp:127.0.0.1:(5760 + 10*instance)
    wipe_eeprom: bool = True
    speedup: int = 1

    def connection_string(self) -> str:
        return f"tcp:127.0.0.1:{5760 + 10 * self.instance}"


def launch(settings: SITLSettings, *, timeout: float = 180.0) -> subprocess.Popen:
    """Start an ArduPilot SITL instance and wait for its MAVLink port."""
    if settings.vehicle not in _VEHICLE_TYPE_BY_KEY:
        raise SITLLaunchError(f"unknown simulated vehicle '{settings.vehicle}', expected 'copter' or 'plane'")
    if not os.path.exists(SIM_VEHICLE_PY):
        raise SITLLaunchError(f"ArduPilot checkout not found at {ARDUPILOT_ROOT}")

    vtype = _VEHICLE_TYPE_BY_KEY[settings.vehicle]
    frame = settings.frame or _DEFAULT_FRAME_BY_KEY[settings.vehicle]
    port = 5760 + 10 * settings.instance

    if _port_already_open(port):
        raise SITLLaunchError(
            f"port {port} (instance {settings.instance}) is already in use by another "
            "process -- likely a leftover SITL instance from a previous session that "
            "didn't shut down cleanly. Stop it first, or pick a different instance number."
        )

    cmd = [
        SITL_PYTHON, SIM_VEHICLE_PY,
        "-v", vtype, "-f", frame,
        "-I", str(settings.instance),
        "--speedup", str(settings.speedup),
        "--no-mavproxy",
    ]
    if settings.wipe_eeprom:
        cmd.append("-w")
    binary_name = _BINARY_NAME_BY_VEHICLE.get(vtype)
    if binary_name and os.path.exists(os.path.join(ARDUPILOT_ROOT, "build", "sitl", "bin", binary_name)):
        cmd.append("--no-rebuild")

    env = dict(os.environ)
    env["PATH"] = "/usr/bin:" + env.get("PATH", "")
    for terminal_env_var in ("DISPLAY", "TMUX", "STY", "ZELLIJ", "SITL_RITW_TERMINAL"):
        env.pop(terminal_env_var, None)

    proc = subprocess.Popen(
        cmd, cwd=ARDUPILOT_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        # Own process group so terminate() reaches SITL's children as well
        start_new_session=True, env=env,
    )

    try:
        _wait_port(port, time.time() + timeout)
    except TimeoutError as e:
        terminate(proc)
        raise SITLLaunchError(
            f"SITL for {vtype}/{frame} (instance {settings.instance}) did not open port {port} "
            f"within {timeout}s"
        ) from e

    if proc.poll() is not None:
        raise SITLLaunchError(
            f"SITL for {vtype}/{frame} (instance {settings.instance}) exited immediately "
            f"(exit code {proc.returncode}) even though port {port} is open -- something "
            "else is using it. Not connecting to a vehicle this launch doesn't own."
        )
    return proc


def _port_already_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def _wait_port(port: int, deadline: float) -> None:
    last_err: OSError | None = None
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                return
        except OSError as e:
            last_err = e
            time.sleep(2)
    raise TimeoutError(f"port {port} never opened: {last_err}")


def terminate(proc: subprocess.Popen) -> None:
    """Stop SITL's whole process group and wait until it is gone."""
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
