"""Per-session blast-radius cap."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

MAX_APPLIES_PER_WINDOW = 5
WINDOW = timedelta(seconds=120)


def blocks_write_due_to_rate_limit(recent_apply_timestamps: list[datetime], *, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    window_start = now - WINDOW
    recent = [
        t for t in recent_apply_timestamps
        if (t if t.tzinfo is not None else t.replace(tzinfo=UTC)) >= window_start
    ]
    return len(recent) >= MAX_APPLIES_PER_WINDOW
