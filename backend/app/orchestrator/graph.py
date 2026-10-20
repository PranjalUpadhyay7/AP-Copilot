"""LangGraph StateGraph: agent/tool/approval nodes."""
from __future__ import annotations

import json
import logging
import re

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from pydantic import BaseModel

from app.audit.logger import AuditEventType
from app.models.api import TurnStep
from app.models.proposal import ProposedChange, ValidatedProposal
from app.orchestrator.prompts import SYSTEM_PROMPT
from app.orchestrator.state import OrchestratorState
from app.orchestrator.tools import RuntimeContext, _vehicle_context_line, build_tools
from app.validation import rate_limit
from app.validation.flight_state import blocks_write_while_armed
from app.validation.validators import revalidate_before_write

logger = logging.getLogger(__name__)

_PARAM_CHANGE_TOOL = "propose_param_change"

_DEDUPABLE_TOOLS = frozenset({"search_ardupilot_docs", "search_web", "get_current_param", "list_params_matching"})

_MAX_TOOL_ROUNDS_PER_TURN = 8

_FORCE_ANSWER_NOTICE = (
    "You have already made several tool calls this turn. Stop calling "
    "tools now and give the user your best answer using the information "
    "you already have, clearly noting anything you were not able to "
    "confirm."
)


_PROPOSAL_TOOLS_RE = re.compile(r"\b(propose_param_change|propose_multi_step_procedure)\s*\(")
_USER_SAID_YES_RE = re.compile(r"^\W*(yes|y|yeah|yep|yup|ok|okay|sure|go ahead|do it|proceed|please do|confirm)\b", re.IGNORECASE)
_OFFER_RE = re.compile(r"reply\W+(with\W+)?yes", re.IGNORECASE)

_PROSE_CALL_NOTICE = (
    "Your last reply wrote a proposal tool call as text instead of making it, so nothing was proposed. "
    "Call the tool now with the real tool-calling mechanism, then summarise in plain prose."
)
_USER_CONFIRMED_NOTICE = (
    "The user just answered yes to the action you offered. Make the proposal(s) you described now by "
    "calling the proposal tool(s); do not describe them again or ask again."
)


def _unperformed_action_notice(history: list, response) -> str | None:
    if getattr(response, "tool_calls", None):
        return None
    if _PROPOSAL_TOOLS_RE.search(str(response.content or "")):
        return _PROSE_CALL_NOTICE
    text = str(response.content or "")
    read_current = any(isinstance(m, ToolMessage) and m.name in ("get_current_param", "list_params_matching") for m in history)
    if _PLACEHOLDER_RE.search(text) or (_OFFER_RE.search(text) and not read_current):
        return _READ_VALUES_NOTICE
    last_human = next((m for m in reversed(history) if isinstance(m, HumanMessage)), None)
    if last_human is None or not _USER_SAID_YES_RE.match(str(last_human.content)):
        return None
    prior_reply = next(
        (m for m in reversed(history) if isinstance(m, AIMessage) and not m.tool_calls and str(m.content or "").strip()),
        None,
    )
    if prior_reply is not None and _OFFER_RE.search(str(prior_reply.content)):
        return _USER_CONFIRMED_NOTICE
    return None


_PLACEHOLDER_RE = re.compile(r"\((check|unknown|tbd|to be checked|not checked)[^)]*\)|\bcheck current\b", re.IGNORECASE)
_READ_VALUES_NOTICE = (
    "Your reply recommends changes but you have not read this vehicle's current values (or you wrote a "
    "placeholder such as '(check current)'). Call get_current_param for every parameter you mention, in one "
    "step, then rewrite the reply with the real current values."
)


_FORCED_ANSWER_FALLBACK = (
    "I made several lookups but could not reach a confident answer within the allowed number of steps. "
    "Please tell me which part to focus on, or rephrase what you need."
)


def _tool_rounds_this_turn(messages: list) -> int:
    count = 0
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            break
        if isinstance(msg, AIMessage) and msg.tool_calls:
            count += 1
    return count


