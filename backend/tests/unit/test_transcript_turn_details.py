from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.api.session_manager import SessionManager

REJECTED = (
    '{"param_name":"X","current_value":null,"proposed_value":5.0,"reason":"r","accepted":false,'
    '"rejection_reason":"not_found","rejection_message":"X does not exist","criticality":null,'
    '"dependency_warnings":[],"reboot_required":false,"definition":null,"proposal_id":"p1"}'
)


def _turns():
    return [
        HumanMessage(content="what is RTL_ALT_M?"),
        AIMessage(content="", tool_calls=[{"name": "get_current_param", "args": {"name": "RTL_ALT_M"}, "id": "c1"}]),
        ToolMessage(content="value 1500", tool_call_id="c1", name="get_current_param"),
        AIMessage(content="It is 1500 cm."),
        HumanMessage(content="set FOO to 5"),
        AIMessage(content="", tool_calls=[{"name": "propose_param_change", "args": {}, "id": "c2"}]),
        ToolMessage(content=REJECTED, tool_call_id="c2", name="propose_param_change"),
        AIMessage(content="That parameter does not exist."),
        HumanMessage(content="hi"),
        AIMessage(content="Hello!"),
        HumanMessage(content="increase the buffer"),  # ends in a pending proposal: no reply yet
        AIMessage(content="", tool_calls=[{"name": "propose_param_change", "args": {}, "id": "c3"}]),
    ]


def test_each_turns_final_reply_carries_its_thinking_steps_and_rejections():
    out = SessionManager.transcript_with_turn_details(_turns())
    replies = {m["content"]: m for m in out if m["role"] == "assistant" and "turn_steps" in m}
    assert set(replies) == {"It is 1500 cm.", "That parameter does not exist.", "Hello!"}

    first = replies["It is 1500 cm."]
    tool_steps = [s for s in first["turn_steps"] if s["stage"] == "tool_call"]
    assert [(s["tool_name"], s["detail"]) for s in tool_steps] == [("get_current_param", "value 1500")]
    assert first["rejected_proposals"] == []

    second = replies["That parameter does not exist."]
    assert [p["param_name"] for p in second["rejected_proposals"]] == ["X"]
    assert second["rejected_proposals"][0]["rejection_message"] == "X does not exist"
    # steps are per turn: the first turn's tool call is not repeated in the second
    assert all(s["tool_name"] != "get_current_param" for s in second["turn_steps"] if s["stage"] == "tool_call")


def test_flat_transcript_is_unchanged_and_unfinished_turns_get_no_reply_details():
    out = SessionManager.transcript_with_turn_details(_turns())
    assert [m["role"] for m in out] == [
        "user", "assistant", "tool", "assistant", "user", "assistant", "tool", "assistant", "user", "assistant", "user", "assistant",
    ]
    assert not any("turn_steps" in m for m in out[-2:])  # pending-proposal turn: nothing to attach
    assert "turn_steps" not in out[1]  # intermediate tool-call message


def test_transcript_endpoint_returns_the_details(monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import session_manager as sm_mod
    from app.main import app

    sm = sm_mod.session_manager
    monkeypatch.setattr(sm.session_store, "get", lambda sid: object())
    monkeypatch.setattr(sm_mod, "load_messages", lambda sid: _turns())
    body = TestClient(app).get("/sessions/s1/transcript").json()
    replies = [m for m in body["messages"] if m.get("turn_steps")]
    assert len(replies) == 3 and replies[1]["rejected_proposals"][0]["param_name"] == "X"


def test_confirmed_and_rejected_actions_come_back_as_applied_bubbles():
    msgs = [
        HumanMessage(content="set FOO to 5"),
        AIMessage(content="", tool_calls=[{"name": "propose_param_change", "args": {}, "id": "a"}]),
        ToolMessage(content="Applied: FOO = 5.0", tool_call_id="a", name="propose_param_change"),
        AIMessage(content="Done."),
        HumanMessage(content="set BAR to 9"),
        AIMessage(content="", tool_calls=[{"name": "propose_param_change", "args": {}, "id": "b"}]),
        ToolMessage(content="The user rejected the proposed change to BAR (too risky). No write was made.",
                    tool_call_id="b", name="propose_param_change"),
        AIMessage(content="Understood."),
    ]
    out = SessionManager.transcript_with_turn_details(msgs)
    bubbles = [m["content"] for m in out if m["role"] == "assistant" and m["content"].startswith("[")]
    assert bubbles == ["[applied] Applied: FOO = 5.0", "[rejected] The user rejected the proposed change to BAR (too risky). No write was made."]
    assert all(m.get("turn_steps") == [] for m in out if m["content"].startswith("["))
    # a pending/rejected-by-validator proposal (JSON content) does NOT create an action bubble
    assert not any(m["content"].startswith("[") for m in SessionManager.transcript_with_turn_details(_turns()))


def test_write_path_steps_are_restored_on_the_applied_bubble():
    steps = [
        {"stage": "revalidation", "tool_name": None, "status": "ok", "detail": "Re-validated FOO = 5.0: accepted."},
        {"stage": "write", "tool_name": None, "status": "ok", "detail": "FOO set to 5.0 and acknowledged."},
    ]
    msgs = [
        HumanMessage(content="set FOO to 5"),
        AIMessage(content="", tool_calls=[{"name": "propose_param_change", "args": {}, "id": "a"}]),
        ToolMessage(content="Applied: FOO = 5.0", tool_call_id="a", name="propose_param_change",
                    additional_kwargs={"write_steps": steps}),
        AIMessage(content="Done."),
    ]
    out = SessionManager.transcript_with_turn_details(msgs)
    bubble = next(m for m in out if m["content"].startswith("[applied]"))
    assert [s["stage"] for s in bubble["turn_steps"]] == ["revalidation", "write"]
    # old sessions (no write_steps stored) still produce a bubble, just without steps
    old = [*msgs[:2], ToolMessage(content="Applied: FOO = 5.0", tool_call_id="a", name="propose_param_change"), msgs[3]]
    assert next(m for m in SessionManager.transcript_with_turn_details(old) if m["content"].startswith("[applied]"))["turn_steps"] == []


def test_the_approval_node_stores_the_write_steps_on_the_tool_message():
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import Command

    from app.orchestrator.graph import build_graph
    from eval.run_bench import _build_context, load_tasks
    from tests.adversarial_llm.fake_chat_model import (
        ScriptedChatModel,
        final_message,
        tool_call_message,
    )

    [task] = load_tasks(["simple_config_01"])
    context, _vehicle = _build_context(task)
    model = ScriptedChatModel(responses=[
        tool_call_message("propose_param_change", {"name": "ATC_ANG_RLL_P", "new_value": 5.5, "reason": "tighten"}, "c1"),
        final_message("Applied."),
    ])
    graph = build_graph(context, model, MemorySaver())
    cfg = {"configurable": {"thread_id": "t195"}, "recursion_limit": 30}
    state = {"messages": [HumanMessage(content=task.prompt)], "session_id": "t195", "pending_proposal": None,
             "pending_tool_call_id": None, "remaining_tool_calls": None}
    result = graph.invoke(state, config=cfg)
    assert "__interrupt__" in result
    result = graph.invoke(Command(resume={"decision": "confirm"}), config=cfg)
    out = SessionManager.transcript_with_turn_details(result["messages"])
    bubble = next(m for m in out if m["content"].startswith("[applied]"))
    assert {s["stage"] for s in bubble["turn_steps"]} >= {"revalidation", "write"}
