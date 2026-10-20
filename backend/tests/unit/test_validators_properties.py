"""Property-based tests for the Validation Layer."""
from __future__ import annotations

import math

from hypothesis import assume, given
from hypothesis import strategies as st

from app.models.params import LiveParam, ParamDefinition
from app.models.proposal import ProposedChange
from app.validation.validators import validate_proposed_change

PARAM_NAME = "TEST_PARAM"

# Any float hypothesis can produce, including nan/inf/-inf/-0.0/huge magnitudes.
any_float = st.floats(allow_nan=True, allow_infinity=True, width=64)
finite_float = st.floats(allow_nan=False, allow_infinity=False, width=32, min_value=-1e6, max_value=1e6)


def _def(**kwargs) -> ParamDefinition:
    return ParamDefinition(
        name=PARAM_NAME, vehicle_types=["ArduCopter"], firmware_version="4.6.0",
        description="test param", **kwargs,
    )


@st.composite
def ranged_numeric_live_param(draw) -> tuple[LiveParam, float, float]:
    a = draw(finite_float)
    b = draw(finite_float)
    lo, hi = (a, b) if a <= b else (b, a)
    assume(lo < hi)  # a degenerate lo==hi range isn't the interesting case here
    definition = _def(min_value=lo, max_value=hi)
    live = LiveParam(name=PARAM_NAME, current_value=lo, definition=definition)
    return live, lo, hi


@given(param_name=st.text(min_size=0, max_size=50), new_value=any_float)
def test_unknown_param_name_always_rejected_not_found(param_name: str, new_value: float):
    change = ProposedChange(param_name=param_name, new_value=new_value, reason="r")
    result = validate_proposed_change(change, {})

    assert result.accepted is False
    assert result.rejection_reason == "not_found"
    assert result.current_value is None


non_finite_float = st.sampled_from([float("nan"), float("inf"), float("-inf")])


@given(ranged=ranged_numeric_live_param(), new_value=non_finite_float)
def test_non_finite_values_never_accepted_for_a_ranged_numeric_param(ranged, new_value: float):
    live, _lo, _hi = ranged
    change = ProposedChange(param_name=PARAM_NAME, new_value=new_value, reason="r")

    result = validate_proposed_change(change, {PARAM_NAME: live})

    assert result.accepted is False


@given(ranged=ranged_numeric_live_param(), new_value=any_float)
def test_accepted_implies_finite_and_within_range(ranged, new_value: float):
    live, lo, hi = ranged
    change = ProposedChange(param_name=PARAM_NAME, new_value=new_value, reason="r")

    result = validate_proposed_change(change, {PARAM_NAME: live})

    if result.accepted:
        assert math.isfinite(new_value)
        assert lo <= new_value <= hi


@given(ranged=ranged_numeric_live_param(), new_value=any_float)
def test_validation_is_pure_and_deterministic(ranged, new_value: float):
    live, _, _ = ranged
    live_params = {PARAM_NAME: live}
    live_params_before = dict(live_params)
    change = ProposedChange(param_name=PARAM_NAME, new_value=new_value, reason="r")

    first = validate_proposed_change(change, live_params)
    second = validate_proposed_change(change, live_params)

    assert first.accepted == second.accepted
    assert first.rejection_reason == second.rejection_reason
    assert live_params == live_params_before


@given(new_value=st.integers(min_value=-(10**18), max_value=10**18))
def test_huge_integers_handled_without_crashing(new_value: int):
    definition = _def(bitmask={0: "A", 1: "B"})
    live = LiveParam(name=PARAM_NAME, current_value=0.0, definition=definition)
    change = ProposedChange(param_name=PARAM_NAME, new_value=float(new_value), reason="r")

    result = validate_proposed_change(change, {PARAM_NAME: live})

    assert isinstance(result.accepted, bool)  # didn't raise; got a real answer


@given(ranged=ranged_numeric_live_param())
def test_dependency_warnings_never_block_acceptance(ranged):
    live, lo, hi = ranged
    mid = (lo + hi) / 2
    assume(not math.isclose(live.current_value, mid, rel_tol=1e-9, abs_tol=1e-9))
    change = ProposedChange(param_name=PARAM_NAME, new_value=mid, reason="r")

    result = validate_proposed_change(change, {PARAM_NAME: live})

    assert result.accepted is True
    assert result.rejection_reason is None
    assert result.rejection_message is None
