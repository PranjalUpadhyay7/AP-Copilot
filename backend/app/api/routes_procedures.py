"""Multi-step procedure endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.session_manager import session_manager
from app.models.api import ProcedureDecisionRequest, ProcedureDecisionResponse
from app.orchestrator.tools import ProcedureProposal

router = APIRouter()


@router.get("/procedures", response_model=list[ProcedureProposal])
def list_procedures(session_id: str) -> list[ProcedureProposal]:
    try:
        session = session_manager.get(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return list(session.context.pending_procedures.values())


@router.post("/procedures/compass-calibration/start", response_model=ProcedureProposal)
def start_compass_calibration(session_id: str) -> ProcedureProposal:
    try:
        session = session_manager.get(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return session_manager.start_compass_calibration(session)


@router.post("/procedures/{procedure_id}/confirm", response_model=ProcedureDecisionResponse)
def confirm_procedure(procedure_id: str, req: ProcedureDecisionRequest) -> ProcedureDecisionResponse:
    return _resolve(procedure_id, req.session_id, "confirm")


@router.post("/procedures/{procedure_id}/reject", response_model=ProcedureDecisionResponse)
def reject_procedure(procedure_id: str, req: ProcedureDecisionRequest) -> ProcedureDecisionResponse:
    return _resolve(procedure_id, req.session_id, "reject")


def _resolve(procedure_id: str, session_id: str, decision: str) -> ProcedureDecisionResponse:
    try:
        session = session_manager.get(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        result = session_manager.resolve_procedure(session, procedure_id, decision)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return ProcedureDecisionResponse(procedure_id=procedure_id, outcome=result["outcome"], detail=result["detail"])
