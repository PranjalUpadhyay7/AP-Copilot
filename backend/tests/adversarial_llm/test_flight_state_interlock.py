from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command

from app.orchestrator.graph import build_graph
from app.validation.flight_state import blocks_write_while_armed
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


def test_blocks_write_while_armed_true_when_armed():
    assert blocks_write_while_armed("ATC_ANG_RLL_P", armed=True) is True


def test_blocks_write_while_armed_false_when_disarmed_and_not_on_allowlist():
    assert blocks_write_while_armed("ATC_ANG_RLL_P", armed=False) is False


def test_blocks_write_while_armed_fails_closed_on_unknown_state():
    assert blocks_write_while_armed("ATC_ANG_RLL_P", armed=None) is True


def test_the_allowlist_is_currently_empty():
    from app.validation.flight_state import IN_FLIGHT_SAFE_PARAMS

    assert IN_FLIGHT_SAFE_PARAMS == frozenset()


def test_confirmed_proposal_is_blocked_when_vehicle_is_armed(context, checkpointer, thread_config):
    context.vehicle_client.get_armed_state = lambda timeout=3.0: True

    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "ATC_ANG_RLL_P", "new_value": 6.0, "reason": "tighten roll"}, "call_1"),
        final_message("ok"),
    ])
    graph = build_graph(context, model, checkpointer)

    graph.invoke(_initial_state("tighten roll"), config=thread_config)
    result = graph.invoke(Command(resume={"decision": "confirm"}), config=thread_config)

    assert context.vehicle_client.set_param_calls == []
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert any("Blocked" in m.content and "armed" in m.content for m in tool_messages)

    events = context.audit_logger.get_events(context.session_id)
    assert not any(e.event_type.value == "apply" for e in events)


def test_confirmed_proposal_is_blocked_when_arm_state_cannot_be_determined(context, checkpointer, thread_config):
    context.vehicle_client.get_armed_state = lambda timeout=3.0: None

    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "ATC_ANG_RLL_P", "new_value": 6.0, "reason": "tighten roll"}, "call_1"),
        final_message("ok"),
    ])
    graph = build_graph(context, model, checkpointer)

    graph.invoke(_initial_state("tighten roll"), config=thread_config)
    result = graph.invoke(Command(resume={"decision": "confirm"}), config=thread_config)

    assert context.vehicle_client.set_param_calls == []
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert any("Blocked" in m.content for m in tool_messages)


def test_confirmed_proposal_still_applies_normally_when_disarmed(context, checkpointer, thread_config):
    context.vehicle_client.get_armed_state = lambda timeout=3.0: False

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
