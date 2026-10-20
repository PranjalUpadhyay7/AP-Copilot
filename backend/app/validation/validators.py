"""Deterministic Validation Layer."""
from __future__ import annotations

import math

from app.models.params import LiveParam
from app.models.proposal import ProposedChange, RejectionReason, ValidatedProposal
from app.validation.criticality import classify_criticality
from app.validation.dependency_rules import get_dependency_warnings
from app.validation.hard_blocks import is_hard_blocked


def _rejected(
    change: ProposedChange,
    live: LiveParam | None,
    reason: RejectionReason,
    message: str,
) -> ValidatedProposal:
    return ValidatedProposal(
        param_name=change.param_name,
        current_value=live.current_value if live is not None else None,
        proposed_value=change.new_value,
        reason=change.reason,
        accepted=False,
        rejection_reason=reason,
        rejection_message=message,
    )


def validate_proposed_change(
    change: ProposedChange,
    live_params: dict[str, LiveParam],
) -> ValidatedProposal:
    """Deterministic checks (existence, type, range, enum, bitmask) on a proposed change; no LLM involved."""
    name = change.param_name

    # Must exist in the reconciled live + metadata set
    live = live_params.get(name)
    if live is None:
        return _rejected(
            change, None, RejectionReason.NOT_FOUND,
            f"{name} does not exist on this vehicle's live parameter set.",
        )

    definition = live.definition
    if definition is None:
        return _rejected(
            change, live, RejectionReason.UNDOCUMENTED,
            f"I don't have verified metadata for {name} on your firmware "
            "version, so I can't propose changes to it.",
        )

    is_discrete = bool(definition.bitmask or definition.values)

    if not math.isfinite(change.new_value):
        return _rejected(
            change, live, RejectionReason.TYPE_MISMATCH,
            f"{name}={change.new_value} is not a finite number.",
        )

    # Bitmask and enum parameters take whole numbers only
    if is_discrete and not float(change.new_value).is_integer():
        return _rejected(
            change, live, RejectionReason.TYPE_MISMATCH,
            f"{name} is a {'bitmask' if definition.bitmask else 'enumerated'} "
            f"parameter and requires a whole-number value, got {change.new_value}.",
        )

    # Range
    if definition.min_value is not None and change.new_value < definition.min_value:
        return _rejected(
            change, live, RejectionReason.OUT_OF_RANGE,
            f"{name}={change.new_value} is below the minimum of {definition.min_value}.",
        )
    if definition.max_value is not None and change.new_value > definition.max_value:
        return _rejected(
            change, live, RejectionReason.OUT_OF_RANGE,
            f"{name}={change.new_value} is above the maximum of {definition.max_value}.",
        )

    # Only defined bits / enum values are allowed
    if definition.bitmask:
        int_value = int(change.new_value)
        known_bits = 0
        for bit in definition.bitmask:
            known_bits |= (1 << bit)
        if int_value < 0 or (int_value & ~known_bits):
            return _rejected(
                change, live, RejectionReason.INVALID_BITMASK_VALUE,
                f"{name}={int_value} sets bits not defined in this parameter's "
                f"known bitmask {sorted(definition.bitmask)}.",
            )
    elif definition.values:
        int_value = int(change.new_value)
        if str(int_value) not in definition.values:
            return _rejected(
                change, live, RejectionReason.INVALID_ENUM_VALUE,
                f"{name}={int_value} is not one of the known values: "
                f"{definition.values}.",
            )

    # Values that are never acceptable, whatever the metadata says
    hard_block_message = is_hard_blocked(name, change.new_value)
    if hard_block_message is not None:
        return _rejected(change, live, RejectionReason.HARD_BLOCKED, hard_block_message)

    # Criticality is a tag shown to the user; it never blocks
    criticality = classify_criticality(name, reboot_required=definition.reboot_required)

    # Dependencies are warnings only
    dependency_warnings = get_dependency_warnings(name)

    return ValidatedProposal(
        param_name=name,
        current_value=live.current_value,
        proposed_value=change.new_value,
        reason=change.reason,
        accepted=True,
        criticality=criticality,
        dependency_warnings=dependency_warnings,
        reboot_required=definition.reboot_required,
        definition=definition,
    )


def revalidate_before_write(
    change: ProposedChange,
    fresh_live_params: dict[str, LiveParam],
) -> ValidatedProposal:
    return validate_proposed_change(change, fresh_live_params)
