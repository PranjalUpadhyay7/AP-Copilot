"""Tool schemas + dispatch."""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from app.audit.logger import AuditLogger
from app.comms.status_text import collect_recent_statustext
from app.comms.vehicle_client import VehicleClient
from app.knowledge.rag_store import (
    DocChunk,
    EmbeddingIndex,
    HybridIndex,
    LexicalIndex,
    expand_query,
    search_ardupilot_docs,
)
from app.knowledge.retrieval_stats import RetrievalStats
from app.knowledge.web_research import search_web_docs, verify_against_official
from app.knowledge.wiki_docs import search_wiki_docs
from app.models.params import LiveParam
from app.models.proposal import ProposedChange, ValidatedProposal
from app.validation.validators import validate_proposed_change


class StepSpec(BaseModel):
    description: str
    manual: bool = True  # True: human must perform this step; False: automatable via VehicleClient


class ProcedureProposal(BaseModel):
    procedure_id: str
    title: str
    steps: list[StepSpec]


@dataclass
class RuntimeContext:
    session_id: str
    vehicle_client: VehicleClient
    live_params: dict[str, LiveParam]
    audit_logger: AuditLogger
    rag_index: LexicalIndex | HybridIndex | None = None
    wiki_index: EmbeddingIndex | None = None
    board_name: str | None = None
    vehicle_info: dict | None = None
    definitions: dict | None = None
    retrieval_stats: RetrievalStats = field(default_factory=RetrievalStats)
    pending_proposals: dict[str, ValidatedProposal] = field(default_factory=dict)
    pending_procedures: dict[str, ProcedureProposal] = field(default_factory=dict)


def _official_lexical_index(rag_index: LexicalIndex | HybridIndex) -> LexicalIndex:
    return rag_index.lexical if isinstance(rag_index, HybridIndex) else rag_index


_HARDWARE_QUERY_RE = re.compile(
    r"\b(wir(e|ing)|connect|port|pinout|power|uart|serial|telem\w*|hardware|board|flight controller|gps|sensor)\b",
    re.IGNORECASE,
)


_expand_query = expand_query


MAX_QUERY_VARIANTS = 4
MAX_RESULTS = 8
MAX_CHUNK_CHARS = 700


def _search_tiers(context: RuntimeContext, query: str) -> list[DocChunk]:
    stats = context.retrieval_stats
    t0 = time.perf_counter()
    official_results = search_ardupilot_docs(query, context.rag_index) if context.rag_index is not None else []
    if context.rag_index is not None:
        stats.tiers["official"].record(
            time.perf_counter() - t0, official_results[0].ranking_score if official_results else None,
        )

    t0 = time.perf_counter()
    wiki_results = search_wiki_docs(query, context.wiki_index) if context.wiki_index is not None else []
    if context.wiki_index is not None:
        stats.tiers["wiki"].record(time.perf_counter() - t0, wiki_results[0].ranking_score if wiki_results else None)
    if context.wiki_index is not None and context.board_name and _HARDWARE_QUERY_RE.search(query):
        seen = {(c.source, c.text) for c in wiki_results}
        wiki_results += [
            c for c in search_wiki_docs(f"{context.board_name} {query}", context.wiki_index) if (c.source, c.text) not in seen
        ]
    stats.both_local_tiers_hit += bool(official_results and wiki_results)
    return official_results + wiki_results


def _search_ardupilot_docs(
    context: RuntimeContext, query: str, alternate_queries: list[str] | None = None,
) -> list[DocChunk]:
    queries = [_expand_query(query)]
    for alt in _as_str_list(alternate_queries):
        if alt.strip() and alt.strip() not in queries:
            queries.append(alt.strip())
    merged: dict[tuple[str, str], DocChunk] = {}
    for q in queries[:MAX_QUERY_VARIANTS]:
        for chunk in _search_tiers(context, q):
            key = (chunk.source, chunk.text)
            if key not in merged or chunk.ranking_score > merged[key].ranking_score:
                merged[key] = chunk
    context.retrieval_stats.searches += 1
    top = sorted(merged.values(), key=lambda c: c.ranking_score, reverse=True)[:MAX_RESULTS]
    return [c.model_copy(update={"text": c.text[:MAX_CHUNK_CHARS]}) if len(c.text) > MAX_CHUNK_CHARS else c for c in top]


def _search_web(context: RuntimeContext, query: str) -> list[DocChunk] | str:
    stats = context.retrieval_stats
    stats.web_fallbacks += 1
    t0 = time.perf_counter()
    results = search_web_docs(query)
    stats.tiers["web"].record(time.perf_counter() - t0, results[0].ranking_score if results else None)
    if not results:
        return "No web results (web search is disabled, unreachable, or found nothing)."
    if context.rag_index is not None:
        results = verify_against_official(results, _official_lexical_index(context.rag_index))
    return results


