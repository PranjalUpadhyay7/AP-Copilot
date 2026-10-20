"""POST /chat, POST /chat/stream."""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import openai
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel

from app.api.session_manager import session_manager
from app.models.api import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)

router = APIRouter()

_RECURSION_LIMIT_DETAIL = (
    "This request needed more back-and-forth with the model than this app "
    "allows in one turn. Try breaking your request into smaller, more specific "
    "steps."
)
_NIM_TIMEOUT_DETAIL = (
    "The AI model didn't respond in time. This is usually a transient issue "
    "with the model provider, not this app -- try again. If it keeps "
    "happening, the configured model may be unavailable (see NIM_MODEL "
    "in backend/.env)."
)


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """Run one chat turn and return the reply or a pending proposal."""
    try:
        session = session_manager.get(req.session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        reply, pending_proposal, rejected_proposals, turn_steps, episode_id = session_manager.send_message(session, req.message)
    except GraphRecursionError as e:
        logger.warning("Graph recursion limit hit on /chat for session %s: %s", req.session_id, e)
        raise HTTPException(status_code=504, detail=_RECURSION_LIMIT_DETAIL) from e
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except openai.APIError as e:
        logger.warning("NIM API error on /chat for session %s: %s", req.session_id, e)
        raise HTTPException(status_code=504, detail=_NIM_TIMEOUT_DETAIL) from e

    return ChatResponse(
        session_id=req.session_id, reply=reply, pending_proposal=pending_proposal,
        rejected_proposals=rejected_proposals, turn_steps=turn_steps, episode_id=episode_id,
    )


def _sse_event(event: dict) -> str:
    def _plain(v: object) -> object:
        if isinstance(v, BaseModel):
            return v.model_dump(mode="json")
        if isinstance(v, list):
            return [_plain(item) for item in v]
        return v

    return f"data: {json.dumps({k: _plain(v) for k, v in event.items()})}\n\n"


@router.post("/chat/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    """Same turn as /chat, streamed as server-sent events."""
    try:
        session = session_manager.get(req.session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    def generate() -> Iterator[str]:
        try:
            for event in session_manager.stream_message(session, req.message):
                yield _sse_event(event)
        except GraphRecursionError as e:
            logger.warning("Graph recursion limit hit on /chat/stream for session %s: %s", req.session_id, e)
            yield _sse_event({"type": "error", "status": 504, "detail": _RECURSION_LIMIT_DETAIL})
        except RuntimeError as e:
            yield _sse_event({"type": "error", "status": 409, "detail": str(e)})
        except openai.APIError as e:
            logger.warning("NIM API error on /chat/stream for session %s: %s", req.session_id, e)
            yield _sse_event({"type": "error", "status": 504, "detail": _NIM_TIMEOUT_DETAIL})

    return StreamingResponse(generate(), media_type="text/event-stream")
