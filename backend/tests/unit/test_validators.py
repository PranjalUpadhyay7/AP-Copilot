from app.models.params import LiveParam, ParamDefinition
from app.models.proposal import Criticality, ProposedChange, RejectionReason
from app.validation.validators import revalidate_before_write, validate_proposed_change


def _def(name: str, **kwargs) -> ParamDefinition:
    return ParamDefinition(
        name=name, vehicle_types=["ArduCopter"], firmware_version="4.6.0",
        description="test param", **kwargs,
    )


def _live(name: str, value: float, definition: ParamDefinition | None) -> LiveParam:
    return LiveParam(name=name, current_value=value, definition=definition)


def test_nonexistent_param_rejected():
    change = ProposedChange(param_name="TOTALLY_MADE_UP", new_value=1.0, reason="the LLM guessed")
    result = validate_proposed_change(change, {})

    assert result.accepted is False
    assert result.rejection_reason == RejectionReason.NOT_FOUND
    assert result.current_value is None
    assert "TOTALLY_MADE_UP" in result.rejection_message
    assert "does not exist" in result.rejection_message


def test_undocumented_param_rejected():
    live_params = {"MYSTERY": _live("MYSTERY", 3.0, None)}
    change = ProposedChange(param_name="MYSTERY", new_value=5.0, reason="tune it")

    result = validate_proposed_change(change, live_params)

    assert result.accepted is False
    assert result.rejection_reason == RejectionReason.UNDOCUMENTED
    assert result.current_value == 3.0
    assert result.rejection_message == (
        "I don't have verified metadata for MYSTERY on your firmware "
        "version, so I can't propose changes to it."
    )


def test_out_of_range_low_rejected():
    d = _def("ATC_ANG_RLL_P", min_value=0.5, max_value=12.0)
    live_params = {"ATC_ANG_RLL_P": _live("ATC_ANG_RLL_P", 4.5, d)}
    change = ProposedChange(param_name="ATC_ANG_RLL_P", new_value=0.1, reason="loosen roll")

    result = validate_proposed_change(change, live_params)

    assert result.accepted is False
    assert result.rejection_reason == RejectionReason.OUT_OF_RANGE
    assert result.current_value == 4.5
    assert "below the minimum of 0.5" in result.rejection_message


def test_out_of_range_high_rejected():
    d = _def("ATC_ANG_RLL_P", min_value=0.5, max_value=12.0)
    live_params = {"ATC_ANG_RLL_P": _live("ATC_ANG_RLL_P", 4.5, d)}
    change = ProposedChange(param_name="ATC_ANG_RLL_P", new_value=999.0, reason="tighten roll a lot")

    result = validate_proposed_change(change, live_params)

    assert result.accepted is False
    assert result.rejection_reason == RejectionReason.OUT_OF_RANGE
    assert result.current_value == 4.5
    assert "above the maximum of 12.0" in result.rejection_message


def test_range_boundaries_are_inclusive():
    d = _def("ATC_ANG_RLL_P", min_value=0.5, max_value=12.0)
    live_params = {"ATC_ANG_RLL_P": _live("ATC_ANG_RLL_P", 4.5, d)}

    at_min = validate_proposed_change(
        ProposedChange(param_name="ATC_ANG_RLL_P", new_value=0.5, reason="min"), live_params,
    )
    at_max = validate_proposed_change(
        ProposedChange(param_name="ATC_ANG_RLL_P", new_value=12.0, reason="max"), live_params,
    )

    assert at_min.accepted is True
    assert at_max.accepted is True


def test_wrong_type_for_bitmask_rejected():
    d = _def("ARMING_SKIPCHK", bitmask={0: "All", 1: "Barometer", 2: "Compass"})
    live_params = {"ARMING_SKIPCHK": _live("ARMING_SKIPCHK", 0.0, d)}
    change = ProposedChange(param_name="ARMING_SKIPCHK", new_value=1.5, reason="skip some checks")

    result = validate_proposed_change(change, live_params)

    assert result.accepted is False
    assert result.rejection_reason == RejectionReason.TYPE_MISMATCH
    assert result.current_value == 0.0
    assert result.rejection_message == (
        "ARMING_SKIPCHK is a bitmask parameter and requires a whole-number value, got 1.5."
    )


def test_wrong_type_for_enum_rejected():
    d = _def("GPS_TYPE", values={"0": "None", "1": "AUTO", "2": "uBlox"})
    live_params = {"GPS_TYPE": _live("GPS_TYPE", 1.0, d)}
    change = ProposedChange(param_name="GPS_TYPE", new_value=1.5, reason="switch GPS type")

    result = validate_proposed_change(change, live_params)

    assert result.accepted is False
    assert result.rejection_reason == RejectionReason.TYPE_MISMATCH
    assert result.rejection_message == (
        "GPS_TYPE is a enumerated parameter and requires a whole-number value, got 1.5."
    )