def _similar_live_params(context: RuntimeContext, name: str, limit: int = 8) -> list[str]:
    tokens = name.split("_")
    for i in range(1, len(tokens)):
        suffix = "_".join(tokens[i:])
        if len(suffix) < 4:
            break
        found = sorted(p for p in context.live_params if suffix in p and p != name)
        if found:
            return found[:limit]
    return []


def _vehicle_context_line(context: RuntimeContext) -> str:
    info = context.vehicle_info
    if not info:
        return ""
    kind = f"{info['frame_label']} running " if info.get("frame_label") else ""
    parts = [f"{kind}{info.get('vehicle_type')} firmware {info.get('firmware_version')}"]
    if info.get("git_hash"):
        parts.append(f"git {info['git_hash']}")
    if context.board_name:
        parts.append(f"board {context.board_name}")
    return "Connected vehicle (read from the autopilot at connection; do not ask the user for it): " + ", ".join(parts) + "."


_PARENT_SUFFIXES = ("TYPE", "ENABLE", "ENABLED", "EN", "ENABLE_")


def _absent_but_documented_hint(context: RuntimeContext, name: str) -> str:
    if not context.definitions or name not in context.definitions:
        return ""
    prefix = name.split("_")[0]
    parents = [
        f"{p}={context.live_params[p].current_value:g}"
        for p in (f"{prefix}_{suffix}" for suffix in _PARENT_SUFFIXES)
        if p in context.live_params
    ]
    hint = (
        f" {name} IS documented for this firmware ({(context.vehicle_info or {}).get('firmware_version', '?')}) but is "
        "not on the vehicle right now: many parameters only appear after a related parameter is enabled and the "
        "autopilot is rebooted."
    )
    if parents:
        hint += f" Related parameter(s) currently: {', '.join(parents)}."
    hint += (
        " Tell the user to set/enable the parent parameter (via a normal proposal), then use the Reboot button in "
        "the header, and look again afterwards. Do NOT tell them the feature is unsupported."
    )
    return hint


def _get_current_param(context: RuntimeContext, name: str) -> LiveParam | str:
    live = context.live_params.get(name)
    if live is None:
        msg = f"NotFound: {name} does not exist on this vehicle's live parameter set." + _absent_but_documented_hint(context, name)
        similar = _similar_live_params(context, name)
        if similar:
            msg += (
                f" Similar live parameters (names change between firmware versions): {', '.join(similar)}."
            )
        return msg
    return live


def _list_params_matching(context: RuntimeContext, pattern: str) -> list[LiveParam]:
    import fnmatch

    return [p for name, p in context.live_params.items() if fnmatch.fnmatch(name, pattern)]


def _propose_param_change(context: RuntimeContext, name: str, new_value: float, reason: str) -> ValidatedProposal:
    change = ProposedChange(param_name=name, new_value=new_value, reason=reason)
    result = validate_proposed_change(change, context.live_params)
    if not result.accepted and result.rejection_reason == "not_found":
        hint = _absent_but_documented_hint(context, name)
        if hint:
            result = result.model_copy(update={"rejection_message": f"{result.rejection_message or ''}{hint}"})

    proposal_id = str(uuid.uuid4())
    result = result.model_copy(update={"proposal_id": proposal_id})
    # Held for human confirmation; the model can never write directly
    context.pending_proposals[proposal_id] = result
    context.audit_logger.log_proposal(context.session_id, result)
    return result


def _propose_multi_step_procedure(context: RuntimeContext, title: str, steps: list[StepSpec]) -> ProcedureProposal:
    procedure_id = str(uuid.uuid4())
    proposal = ProcedureProposal(procedure_id=procedure_id, title=title, steps=steps)
    context.pending_procedures[procedure_id] = proposal
    return proposal


def _request_vehicle_telemetry(context: RuntimeContext, field: str, overall_timeout: float = 5.0) -> dict | str:
    msg_type, _, subfield = field.partition(".")
    for event in context.vehicle_client.stream_telemetry(fields=[msg_type], timeout=1.0, max_wait=overall_timeout):
        if subfield:
            if subfield not in event.value:
                return f"NotFound: {msg_type} has no field '{subfield}'"
            return {subfield: event.value[subfield]}
        return event.value
    return f"NotFound: no {msg_type} telemetry received within {overall_timeout}s"


def _as_int(value, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(float(value))))
    except (TypeError, ValueError):
        return default


def _as_str_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                value = json.loads(text)
            except ValueError:
                return [text]
        else:
            return [text] if text else []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if isinstance(v, (str, int, float)) and str(v).strip()]
    return []


