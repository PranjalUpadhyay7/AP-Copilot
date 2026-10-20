import pytest

from app.comms import mavlink_client
from app.comms.mavlink_client import MavlinkVehicleClient


class _Mav:
    def __init__(self):
        self.sent = 0

    def heartbeat_send(self, *a):
        self.sent += 1


class _Conn:
    def __init__(self, reply_after):
        self.mav, self.reply_after, self.polls, self.closed = _Mav(), reply_after, 0, False
        self.message_hooks = []  # pymavlink's per-message hook list

    def wait_heartbeat(self, timeout):
        self.polls += 1
        return object() if self.mav.sent >= self.reply_after else None

    def close(self):
        self.closed = True


def test_connect_sends_gcs_heartbeats_until_the_vehicle_answers(monkeypatch):
    conn = _Conn(reply_after=3)  # the board only speaks after the 3rd GCS heartbeat
    monkeypatch.setattr(mavlink_client.mavutil, "mavlink_connection", lambda s: conn)
    client = MavlinkVehicleClient("/dev/ttyACM0")
    client.connect()
    assert conn.mav.sent == 3 and client.is_connected


def test_connect_times_out_cleanly_and_closes(monkeypatch):
    conn = _Conn(reply_after=10**9)
    monkeypatch.setattr(mavlink_client.mavutil, "mavlink_connection", lambda s: conn)
    client = MavlinkVehicleClient("/dev/ttyACM0")
    with pytest.raises(TimeoutError):
        client.connect(timeout=0.05)
    assert conn.closed and not client.is_connected


def test_connect_hint_points_at_detected_serial_device(monkeypatch):
    from types import SimpleNamespace

    from app.api import routes_session

    monkeypatch.setattr(routes_session, "list_serial_ports", lambda: ["/dev/ttyACM0"])
    hint = routes_session._connect_hint(SimpleNamespace(mode="hardware", connection_string="tcp:127.0.0.1:5760"))
    assert "/dev/ttyACM0" in hint
    assert routes_session._connect_hint(SimpleNamespace(mode="simulation", connection_string="x")) == ""
    monkeypatch.setattr(routes_session, "list_serial_ports", list)
    assert "not present" in routes_session._connect_hint(SimpleNamespace(mode="hardware", connection_string="/dev/ttyACM0"))


def test_non_ardupilot_autopilot_is_refused_with_a_clear_message():
    from types import SimpleNamespace

    from app.knowledge.metadata_fetcher import (
        UnsupportedAutopilotError,
        fetch_autopilot_version,
    )

    class Conn:
        def recv_match(self, **kw):
            return SimpleNamespace(type=2, autopilot=12)  # MAV_AUTOPILOT_PX4

    with pytest.raises(UnsupportedAutopilotError, match="PX4, not ArduPilot") as e:
        fetch_autopilot_version(Conn(), timeout=1)
    assert isinstance(e.value, ConnectionError)  # -> the API's existing 502 "could not connect" path


def test_serial_error_mid_connect_becomes_connection_error(monkeypatch):
    class Dying(_Conn):
        def wait_heartbeat(self, timeout):
            raise OSError("device reports readiness to read but returned no data")

    conn = Dying(reply_after=0)
    monkeypatch.setattr(mavlink_client.mavutil, "mavlink_connection", lambda s: conn)
    client = MavlinkVehicleClient("/dev/ttyACM0")
    with pytest.raises(ConnectionError, match="rebooting or unplugged"):  # -> API 502, not a 500
        client.connect()
    assert conn.closed and not client.is_connected


