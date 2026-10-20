"""Adversarial LLM test suite."""
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command

from app.orchestrator.graph import build_graph
from tests.adversarial_llm.fake_chat_model import (
    LoopingChatModel,
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


def test_hallucinated_param_never_reaches_interrupt(context, checkpointer, thread_config):
    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "TOTALLY_INVENTED_PARAM", "new_value": 1.0, "reason": "seemed right"}, "call_1"),
        final_message("I couldn't propose that -- the parameter doesn't exist on this vehicle."),
    ])
    graph = build_graph(context, model, checkpointer)

    result = graph.invoke(_initial_state("tune the invented thing"), config=thread_config)

    assert "__interrupt__" not in result
    assert context.vehicle_client.set_param_calls == []
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert any("not_found" in m.content.lower() or "does not exist" in m.content.lower() for m in tool_messages)


def test_out_of_range_proposal_never_reaches_interrupt(context, checkpointer, thread_config):
    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "ATC_ANG_RLL_P", "new_value": 99999.0, "reason": "much tighter"}, "call_1"),
        final_message("That value is out of range, so I couldn't propose it."),
    ])
    graph = build_graph(context, model, checkpointer)

    result = graph.invoke(_initial_state("crank up roll gain"), config=thread_config)

    assert "__interrupt__" not in result
    assert context.vehicle_client.set_param_calls == []


def test_undocumented_param_never_reaches_interrupt(context, checkpointer, thread_config):
    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "UNDOCUMENTED", "new_value": 2.0, "reason": "why not"}, "call_1"),
        final_message("I don't have verified metadata for that parameter."),
    ])
    graph = build_graph(context, model, checkpointer)

    result = graph.invoke(_initial_state("change the mystery param"), config=thread_config)

    assert "__interrupt__" not in result
    assert context.vehicle_client.set_param_calls == []


def test_valid_proposal_reaches_exactly_one_interrupt_and_requires_confirm(context, checkpointer, thread_config):
    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "ATC_ANG_RLL_P", "new_value": 6.0, "reason": "tighten roll"}, "call_1"),
        final_message("Applied."),
    ])
    graph = build_graph(context, model, checkpointer)

    result = graph.invoke(_initial_state("tighten roll"), config=thread_config)

    assert "__interrupt__" in result
    # The write must not have happened yet -- only the interrupt fired.
    assert context.vehicle_client.set_param_calls == []


def test_implicit_batch_confirm_gets_two_sequential_interrupts_not_one(context, checkpointer, thread_config):
    from langchain_core.messages import AIMessage

    model = ScriptedChatModel(responses=[
        AIMessage(content="", tool_calls=[
            {"name": "propose_param_change", "args": {"name": "ATC_ANG_RLL_P", "new_value": 6.0, "reason": "tighten roll"}, "id": "call_1", "type": "tool_call"},
            {"name": "propose_param_change", "args": {"name": "ATC_ANG_PIT_P", "new_value": 6.0, "reason": "tighten pitch"}, "id": "call_2", "type": "tool_call"},
        ]),
        final_message("Both applied."),
    ])
    graph = build_graph(context, model, checkpointer)

    result1 = graph.invoke(_initial_state("tighten roll and pitch"), config=thread_config)
    assert "__interrupt__" in result1
    interrupt_payload_1 = result1["__interrupt__"][0].value
    assert interrupt_payload_1["param_name"] == "ATC_ANG_RLL_P"
    assert context.vehicle_client.set_param_calls == []

    result2 = graph.invoke(Command(resume={"decision": "confirm"}), config=thread_config)
    assert context.vehicle_client.set_param_calls == [("ATC_ANG_RLL_P", 6.0)]
    assert "__interrupt__" in result2
    interrupt_payload_2 = result2["__interrupt__"][0].value
    assert interrupt_payload_2["param_name"] == "ATC_ANG_PIT_P"

    result3 = graph.invoke(Command(resume={"decision": "confirm"}), config=thread_config)
    assert context.vehicle_client.set_param_calls == [
        ("ATC_ANG_RLL_P", 6.0), ("ATC_ANG_PIT_P", 6.0),
    ]
    assert "__interrupt__" not in result3


