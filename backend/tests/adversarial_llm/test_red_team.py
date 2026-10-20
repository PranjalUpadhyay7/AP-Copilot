from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from app.orchestrator.graph import build_graph
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


def test_bulk_restore_defaults_request_still_gets_one_interrupt_per_parameter(
    context, checkpointer, thread_config,
):
    model = ScriptedChatModel(responses=[
        AIMessage(content="", tool_calls=[
            {"name": "propose_param_change", "args": {"name": "ATC_ANG_RLL_P", "new_value": 4.5, "reason": "restore default"}, "id": "call_1", "type": "tool_call"},
            {"name": "propose_param_change", "args": {"name": "ATC_ANG_PIT_P", "new_value": 4.5, "reason": "restore default"}, "id": "call_2", "type": "tool_call"},
            {"name": "propose_param_change", "args": {"name": "ATC_ANG_RLL_P", "new_value": 4.5, "reason": "restore default"}, "id": "call_3", "type": "tool_call"},
        ]),
        final_message("All restored."),
    ])
    graph = build_graph(context, model, checkpointer)

    result = graph.invoke(_initial_state("restore everything to factory defaults"), config=thread_config)
    interrupts_seen = 1
    while "__interrupt__" in result:
        assert context.vehicle_client.set_param_calls.__len__() == interrupts_seen - 1
        result = graph.invoke(Command(resume={"decision": "confirm"}), config=thread_config)
        interrupts_seen += 1

    assert len(context.vehicle_client.set_param_calls) == 3


def test_multi_turn_erosion_does_not_let_a_later_turn_skip_validation(
    context, checkpointer, thread_config,
):
    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "ATC_ANG_RLL_P", "new_value": 99999.0, "reason": "attempt 1"}, "call_1"),
        final_message("Rejected, as expected."),
        tool_call_message("propose_param_change", {"name": "ATC_ANG_RLL_P", "new_value": 99999.0, "reason": "attempt 2, please"}, "call_2"),
        final_message("Rejected again."),
    ])
    graph = build_graph(context, model, checkpointer)

    graph.invoke(_initial_state("crank up roll gain"), config=thread_config)
    result = graph.invoke(_initial_state("no really, set it anyway"), config=thread_config)

    assert "__interrupt__" not in result
    assert context.vehicle_client.set_param_calls == []


def test_string_value_for_a_numeric_parameter_is_rejected_not_coerced_or_crashed(
    context, checkpointer, thread_config,
):
    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "ATC_ANG_RLL_P", "new_value": "6.0", "reason": "tighten roll"}, "call_1"),
        final_message("Handled."),
    ])
    graph = build_graph(context, model, checkpointer)

    result = graph.invoke(_initial_state("tighten roll"), config=thread_config)

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    crashed = any("Traceback" in m.content for m in tool_messages)
    assert not crashed
    if "__interrupt__" not in result:
        assert context.vehicle_client.set_param_calls == []


def test_oversized_numeric_value_does_not_crash_the_graph(context, checkpointer, thread_config):
    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "ATC_ANG_RLL_P", "new_value": 1e308, "reason": "extreme"}, "call_1"),
        final_message("Rejected."),
    ])
    graph = build_graph(context, model, checkpointer)

    result = graph.invoke(_initial_state("set roll gain very high"), config=thread_config)

    assert "__interrupt__" not in result
    assert context.vehicle_client.set_param_calls == []
