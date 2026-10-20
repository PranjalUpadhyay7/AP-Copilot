"""Resolve a board name from AUTOPILOT_VERSION.board_version."""

from __future__ import annotations

import re
import urllib.request
from pathlib import Path

BOARD_TYPES_URL = "https://raw.githubusercontent.com/ArduPilot/ardupilot/master/Tools/AP_Bootloader/board_types.txt"
_LINE_RE = re.compile(r"^(?:AP_HW_|TARGET_HW_)(\w+)\s+(\d+)\s*$")


def parse_board_types(text: str) -> dict[int, str]:
    """ID -> name with the AP_HW_/TARGET_HW_ prefix stripped; comments and unparseable lines are skipped."""
    boards: dict[int, str] = {}
    for line in text.splitlines():
        m = _LINE_RE.match(line.strip())
        if m:
            boards.setdefault(int(m.group(2)), m.group(1))
    return boards


def _load_registry_text(ardupilot_root: str | None) -> str | None:
    if ardupilot_root:
        path = Path(ardupilot_root) / "Tools/AP_Bootloader/board_types.txt"
        if path.is_file():
            return path.read_text(errors="ignore")
    try:
        with urllib.request.urlopen(BOARD_TYPES_URL, timeout=5) as resp:
            return resp.read().decode(errors="ignore")
    except OSError:
        return None


def resolve_board_name(board_version: int, ardupilot_root: str | None = None) -> str | None:
    """Board name for a connected vehicle, or None if unknown/unavailable."""
    board_id = board_version >> 16
    if board_id == 0:
        return None
    text = _load_registry_text(ardupilot_root)
    return parse_board_types(text).get(board_id) if text else None
