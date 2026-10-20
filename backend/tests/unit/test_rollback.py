import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from app.api.session_manager import Session, SessionManager
from app.audit.logger import AuditLogger
from app.comms.vehicle_client import VehicleClient
from app.models.params import LiveParam, ParamDefinition
from app.models.telemetry import CommandResult, ParamSetResult, TelemetryEvent
from app.models.vehicle import VehicleVersionInfo
from app.orchestrator.graph import build_graph
from app.orchestrator.tools import RuntimeContext
from tests.adversarial_llm.fake_chat_model import (
    ScriptedChatModel,
    final_message,
    tool_call_message,
)


class _FakeVehicleClient(VehicleClient):
    def __init__(self, live_params: dict[str, LiveParam]):
        self.set_param_calls: list[tuple[str, float]] = []
        self.armed = False
        self._live_params = live_params

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    @property
    def is_connected(self) -> bool:
        return True

    def get_autopilot_version(self) -> VehicleVersionInfo:
        raise NotImplementedError

    def stream_params(self) -> dict[str, float]:
        return {name: p.current_value for name, p in self._live_params.items()}

    def set_param(self, name: str, value: float, timeout: float = 10.0) -> ParamSetResult:
        self.set_param_calls.append((name, value))
        if name in self._live_params:
            self._live_params[name].current_value = value
        return ParamSetResult(name=name, requested_value=value, acked_value=value, acked=True)

    def stream_telemetry(self, fields=None, timeout: float = 1.0, max_wait: float | None = None) -> Iterator[TelemetryEvent]:
        return iter([])

    def send_command(self, command: int, params: tuple[float, ...] = (), timeout: float = 5.0) -> CommandResult:
        raise NotImplementedError

    def get_armed_state(self, timeout: float = 3.0) -> bool | None:
        return self.armed


def _make_session(session_id: str = "rollback-test") -> Session:
    d = ParamDefinition(
        name="ATC_ANG_RLL_P", vehicle_types=["ArduCopter"], firmware_version="4.6.0",
        description="d", min_value=0.5, max_value=12.0,
    )
    live_params = {"ATC_ANG_RLL_P": LiveParam(name="ATC_ANG_RLL_P", current_value=4.5, definition=d)}
    context = RuntimeContext(
        session_id=session_id, vehicle_client=_FakeVehicleClient(live_params), live_params=live_params,
        audit_logger=AuditLogger(db_path=":memory:"),
    )
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    thread_config = {"configurable": {"thread_id": session_id}}
    model = ScriptedChatModel(responses=[final_message("unused")])
    graph = build_graph(context, model, checkpointer)
    return Session(
        session_id=session_id, started_at=datetime.now(UTC), ended_at=None,
        vehicle_type="ArduCopter", firmware_version="4.6.0", read_only=False,
        context=context, graph=graph, thread_config=thread_config,
        _checkpoint_conn=conn, _sitl_process=None,
    )


def _bare_session_manager(session: Session) -> SessionManager:
    sm = SessionManager.__new__(SessionManager)
    sm._sessions = {session.session_id: session}
    return sm


def _apply_a_real_change(session: Session, param_name: str, before: float, after: float) -> int:
    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": param_name, "new_value": after, "reason": "test change"}, "call_1"),
        final_message("ok"),
    ])
    conn = session._checkpoint_conn
    checkpointer = SqliteSaver(conn)
    graph = build_graph(session.context, model, checkpointer)
    session.graph = graph

    graph.invoke(
        {
            "messages": [HumanMessage(content="change it")], "session_id": session.session_id,
            "pending_proposal": None, "pending_tool_call_id": None, "remaining_tool_calls": None,
        },
        config=session.thread_config,
    )
    graph.invoke(Command(resume={"decision": "confirm"}), config=session.thread_config)

    events = session.context.audit_logger.get_events(session.session_id)
    apply_event = next(e for e in events if e.event_type.value == "apply")
    return apply_event.id


def test_propose_rollback_creates_an_accepted_proposal_for_the_before_value():
    session = _make_session()
    event_id = _apply_a_real_change(session, "ATC_ANG_RLL_P", before=4.5, after=6.0)

    sm = _bare_session_manager(session)
    proposal = sm.propose_rollback(session, event_id)

    assert proposal.accepted is True
    assert proposal.param_name == "ATC_ANG_RLL_P"
    assert proposal.proposed_value == 4.5
    assert proposal.proposal_id in session.context.pending_proposals


def test_confirming_a_rollback_writes_the_before_value_and_logs_a_new_apply():
    session = _make_session()
    event_id = _apply_a_real_change(session, "ATC_ANG_RLL_P", before=4.5, after=6.0)

    sm = _bare_session_manager(session)
    proposal = sm.propose_rollback(session, event_id)
    outcome, detail, _steps, _ep = sm.resolve_proposal(session, proposal.proposal_id, "confirm")

    assert outcome == "applied"
    assert "Applied" in detail
    assert session.context.vehicle_client.set_param_calls[-1] == ("ATC_ANG_RLL_P", 4.5)
    assert proposal.proposal_id not in session.context.pending_proposals

    events = session.context.audit_logger.get_events(session.session_id)
    apply_events = [e for e in events if e.event_type.value == "apply"]
    assert len(apply_events) == 2  # the original change, then the rollback
    assert apply_events[-1].after_value == 4.5


def test_rejecting_a_rollback_does_not_write():
    session = _make_session()
    event_id = _apply_a_real_change(session, "ATC_ANG_RLL_P", before=4.5, after=6.0)

    sm = _bare_session_manager(session)
    proposal = sm.propose_rollback(session, event_id)
    outcome, _, _steps, _ep = sm.resolve_proposal(session, proposal.proposal_id, "reject")

    assert outcome == "rejected"
    assert session.context.vehicle_client.set_param_calls == [("ATC_ANG_RLL_P", 6.0)]  # only the original write
    assert proposal.proposal_id not in session.context.pending_proposals


def test_rollback_is_blocked_by_the_flight_state_interlock_while_armed():
    session = _make_session()
    event_id = _apply_a_real_change(session, "ATC_ANG_RLL_P", before=4.5, after=6.0)
    session.context.vehicle_client.armed = True

    sm = _bare_session_manager(session)
    proposal = sm.propose_rollback(session, event_id)
    outcome, detail, _steps, _ep = sm.resolve_proposal(session, proposal.proposal_id, "confirm")

    assert outcome == "blocked_at_write_time"
    assert "armed" in detail.lower()
    assert session.context.vehicle_client.set_param_calls == [("ATC_ANG_RLL_P", 6.0)]  # rollback write never happened


def test_propose_rollback_rejects_an_event_id_from_a_different_session():
    session_a = _make_session("session-a")
    session_b = _make_session("session-b")
    event_id = _apply_a_real_change(session_a, "ATC_ANG_RLL_P", before=4.5, after=6.0)

    sm = _bare_session_manager(session_b)
    try:
        sm.propose_rollback(session_b, event_id)
        raised = False
    except KeyError:
        raised = True
    assert raised


def test_propose_rollback_rejects_a_non_apply_event_id():
    session = _make_session()
    session.context.audit_logger.log_reject(session.session_id, "ATC_ANG_RLL_P", reason="test")
    reject_event = session.context.audit_logger.get_events(session.session_id)[0]

    sm = _bare_session_manager(session)
    try:
        sm.propose_rollback(session, reject_event.id)
        raised = False
    except KeyError:
        raised = True
    assert raised
