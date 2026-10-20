"""Append-only JSONL log of problem-solving episodes."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

RESOLUTION_SIGNALS = ("worked", "did_not_work")


def log_path() -> Path:
    # AP_COPILOT_RL_LOG lets tests (and operators) redirect just this file.
    override = os.environ.get("AP_COPILOT_RL_LOG")
    if override:
        return Path(override)
    return Path(os.environ.get("AP_COPILOT_HOME", Path.home() / ".ap-copilot")) / "rl_training_log.jsonl"


def _append(record: dict) -> None:
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except OSError as e:
        logger.warning("could not write rl_training_log: %s", e)


def log_episode(
    *, session_id: str, user_problem: str, approaches_tried: list[dict], final_outcome: str,
) -> str | None:
    if not approaches_tried:
        return None
    episode_id = str(uuid.uuid4())
    _append({
        "record": "episode", "episode_id": episode_id, "timestamp": datetime.now(UTC).isoformat(),
        "session_id": session_id, "user_problem": user_problem, "approaches_tried": approaches_tried,
        "final_outcome": final_outcome, "resolution_signal": "not_asked",
    })
    return episode_id


def log_update(episode_id: str, **fields: str) -> None:
    _append({"record": "update", "episode_id": episode_id, "timestamp": datetime.now(UTC).isoformat(), **fields})


def log_resolution_signal(episode_id: str, signal: str) -> None:
    if signal not in RESOLUTION_SIGNALS:
        raise ValueError(f"resolution signal must be one of {RESOLUTION_SIGNALS}, got {signal!r}")
    log_update(episode_id, resolution_signal=signal)
