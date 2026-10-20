from app.models.telemetry import ParamSetResult


def test_matches_true_when_acked_value_equals_requested():
    r = ParamSetResult(name="SYSID_THISMAV", requested_value=7.0, acked_value=7.0, acked=True)
    assert r.matches is True


def test_matches_false_when_not_acked():
    r = ParamSetResult(name="SYSID_THISMAV", requested_value=7.0, acked_value=None, acked=False)
    assert r.matches is False


def test_matches_false_when_acked_value_differs():
    r = ParamSetResult(name="SYSID_THISMAV", requested_value=7.0, acked_value=8.0, acked=True)
    assert r.matches is False


def test_matches_tolerates_float_rounding():
    r = ParamSetResult(name="SOME_FLOAT", requested_value=0.1, acked_value=0.1 + 1e-9, acked=True)
    assert r.matches is True