def _get_recent_status_messages(context: RuntimeContext, count: int = 10) -> list[dict] | str:
    count = _as_int(count, default=10, lo=1, hi=50)
    recent = getattr(context.vehicle_client, "recent_status_messages", None)
    buffered = recent(count) if recent is not None else None
    if buffered:
        return buffered
    entries = collect_recent_statustext(context.vehicle_client, max_count=count) if buffered is None else []
    if not entries:
        return (
            "No STATUSTEXT diagnostic messages received "
            + ("since this session connected. " if buffered is not None else "in the last few seconds. ")
            + "ArduPilot re-sends an active PreArm failure roughly every couple of "
            "seconds while it persists -- if the user just reported a problem, "
            "ask them to try the action again (e.g. attempt to arm) and retry this."
        )
    return entries


def build_tools(context: RuntimeContext) -> list[StructuredTool]:
    """The tools the model can call; none of them writes to the vehicle."""
    return [
        StructuredTool.from_function(
            func=lambda query, alternate_queries=None: _search_ardupilot_docs(context, query, alternate_queries),
            name="search_ardupilot_docs",
            description="You design the queries. `query` is your best search; "
                        "`alternate_queries` (up to 3) MUST list other names for the same "
                        "thing -- the user's words often differ from ArduPilot's own terms "
                        "(e.g. a camera 'strobe'/'flash'/'hotshoe' output is documented as "
                        "camera 'feedback'; 'kill switch' is 'motor emergency stop'), so "
                        "think of ArduPilot's terminology, parameter-name fragments and "
                        "related features first. All variants are searched and merged. "
                        "Search ArduPilot parameter documentation AND the full ArduPilot "
                        "documentation site (tuning guides, setup/calibration procedures, "
                        "hardware docs) for a query. Results are tagged by source: "
                        "'official' (version-pinned exact parameter definitions), 'wiki' "
                        "(the ArduPilot documentation site -- good for procedural/how-to "
                        "questions a bare parameter description can't answer), each with a "
                        "reliability score. For anything not found here, use `search_web`. Always call this (or "
                        "get_current_param) before proposing a value you haven't just "
                        "retrieved -- never propose from memory. Only state something as "
                        "fact from an official/wiki source; caveat anything with an "
                        "'unverified' web tag explicitly to the user.",
        ),
        StructuredTool.from_function(
            func=lambda query: _search_web(context, query),
            name="search_web",
            description="Search the internet (ardupilot.org) when `search_ardupilot_docs` "
                        "returned nothing relevant after you tried alternate names. Your call: "
                        "use it when the docs didn't answer, not as a first step. Results are "
                        "advisory and tagged 'web' -- attribute them, and pass on any "
                        "'[unverified against official docs]' caveat.",
        ),
        StructuredTool.from_function(
            func=lambda name: _get_current_param(context, name),
            name="get_current_param",
            description="Get the live current value and metadata for a named parameter on "
                        "the connected vehicle. Returns 'NotFound: ...' if it doesn't exist.",
        ),
        StructuredTool.from_function(
            func=lambda pattern: _list_params_matching(context, pattern),
            name="list_params_matching",
            description="List live parameters matching a glob pattern (e.g. 'ATC_RAT_RLL_*').",
        ),
        StructuredTool.from_function(
            func=lambda name, new_value, reason: _propose_param_change(context, name, new_value, reason),
            name="propose_param_change",
            description="Propose a change to a single parameter. This does NOT write to the "
                        "vehicle -- it runs the change through deterministic validation and "
                        "returns a ValidatedProposal, which may already be a rejection. You "
                        "must relay a rejection honestly, not retry silently with a different "
                        "value without telling the user. You never assert a change has been "
                        "made -- only the user's explicit confirm can cause a write.",
        ),
        StructuredTool.from_function(
            func=lambda title, steps: _propose_multi_step_procedure(context, title, steps),
            name="propose_multi_step_procedure",
            description="Propose a named multi-step procedure (e.g. compass calibration) as "
                        "a list of steps for the user to review, not an immediate action.",
        ),
        StructuredTool.from_function(
            func=lambda field: _request_vehicle_telemetry(context, field),
            name="request_vehicle_telemetry",
            description="Read a live telemetry value from the connected vehicle (read-only). "
                        "`field` is a MAVLink message type, optionally with '.subfield', e.g. "
                        "'ATTITUDE.roll' or 'GLOBAL_POSITION_INT'.",
        ),
        StructuredTool.from_function(
            func=lambda count=10: _get_recent_status_messages(context, count),
            name="get_recent_status_messages",
            description="Get the vehicle's recent diagnostic STATUSTEXT messages (read-only) -- "
                        "PreArm check failures, EKF/GPS warnings, calibration progress, and "
                        "similar text the flight controller reports on its own. Always call "
                        "this first when the user asks why something won't arm, reports an "
                        "error, or asks 'what's wrong' -- these messages are the vehicle's own "
                        "words about the problem, more reliable than guessing from parameter "
                        "values alone. Covers the whole session since connecting: each entry has "
                        "`count` (how many times it repeated) and `seconds_ago` (when last seen), so "
                        "tell an ACTIVE problem (repeating, seen seconds ago) from an old one. "
                        "`count` is how many recent messages to return (default 10).",
        ),
    ]
