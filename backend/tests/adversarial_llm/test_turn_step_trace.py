from app.models.proposal import ValidatedProposal
from app.orchestrator.graph import apply_confirmed_write
from app.validation import rate_limit


def _proposal(param_name="ATC_ANG_RLL_P", current_value=4.5, proposed_value=6.0) -> ValidatedProposal:
    return ValidatedProposal(
        param_name=param_name, current_value=current_value, proposed_value=proposed_value,
        reason="test", accepted=True, proposal_id="p1",
    )


def test_successful_write_produces_four_ok_steps_in_order(context):
    content, steps = apply_confirmed_write(context, _proposal())

    assert "Applied" in content
    stages = [s.stage for s in steps]
    assert stages == ["revalidation", "flight_state", "rate_limit", "write"]
    assert all(s.status == "ok" for s in steps)
    assert steps[-1].detail == content


def test_revalidation_failure_produces_exactly_one_blocked_step(context):
    content, steps = apply_confirmed_write(context, _proposal(proposed_value=999.0))

    assert "no longer safe" in content.lower()
    assert len(steps) == 1
    assert steps[0].stage == "revalidation"
    assert steps[0].status == "blocked"
    assert steps[0].detail == content


def test_flight_state_block_stops_after_two_steps(context):
    context.vehicle_client.get_armed_state = lambda timeout=3.0: True

    content, steps = apply_confirmed_write(context, _proposal())

    assert "armed" in content.lower()
    assert [s.stage for s in steps] == ["revalidation", "flight_state"]
    assert steps[0].status == "ok"
    assert steps[1].status == "blocked"
    assert steps[1].detail == content


def test_rate_limit_block_stops_after_three_steps(context):
    for _ in range(rate_limit.MAX_APPLIES_PER_WINDOW):
        context.audit_logger.log_apply(context.session_id, "ATC_ANG_PIT_P", 1.0, 2.0, reboot_required=False)

    content, steps = apply_confirmed_write(context, _proposal())

    assert "rate limit" in content.lower() or "too many changes" in content.lower()
    assert [s.stage for s in steps] == ["revalidation", "flight_state", "rate_limit"]
    assert steps[-1].status == "blocked"
    assert steps[-1].detail == content


def test_write_exception_produces_an_error_step(context):
    def _boom(name, value, timeout=10.0):
        raise ConnectionError("link lost")

    context.vehicle_client.set_param = _boom

    content, steps = apply_confirmed_write(context, _proposal())

    assert "could not write" in content.lower()
    assert [s.stage for s in steps] == ["revalidation", "flight_state", "rate_limit", "write"]
    assert steps[-1].status == "error"
    assert steps[-1].detail == content
