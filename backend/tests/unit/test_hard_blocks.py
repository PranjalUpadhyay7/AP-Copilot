from app.validation.hard_blocks import is_hard_blocked


def test_is_hard_blocked_returns_none_for_anything_with_an_empty_seed_list():
    assert is_hard_blocked("ARMING_SKIPCHK", 1.0) is None
    assert is_hard_blocked("ARMING_CHECK", 0.0) is None
    assert is_hard_blocked("ANYTHING_AT_ALL", 99999.0) is None