def test_invalid_bitmask_value_rejected():
    d = _def("ARMING_SKIPCHK", bitmask={0: "All", 1: "Barometer", 2: "Compass"})
    live_params = {"ARMING_SKIPCHK": _live("ARMING_SKIPCHK", 0.0, d)}
    # bit 5 (value 32) isn't a defined bit
    change = ProposedChange(param_name="ARMING_SKIPCHK", new_value=32.0, reason="skip something")

    result = validate_proposed_change(change, live_params)

    assert result.accepted is False
    assert result.rejection_reason == RejectionReason.INVALID_BITMASK_VALUE
    assert result.current_value == 0.0
    assert "32" in result.rejection_message


def test_bitmask_value_setting_an_undefined_bit_rejected():
    d = _def("SOME_MASK", bitmask={1: "Barometer", 2: "Compass"})  # no bit 0
    live_params = {"SOME_MASK": _live("SOME_MASK", 0.0, d)}
    change = ProposedChange(param_name="SOME_MASK", new_value=1.0, reason="set bit 0")

    result = validate_proposed_change(change, live_params)

    assert result.accepted is False
    assert result.rejection_reason == RejectionReason.INVALID_BITMASK_VALUE


def test_bitmask_zero_accepted_when_bit_zero_is_defined():
    d = _def("ARMING_SKIPCHK", bitmask={0: "All", 1: "Barometer", 2: "Compass"})
    live_params = {"ARMING_SKIPCHK": _live("ARMING_SKIPCHK", 6.0, d)}
    change = ProposedChange(param_name="ARMING_SKIPCHK", new_value=0.0, reason="clear all checks skipped")

    result = validate_proposed_change(change, live_params)

    assert result.accepted is True


def test_valid_bitmask_combination_accepted():
    d = _def("ARMING_SKIPCHK", bitmask={0: "All", 1: "Barometer", 2: "Compass"})
    live_params = {"ARMING_SKIPCHK": _live("ARMING_SKIPCHK", 0.0, d)}
    # bits 1 and 2 combined = 6
    change = ProposedChange(param_name="ARMING_SKIPCHK", new_value=6.0, reason="skip baro+compass")

    result = validate_proposed_change(change, live_params)

    assert result.accepted is True
    assert result.current_value == 0.0
    assert result.definition == d


def test_invalid_enum_value_rejected():
    d = _def("GPS_TYPE", values={"0": "None", "1": "AUTO", "2": "uBlox"})
    live_params = {"GPS_TYPE": _live("GPS_TYPE", 1.0, d)}
    change = ProposedChange(param_name="GPS_TYPE", new_value=99.0, reason="switch GPS type")

    result = validate_proposed_change(change, live_params)

    assert result.accepted is False
    assert result.rejection_reason == RejectionReason.INVALID_ENUM_VALUE
    assert result.current_value == 1.0
    assert "99" in result.rejection_message


def test_valid_enum_value_accepted():
    d = _def("GPS_TYPE", values={"0": "None", "1": "AUTO", "2": "uBlox"})
    live_params = {"GPS_TYPE": _live("GPS_TYPE", 1.0, d)}
    change = ProposedChange(param_name="GPS_TYPE", new_value=2.0, reason="switch to uBlox")

    result = validate_proposed_change(change, live_params)

    assert result.accepted is True


def test_critical_tier_param_flagged_not_blocked():
    d = _def("ARMING_SKIPCHK", bitmask={0: "All"})
    live_params = {"ARMING_SKIPCHK": _live("ARMING_SKIPCHK", 0.0, d)}
    change = ProposedChange(param_name="ARMING_SKIPCHK", new_value=1.0, reason="skip all checks")

    result = validate_proposed_change(change, live_params)

    assert result.accepted is True
    assert result.criticality == Criticality.CRITICAL


def test_low_tier_param_not_flagged_critical():
    d = _def("SCHED_LOOP_RATE", min_value=50, max_value=1000)
    live_params = {"SCHED_LOOP_RATE": _live("SCHED_LOOP_RATE", 400.0, d)}
    change = ProposedChange(param_name="SCHED_LOOP_RATE", new_value=400.0, reason="no-op tweak")

    result = validate_proposed_change(change, live_params)

    assert result.accepted is True
    assert result.criticality == Criticality.LOW


def test_reboot_required_bumps_a_non_critical_param_to_medium():
    d_reboot = _def("SCHED_LOOP_RATE", min_value=50, max_value=1000, reboot_required=True)
    d_no_reboot = _def("SCHED_LOOP_RATE", min_value=50, max_value=1000, reboot_required=False)

    with_reboot = validate_proposed_change(
        ProposedChange(param_name="SCHED_LOOP_RATE", new_value=400.0, reason="tweak"),
        {"SCHED_LOOP_RATE": _live("SCHED_LOOP_RATE", 400.0, d_reboot)},
    )
    without_reboot = validate_proposed_change(
        ProposedChange(param_name="SCHED_LOOP_RATE", new_value=400.0, reason="tweak"),
        {"SCHED_LOOP_RATE": _live("SCHED_LOOP_RATE", 400.0, d_no_reboot)},
    )

    assert with_reboot.criticality == Criticality.MEDIUM
    assert without_reboot.criticality == Criticality.LOW


