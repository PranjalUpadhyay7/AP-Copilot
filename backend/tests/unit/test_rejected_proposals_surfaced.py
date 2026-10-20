from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.api.session_manager import SessionManager
from app.models.proposal import ValidatedProposal


def _rejected(param_name: str) -> ValidatedProposal:
    return ValidatedProposal(
        param_name=param_name, current_value=1.0, proposed_value=99.0, reason="test",
        accepted=False, rejection_reason="out_of_range", rejection_message=f"{param_name} out of range",
    )


def _accepted(param_name: str) -> ValidatedProposal:
    return ValidatedProposal(
        param_name=param_name, current_value=1.0, proposed_value=2.0, reason="test",
        accepted=True, proposal_id="p1",
    )


def test_rejected_proposal_tool_message_is_extracted():
    messages = [
        HumanMessage(content="tighten roll gain to 99"),
        AIMessage(content="", tool_calls=[{"name": "propose_param_change", "args": {}, "id": "call_1"}]),
        ToolMessage(content=_rejected("ATC_ANG_RLL_P").model_dump_json(), tool_call_id="call_1", name="propose_param_change"),
        AIMessage(content="That's out of range, so I didn't propose it."),
    ]
    rejected = SessionManager._rejected_proposals_since(messages, prior_message_count=0)
    assert len(rejected) == 1
    assert rejected[0].param_name == "ATC_ANG_RLL_P"
    assert rejected[0].accepted is False
    assert rejected[0].rejection_message == "ATC_ANG_RLL_P out of range"


def test_only_scans_messages_added_this_turn():
    messages = [
        ToolMessage(content=_rejected("OLD_PARAM").model_dump_json(), tool_call_id="call_0", name="propose_param_change"),
        AIMessage(content="old reply"),
        HumanMessage(content="a new, different question"),
        AIMessage(content="a plain prose answer, no proposal at all"),
    ]
    rejected = SessionManager._rejected_proposals_since(messages, prior_message_count=2)
    assert rejected == []


def test_accepted_proposal_is_not_treated_as_rejected():
    messages = [
        ToolMessage(content=_accepted("ATC_ANG_RLL_P").model_dump_json(), tool_call_id="call_1", name="propose_param_change"),
    ]
    assert SessionManager._rejected_proposals_since(messages, prior_message_count=0) == []


def test_non_proposal_tool_messages_are_ignored():
    messages = [
        ToolMessage(content="NotFound: FOO does not exist", tool_call_id="call_1", name="get_current_param"),
        ToolMessage(content="Error: 'bogus_tool' is not a recognized tool.", tool_call_id="call_2", name="bogus_tool"),
    ]
    assert SessionManager._rejected_proposals_since(messages, prior_message_count=0) == []


def test_multiple_rejections_in_one_turn_are_all_surfaced():
    messages = [
        ToolMessage(content=_rejected("PARAM_A").model_dump_json(), tool_call_id="call_1", name="propose_param_change"),
        ToolMessage(content=_rejected("PARAM_B").model_dump_json(), tool_call_id="call_2", name="propose_param_change"),
    ]
    rejected = SessionManager._rejected_proposals_since(messages, prior_message_count=0)
    assert {p.param_name for p in rejected} == {"PARAM_A", "PARAM_B"}
