"""POST /session/start, POST /session/end, GET /session/summary, GET /vehicle/status."""
from __future__ import annotations

import json
import logging
import queue
import threading

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.session_manager import session_manager
from app.audit.logger import AuditEventType
from app.comms import serial_ports
from app.models.api import (
    SessionListEntry,
    SessionStartRequest,
    SessionStartResponse,
    SessionSummary,
    SessionTranscript,
    TranscriptMessage,
    VehicleStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _start_response(session) -> SessionStartResponse:
    undocumented = sum(1 for p in session.context.live_params.values() if not p.is_documented)
    return SessionStartResponse(
        session_id=session.session_id,
        vehicle_type=session.vehicle_type,
        firmware_version=session.firmware_version,
        param_count=len(session.context.live_params),
        undocumented_param_count=undocumented,
        frame_label=(session.context.vehicle_info or {}).get("frame_label"),
        board_label=(session.context.vehicle_info or {}).get("board_label"),
        read_only=session.read_only,
    )


@router.post("/session/start/stream")
def start_session_stream(req: SessionStartRequest) -> StreamingResponse:
    """Start a session, streaming progress events."""
    events: queue.Queue = queue.Queue()

    def run() -> None:
        try:
            session = session_manager.start_session(
                req.connection_string, mode=req.mode,
                sitl_settings=req.sitl_settings.model_dump() if req.sitl_settings else None,
                llm_config=req.llm_config.model_dump() if req.llm_config else None,
                progress=events.put,
            )
            events.put({"type": "final", **_start_response(session).model_dump()})
        except (TimeoutError, ConnectionError) as e:
            events.put({"type": "error", "status": 502, "detail": f"could not connect to vehicle: {e}{_connect_hint(req)}"})
        except Exception as e:
            logger.exception("session start failed")
            events.put({"type": "error", "status": 500, "detail": f"session start failed: {e}"})
        events.put(None)

    threading.Thread(target=run, daemon=True).start()

    def generate():
        while (event := events.get()) is not None:
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/session/start", response_model=SessionStartResponse)
def start_session(req: SessionStartRequest) -> SessionStartResponse:
    try:
        session = session_manager.start_session(
            req.connection_string,
            mode=req.mode,
            sitl_settings=req.sitl_settings.model_dump() if req.sitl_settings else None,
            llm_config=req.llm_config.model_dump() if req.llm_config else None,
        )
    except (TimeoutError, ConnectionError) as e:
        raise HTTPException(status_code=502, detail=f"could not connect to vehicle: {e}{_connect_hint(req)}") from e

    return _start_response(session)


@router.post("/session/reboot/stream")
def reboot_stream(session_id: str) -> StreamingResponse:
    """Reboot the vehicle and reconnect this session, streaming progress."""
    try:
        session = session_manager.get(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    events: queue.Queue = queue.Queue()

    def run() -> None:
        try:
            result = session_manager.reboot_vehicle(session, progress=events.put)
            events.put({"type": "final", **result})
        except RuntimeError as e:
            events.put({"type": "error", "status": 409, "detail": str(e)})
        except (TimeoutError, ConnectionError) as e:
            events.put({"type": "error", "status": 502, "detail": str(e)})
        except Exception as e:
            logger.exception("reboot failed")
            events.put({"type": "error", "status": 500, "detail": f"reboot failed: {e}"})
        events.put(None)

    threading.Thread(target=run, daemon=True).start()

    def generate():
        while (event := events.get()) is not None:
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/session/end", response_model=SessionSummary)
def end_session(session_id: str) -> SessionSummary:
    try:
        session = session_manager.end_session(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _build_summary(session)


@router.get("/session/summary", response_model=SessionSummary)
def get_session_summary(session_id: str) -> SessionSummary:
    try:
        session = session_manager.get(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _build_summary(session)


def list_serial_ports() -> list[str]:
    return [p["path"] for p in serial_ports.list_ports()]


def _connect_hint(req) -> str:
    if req.mode != "hardware":
        return ""
    ports = list_serial_ports()
    if req.connection_string.startswith("tcp:") and ports:
        return f" -- nothing is serving that TCP address. Serial devices detected: {', '.join(ports)}; enter one of those instead."
    if req.connection_string.startswith("/dev/") and not ports:
        return " -- that serial device is not present (is the flight controller plugged in?)."
    return ""


@router.get("/ports")
def get_serial_ports() -> list[dict]:
    return serial_ports.list_ports()


@router.get("/session/retrieval-stats")
def get_retrieval_stats(session_id: str) -> dict:
    try:
        session = session_manager.get(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return session.context.retrieval_stats.as_dict()


def _build_summary(session) -> SessionSummary:
    events = session.context.audit_logger.get_events(session.session_id)
    applied = sum(1 for e in events if e.event_type == AuditEventType.APPLY)
    rejected = sum(1 for e in events if e.event_type == AuditEventType.REJECT)
    pending = len(session.context.pending_proposals)
    reboot_required = sorted({
        e.param_name for e in events
        if e.event_type == AuditEventType.APPLY and e.reboot_required
    })

    text, params = session_manager.safety_snapshot_text_and_params(session)
    return SessionSummary(
        session_id=session.session_id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        applied_count=applied,
        rejected_count=rejected,
        pending_count=pending,
        reboot_required_params=reboot_required,
        safety_snapshot_text=text,
        safety_snapshot_params=params,
    )


@router.get("/sessions", response_model=list[SessionListEntry])
def list_sessions() -> list[SessionListEntry]:
    return [
        SessionListEntry(
            session_id=r.session_id, started_at=r.started_at, ended_at=r.ended_at,
            vehicle_type=r.vehicle_type, firmware_version=r.firmware_version, read_only=r.read_only,
        )
        for r in session_manager.list_session_history()
    ]


@router.get("/sessions/{session_id}/transcript", response_model=SessionTranscript)
def get_session_transcript(session_id: str) -> SessionTranscript:
    if session_manager.session_store.get(session_id) is None:
        raise HTTPException(status_code=404, detail=f"no such session: {session_id}")
    messages = session_manager.get_transcript(session_id)
    return SessionTranscript(
        session_id=session_id,
        messages=[TranscriptMessage(**m) for m in messages],
    )


@router.get("/vehicle/status", response_model=VehicleStatus)
def vehicle_status(session_id: str) -> VehicleStatus:
    """Connection state and identity of the vehicle behind a session."""
    try:
        session = session_manager.get(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return VehicleStatus(
        session_id=session.session_id,
        connected=session.context.vehicle_client.is_connected,
        vehicle_type=session.vehicle_type,
        firmware_version=session.firmware_version,
        read_only=session.read_only,
        frame_label=(session.context.vehicle_info or {}).get("frame_label"),
        board_label=(session.context.vehicle_info or {}).get("board_label"),
    )
