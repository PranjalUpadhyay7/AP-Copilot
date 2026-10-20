"""Request/response models for the backend API surface."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models.proposal import ValidatedProposal
from app.validation.safety_snapshot import SafetyParamEntry


class SITLSettingsRequest(BaseModel):
    vehicle: str = "copter"   # "copter" | "plane"
    frame: str | None = None  # defaults per vehicle if omitted
    instance: int = 0
    wipe_eeprom: bool = True
    speedup: int = 1


class LLMConfigRequest(BaseModel):
    base_url: str
    api_key: str
    model: str


class SessionStartRequest(BaseModel):
    mode: str = "hardware"  # "hardware" | "simulation"
    connection_string: str = "tcp:127.0.0.1:5760"  # used when mode == "hardware"
    sitl_settings: SITLSettingsRequest | None = None  # used when mode == "simulation"
    llm_config: LLMConfigRequest | None = None  # omit to use the server-configured .env model


class SessionStartResponse(BaseModel):
    session_id: str
    vehicle_type: str
    firmware_version: str
    param_count: int
    undocumented_param_count: int
    frame_label: str | None = None
    board_label: str | None = None  # hardware, e.g. "Hex ProfiCNC CubeBlack" (from the USB name) or "Simulator (SITL)"
    read_only: bool


class ChatRequest(BaseModel):
    session_id: str
    message: str


class TurnStep(BaseModel):
    stage: str
    tool_name: str | None = None
    status: str  # "ok" | "blocked" | "error"
    detail: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str | None  # None if the turn ended in a pending approval rather than a final message
    pending_proposal: ValidatedProposal | None = None
    rejected_proposals: list[ValidatedProposal] = []
    turn_steps: list[TurnStep] = []
    episode_id: str | None = None


class ProposalDecisionRequest(BaseModel):
    session_id: str
    reason: str | None = None


class ProposalReviseRequest(BaseModel):
    session_id: str
    new_value: float


class RollbackRequest(BaseModel):
    session_id: str


class AuditVerifyResponse(BaseModel):
    intact: bool
    broken_at_event_id: int | None


class AuditEventResponse(BaseModel):
    id: int
    timestamp: datetime
    event_type: str
    param_name: str
    before_value: float | None
    after_value: float | None
    reason: str | None
    criticality: str | None
    reboot_required: bool
    prev_hash: str
    hash: str


class ProposalDecisionResponse(BaseModel):
    proposal_id: str
    outcome: str  # "applied" | "rejected" | "blocked_at_write_time"
    detail: str
    steps: list[TurnStep] = []
    episode_id: str | None = None


class EpisodeFeedbackRequest(BaseModel):
    session_id: str
    worked: bool


class SessionSummary(BaseModel):
    session_id: str
    started_at: datetime
    ended_at: datetime | None
    applied_count: int
    rejected_count: int
    pending_count: int
    reboot_required_params: list[str]
    safety_snapshot_text: str
    safety_snapshot_params: list[SafetyParamEntry]


class VehicleStatus(BaseModel):
    session_id: str
    connected: bool
    vehicle_type: str
    firmware_version: str
    read_only: bool
    frame_label: str | None = None
    board_label: str | None = None


class ProcedureDecisionRequest(BaseModel):
    session_id: str


class ProcedureDecisionResponse(BaseModel):
    procedure_id: str
    outcome: str  # "triggered" | "trigger_not_acknowledged" | "acknowledged" | "rejected"
    detail: object


class SessionListEntry(BaseModel):
    session_id: str
    started_at: datetime
    ended_at: datetime | None
    vehicle_type: str
    firmware_version: str
    read_only: bool


class TranscriptMessage(BaseModel):
    role: str  # "user" | "assistant" | "tool"
    content: str
    tool_name: str | None = None
    turn_steps: list[TurnStep] | None = None
    rejected_proposals: list[ValidatedProposal] | None = None


class SessionTranscript(BaseModel):
    session_id: str
    messages: list[TranscriptMessage]