def test_session_start_stream_emits_progress_then_final_or_error(monkeypatch):
    import json
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from app.api.session_manager import session_manager
    from app.main import app

    def fake_start(conn, *, progress, **kw):
        progress({"type": "progress", "stage": "download", "label": "x", "percent": 40.0})
        if conn == "boom":
            raise ConnectionError("nope")
        ctx = SimpleNamespace(live_params={}, vehicle_info={"frame_label": "Quadcopter"})
        return SimpleNamespace(session_id="s1", vehicle_type="ArduCopter", firmware_version="4.6.3", context=ctx, read_only=False)

    monkeypatch.setattr(session_manager, "start_session", fake_start)
    client = TestClient(app)

    def events(conn):
        r = client.post("/session/start/stream", json={"mode": "hardware", "connection_string": conn})
        return [json.loads(line[6:]) for line in r.text.split("\n\n") if line.startswith("data: ")]

    ok = events("auto")
    assert [e["type"] for e in ok] == ["progress", "final"] and ok[0]["percent"] == 40.0
    assert ok[1]["session_id"] == "s1" and ok[1]["firmware_version"] == "4.6.3"
    assert ok[1]["frame_label"] == "Quadcopter" and ok[1]["vehicle_type"] == "ArduCopter"
    bad = events("boom")
    assert [e["type"] for e in bad] == ["progress", "error"] and bad[1]["status"] == 502 and "nope" in bad[1]["detail"]


class _BeatConn(_Conn):
    def __init__(self):
        super().__init__(reply_after=1)


def _connected_client(monkeypatch, conn):
    monkeypatch.setattr(mavlink_client, "HEARTBEAT_INTERVAL_S", 0.02)
    monkeypatch.setattr(mavlink_client.mavutil, "mavlink_connection", lambda s: conn)
    client = MavlinkVehicleClient("/dev/ttyACM0")
    client.connect()
    return client


def test_gcs_heartbeat_keeps_flowing_after_connect_and_stops_on_disconnect(monkeypatch):
    import time

    conn = _BeatConn()
    client = _connected_client(monkeypatch, conn)
    after_handshake = conn.mav.sent
    time.sleep(0.3)
    assert conn.mav.sent >= after_handshake + 5  # ~15 beats expected at 20 ms; allow scheduler jitter
    client.disconnect()
    time.sleep(0.1)
    frozen = conn.mav.sent
    time.sleep(0.2)
    assert conn.mav.sent == frozen  # the thread really stopped


def test_heartbeat_thread_never_writes_while_another_operation_holds_the_lock(monkeypatch):
    import time

    conn = _BeatConn()
    client = _connected_client(monkeypatch, conn)
    with client._conn_lock:
        time.sleep(0.05)  # let any in-flight beat finish
        held = conn.mav.sent
        time.sleep(0.2)
        assert conn.mav.sent == held  # no interleaved write while the lock is held
    time.sleep(0.2)
    assert conn.mav.sent > held  # resumes afterwards
    client.disconnect()


def test_heartbeat_thread_exits_quietly_if_the_link_vanishes(monkeypatch):
    import time

    conn = _BeatConn()
    client = _connected_client(monkeypatch, conn)

    def dead(*a):
        raise OSError("device disconnected")

    conn.mav.heartbeat_send = dead
    time.sleep(0.2)  # the thread hits the error and stops; nothing is raised into the test
    client.disconnect()


def test_long_parameter_sweep_sends_its_own_heartbeats(monkeypatch):
    from app.knowledge import metadata_fetcher

    monkeypatch.setattr(metadata_fetcher, "KEEPALIVE_INTERVAL_S", 0.0)

    class Msg:
        def __init__(self, i):
            self.param_count, self.param_id, self.param_value, self.param_index = 3, f"P{i}", float(i), i

    class Conn:
        target_system = target_component = 1

        def __init__(self):
            self.msgs = [Msg(0), Msg(1), Msg(2)]
            self.mav = SimpleNamespaceMav()

        def recv_match(self, **kw):
            return self.msgs.pop(0) if self.msgs else None

    class SimpleNamespaceMav:
        def param_request_list_send(self, *a):
            pass

    beats = []
    values = metadata_fetcher.fetch_live_param_values(Conn(), keepalive=lambda: beats.append(1))
    assert values == {"P0": 0.0, "P1": 1.0, "P2": 2.0} and len(beats) >= 2
