from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite import SqliteSaver

from app.api.session_manager import Session, SessionManager, session_manager
from app.audit.logger import AuditLogger
from app.comms.vehicle_client import VehicleClient
from app.main import app
from app.models.params import LiveParam, ParamDefinition
from app.models.telemetry import CommandResult, ParamSetResult
from app.orchestrator.graph import build_graph
from app.orchestrator.tools import RuntimeContext
from tests.adversarial_llm.fake_chat_model import (
    ScriptedChatModel,
    final_message,
    tool_call_message,
)


class _FakeVehicleClient(VehicleClient):
    def __init__(self):
        self.set_param_calls: list[tuple[str, float]] = []

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    @property
    def is_connected(self) -> bool:
        return True

    def get_autopilot_version(self):
        raise NotImplementedError

    def stream_params(self) -> dict[str, float]:
        raise NotImplementedError

    def set_param(self, name: str, value: float, timeout: float = 10.0) -> ParamSetResult:
        self.set_param_calls.append((name, value))
        return ParamSetResult(name=name, requested_value=value, acked_value=value, acked=True)

    def stream_telemetry(self, fields=None, timeout: float = 1.0, max_wait: float | None = None):
        return iter([])

    def send_command(self, command: int, params: tuple[float, ...] = (), timeout: float = 5.0) -> CommandResult:
        raise NotImplementedError

    def get_armed_state(self, timeout: float = 3.0) -> bool | None:
        return False


def _make_session(model: ScriptedChatModel, session_id: str = "stream-test") -> Session:
    definition = ParamDefinition(
        name="ATC_ANG_RLL_P", vehicle_types=["ArduCopter"], firmware_version="4.6.0",
        description="d", min_value=0.5, max_value=12.0,
    )
    live_params = {"ATC_ANG_RLL_P": LiveParam(name="ATC_ANG_RLL_P", current_value=4.5, definition=definition)}
    context = RuntimeContext(
        session_id=session_id, vehicle_client=_FakeVehicleClient(), live_params=live_params,
        audit_logger=AuditLogger(db_path=":memory:"),
    )
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    thread_config = {"configurable": {"thread_id": session_id}}
    graph = build_graph(context, model, checkpointer)
    return Session(
        session_id=session_id, started_at=datetime.now(UTC), ended_at=None,
        vehicle_type="ArduCopter", firmware_version="4.6.0", read_only=False,
        context=context, graph=graph, thread_config=thread_config,
        _checkpoint_conn=conn, _sitl_process=None,
    )


def _parse_sse_events(body: str) -> list[dict]:
    events = []
    for block in body.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


def test_stream_emits_tool_call_step_then_final_reply():
    model = ScriptedChatModel(responses=[
        tool_call_message("get_current_param", {"name": "ATC_ANG_RLL_P"}, "call_1"),
        final_message("it's currently 4.5"),
    ])
    session = _make_session(model)

    with (
        patch.object(session_manager, "get", return_value=session),
        TestClient(app) as client,
    ):
        resp = client.post("/chat/stream", json={"session_id": session.session_id, "message": "what's the value"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse_events(resp.text)

    step_events = [e for e in events if e["type"] == "step"]
    final_events = [e for e in events if e["type"] == "final"]
    assert len(final_events) == 1
    assert len(step_events) == 2
    assert step_events[0]["step"]["stage"] == "tool_call"
    assert step_events[0]["step"]["tool_name"] == "get_current_param"
    assert step_events[0]["step"]["status"] == "ok"
    assert step_events[1]["step"]["stage"] == "thinking"
    assert step_events[1]["step"]["detail"] == "it's currently 4.5"

    final = final_events[0]
    assert final["reply"] == "it's currently 4.5"
    assert final["pending_proposal"] is None
    assert final["rejected_proposals"] == []
    assert len(final["turn_steps"]) == 2


def test_stream_final_event_carries_pending_proposal_not_a_reply():
    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "ATC_ANG_RLL_P", "new_value": 6.0, "reason": "t"}, "call_1"),
    ])
    session = _make_session(model)

    with (
        patch.object(session_manager, "get", return_value=session),
        TestClient(app) as client,
    ):
        resp = client.post("/chat/stream", json={"session_id": session.session_id, "message": "tune it"})

    events = _parse_sse_events(resp.text)
    final = next(e for e in events if e["type"] == "final")
    assert final["reply"] is None
    assert final["pending_proposal"]["param_name"] == "ATC_ANG_RLL_P"
    assert final["pending_proposal"]["accepted"] is True


def test_stream_surfaces_a_rejected_proposal_in_the_final_event():
    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "ATC_ANG_RLL_P", "new_value": 999.0, "reason": "t"}, "call_1"),
        final_message("that's out of range, so I didn't propose it"),
    ])
    session = _make_session(model)

    with (
        patch.object(session_manager, "get", return_value=session),
        TestClient(app) as client,
    ):
        resp = client.post("/chat/stream", json={"session_id": session.session_id, "message": "set it to 999"})

    events = _parse_sse_events(resp.text)
    final = next(e for e in events if e["type"] == "final")
    assert len(final["rejected_proposals"]) == 1
    assert final["rejected_proposals"][0]["accepted"] is False


def test_stream_404_when_session_does_not_exist():
    with TestClient(app) as client:
        resp = client.post("/chat/stream", json={"session_id": "no-such-session", "message": "hi"})
    assert resp.status_code == 404


def test_stream_reports_a_pending_proposal_conflict_as_an_in_band_error_not_a_409():
    fake_session = MagicMock()

    with (
        patch.object(session_manager, "get", return_value=fake_session),
        patch.object(
            session_manager, "stream_message",
            side_effect=RuntimeError("a proposal is pending confirmation/rejection on this session"),
        ),
        TestClient(app) as client,
    ):
        resp = client.post("/chat/stream", json={"session_id": "fake-session", "message": "hello"})

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert events[0]["status"] == 409
    assert "pending" in events[0]["detail"].lower()


def test_streaming_and_non_streaming_produce_the_same_steps_for_the_same_turn():
    def scripted():
        return ScriptedChatModel(responses=[
            tool_call_message("get_current_param", {"name": "ATC_ANG_RLL_P"}, "call_1"),
            final_message("it's 4.5"),
        ])

    session_a = _make_session(scripted(), "a")
    session_b = _make_session(scripted(), "b")

    sm = SessionManager.__new__(SessionManager)
    sm._sessions = {}

    reply, _pending, _rejected, turn_steps, _ep = sm.send_message(session_a, "what's the value")
    streamed_events = list(sm.stream_message(session_b, "what's the value"))
    streamed_final = next(e for e in streamed_events if e["type"] == "final")

    assert streamed_final["reply"] == reply
    assert [s.model_dump() for s in turn_steps] == [e["step"].model_dump() for e in streamed_events if e["type"] == "step"]
