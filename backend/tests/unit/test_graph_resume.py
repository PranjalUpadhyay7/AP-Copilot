from collections.abc import Iterator

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

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
    def __init__(self):
        self.set_param_calls: list[tuple[str, float]] = []

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
        raise NotImplementedError

    def set_param(self, name: str, value: float, timeout: float = 10.0) -> ParamSetResult:
        self.set_param_calls.append((name, value))
        return ParamSetResult(name=name, requested_value=value, acked_value=value, acked=True)

    def stream_telemetry(self, fields: list[str] | None = None, timeout: float = 1.0, max_wait: float | None = None) -> Iterator[TelemetryEvent]:
        return iter([])

    def send_command(self, command: int, params: tuple[float, ...] = (), timeout: float = 5.0) -> CommandResult:
        raise NotImplementedError

    def get_armed_state(self, timeout: float = 3.0) -> bool | None:
        return False  # test fakes default to a disarmed, ground-safe vehicle


def _make_context(session_id: str) -> RuntimeContext:
    d = ParamDefinition(
        name="ATC_ANG_RLL_P", vehicle_types=["ArduCopter"], firmware_version="4.6.0",
        description="d", min_value=0.5, max_value=12.0,
    )
    live_params = {"ATC_ANG_RLL_P": LiveParam(name="ATC_ANG_RLL_P", current_value=4.5, definition=d)}
    return RuntimeContext(
        session_id=session_id, vehicle_client=_FakeVehicleClient(), live_params=live_params,
        audit_logger=AuditLogger(db_path=":memory:"),
    )


def test_interrupted_proposal_survives_across_fresh_graph_instances(tmp_path):
    db_path = str(tmp_path / "checkpoints.sqlite3")
    thread_config = {"configurable": {"thread_id": "resume-test-thread"}}

    # "Process 1": build a graph, get it paused at approval.
    import sqlite3
    conn1 = sqlite3.connect(db_path, check_same_thread=False)
    checkpointer1 = SqliteSaver(conn1)
    context1 = _make_context("resume-session")
    model1 = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "ATC_ANG_RLL_P", "new_value": 6.0, "reason": "tighten"}, "call_1"),
        final_message("ok"),
    ])
    graph1 = build_graph(context1, model1, checkpointer1)

    result1 = graph1.invoke(
        {
            "messages": [HumanMessage(content="tighten roll")],
            "session_id": "resume-session",
            "pending_proposal": None,
            "pending_tool_call_id": None,
            "remaining_tool_calls": None,
        },
        config=thread_config,
    )
    assert "__interrupt__" in result1
    assert context1.vehicle_client.set_param_calls == []
    conn1.close()  # simulates the process going away

    conn2 = sqlite3.connect(db_path, check_same_thread=False)
    checkpointer2 = SqliteSaver(conn2)
    context2 = _make_context("resume-session")
    model2 = ScriptedChatModel(responses=[final_message("Applied after restart.")])
    graph2 = build_graph(context2, model2, checkpointer2)

    state = graph2.get_state(thread_config)
    assert state.values["pending_proposal"]["param_name"] == "ATC_ANG_RLL_P"
    assert state.values["pending_proposal"]["proposed_value"] == 6.0

    result2 = graph2.invoke(Command(resume={"decision": "confirm"}), config=thread_config)

    assert context2.vehicle_client.set_param_calls == [("ATC_ANG_RLL_P", 6.0)]
    tool_messages = [m for m in result2["messages"] if isinstance(m, ToolMessage)]
    assert any("applied" in m.content.lower() for m in tool_messages)
    conn2.close()
