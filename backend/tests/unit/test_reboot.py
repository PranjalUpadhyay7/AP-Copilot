from types import SimpleNamespace

import pytest

from app.api import session_manager as sm_mod
from app.api.session_manager import SessionManager
from app.models.telemetry import CommandResult
from app.models.vehicle import VehicleVersionInfo


def _version(h="92b0cd78", vt="ArduCopter"):
    return VehicleVersionInfo(vehicle_type=vt, mav_type=2, board_type=0, flight_sw_version="4.6.3", git_hash=h)


class FakeClient:
    def __init__(self, armed=False, ack=True, version=None, connect_failures=0):
        self.armed, self.ack, self.version = armed, ack, version or _version()
        self.sent, self.connected, self.failures = [], True, connect_failures

    def get_armed_state(self, timeout=3.0):
        return self.armed

    def send_command(self, command, params=(), timeout=5.0):
        self.sent.append((command, params))
        if self.ack is None:
            return CommandResult(command=command, accepted=False, result_code=None)  # no ACK: normal on reset
        return CommandResult(command=command, accepted=self.ack, result_code=0 if self.ack else 4)

    def disconnect(self):
        self.connected = False

    def connect(self, timeout=30.0):
        if self.failures > 0:
            self.failures -= 1
            raise ConnectionError("port not back yet")
        self.connected = True

    def get_autopilot_version(self):
        return self.version


class Audit:
    def __init__(self):
        self.events = []

    def log_reboot(self, session_id, reason=""):
        self.events.append(session_id)


def _session(client, pending=None, pending_props=None):
    graph = SimpleNamespace(get_state=lambda cfg: SimpleNamespace(values={"pending_proposal": pending}))
    ctx = SimpleNamespace(
        vehicle_client=client, audit_logger=Audit(), pending_proposals=pending_props or {}, pending_procedures={},
        vehicle_info={"vehicle_type": "ArduCopter", "git_hash": "92b0cd78"}, live_params={},
    )
    return SimpleNamespace(
        session_id="s1", graph=graph, thread_config={}, context=ctx, rebooting=False, connection_string="/dev/ttyACM0",
    )


def _manager(monkeypatch, new_client):
    sm = SessionManager.__new__(SessionManager)
    monkeypatch.setattr(sm_mod, "MavlinkVehicleClient", lambda cs: new_client)
    monkeypatch.setattr(SessionManager, "refresh_live_params", lambda self, s: s.context.__setattr__("live_params", {"A": 1, "B": 2}))
    return sm


@pytest.mark.parametrize("armed,msg", [(True, "armed"), (None, "could not confirm")])
def test_reboot_refused_unless_confirmed_disarmed(monkeypatch, armed, msg):
    old = FakeClient(armed=armed)
    session = _session(old)
    with pytest.raises(RuntimeError, match=msg):
        _manager(monkeypatch, FakeClient()).reboot_vehicle(session, settle_s=0)
    assert old.sent == [] and old.connected and not session.rebooting and session.context.audit_logger.events == []


def test_reboot_refused_while_a_proposal_is_pending(monkeypatch):
    for kw in ({"pending": {"proposal_id": "p"}}, {"pending_props": {"p": object()}}):
        old = FakeClient()
        with pytest.raises(RuntimeError, match="pending"):
            _manager(monkeypatch, FakeClient()).reboot_vehicle(_session(old, **kw), settle_s=0)
        assert old.sent == []


def test_reboot_reconnects_the_same_session_and_reports_link_down_then_up(monkeypatch):
    old, new = FakeClient(), FakeClient(connect_failures=2)
    session, events = _session(old), []
    result = _manager(monkeypatch, new).reboot_vehicle(session, events.append, settle_s=0, reconnect_timeout=30)
    assert old.sent == [(246, (1.0,))] and not old.connected  # MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN, param1=1 (autopilot)
    assert session.context.vehicle_client is new and new.connected  # same session, new link
    assert session.context.audit_logger.events == ["s1"]
    assert result == {"param_count": 2, "armed": False} and not session.rebooting
    links = [e["link"] for e in events]
    assert links[0] == "up" and "down" in links and links[-1] == "up"
    assert [e["percent"] for e in events] == sorted(e["percent"] for e in events) and events[-1]["percent"] == 100


def test_no_command_ack_is_normal_but_an_explicit_refusal_is_not(monkeypatch):
    _manager(monkeypatch, FakeClient()).reboot_vehicle(_session(FakeClient(ack=None)), settle_s=0)  # board reset before answering
    old = FakeClient(ack=False)
    session = _session(old)
    with pytest.raises(RuntimeError, match="refused the reboot"):
        _manager(monkeypatch, FakeClient()).reboot_vehicle(session, settle_s=0)
    assert old.connected and not session.rebooting  # still on the old link: nothing was torn down


def test_different_firmware_after_reboot_aborts_without_swapping_clients(monkeypatch):
    old, other = FakeClient(), FakeClient(version=_version(h="deadbeef"))
    session = _session(old)
    with pytest.raises(ConnectionError, match="not the firmware this chat was about"):
        _manager(monkeypatch, other).reboot_vehicle(session, settle_s=0)
    assert session.context.vehicle_client is old and not other.connected and not session.rebooting


def test_vehicle_that_never_returns_times_out_and_clears_the_flag(monkeypatch):
    session = _session(FakeClient())
    with pytest.raises(TimeoutError, match="did not come back"):
        _manager(monkeypatch, FakeClient(connect_failures=10**6)).reboot_vehicle(session, settle_s=0, reconnect_timeout=0.05)
    assert not session.rebooting


def test_chat_is_blocked_while_rebooting():
    session = SimpleNamespace(rebooting=True)
    with pytest.raises(RuntimeError, match="rebooting"):
        SessionManager._require_not_rebooting(session)
    SessionManager._require_not_rebooting(SimpleNamespace(rebooting=False))  # no error when idle


def test_reboot_stream_route_maps_refusals_to_409_and_streams_events(monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from app.main import app

    def fake_reboot(session, progress, **kw):
        progress({"type": "progress", "stage": "x", "label": "l", "percent": 50.0, "link": "down"})
        if session == "armed":
            raise RuntimeError("the vehicle is armed -- disarm it before rebooting")
        return {"param_count": 7, "armed": False}

    monkeypatch.setattr(sm_mod.session_manager, "get", lambda sid: {"ok": "fine", "armed": "armed"}[sid])
    monkeypatch.setattr(sm_mod.session_manager, "reboot_vehicle", fake_reboot)
    client = TestClient(app)

    def events(sid):
        r = client.post(f"/session/reboot/stream?session_id={sid}")
        return [json.loads(line[6:]) for line in r.text.split("\n\n") if line.startswith("data: ")]

    ok = events("ok")
    assert [e["type"] for e in ok] == ["progress", "final"] and ok[0]["link"] == "down" and ok[1]["param_count"] == 7
    bad = events("armed")
    assert bad[-1]["type"] == "error" and bad[-1]["status"] == 409 and "armed" in bad[-1]["detail"]