def _dedupe_key(name: str, args: dict) -> tuple[str, str]:
    return (name, json.dumps(args, sort_keys=True, default=str))


def _prior_tool_results(messages: list) -> dict[tuple[str, str], str]:
    calls_by_id: dict[str, tuple[str, dict]] = {}
    for msg in messages:
        if isinstance(msg, AIMessage):
            for call in msg.tool_calls or []:
                calls_by_id[call["id"]] = (call["name"], call["args"])

    results: dict[tuple[str, str], str] = {}
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.tool_call_id in calls_by_id:
            name, args = calls_by_id[msg.tool_call_id]
            if name in _DEDUPABLE_TOOLS:
                results.setdefault(_dedupe_key(name, args), str(msg.content))
    return results


def _serialize_tool_result(result) -> str:
    if isinstance(result, BaseModel):
        return result.model_dump_json()
    if isinstance(result, list):
        return json.dumps([r.model_dump(mode="json") if isinstance(r, BaseModel) else r for r in result])
    if isinstance(result, str):
        return result
    return json.dumps(result, default=str)


def apply_confirmed_write(context: RuntimeContext, proposal: ValidatedProposal) -> tuple[str, list[TurnStep]]:
    """Re-validate against fresh state, apply the interlocks, then write and verify one parameter."""
    steps: list[TurnStep] = []
    context.audit_logger.log_confirm(context.session_id, proposal.param_name)

    change = ProposedChange(
        param_name=proposal.param_name, new_value=proposal.proposed_value, reason=proposal.reason,
    )
    # The vehicle may have changed since the proposal was shown: validate again
    revalidated = revalidate_before_write(change, context.live_params)

    if not revalidated.accepted:
        context.audit_logger.log_reject(
            context.session_id, proposal.param_name,
            reason=f"pre-write re-validation failed: {revalidated.rejection_message}",
        )
        content = (
            f"This is no longer safe to apply as proposed: {revalidated.rejection_message} "
            "The change was NOT applied."
        )
        steps.append(TurnStep(stage="revalidation", status="blocked", detail=content))
        return content, steps
    steps.append(TurnStep(
        stage="revalidation", status="ok",
        detail=f"Re-validated {proposal.param_name} = {proposal.proposed_value} against fresh live state: accepted.",
    ))

    armed_state = context.vehicle_client.get_armed_state()
    if blocks_write_while_armed(proposal.param_name, armed_state):
        context.audit_logger.log_reject(
            context.session_id, proposal.param_name,
            reason="blocked by the flight-state interlock: vehicle is armed (or arm state could not be confirmed)",
        )
        content = (
            f"Blocked: {proposal.param_name} was NOT applied because the vehicle is "
            "currently armed (or its arm state could not be confirmed), and this "
            "parameter is not on the reviewed in-flight-safe list. Disarm the vehicle "
            "and try again."
        )
        steps.append(TurnStep(stage="flight_state", status="blocked", detail=content))
        return content, steps
    steps.append(TurnStep(
        stage="flight_state", status="ok", detail=f"Flight-state check passed (armed={armed_state}).",
    ))

    recent_applies = [
        e.timestamp for e in context.audit_logger.get_events(context.session_id)
        if e.event_type == AuditEventType.APPLY
    ]
    if rate_limit.blocks_write_due_to_rate_limit(recent_applies):
        context.audit_logger.log_reject(
            context.session_id, proposal.param_name,
            reason=f"blocked by the rate limit: {rate_limit.MAX_APPLIES_PER_WINDOW}+ changes already applied in the last {int(rate_limit.WINDOW.total_seconds())}s",
        )
        content = (
            f"Blocked: {proposal.param_name} was NOT applied because too many changes "
            f"have already been applied in the last {int(rate_limit.WINDOW.total_seconds())} "
            "seconds. Wait a moment before applying more, so each change gets a genuine, "
            "separate review rather than being rushed through."
        )
        steps.append(TurnStep(stage="rate_limit", status="blocked", detail=content))
        return content, steps
    steps.append(TurnStep(
        stage="rate_limit", status="ok",
        detail=f"Rate limit check passed ({len(recent_applies)} applied in the current window).",
    ))

    try:
        set_result = context.vehicle_client.set_param(proposal.param_name, proposal.proposed_value)
    except Exception as e:  # noqa: BLE001
        context.audit_logger.log_reject(
            context.session_id, proposal.param_name,
            reason=f"write failed: {type(e).__name__}: {e}",
        )
        content = (
            f"Could not write {proposal.param_name} to the vehicle: {type(e).__name__}: {e}. "
            "The change was NOT confirmed as applied -- check the connection and try again."
        )
        steps.append(TurnStep(stage="write", status="error", detail=content))
        return content, steps

    before = proposal.current_value if proposal.current_value is not None else 0.0
    after = set_result.acked_value if set_result.acked_value is not None else proposal.proposed_value
    context.audit_logger.log_apply(
        context.session_id, proposal.param_name, before, after,
        reboot_required=proposal.reboot_required,
    )
    content = (
        f"Applied: {proposal.param_name} = {after}"
        if set_result.matches
        else f"Write to {proposal.param_name} was sent but not acknowledged as expected -- verify manually."
    )
    if proposal.dependency_warnings:
        related = ", ".join(name for w in proposal.dependency_warnings for name in w.related_params)
        content += f" Related parameters to review: {related}."
    steps.append(TurnStep(stage="write", status="ok" if set_result.matches else "blocked", detail=content))
    return content, steps


