from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.api.session_manager import SessionManager
from app.models.proposal import ValidatedProposal


def _accepted_proposal_json() -> str:
    return ValidatedProposal(
        param_name="ATC_ANG_RLL_P", current_value=4.5, proposed_value=6.0, reason="t",
        accepted=True, proposal_id="p1",
    ).model_dump_json()


def _rejected_proposal_json() -> str:
    return ValidatedProposal(
        param_name="ATC_ANG_RLL_P", current_value=4.5, proposed_value=99.0, reason="t",
        accepted=False, rejection_reason="out_of_range", rejection_message="out of range",
    ).model_dump_json()


def test_thinking_step_captured_from_ai_message_prose():
    messages = [
        HumanMessage(content="why won't it arm"),
        AIMessage(content="Let me check the recent status messages first."),
    ]
    steps = SessionManager._turn_steps_since(messages, prior_message_count=1)
    assert len(steps) == 1
    assert steps[0].stage == "thinking"
    assert steps[0].detail == "Let me check the recent status messages first."


def test_tool_call_and_result_produce_one_ok_step():
    messages = [
        AIMessage(content="", tool_calls=[{"name": "get_current_param", "args": {"name": "FOO"}, "id": "c1"}]),
        ToolMessage(content='{"name": "FOO", "current_value": 1.0}', tool_call_id="c1", name="get_current_param"),
    ]
    steps = SessionManager._turn_steps_since(messages, prior_message_count=0)
    assert len(steps) == 1
    assert steps[0].stage == "tool_call"
    assert steps[0].tool_name == "get_current_param"
    assert steps[0].status == "ok"


def test_notfound_result_is_marked_error():
    messages = [
        AIMessage(content="", tool_calls=[{"name": "get_current_param", "args": {"name": "BOGUS"}, "id": "c1"}]),
        ToolMessage(content="NotFound: BOGUS does not exist", tool_call_id="c1", name="get_current_param"),
    ]
    steps = SessionManager._turn_steps_since(messages, prior_message_count=0)
    assert steps[0].status == "error"


def test_accepted_proposal_tool_call_is_marked_ok():
    messages = [
        AIMessage(content="", tool_calls=[{"name": "propose_param_change", "args": {}, "id": "c1"}]),
        ToolMessage(content=_accepted_proposal_json(), tool_call_id="c1", name="propose_param_change"),
    ]
    steps = SessionManager._turn_steps_since(messages, prior_message_count=0)
    assert steps[0].tool_name == "propose_param_change"
    assert steps[0].status == "ok"


def test_rejected_proposal_tool_call_is_marked_blocked():
    messages = [
        AIMessage(content="", tool_calls=[{"name": "propose_param_change", "args": {}, "id": "c1"}]),
        ToolMessage(content=_rejected_proposal_json(), tool_call_id="c1", name="propose_param_change"),
    ]
    steps = SessionManager._turn_steps_since(messages, prior_message_count=0)
    assert steps[0].status == "blocked"


def test_multiple_tool_calls_in_one_turn_preserve_order():
    messages = [
        AIMessage(content="", tool_calls=[
            {"name": "get_current_param", "args": {"name": "A"}, "id": "c1"},
            {"name": "get_current_param", "args": {"name": "B"}, "id": "c2"},
        ]),
        ToolMessage(content='{"name": "A"}', tool_call_id="c1", name="get_current_param"),
        ToolMessage(content='{"name": "B"}', tool_call_id="c2", name="get_current_param"),
        AIMessage(content="Both look fine."),
    ]
    steps = SessionManager._turn_steps_since(messages, prior_message_count=0)
    assert [s.stage for s in steps] == ["tool_call", "tool_call", "thinking"]


def test_only_scans_messages_added_this_turn():
    messages = [
        AIMessage(content="an old thought from a prior turn"),
        HumanMessage(content="a new question"),
        AIMessage(content="a fresh answer, no tools needed"),
    ]
    steps = SessionManager._turn_steps_since(messages, prior_message_count=2)
    assert len(steps) == 1
    assert steps[0].detail == "a fresh answer, no tools needed"
