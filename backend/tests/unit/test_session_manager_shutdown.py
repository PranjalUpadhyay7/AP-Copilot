import sqlite3
from datetime import UTC, datetime
from unittest.mock import MagicMock

from app.api.session_manager import Session, SessionManager


def _fake_session(session_id: str, *, ended_at=None) -> Session:
    vehicle_client = MagicMock()
    return Session(
        session_id=session_id,
        started_at=datetime.now(UTC),
        ended_at=ended_at,
        vehicle_type="ArduCopter",
        firmware_version="4.6.0",
        read_only=False,
        context=MagicMock(vehicle_client=vehicle_client, pending_proposals={}),
        graph=MagicMock(),
        thread_config={},
        _checkpoint_conn=sqlite3.connect(":memory:"),
        _sitl_process=None,  # no real SITL process to terminate
    )


def _bare_session_manager() -> SessionManager:
    sm = SessionManager.__new__(SessionManager)
    sm._sessions = {}
    sm.session_store = MagicMock()
    return sm


def test_end_all_active_sessions_ends_every_still_active_session():
    sm = _bare_session_manager()
    sm._sessions["a"] = _fake_session("a")
    sm._sessions["b"] = _fake_session("b")

    sm.end_all_active_sessions()

    assert sm._sessions["a"].ended_at is not None
    assert sm._sessions["b"].ended_at is not None
    sm._sessions["a"].context.vehicle_client.disconnect.assert_called_once()
    sm._sessions["b"].context.vehicle_client.disconnect.assert_called_once()


def test_end_all_active_sessions_skips_already_ended_sessions():
    sm = _bare_session_manager()
    already_ended = _fake_session("already-ended", ended_at=datetime.now(UTC))
    sm._sessions["already-ended"] = already_ended

    sm.end_all_active_sessions()

    already_ended.context.vehicle_client.disconnect.assert_not_called()


def test_end_all_active_sessions_one_failure_does_not_block_the_rest():
    sm = _bare_session_manager()
    failing = _fake_session("failing")
    failing.context.vehicle_client.disconnect.side_effect = RuntimeError("boom")
    healthy = _fake_session("healthy")
    sm._sessions["failing"] = failing
    sm._sessions["healthy"] = healthy

    sm.end_all_active_sessions()  # must not raise

    healthy.context.vehicle_client.disconnect.assert_called_once()
    assert healthy.ended_at is not None


def test_end_all_active_sessions_noop_when_no_sessions():
    sm = _bare_session_manager()
    sm.end_all_active_sessions()  # must not raise
