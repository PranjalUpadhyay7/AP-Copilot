"""Hard-blocked changes."""
from __future__ import annotations


def is_hard_blocked(param_name: str, new_value: float) -> str | None:
    """Returns a rejection message if `param_name = new_value` is hard-blocked, else `None`."""
    return None
