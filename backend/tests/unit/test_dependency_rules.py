from app.validation.dependency_rules import get_dependency_warnings


def test_ek3_enable_warns_about_ahrs_and_ek2():
    warnings = get_dependency_warnings("EK3_ENABLE")
    assert len(warnings) == 1
    assert set(warnings[0].related_params) == {"AHRS_EKF_TYPE", "EK2_ENABLE"}


def test_unrelated_param_has_no_warnings():
    assert get_dependency_warnings("SCHED_LOOP_RATE") == []


def test_arming_skipchk_warns_about_arming_require():
    warnings = get_dependency_warnings("ARMING_SKIPCHK")
    assert len(warnings) == 1
    assert "ARMING_REQUIRE" in warnings[0].related_params
