from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command

from app.orchestrator.graph import build_graph
from app.validation.rate_limit import MAX_APPLIES_PER_WINDOW
from tests.adversarial_llm.fake_chat_model import (
    ScriptedChatModel,
    final_message,
    tool_call_message,
)


def _initial_state(text: str) -> dict:
    return {
        "messages": [HumanMessage(content=text)],
        "session_id": "test-session",
        "pending_proposal": None,
        "pending_tool_call_id": None,
        "remaining_tool_calls": None,
    }


def test_confirmed_write_is_blocked_after_the_rate_limit_is_hit(context, checkpointer, thread_config):
    for i in range(MAX_APPLIES_PER_WINDOW):
        context.audit_logger.log_apply(context.session_id, "ATC_ANG_PIT_P", 4.5, 4.5 + i)

    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "ATC_ANG_RLL_P", "new_value": 6.0, "reason": "tighten roll"}, "call_1"),
        final_message("ok"),
    ])
    graph = build_graph(context, model, checkpointer)

    graph.invoke(_initial_state("tighten roll"), config=thread_config)
    result = graph.invoke(Command(resume={"decision": "confirm"}), config=thread_config)

    assert context.vehicle_client.set_param_calls == []
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert any("too many changes" in m.content.lower() for m in tool_messages)


def test_confirmed_write_proceeds_normally_when_under_the_rate_limit(context, checkpointer, thread_config):
    for i in range(MAX_APPLIES_PER_WINDOW - 1):
        context.audit_logger.log_apply(context.session_id, "ATC_ANG_PIT_P", 4.5, 4.5 + i)

    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "ATC_ANG_RLL_P", "new_value": 6.0, "reason": "tighten roll"}, "call_1"),
        final_message("ok"),
    ])
    graph = build_graph(context, model, checkpointer)

    graph.invoke(_initial_state("tighten roll"), config=thread_config)
    result = graph.invoke(Command(resume={"decision": "confirm"}), config=thread_config)

    assert context.vehicle_client.set_param_calls == [("ATC_ANG_RLL_P", 6.0)]
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert any("Applied" in m.content for m in tool_messages)
