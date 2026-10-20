"""Flight-state interlock."""
from __future__ import annotations

IN_FLIGHT_SAFE_PARAMS: frozenset[str] = frozenset()


def blocks_write_while_armed(param_name: str, armed: bool | None) -> bool:
    """Block writes while armed; an unknown arm state counts as armed (fail closed)."""
    if param_name in IN_FLIGHT_SAFE_PARAMS:
        return False
    return armed is None or armed
