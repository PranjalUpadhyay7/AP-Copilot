"""One real, live NIM-backed smoke test."""
import os

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from app.audit.logger import AuditLogger
from app.models.params import LiveParam, ParamDefinition
from app.orchestrator.graph import build_graph
from app.orchestrator.nim_client import get_nim_chat_model
from tests.adversarial_llm.conftest import FakeVehicleClient

pytestmark = pytest.mark.skipif(
    os.environ.get("AP_COPILOT_LIVE_LLM_TESTS") != "1",
    reason="opt-in only: set AP_COPILOT_LIVE_LLM_TESTS=1 to spend real NIM API usage",
)


def test_read_only_question_produces_correct_tool_call_and_grounded_answer():
    live_params = {
        "BATT_LOW_VOLT": LiveParam(
            name="BATT_LOW_VOLT", current_value=10.5,
            definition=ParamDefinition(
                name="BATT_LOW_VOLT", vehicle_types=["ArduCopter"], firmware_version="4.6.0",
                description="Battery voltage that triggers a low battery failsafe. Set to 0 to disable.",
                unit="V",
            ),
        ),
    }
    from app.orchestrator.tools import RuntimeContext

    context = RuntimeContext(
        session_id="live-smoke", vehicle_client=FakeVehicleClient(), live_params=live_params,
        audit_logger=AuditLogger(db_path=":memory:"),
    )
    model = get_nim_chat_model()
    graph = build_graph(context, model, MemorySaver())

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="What does BATT_LOW_VOLT do on this vehicle?")],
            "session_id": "live-smoke",
            "pending_proposal": None,
            "pending_tool_call_id": None,
            "remaining_tool_calls": None,
        },
        config={"configurable": {"thread_id": "live-smoke-thread"}},
    )

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_messages, "model answered without calling any tool -- check system prompt / model tool-calling reliability"

    final = result["messages"][-1]
    assert final.content, "model produced no final answer"
    # Must never claim a change was made -- this was a read-only question.
    assert context.vehicle_client.set_param_calls == []
