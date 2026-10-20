"""GET /proposals, POST /proposals/{id}/confirm, POST /proposals/{id}/reject, GET /safety-snapshot."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.api.session_manager import session_manager
from app.models.api import (
    AuditEventResponse,
    AuditVerifyResponse,
    EpisodeFeedbackRequest,
    ProposalDecisionRequest,
    ProposalDecisionResponse,
    ProposalReviseRequest,
    RollbackRequest,
)
from app.models.proposal import ValidatedProposal
from app.telemetry import rl_log

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/proposals", response_model=list[ValidatedProposal])
def list_proposals(session_id: str) -> list[ValidatedProposal]:
    try:
        session = session_manager.get(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return list(session.context.pending_proposals.values())


@router.post("/proposals/{proposal_id}/confirm", response_model=ProposalDecisionResponse)
def confirm_proposal(proposal_id: str, req: ProposalDecisionRequest) -> ProposalDecisionResponse:
    return _resolve(proposal_id, req.session_id, "confirm")


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalDecisionResponse)
def reject_proposal(proposal_id: str, req: ProposalDecisionRequest) -> ProposalDecisionResponse:
    return _resolve(proposal_id, req.session_id, "reject", reason=req.reason)


_LIVE_PARAM_REFRESH_FAILED_DETAIL = (
    "Could not read a fresh set of parameters from the vehicle before this write -- the "
    "connection may be too slow or lossy right now. Nothing was changed; try again."
)


@router.post("/proposals/{proposal_id}/revise", response_model=ValidatedProposal)
def revise_proposal(proposal_id: str, req: ProposalReviseRequest) -> ValidatedProposal:
    try:
        session = session_manager.get(req.session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        return session_manager.revise_proposal(session, proposal_id, req.new_value)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except TimeoutError as e:
        logger.warning("live-param refresh timed out on /proposals/%s/revise: %s", proposal_id, e)
        raise HTTPException(status_code=502, detail=_LIVE_PARAM_REFRESH_FAILED_DETAIL) from e


def _resolve(proposal_id: str, session_id: str, decision: str, reason: str | None = None) -> ProposalDecisionResponse:
    try:
        session = session_manager.get(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        outcome, detail, steps, episode_id = session_manager.resolve_proposal(session, proposal_id, decision, reason=reason)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except TimeoutError as e:
        logger.warning("live-param refresh timed out resolving proposal %s: %s", proposal_id, e)
        raise HTTPException(status_code=502, detail=_LIVE_PARAM_REFRESH_FAILED_DETAIL) from e

    return ProposalDecisionResponse(
        proposal_id=proposal_id, outcome=outcome, detail=detail, steps=steps, episode_id=episode_id,
    )


@router.post("/episodes/{episode_id}/feedback")
def episode_feedback(episode_id: str, req: EpisodeFeedbackRequest) -> dict:
    try:
        session_manager.get(req.session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    rl_log.log_resolution_signal(episode_id, "worked" if req.worked else "did_not_work")
    return {"recorded": True}


@router.get("/audit/verify", response_model=AuditVerifyResponse)
def verify_audit_chain(session_id: str) -> AuditVerifyResponse:
    try:
        session = session_manager.get(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    intact, broken_at_event_id = session.context.audit_logger.verify_chain()
    return AuditVerifyResponse(intact=intact, broken_at_event_id=broken_at_event_id)


@router.get("/audit", response_model=list[AuditEventResponse])
def list_audit_events(session_id: str) -> list[AuditEventResponse]:
    """Raw audit trail for a session."""
    try:
        session = session_manager.get(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    events = session.context.audit_logger.get_events(session.session_id)
    return [
        AuditEventResponse(
            id=e.id, timestamp=e.timestamp, event_type=e.event_type.value, param_name=e.param_name,
            before_value=e.before_value, after_value=e.after_value, reason=e.reason,
            criticality=e.criticality, reboot_required=e.reboot_required,
            prev_hash=e.prev_hash, hash=e.hash,
        )
        for e in events
    ]


@router.post("/audit/{event_id}/rollback", response_model=ValidatedProposal)
def rollback_change(event_id: int, req: RollbackRequest) -> ValidatedProposal:
    try:
        session = session_manager.get(req.session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        return session_manager.propose_rollback(session, event_id)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except TimeoutError as e:
        logger.warning("live-param refresh timed out proposing rollback for event %s: %s", event_id, e)
        raise HTTPException(status_code=502, detail=_LIVE_PARAM_REFRESH_FAILED_DETAIL) from e


@router.get("/safety-snapshot")
def safety_snapshot(session_id: str, format: str = "json"):
    try:
        session = session_manager.get(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    text, params = session_manager.safety_snapshot_text_and_params(session)
    if format == "text":
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(text)
    return {"text": text, "params": [p.model_dump() for p in params]}
