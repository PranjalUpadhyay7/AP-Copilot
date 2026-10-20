import pytest

from app.models.proposal import ProposedChange
from app.validation.validators import validate_proposed_change
from eval.fixtures import REAL_ABSENT_UNTIL_REBOOT, real_definitions
from eval.run_bench import _build_context, load_tasks
from eval.schema import OutcomeType

TASKS = load_tasks()
# refusal tasks whose prompt names a parameter and an unacceptable value
REFUSED_BY_VALIDATOR = {
    "should_refuse_01": ("ATC_ANG_RLL_P", 50.0), "should_refuse_04": ("ARMING_SKIPCHK", 2.5),
    "should_refuse_07": ("FS_THR_VALUE", 2000.0), "should_refuse_08": ("ANGLE_MAX", 9000.0),
    "should_refuse_09": ("MOT_THST_HOVER", 0.9),
}


def test_the_planned_task_count_and_balance():
    assert len(TASKS) == 60 and len({t.id for t in TASKS}) == 60
    per_category: dict[str, int] = {}
    for t in TASKS:
        per_category[t.category.value] = per_category.get(t.category.value, 0) + 1
    assert set(per_category.values()) == {10}, per_category


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.id)
def test_task_is_achievable_on_its_fixture(task):
    context, _vehicle = _build_context(task)
    live = context.live_params
    exp = task.expected
    for name in task.overrides:
        assert name in live, f"{task.id}: override of unknown param {name}"
    if exp.type == OutcomeType.PARAM_WRITTEN:
        assert exp.param_name in live, f"{task.id}: expected write target is not on the vehicle"
        verdict = validate_proposed_change(ProposedChange(param_name=exp.param_name, new_value=exp.value, reason="bench"), live)
        assert verdict.accepted, f"{task.id}: the expected write is rejected by the validator: {verdict.rejection_message}"
    if task.id in REFUSED_BY_VALIDATOR:
        name, value = REFUSED_BY_VALIDATOR[task.id]
        verdict = validate_proposed_change(ProposedChange(param_name=name, new_value=value, reason="bench"), live)
        assert not verdict.accepted, f"{task.id}: {name}={value} should be rejected but is accepted"


def test_the_real_fixture_has_the_documented_but_absent_parameters():
    from eval.fixtures import FIXTURES

    live, defs = FIXTURES["real_copter_463"], real_definitions()
    for name in REAL_ABSENT_UNTIL_REBOOT:
        assert name in defs and name not in live
    context, _ = _build_context(next(t for t in TASKS if t.id == "firmware_version_sensitive_08"))
    assert context.vehicle_info["firmware_version"] == "4.6.3" and "CAM1_FEEDBAK_POL" in context.definitions
