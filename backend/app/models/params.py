"""Firmware-aware parameter metadata models."""
from __future__ import annotations

from pydantic import BaseModel


class ParamDefinition(BaseModel):
    name: str
    vehicle_types: list[str]
    firmware_version: str
    description: str
    unit: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    increment: float | None = None
    bitmask: dict[int, str] | None = None
    reboot_required: bool = False
    values: dict[str, str] | None = None
    doc_url: str | None = None
    github_source_url: str | None = None


class LiveParam(BaseModel):
    name: str
    current_value: float
    definition: ParamDefinition | None = None

    @property
    def is_documented(self) -> bool:
        return self.definition is not None