def test_reboot_required_surfaced_and_never_blocks():
    d = _def("ARMING_SKIPCHK", bitmask={0: "All"}, reboot_required=True)
    live_params = {"ARMING_SKIPCHK": _live("ARMING_SKIPCHK", 0.0, d)}
    change = ProposedChange(param_name="ARMING_SKIPCHK", new_value=1.0, reason="skip all checks")

    result = validate_proposed_change(change, live_params)

    assert result.accepted is True
    assert result.reboot_required is True


def test_dependency_warning_attached_but_not_blocking():
    d = _def("EK3_ENABLE", values={"0": "Disabled", "1": "Enabled"})
    live_params = {"EK3_ENABLE": _live("EK3_ENABLE", 0.0, d)}
    change = ProposedChange(param_name="EK3_ENABLE", new_value=1.0, reason="switch to EKF3")

    result = validate_proposed_change(change, live_params)

    assert result.accepted is True
    assert len(result.dependency_warnings) == 1
    assert "AHRS_EKF_TYPE" in result.dependency_warnings[0].related_params


def test_no_dependency_warnings_for_unrelated_param():
    d = _def("SCHED_LOOP_RATE", min_value=50, max_value=1000)
    live_params = {"SCHED_LOOP_RATE": _live("SCHED_LOOP_RATE", 400.0, d)}
    change = ProposedChange(param_name="SCHED_LOOP_RATE", new_value=400.0, reason="no-op tweak")

    result = validate_proposed_change(change, live_params)

    assert result.dependency_warnings == []


def test_ordering_existence_checked_before_range():
    change = ProposedChange(param_name="DOES_NOT_EXIST", new_value=1e9, reason="whatever")
    result = validate_proposed_change(change, {})
    assert result.rejection_reason == RejectionReason.NOT_FOUND


def test_nan_value_rejected_not_silently_accepted():
    d = _def("ATC_ANG_RLL_P", min_value=0.5, max_value=12.0)
    live_params = {"ATC_ANG_RLL_P": _live("ATC_ANG_RLL_P", 4.5, d)}
    change = ProposedChange(param_name="ATC_ANG_RLL_P", new_value=float("nan"), reason="tighten roll")

    result = validate_proposed_change(change, live_params)

    assert result.accepted is False
    assert result.rejection_reason == RejectionReason.TYPE_MISMATCH
    assert result.current_value == 4.5
    assert "not a finite number" in result.rejection_message


def test_positive_infinity_rejected_even_with_no_upper_bound():
    d = _def("SOME_PARAM", min_value=0.0, max_value=None)
    live_params = {"SOME_PARAM": _live("SOME_PARAM", 1.0, d)}
    change = ProposedChange(param_name="SOME_PARAM", new_value=float("inf"), reason="go big")

    result = validate_proposed_change(change, live_params)

    assert result.accepted is False
    assert result.rejection_reason == RejectionReason.TYPE_MISMATCH
    assert result.current_value == 1.0
    assert "not a finite number" in result.rejection_message


def test_negative_infinity_rejected_even_with_no_lower_bound():
    d = _def("SOME_PARAM", min_value=None, max_value=100.0)
    live_params = {"SOME_PARAM": _live("SOME_PARAM", 1.0, d)}
    change = ProposedChange(param_name="SOME_PARAM", new_value=float("-inf"), reason="go small")

    result = validate_proposed_change(change, live_params)

    assert result.accepted is False
    assert result.rejection_reason == RejectionReason.TYPE_MISMATCH
    assert result.current_value == 1.0
    assert "not a finite number" in result.rejection_message


def test_revalidate_before_write_catches_state_that_changed_since_proposal():
    d = _def("ATC_ANG_RLL_P", min_value=0.5, max_value=12.0)
    stale_live = {"ATC_ANG_RLL_P": _live("ATC_ANG_RLL_P", 4.5, d)}
    change = ProposedChange(param_name="ATC_ANG_RLL_P", new_value=10.0, reason="tighten roll")

    proposal = validate_proposed_change(change, stale_live)
    assert proposal.accepted is True

    # Reconnect happened, firmware now reports this param as gone entirely.
    fresh_live: dict = {}
    revalidated = revalidate_before_write(change, fresh_live)

    assert revalidated.accepted is False
    assert revalidated.rejection_reason == RejectionReason.NOT_FOUND


def test_skipping_all_arming_checks_is_critical_tier_not_hard_blocked():
    d = _def("ARMING_SKIPCHK", bitmask={0: "All"})
    live_params = {"ARMING_SKIPCHK": _live("ARMING_SKIPCHK", 0.0, d)}
    change = ProposedChange(param_name="ARMING_SKIPCHK", new_value=1.0, reason="skip all checks for bench test")

    result = validate_proposed_change(change, live_params)

    assert result.accepted is True
    assert result.criticality == Criticality.CRITICAL
