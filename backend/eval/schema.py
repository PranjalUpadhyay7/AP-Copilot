"""Benchmark task schema."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, model_validator


class TaskCategory(str, Enum):
    SIMPLE_CONFIG = "simple_config"
    MULTI_STEP_DEPENDENT = "multi_step_dependent"
    FIRMWARE_VERSION_SENSITIVE = "firmware_version_sensitive"
    DIAGNOSTIC_QA = "diagnostic_qa"
    SHOULD_REFUSE = "should_refuse"
    UNDER_SPECIFIED = "under_specified"


class OutcomeType(str, Enum):
    PARAM_WRITTEN = "param_written"
    NO_WRITE = "no_write"
    CLARIFICATION = "clarification"


class ExpectedOutcome(BaseModel):
    type: OutcomeType
    # PARAM_WRITTEN only.
    param_name: str | None = None
    value: float | None = None
    value_tolerance: float = 1e-6
    reply_must_mention: list[str] = []
    must_not_propose: list[str] = []

    @model_validator(mode="after")
    def _param_written_needs_param_and_value(self) -> ExpectedOutcome:
        if self.type == OutcomeType.PARAM_WRITTEN and (self.param_name is None or self.value is None):
            raise ValueError("PARAM_WRITTEN outcome requires param_name and value")
        return self


class BenchTask(BaseModel):
    id: str
    category: TaskCategory
    description: str  # human-readable, for reports -- not shown to the model
    prompt: str
    expected: ExpectedOutcome
    fixture: str = "default_copter"
    overrides: dict[str, float] = {}

    statustext: list[tuple[int, str]] = []
