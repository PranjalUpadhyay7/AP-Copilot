from types import SimpleNamespace

from app.comms import mavlink_client
from app.comms.mavlink_client import MavlinkVehicleClient
from app.comms.status_text import StatusTextBuffer
from app.orchestrator import tools
from app.orchestrator.tools import RuntimeContext


def test_repeats_merge_with_a_count_and_ages_are_reported():
    b = StatusTextBuffer()
    for t in (100.0, 102.0, 104.0):
        b.add(4, "PreArm: Compass not calibrated", now=t)
    b.add(6, "EKF3 IMU0 is using GPS", now=105.0)
    out = b.recent(now=110.0)
    assert [(e["text"], e["count"], e["seconds_ago"]) for e in out] == [
        ("PreArm: Compass not calibrated", 3, 6), ("EKF3 IMU0 is using GPS", 1, 5),
    ]
    assert out[0]["severity_label"] == "WARNING"


def test_chunked_long_messages_are_rejoined_and_blank_text_is_ignored():
    b = StatusTextBuffer()
    b.add(4, "PreArm: this is a very long message that ArduPilot ", chunk_id=7, chunk_seq=0, now=1.0)
    b.add(4, "split into two chunks", chunk_id=7, chunk_seq=1, now=1.0)
    b.add(4, "\x00\x00", now=2.0)
    assert [e["text"] for e in b.recent(now=3.0)] == ["PreArm: this is a very long message that ArduPilot split into two chunks"]


def test_the_ring_buffer_keeps_only_the_newest_entries():
    b = StatusTextBuffer(maxlen=3)
    for i in range(10):
        b.add(6, f"message {i}", now=float(i))
    assert [e["text"] for e in b.recent(now=10.0)] == ["message 7", "message 8", "message 9"]


def test_connect_installs_a_hook_that_records_statustext_whatever_the_reader_filtered_for(monkeypatch):
    class Mav:
        def heartbeat_send(self, *a):
            pass

    class Conn:
        def __init__(self):
            self.mav, self.message_hooks = Mav(), []

        def wait_heartbeat(self, timeout):
            return object()

        def close(self):
            pass

    conn = Conn()
    monkeypatch.setattr(mavlink_client.mavutil, "mavlink_connection", lambda s: conn)
    client = MavlinkVehicleClient("/dev/ttyACM0")
    client.connect()
    assert len(conn.message_hooks) == 1
    stext = SimpleNamespace(get_type=lambda: "STATUSTEXT", severity=4, text="PreArm: RC not found", id=0, chunk_seq=0)
    other = SimpleNamespace(get_type=lambda: "ATTITUDE")
    conn.message_hooks[0](conn, other)
    conn.message_hooks[0](conn, stext)
    assert [e["text"] for e in client.recent_status_messages()] == ["PreArm: RC not found"]
    client.disconnect()


def test_tool_prefers_the_buffer_and_falls_back_for_clients_without_one(monkeypatch):
    buf = [{"severity": 4, "severity_label": "WARNING", "text": "PreArm: x", "count": 2, "seconds_ago": 3}]
    ctx = RuntimeContext(session_id="s", live_params={}, audit_logger=None,
                         vehicle_client=SimpleNamespace(recent_status_messages=lambda n: buf))
    assert tools._get_recent_status_messages(ctx) == buf
    ctx.vehicle_client = SimpleNamespace(recent_status_messages=lambda n: [])  # buffer exists, nothing yet
    assert "since this session connected" in tools._get_recent_status_messages(ctx)
    monkeypatch.setattr(tools, "collect_recent_statustext", lambda c, max_count: [{"text": "live"}])
    ctx.vehicle_client = SimpleNamespace(recent_status_messages=lambda n: None)  # no buffer: short live capture
    assert tools._get_recent_status_messages(ctx) == [{"text": "live"}]
    ctx.vehicle_client = SimpleNamespace()  # an older client object without the method
    assert tools._get_recent_status_messages(ctx) == [{"text": "live"}]
