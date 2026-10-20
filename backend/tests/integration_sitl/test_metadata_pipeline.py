import os
import subprocess
import time

import pytest
from pymavlink import mavutil

from app.comms.sitl_manager import terminate as _terminate_sitl
from app.knowledge.metadata_fetcher import (
    MetadataCache,
    fetch_autopilot_version,
    fetch_live_param_values,
    get_param_definitions,
    reconcile,
)

ARDUPILOT_ROOT = os.environ.get("ARDUPILOT_ROOT") or os.path.expanduser("~/ardupilot")
SIM_VEHICLE = os.path.join(ARDUPILOT_ROOT, "Tools/autotest/sim_vehicle.py")
SITL_PYTHON = os.environ.get("SITL_PYTHON", "/usr/bin/python3")

VEHICLES = {
    "copter": ("ArduCopter", "quad", 20, 5960),
    "plane": ("ArduPlane", "plane", 21, 5970),
}


def _sitl_env() -> dict:
    env = dict(os.environ)
    for var in ("DISPLAY", "TMUX", "STY", "ZELLIJ", "SITL_RITW_TERMINAL"):
        env.pop(var, None)
    return env


def _boot_sitl(vtype: str, frame: str, instance: int):
    if not os.path.exists(SIM_VEHICLE):
        pytest.skip(f"ArduPilot checkout not found at {ARDUPILOT_ROOT}")
    proc = subprocess.Popen(
        [SITL_PYTHON, SIM_VEHICLE, "-v", vtype, "-f", frame, "-I", str(instance),
         "--no-mavproxy", "--no-rebuild", "-w"],
        cwd=ARDUPILOT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=_sitl_env(),
    )
    return proc


def _wait_port(port: int, deadline: float):
    import socket

    last_err = None
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                return
        except OSError as e:
            last_err = e
            time.sleep(2)
    raise TimeoutError(f"port {port} never opened: {last_err}")


@pytest.fixture
def sitl_connection():
    procs = []

    def _connect(vehicle: str):
        vtype, frame, instance, port = VEHICLES[vehicle]
        proc = _boot_sitl(vtype, frame, instance)
        procs.append(proc)
        _wait_port(port, time.time() + 180)
        conn = mavutil.mavlink_connection(f"tcp:127.0.0.1:{port}")
        conn.wait_heartbeat(timeout=30)
        return conn

    yield _connect

    for proc in procs:
        _terminate_sitl(proc)


def test_copter_and_plane_produce_distinct_cached_param_sets(sitl_connection, tmp_path):
    cache = MetadataCache(root=tmp_path)

    conn = sitl_connection("copter")
    copter_version = fetch_autopilot_version(conn)
    assert copter_version.vehicle_type == "ArduCopter"
    copter_values = fetch_live_param_values(conn, timeout=60)
    conn.close()

    copter_defs = get_param_definitions(
        copter_version, cache=cache, ardupilot_root=ARDUPILOT_ROOT, trust_local_checkout=True,
    )
    assert copter_defs is not None
    assert "ARMING_SKIPCHK" in copter_defs
    assert "ATC_ANG_RLL_P" in copter_defs  # copter-only attitude controller param

    conn = sitl_connection("plane")
    plane_version = fetch_autopilot_version(conn)
    assert plane_version.vehicle_type == "ArduPlane"
    plane_values = fetch_live_param_values(conn, timeout=60)
    conn.close()

    plane_defs = get_param_definitions(
        plane_version, cache=cache, ardupilot_root=ARDUPILOT_ROOT, trust_local_checkout=True,
    )
    assert plane_defs is not None
    assert "ARMING_SKIPCHK" in plane_defs
    assert "ATC_ANG_RLL_P" not in plane_defs  # not a plane param

    # distinct, cached, version-keyed on disk
    assert cache.get("ArduCopter", copter_version.version_key) is not None
    assert cache.get("ArduPlane", plane_version.version_key) is not None
    assert set(copter_defs) != set(plane_defs)

    copter_reconciled = reconcile(copter_values, copter_defs)
    plane_reconciled = reconcile(plane_values, plane_defs)
    assert copter_reconciled["ARMING_SKIPCHK"].is_documented
    assert plane_reconciled["ARMING_SKIPCHK"].is_documented


def test_unknown_firmware_falls_back_to_read_only_without_crash(sitl_connection, tmp_path):
    from app.models.vehicle import VehicleVersionInfo

    cache = MetadataCache(root=tmp_path)
    fake_version = VehicleVersionInfo(
        vehicle_type="ArduCopter",
        mav_type=2,
        board_type=0,
        flight_sw_version="0.0.0",
        git_hash="deadbeefdeadbeef",  # not in cache, not the local checkout's hash
    )

    definitions = get_param_definitions(fake_version, cache=cache)
    assert definitions is None
    assert cache.get("ArduCopter", "deadbeefdeadbeef") is None

    conn = sitl_connection("copter")
    live_values = fetch_live_param_values(conn, timeout=60)
    conn.close()

    reconciled = reconcile(live_values, definitions)
    assert len(reconciled) == len(live_values)
    assert all(not p.is_documented for p in reconciled.values())
