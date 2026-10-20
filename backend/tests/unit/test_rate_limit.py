from datetime import UTC, datetime, timedelta

from app.validation.rate_limit import (
    MAX_APPLIES_PER_WINDOW,
    WINDOW,
    blocks_write_due_to_rate_limit,
)


def test_no_recent_applies_never_blocks():
    assert blocks_write_due_to_rate_limit([]) is False


def test_fewer_than_the_cap_within_the_window_does_not_block():
    now = datetime.now(UTC)
    recent = [now - timedelta(seconds=i) for i in range(MAX_APPLIES_PER_WINDOW - 1)]
    assert blocks_write_due_to_rate_limit(recent, now=now) is False


def test_at_the_cap_within_the_window_blocks():
    now = datetime.now(UTC)
    recent = [now - timedelta(seconds=i) for i in range(MAX_APPLIES_PER_WINDOW)]
    assert blocks_write_due_to_rate_limit(recent, now=now) is True


def test_applies_outside_the_window_do_not_count():
    now = datetime.now(UTC)
    old = [now - WINDOW - timedelta(seconds=1) for _ in range(MAX_APPLIES_PER_WINDOW + 5)]
    assert blocks_write_due_to_rate_limit(old, now=now) is False


def test_naive_timestamps_are_treated_as_utc_not_rejected_or_miscompared():
    now = datetime.now(UTC)
    naive_recent = [(now - timedelta(seconds=i)).replace(tzinfo=None) for i in range(MAX_APPLIES_PER_WINDOW)]
    assert blocks_write_due_to_rate_limit(naive_recent, now=now) is True
