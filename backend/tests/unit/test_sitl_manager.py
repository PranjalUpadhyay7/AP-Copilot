import os
from unittest.mock import MagicMock, patch

import pytest

from app.comms import sitl_manager
from app.comms.sitl_manager import SITLLaunchError, SITLSettings, launch


@pytest.fixture(autouse=True)
def _fake_ardupilot_checkout(tmp_path, monkeypatch):
    script = tmp_path / "sim_vehicle.py"
    script.write_text("")
    monkeypatch.setattr(sitl_manager, "SIM_VEHICLE_PY", str(script))
    monkeypatch.setattr(sitl_manager, "ARDUPILOT_ROOT", str(tmp_path))


def _running_proc() -> MagicMock:
    proc = MagicMock()
    proc.poll.return_value = None
    return proc


def test_connection_string_default_instance():
    assert SITLSettings().connection_string() == "tcp:127.0.0.1:5760"


def test_connection_string_offset_by_instance():
    assert SITLSettings(instance=30).connection_string() == "tcp:127.0.0.1:6060"


def test_launch_rejects_unknown_vehicle():
    with pytest.raises(SITLLaunchError, match="unknown simulated vehicle"):
        launch(SITLSettings(vehicle="rover"))


def test_launch_missing_checkout_raises(monkeypatch):
    monkeypatch.setattr("app.comms.sitl_manager.SIM_VEHICLE_PY", "/nonexistent/sim_vehicle.py")
    with pytest.raises(SITLLaunchError, match="ArduPilot checkout not found"):
        launch(SITLSettings())


def test_launch_rejects_port_already_in_use():
    with (
        patch("app.comms.sitl_manager._port_already_open", return_value=True),
        patch("subprocess.Popen") as mock_popen,
        pytest.raises(SITLLaunchError, match="already in use"),
    ):
        launch(SITLSettings())
    mock_popen.assert_not_called()


def test_launch_rejects_if_own_process_exited_despite_port_open():
    dead_proc = MagicMock()
    dead_proc.poll.return_value = 1  # already exited, non-None
    with (
        patch("app.comms.sitl_manager._port_already_open", return_value=False),
        patch("subprocess.Popen", return_value=dead_proc),
        patch("app.comms.sitl_manager._wait_port"),
        patch("os.path.exists", return_value=True),
        pytest.raises(SITLLaunchError, match="exited immediately"),
    ):
        launch(SITLSettings())


def test_launch_terminates_process_on_port_timeout():
    fake_proc = _running_proc()
    with (
        patch("app.comms.sitl_manager._port_already_open", return_value=False),
        patch("subprocess.Popen", return_value=fake_proc),
        patch("app.comms.sitl_manager._wait_port", side_effect=TimeoutError("never opened")),
        patch("app.comms.sitl_manager.terminate") as mock_terminate,
        patch("os.path.exists", return_value=True),
        pytest.raises(SITLLaunchError, match="did not open port"),
    ):
        launch(SITLSettings(), timeout=1)
    mock_terminate.assert_called_once_with(fake_proc)


def _existing_paths(*existing: str):
    def _exists(path):
        return path in existing
    return _exists


def test_launch_skips_rebuild_when_binary_already_exists():
    fake_proc = _running_proc()
    binary_path = os.path.join(sitl_manager.ARDUPILOT_ROOT, "build", "sitl", "bin", "arducopter")
    captured = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return fake_proc

    with (
        patch("app.comms.sitl_manager._port_already_open", return_value=False),
        patch("subprocess.Popen", side_effect=fake_popen),
        patch("app.comms.sitl_manager._wait_port"),
        patch("os.path.exists", side_effect=_existing_paths(sitl_manager.SIM_VEHICLE_PY, binary_path)),
    ):
        launch(SITLSettings())

    assert "--no-rebuild" in captured["cmd"]


def test_launch_strips_terminal_env_vars_from_subprocess_env(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":1")
    monkeypatch.setenv("TMUX", "some-tmux-value")
    fake_proc = _running_proc()
    captured = {}

    def fake_popen(cmd, **kwargs):
        captured["env"] = kwargs["env"]
        return fake_proc

    with (
        patch("app.comms.sitl_manager._port_already_open", return_value=False),
        patch("subprocess.Popen", side_effect=fake_popen),
        patch("app.comms.sitl_manager._wait_port"),
        patch("os.path.exists", return_value=True),
    ):
        launch(SITLSettings())

    for var in ("DISPLAY", "TMUX", "STY", "ZELLIJ", "SITL_RITW_TERMINAL"):
        assert var not in captured["env"]


def test_launch_still_builds_when_binary_missing_first_time():
    fake_proc = _running_proc()
    captured = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return fake_proc

    with (
        patch("app.comms.sitl_manager._port_already_open", return_value=False),
        patch("subprocess.Popen", side_effect=fake_popen),
        patch("app.comms.sitl_manager._wait_port"),
        patch("os.path.exists", side_effect=_existing_paths(sitl_manager.SIM_VEHICLE_PY)),
    ):
        launch(SITLSettings())

    assert "--no-rebuild" not in captured["cmd"]
