"""Graph State."""
from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class OrchestratorState(TypedDict):
    messages: Annotated[list, add_messages]
    session_id: str
    pending_proposal: dict | None
    pending_tool_call_id: str | None
    remaining_tool_calls: list[dict] | None
    last_action_steps: list[dict] | None
