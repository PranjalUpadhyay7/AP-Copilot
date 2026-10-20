"""Vehicle identity models used to key the metadata cache."""
from __future__ import annotations

from pydantic import BaseModel


class VehicleVersionInfo(BaseModel):
    """Identifies exactly which firmware a connected vehicle is running."""

    vehicle_type: str  # e.g. "ArduCopter", "ArduPlane" -- matches param_parse.py's --vehicle values
    mav_type: int  # raw HEARTBEAT.type, kept for diagnostics
    board_type: int  # AUTOPILOT_VERSION.board_version
    flight_sw_version: str  # dotted version, e.g. "4.6.0"
    git_hash: str | None = None  # from AUTOPILOT_VERSION.flight_custom_version, if non-zero

    @property
    def version_key(self) -> str:
        return self.git_hash if self.git_hash else self.flight_sw_version