def build_graph(
    context: RuntimeContext,
    chat_model: BaseChatModel,
    checkpointer,
) -> CompiledStateGraph:
    """Compile the agent graph: model -> tools -> human approval -> validated write."""
    tools = build_tools(context)
    tools_by_name = {t.name: t for t in tools}
    model_with_tools = chat_model.bind_tools(tools)

    def agent_node(state: OrchestratorState) -> dict:
        messages = state["messages"]
        if not messages or not isinstance(messages[0], SystemMessage):
            vehicle_line = _vehicle_context_line(context)
            system_text = f"{SYSTEM_PROMPT}\n{vehicle_line}" if vehicle_line else SYSTEM_PROMPT
            messages = [SystemMessage(content=system_text), *messages]

        try:
            # Cap tool rounds so a looping model has to answer
            if _tool_rounds_this_turn(state["messages"]) >= _MAX_TOOL_ROUNDS_PER_TURN:
                forced = [*messages, HumanMessage(content=_FORCE_ANSWER_NOTICE)]
                response = model_with_tools.bind(tool_choice="none").invoke(forced)
                # Some providers ignore tool_choice=none; the turn must end anyway
                if getattr(response, "tool_calls", None):
                    try:
                        response = chat_model.invoke(forced)
                    except Exception:
                        logger.warning("forced no-tools answer failed for session %s", context.session_id, exc_info=True)
                        response = AIMessage(content="")
                    if getattr(response, "tool_calls", None) or not str(response.content or "").strip():
                        response = AIMessage(content=_FORCED_ANSWER_FALLBACK)
            else:
                response = model_with_tools.invoke(messages)
                notice = _unperformed_action_notice(state["messages"], response)
                if notice is not None:
                    response = model_with_tools.invoke([*messages, HumanMessage(content=notice)])
        except Exception as e:
            logger.exception("agent_node: LLM call failed for session %s", context.session_id)
            response = AIMessage(content=f"I hit a technical problem talking to the language model ({type(e).__name__}) and can't continue this turn. Please try again.")
        return {"messages": [response]}

    def tool_node(state: OrchestratorState) -> dict:
        tool_calls = state.get("remaining_tool_calls")
        if not tool_calls:
            last = state["messages"][-1]
            tool_calls = list(getattr(last, "tool_calls", None) or [])

        prior_results = _prior_tool_results(state["messages"])
        new_messages = []
        for idx, call in enumerate(tool_calls):
            # A repeated read-only call is answered from the earlier result
            dedupe_key = _dedupe_key(call["name"], call["args"]) if call["name"] in _DEDUPABLE_TOOLS else None
            if dedupe_key is not None and dedupe_key in prior_results:
                new_messages.append(ToolMessage(
                    content=prior_results[dedupe_key], tool_call_id=call["id"], name=call["name"],
                ))
                continue

            tool = tools_by_name.get(call["name"])
            if tool is None:
                new_messages.append(ToolMessage(
                    content=f"Error: {call['name']!r} is not a recognized tool. "
                            f"Valid tools are: {sorted(tools_by_name)}.",
                    tool_call_id=call["id"], name=call["name"],
                ))
                continue

            try:
                result = tool.invoke(call["args"])
            except Exception as e:  # noqa: BLE001 -- any tool-invocation failure (bad args, a
                new_messages.append(ToolMessage(
                    content=f"Error calling {call['name']}: {type(e).__name__}: {e}",
                    tool_call_id=call["id"], name=call["name"],
                ))
                continue

            if dedupe_key is not None:
                prior_results[dedupe_key] = _serialize_tool_result(result)

            if call["name"] == _PARAM_CHANGE_TOOL and isinstance(result, ValidatedProposal) and result.accepted:
                return {
                    "messages": new_messages,
                    "pending_proposal": result.model_dump(mode="json"),
                    "pending_tool_call_id": call["id"],
                    "remaining_tool_calls": tool_calls[idx + 1:],
                }

            new_messages.append(ToolMessage(
                content=_serialize_tool_result(result), tool_call_id=call["id"], name=call["name"],
            ))

        return {"messages": new_messages, "remaining_tool_calls": None}

    def approval_node(state: OrchestratorState) -> dict:
        # Pauses here; nothing below runs until a human confirms or rejects
        decision = interrupt(state["pending_proposal"])

        proposal = ValidatedProposal.model_validate(state["pending_proposal"])
        tool_call_id = state["pending_tool_call_id"]

        if decision.get("decision") == "confirm":
            content, steps = apply_confirmed_write(context, proposal)
        else:
            reject_reason = decision.get("reason") or "user rejected"
            context.audit_logger.log_reject(context.session_id, proposal.param_name, reason=reject_reason)
            content = f"The user rejected the proposed change to {proposal.param_name}"
            content += f" ({decision.get('reason')}). No write was made." if decision.get("reason") else ". No write was made."
            steps = []

        if proposal.proposal_id is not None:
            context.pending_proposals.pop(proposal.proposal_id, None)

        return {
            "messages": [ToolMessage(
                content=content, tool_call_id=tool_call_id, name=_PARAM_CHANGE_TOOL,
                additional_kwargs={"write_steps": [s.model_dump(mode="json") for s in steps]},
            )],
            "pending_proposal": None,
            "pending_tool_call_id": None,
            "last_action_steps": [s.model_dump(mode="json") for s in steps],
        }

    def route_after_agent(state: OrchestratorState) -> str:
        last = state["messages"][-1]
        return "tool_node" if getattr(last, "tool_calls", None) else END

    def route_after_tool_node(state: OrchestratorState) -> str:
        return "approval_node" if state.get("pending_proposal") is not None else "agent_node"

    def route_after_approval_node(state: OrchestratorState) -> str:
        return "tool_node" if state.get("remaining_tool_calls") else "agent_node"

    graph = StateGraph(OrchestratorState)
    graph.add_node("agent_node", agent_node)
    graph.add_node("tool_node", tool_node)
    graph.add_node("approval_node", approval_node)

    graph.add_edge(START, "agent_node")
    graph.add_conditional_edges("agent_node", route_after_agent, {"tool_node": "tool_node", END: END})
    graph.add_conditional_edges(
        "tool_node", route_after_tool_node, {"approval_node": "approval_node", "agent_node": "agent_node"},
    )
    graph.add_conditional_edges(
        "approval_node", route_after_approval_node, {"tool_node": "tool_node", "agent_node": "agent_node"},
    )

    return graph.compile(checkpointer=checkpointer)
