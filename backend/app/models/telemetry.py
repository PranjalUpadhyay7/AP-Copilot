"""Comms-layer result/event models."""
from __future__ import annotations

from pydantic import BaseModel


class ParamSetResult(BaseModel):
    name: str
    requested_value: float
    acked_value: float | None = None
    acked: bool

    @property
    def matches(self) -> bool:
        return self.acked and self.acked_value is not None and abs(self.acked_value - self.requested_value) < 1e-6


class CommandResult(BaseModel):
    command: int
    accepted: bool
    result_code: int | None = None


class TelemetryEvent(BaseModel):
    field: str
    value: dict
