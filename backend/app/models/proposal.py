"""Validation Layer output models."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from app.models.params import ParamDefinition


class Criticality(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    CRITICAL = "critical"


class RejectionReason(str, Enum):
    NOT_FOUND = "not_found"
    UNDOCUMENTED = "undocumented"
    TYPE_MISMATCH = "type_mismatch"
    OUT_OF_RANGE = "out_of_range"
    INVALID_BITMASK_VALUE = "invalid_bitmask_value"
    INVALID_ENUM_VALUE = "invalid_enum_value"
    HARD_BLOCKED = "hard_blocked"
    ALREADY_SET = "already_set"


class ProposedChange(BaseModel):
    """What the LLM's `propose_param_change` tool call produces."""

    param_name: str
    new_value: float
    reason: str


class DependencyWarning(BaseModel):
    related_params: list[str]
    message: str


class ValidatedProposal(BaseModel):
    """A proposal after validation: accepted, or rejected with a reason."""
    param_name: str
    current_value: float | None
    proposed_value: float
    reason: str

    accepted: bool
    rejection_reason: RejectionReason | None = None
    rejection_message: str | None = None

    criticality: Criticality | None = None
    dependency_warnings: list[DependencyWarning] = []
    reboot_required: bool = False
    definition: ParamDefinition | None = None

    proposal_id: str | None = None
