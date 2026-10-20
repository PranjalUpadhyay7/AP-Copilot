from app.models.proposal import Criticality
from app.validation.criticality import classify_criticality, suggests_review


def test_arming_prefix_is_critical():
    assert classify_criticality("ARMING_SKIPCHK") == Criticality.CRITICAL


def test_fs_prefix_is_critical():
    assert classify_criticality("FS_THR_ENABLE") == Criticality.CRITICAL


def test_mot_prefix_is_critical():
    assert classify_criticality("MOT_PWM_MIN") == Criticality.CRITICAL


def test_fence_prefix_is_critical():
    assert classify_criticality("FENCE_ENABLE") == Criticality.CRITICAL


def test_compass_prefix_is_critical():
    assert classify_criticality("COMPASS_OFS_X") == Criticality.CRITICAL


def test_ekf_exact_names_are_critical():
    assert classify_criticality("EK2_ENABLE") == Criticality.CRITICAL
    assert classify_criticality("EK3_ENABLE") == Criticality.CRITICAL
    assert classify_criticality("AHRS_EKF_TYPE") == Criticality.CRITICAL


def test_battery_failsafe_threshold_is_critical():
    assert classify_criticality("BATT_LOW_VOLT") == Criticality.CRITICAL
    assert classify_criticality("BATT_CRT_VOLT") == Criticality.CRITICAL


def test_battery_non_failsafe_param_is_not_auto_critical():
    assert classify_criticality("BATT_CAPACITY") != Criticality.CRITICAL


def test_core_attitude_pid_is_critical():
    assert classify_criticality("ATC_RAT_RLL_P") == Criticality.CRITICAL
    assert classify_criticality("ATC_ANG_PIT_P") == Criticality.CRITICAL


def test_non_core_atc_param_is_not_auto_critical():
    assert classify_criticality("ATC_THR_MIX_MAN") != Criticality.CRITICAL


def test_rc_failsafe_is_critical():
    assert classify_criticality("RC_FS_TIMEOUT") == Criticality.CRITICAL
    assert classify_criticality("RC1_FS_PWM") == Criticality.CRITICAL


def test_gps_type_is_critical():
    assert classify_criticality("GPS_TYPE") == Criticality.CRITICAL


def test_unrelated_low_param_is_low():
    assert classify_criticality("SCHED_LOOP_RATE") == Criticality.LOW


def test_reboot_required_non_critical_is_medium():
    assert classify_criticality("SCHED_LOOP_RATE", reboot_required=True) == Criticality.MEDIUM


def test_suggests_review_for_offlist_arming_sounding_name():
    assert suggests_review("SOME_NEW_ARM_TIMEOUT", Criticality.LOW) is True


def test_suggests_review_false_for_actual_critical():
    assert suggests_review("ARMING_SKIPCHK", Criticality.CRITICAL) is False


def test_suggests_review_false_for_unrelated_param():
    assert suggests_review("SCHED_LOOP_RATE", Criticality.LOW) is False
