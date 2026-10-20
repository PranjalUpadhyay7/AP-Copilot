from __future__ import annotations

import ast
from pathlib import Path

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command

from app.orchestrator import tools as tools_module
from app.orchestrator.graph import build_graph
from tests.adversarial_llm.fake_chat_model import (
    ScriptedChatModel,
    final_message,
    tool_call_message,
)

APP_DIR = Path(__file__).resolve().parents[2] / "app"


def _initial_state(text: str) -> dict:
    return {
        "messages": [HumanMessage(content=text)],
        "session_id": "test-session",
        "pending_proposal": None,
        "pending_tool_call_id": None,
        "remaining_tool_calls": None,
    }


def _find_set_param_calls_in_file(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text())
    hits = []

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.func_stack: list[str] = []

        def visit_FunctionDef(self, node):
            self.func_stack.append(node.name)
            self.generic_visit(node)
            self.func_stack.pop()

        def visit_Call(self, node):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "set_param":
                enclosing = self.func_stack[-1] if self.func_stack else "<module>"
                hits.append((node.lineno, enclosing))
            self.generic_visit(node)

    Visitor().visit(tree)
    return hits


def test_set_param_has_exactly_one_call_site_in_the_whole_app_and_it_is_apply_confirmed_write():
    call_sites: list[tuple[Path, int, str]] = []
    for py_file in APP_DIR.rglob("*.py"):
        for lineno, func_name in _find_set_param_calls_in_file(py_file):
            call_sites.append((py_file, lineno, func_name))

    assert len(call_sites) == 1, f"expected exactly one set_param call site, found {call_sites}"
    path, _, func_name = call_sites[0]
    assert path.name == "graph.py"
    assert func_name == "apply_confirmed_write"


def test_no_tool_schema_has_a_confirmation_or_approval_argument(context):
    suspicious_substrings = ("confirm", "approv", "authoriz", "override", "skip_review", "bypass")
    tools = tools_module.build_tools(context)
    assert tools, "expected at least one tool to be registered"

    for tool in tools:
        schema = tool.args_schema
        field_names = list(getattr(schema, "model_fields", {}).keys()) if schema else []
        for name in field_names:
            lowered = name.lower()
            assert not any(s in lowered for s in suspicious_substrings), (
                f"tool {tool.name!r} has a suspicious argument {name!r} -- "
                "a tool argument must never let the model self-approve a write"
            )


def test_propose_param_change_signature_has_exactly_the_three_documented_arguments(context):
    tools = tools_module.build_tools(context)
    propose = next(t for t in tools if t.name == "propose_param_change")
    field_names = set(propose.args_schema.model_fields.keys())
    assert field_names == {"name", "new_value", "reason"}


def test_client_supplied_resume_fields_other_than_decision_are_ignored(context, checkpointer, thread_config):
    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "ATC_ANG_RLL_P", "new_value": 6.0, "reason": "tighten roll"}, "call_1"),
        final_message("ok"),
    ])
    graph = build_graph(context, model, checkpointer)

    graph.invoke(_initial_state("tighten roll"), config=thread_config)
    graph.invoke(
        Command(resume={"decision": "confirm", "new_value": 9999.0, "param_name": "ATC_ANG_PIT_P"}),
        config=thread_config,
    )

    assert context.vehicle_client.set_param_calls == [("ATC_ANG_RLL_P", 6.0)]


def test_resuming_an_already_resolved_proposal_does_not_write_a_second_time(context, checkpointer, thread_config):
    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "ATC_ANG_RLL_P", "new_value": 6.0, "reason": "tighten roll"}, "call_1"),
        final_message("ok"),
    ])
    graph = build_graph(context, model, checkpointer)

    graph.invoke(_initial_state("tighten roll"), config=thread_config)
    graph.invoke(Command(resume={"decision": "confirm"}), config=thread_config)
    assert context.vehicle_client.set_param_calls == [("ATC_ANG_RLL_P", 6.0)]

    raised = None
    try:
        graph.invoke(Command(resume={"decision": "confirm"}), config=thread_config)
    except Exception as e:  # noqa: BLE001 -- any exception here is acceptable; a second write is not
        raised = e
    assert raised is None or isinstance(raised, Exception)  # either outcome is acceptable

    assert context.vehicle_client.set_param_calls == [("ATC_ANG_RLL_P", 6.0)]


def test_vehicle_write_exception_fails_closed_not_crashed_and_not_logged_as_applied(context, checkpointer, thread_config):
    def _raise(*args, **kwargs):
        raise RuntimeError("not connected -- call connect() first")

    context.vehicle_client.set_param = _raise

    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "ATC_ANG_RLL_P", "new_value": 6.0, "reason": "tighten roll"}, "call_1"),
        final_message("ok"),
    ])
    graph = build_graph(context, model, checkpointer)

    graph.invoke(_initial_state("tighten roll"), config=thread_config)
    result = graph.invoke(Command(resume={"decision": "confirm"}), config=thread_config)

    assert "__interrupt__" not in result
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert any("Could not write" in m.content for m in tool_messages)
    assert not any("Applied:" in m.content for m in tool_messages)

    events = context.audit_logger.get_events(context.session_id)
    assert not any(e.event_type.value == "apply" for e in events)


def test_confirm_and_reject_are_the_only_recognized_resume_decisions(context, checkpointer, thread_config):
    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "ATC_ANG_RLL_P", "new_value": 6.0, "reason": "tighten roll"}, "call_1"),
        final_message("ok"),
    ])
    graph = build_graph(context, model, checkpointer)

    graph.invoke(_initial_state("tighten roll"), config=thread_config)
    graph.invoke(Command(resume={"decision": "definitely_not_a_real_decision"}), config=thread_config)

    assert context.vehicle_client.set_param_calls == []


def test_a_model_that_ignores_tool_choice_none_still_ends_the_turn(context, checkpointer, thread_config):
    from langchain_core.messages import HumanMessage

    from app.orchestrator.graph import build_graph
    from tests.adversarial_llm.fake_chat_model import StubbornLoopingChatModel

    graph = build_graph(context, StubbornLoopingChatModel(), checkpointer)
    out = graph.invoke(
        {"messages": [HumanMessage(content="look at everything")], "session_id": "stubborn",
         "pending_proposal": None, "pending_tool_call_id": None, "remaining_tool_calls": None},
        config={**thread_config, "recursion_limit": 60},
    )
    final = out["messages"][-1]
    assert not final.tool_calls and final.content  # a plain-text answer, no GraphRecursionError


def test_when_the_cap_is_ignored_the_model_is_asked_again_without_tools_and_its_real_answer_is_kept(
    context, checkpointer, thread_config,
):
    from langchain_core.messages import HumanMessage

    from app.orchestrator.graph import build_graph
    from tests.adversarial_llm.fake_chat_model import ToolsIgnoreNoneChoiceChatModel

    graph = build_graph(context, ToolsIgnoreNoneChoiceChatModel(), checkpointer)
    out = graph.invoke(
        {"messages": [HumanMessage(content="why won't it arm")], "session_id": "s2",
         "pending_proposal": None, "pending_tool_call_id": None, "remaining_tool_calls": None},
        config={**thread_config, "recursion_limit": 60},
    )
    final = out["messages"][-1]
    assert not final.tool_calls and "compass is not calibrated" in final.content  # the model's own answer, not the canned one

