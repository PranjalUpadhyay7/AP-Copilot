import os
import subprocess
import time

import pytest

from app.comms.mavlink_client import MavlinkVehicleClient
from app.comms.sitl_manager import terminate as _terminate_sitl

ARDUPILOT_ROOT = os.environ.get("ARDUPILOT_ROOT") or os.path.expanduser("~/ardupilot")
SIM_VEHICLE = os.path.join(ARDUPILOT_ROOT, "Tools/autotest/sim_vehicle.py")
SITL_PYTHON = os.environ.get("SITL_PYTHON", "/usr/bin/python3")

INSTANCE = 22
PORT = 5760 + 10 * INSTANCE

TEST_PARAM = "LOG_FILE_BUFSIZE"


def _sitl_env() -> dict:
    env = dict(os.environ)
    for var in ("DISPLAY", "TMUX", "STY", "ZELLIJ", "SITL_RITW_TERMINAL"):
        env.pop(var, None)
    return env


def _wait_port(port: int, deadline: float) -> None:
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
def sitl_copter():
    if not os.path.exists(SIM_VEHICLE):
        pytest.skip(f"ArduPilot checkout not found at {ARDUPILOT_ROOT}")
    proc = subprocess.Popen(
        [SITL_PYTHON, SIM_VEHICLE, "-v", "ArduCopter", "-f", "quad", "-I", str(INSTANCE),
         "--no-mavproxy", "--no-rebuild", "-w"],
        cwd=ARDUPILOT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=_sitl_env(),
    )
    try:
        _wait_port(PORT, time.time() + 180)
        yield f"tcp:127.0.0.1:{PORT}"
    finally:
        _terminate_sitl(proc)


def test_connect_stream_params_set_and_readback(sitl_copter):
    client = MavlinkVehicleClient(sitl_copter)
    client.connect()
    assert client.is_connected

    version = client.get_autopilot_version()
    assert version.vehicle_type == "ArduCopter"

    all_params = client.stream_params()
    assert TEST_PARAM in all_params
    original_value = all_params[TEST_PARAM]

    new_value = 42.0 if original_value != 42.0 else 43.0
    result = client.set_param(TEST_PARAM, new_value)
    assert result.acked is True
    assert result.matches is True

    readback = client.stream_params()
    assert readback[TEST_PARAM] == new_value

    # restore, so this test doesn't leave the vehicle's persisted state changed
    restore = client.set_param(TEST_PARAM, original_value)
    assert restore.matches is True

    client.disconnect()
    assert not client.is_connected


def test_disconnect_and_reconnect_cleanly(sitl_copter):
    client = MavlinkVehicleClient(sitl_copter)

    client.connect()
    assert client.is_connected
    first_version = client.get_autopilot_version()
    client.disconnect()
    assert not client.is_connected

    client.connect()
    assert client.is_connected
    second_version = client.get_autopilot_version()
    assert second_version.vehicle_type == first_version.vehicle_type

    params = client.stream_params()
    assert len(params) > 0

    client.disconnect()


def test_set_param_on_nonexistent_param_does_not_ack(sitl_copter):
    client = MavlinkVehicleClient(sitl_copter)
    client.connect()

    result = client.set_param("TOTALLY_NOT_A_REAL_PARAM_XYZ", 1.0, timeout=5.0)
    assert result.acked is False

    client.disconnect()


def test_statustext_buffer_collects_vehicle_diagnostics_while_reading_other_messages(sitl_copter):
    client = MavlinkVehicleClient(sitl_copter)
    client.connect()
    try:
        for _ in client.stream_telemetry(fields=["HEARTBEAT"], timeout=0.5, max_wait=40):
            if client.recent_status_messages():
                break
        messages = client.recent_status_messages()
        assert messages, "SITL prints boot diagnostics (EKF/GPS init); the buffer should have caught some"
        assert all(m["text"] and m["severity_label"] for m in messages)
    finally:
        client.disconnect()
