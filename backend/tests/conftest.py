import pytest


@pytest.fixture(autouse=True)
def _isolated_rl_log(tmp_path, monkeypatch):
    monkeypatch.setenv("AP_COPILOT_RL_LOG", str(tmp_path / "rl_training_log.jsonl"))
    monkeypatch.setenv("AP_COPILOT_SKIP_ORPHAN_CLEANUP", "1")


@pytest.fixture(autouse=True)
def _no_real_serial_port_holders(monkeypatch):
    from app.comms import serial_ports

    monkeypatch.setattr(serial_ports, "port_holders", lambda path: [])
