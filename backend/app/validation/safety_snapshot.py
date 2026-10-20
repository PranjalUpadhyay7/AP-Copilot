"""Safety Parameter Snapshot."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from pydantic import BaseModel

from app.models.params import LiveParam

_SAFETY_PREFIXES = (
    "FS_",       # all failsafe action/threshold params
    "FENCE_",    # enable + radius/altitude
)

_SAFETY_EXACT_CANDIDATES = (
    "ARMING_CHECK",     # pre-rename name, kept in case an older firmware still uses it
    "ARMING_SKIPCHK",
    "BATT_LOW_VOLT", "BATT_CRT_VOLT",
    "BATT_LOW_MAH", "BATT_CRT_MAH",
    "RC_FS_TIMEOUT",
    "EK2_ENABLE", "EK3_ENABLE", "AHRS_EKF_TYPE",  # EKF failsafe action lives under FS_EKF_*, covered by prefix
    "GPS_TYPE", "GPS_PRIMARY",
)


def _is_safety_param(name: str) -> bool:
    return name.startswith(_SAFETY_PREFIXES) or name in _SAFETY_EXACT_CANDIDATES


class SafetyParamEntry(BaseModel):
    name: str
    current_value: float
    documented: bool


class SafetySnapshot(BaseModel):
    """Values of the safety-critical parameters at one point in time."""
    timestamp: datetime
    params: list[SafetyParamEntry]

    def as_text(self) -> str:
        lines = [f"Safety Parameter Snapshot ({self.timestamp.isoformat()})", "-" * 50]
        if not self.params:
            lines.append("(no safety-relevant parameters found on this vehicle)")
        for p in sorted(self.params, key=lambda e: e.name):
            flag = "" if p.documented else "  [undocumented for this firmware]"
            lines.append(f"{p.name:<24} = {p.current_value}{flag}")
        return "\n".join(lines)

    def as_json(self) -> str:
        return json.dumps(
            {
                "timestamp": self.timestamp.isoformat(),
                "params": [p.model_dump() for p in self.params],
            },
            indent=2,
        )


def compute_safety_snapshot(live_params: dict[str, LiveParam]) -> SafetySnapshot:
    entries = [
        SafetyParamEntry(name=name, current_value=p.current_value, documented=p.is_documented)
        for name, p in live_params.items()
        if _is_safety_param(name)
    ]
    return SafetySnapshot(timestamp=datetime.now(UTC), params=entries)
