from __future__ import annotations

import threading
from types import SimpleNamespace

from app.comms.mavlink_client import MavlinkVehicleClient


def _make_client() -> MavlinkVehicleClient:
    client = MavlinkVehicleClient()
    client._conn = SimpleNamespace(target_system=1, target_component=1)  # bypass connect()
    return client


def test_get_armed_state_blocks_while_another_method_holds_the_conn_lock():
    client = _make_client()
    holder_has_lock = threading.Event()
    release_holder = threading.Event()

    def hold_lock():
        with client._conn_lock:
            holder_has_lock.set()
            release_holder.wait(timeout=2.0)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert holder_has_lock.wait(timeout=2.0), "setup failed: holder never acquired the lock"

    recv_match_called = threading.Event()
    client._conn.recv_match = lambda **kwargs: (recv_match_called.set(), None)[1]

    waiter = threading.Thread(target=lambda: client.get_armed_state(timeout=0.5))
    waiter.start()

    assert not recv_match_called.wait(timeout=0.3), (
        "get_armed_state read the connection while another method still held _conn_lock"
    )

    release_holder.set()
    holder.join(timeout=2.0)
    waiter.join(timeout=2.0)
    assert recv_match_called.is_set()  # it does proceed once the lock is actually free


def test_stream_telemetry_acquires_the_same_lock_instance_per_poll():
    client = _make_client()
    seen_lock_states: list[bool] = []

    def fake_recv_match(**kwargs):
        seen_lock_states.append(client._conn_lock.locked())

    client._conn.recv_match = fake_recv_match

    list(client.stream_telemetry(fields=["ATTITUDE"], timeout=0.01, max_wait=0.05))

    assert len(seen_lock_states) >= 2
    # The lock IS held during each individual recv_match call...
    assert all(seen_lock_states)
    assert not client._conn_lock.locked()


def test_stream_params_and_get_autopilot_version_pass_the_real_conn_lock_through(monkeypatch):
    import app.comms.mavlink_client as mod

    client = _make_client()
    captured: dict[str, object] = {}

    def fake_fetch_live_param_values(conn, lock=None, **kwargs):
        captured["stream_params_lock"] = lock
        return {}

    def fake_fetch_autopilot_version(conn, lock=None, **kwargs):
        captured["autopilot_version_lock"] = lock
        return SimpleNamespace()

    monkeypatch.setattr(mod, "fetch_live_param_values", fake_fetch_live_param_values)
    monkeypatch.setattr(mod, "fetch_autopilot_version", fake_fetch_autopilot_version)

    client.stream_params()
    client.get_autopilot_version()

    assert captured["stream_params_lock"] is client._conn_lock
    assert captured["autopilot_version_lock"] is client._conn_lock