def test_reject_decision_never_writes(context, checkpointer, thread_config):
    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "ATC_ANG_RLL_P", "new_value": 6.0, "reason": "tighten roll"}, "call_1"),
        final_message("Understood, not applying that."),
    ])
    graph = build_graph(context, model, checkpointer)

    graph.invoke(_initial_state("tighten roll"), config=thread_config)
    result = graph.invoke(Command(resume={"decision": "reject"}), config=thread_config)

    assert context.vehicle_client.set_param_calls == []
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert any("rejected" in m.content.lower() for m in tool_messages)


def test_pre_write_revalidation_blocks_write_if_state_changed_since_proposal(context, checkpointer, thread_config):
    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "ATC_ANG_RLL_P", "new_value": 6.0, "reason": "tighten roll"}, "call_1"),
        final_message("ok"),
    ])
    graph = build_graph(context, model, checkpointer)

    graph.invoke(_initial_state("tighten roll"), config=thread_config)

    del context.live_params["ATC_ANG_RLL_P"]

    result = graph.invoke(Command(resume={"decision": "confirm"}), config=thread_config)

    assert context.vehicle_client.set_param_calls == []
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert any("no longer safe" in m.content.lower() for m in tool_messages)


def test_read_only_tools_never_call_set_param(context, checkpointer, thread_config):
    model = ScriptedChatModel(responses=[
        tool_call_message("get_current_param", {"name": "ATC_ANG_RLL_P"}, "call_1"),
        final_message("The current value is 4.5."),
    ])
    graph = build_graph(context, model, checkpointer)

    result = graph.invoke(_initial_state("what's the current roll gain?"), config=thread_config)

    assert "__interrupt__" not in result
    assert context.vehicle_client.set_param_calls == []


def test_malformed_tool_call_name_never_crashes_the_graph(context, checkpointer, thread_config):
    model = ScriptedChatModel(responses=[
        tool_call_message("search_ardupilot_docs<|channel|>commentary", {"query": "roll gain"}, "call_1"),
        final_message("Let me try that again -- here's what I found."),
    ])
    graph = build_graph(context, model, checkpointer)

    result = graph.invoke(_initial_state("what does roll gain do?"), config=thread_config)

    assert "__interrupt__" not in result
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert any("not a recognized tool" in m.content for m in tool_messages)


def test_malformed_tool_call_args_never_crash_the_graph(context, checkpointer, thread_config):
    model = ScriptedChatModel(responses=[
        tool_call_message(
            "propose_multi_step_procedure",
            {"title": "Compass calibration", "steps": ["1. Do the first thing.", "2. Do the second thing."]},
            "call_1",
        ),
        final_message("Let me describe that differently."),
    ])
    graph = build_graph(context, model, checkpointer)

    result = graph.invoke(_initial_state("how do I calibrate the compass?"), config=thread_config)

    assert "__interrupt__" not in result
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert any("Error calling propose_multi_step_procedure" in m.content for m in tool_messages)


def test_confirmed_write_relays_dependency_warnings_to_the_model(context, checkpointer, thread_config):
    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "FENCE_ENABLE", "new_value": 1.0, "reason": "enable geofence"}, "call_1"),
        final_message("Enabled the geofence. You should also review FENCE_TYPE and FENCE_ACTION."),
    ])
    graph = build_graph(context, model, checkpointer)

    graph.invoke(_initial_state("turn on the geofence"), config=thread_config)
    result = graph.invoke(Command(resume={"decision": "confirm"}), config=thread_config)

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    confirmation = next(m for m in tool_messages if "Applied" in m.content)
    assert "FENCE_TYPE" in confirmation.content
    assert "FENCE_ACTION" in confirmation.content


def test_model_that_never_stops_calling_tools_is_forced_to_a_final_answer(context, checkpointer, thread_config):
    model = LoopingChatModel()
    graph = build_graph(context, model, checkpointer)

    result = graph.invoke(_initial_state("tell me everything about every parameter"), config=thread_config)

    assert "__interrupt__" not in result
    final = result["messages"][-1]
    assert not getattr(final, "tool_calls", None)
    assert "best answer" in final.content.lower()
    assert context.vehicle_client.set_param_calls == []
