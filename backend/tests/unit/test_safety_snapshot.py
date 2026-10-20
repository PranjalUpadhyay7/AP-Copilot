import json

from app.models.params import LiveParam, ParamDefinition
from app.validation.safety_snapshot import compute_safety_snapshot


def _def(name: str) -> ParamDefinition:
    return ParamDefinition(name=name, vehicle_types=["ArduCopter"], firmware_version="4.6.0", description="d")


def test_matches_failsafe_and_fence_prefixes_and_exact_names():
    live_params = {
        "FS_THR_ENABLE": LiveParam(name="FS_THR_ENABLE", current_value=1.0, definition=_def("FS_THR_ENABLE")),
        "FENCE_ENABLE": LiveParam(name="FENCE_ENABLE", current_value=1.0, definition=_def("FENCE_ENABLE")),
        "ARMING_SKIPCHK": LiveParam(name="ARMING_SKIPCHK", current_value=0.0, definition=_def("ARMING_SKIPCHK")),
        "BATT_LOW_VOLT": LiveParam(name="BATT_LOW_VOLT", current_value=10.5, definition=_def("BATT_LOW_VOLT")),
        "SCHED_LOOP_RATE": LiveParam(name="SCHED_LOOP_RATE", current_value=400.0, definition=_def("SCHED_LOOP_RATE")),
    }

    snapshot = compute_safety_snapshot(live_params)
    names = {p.name for p in snapshot.params}

    assert names == {"FS_THR_ENABLE", "FENCE_ENABLE", "ARMING_SKIPCHK", "BATT_LOW_VOLT"}
    assert "SCHED_LOOP_RATE" not in names


def test_undocumented_safety_param_still_included_and_flagged():
    live_params = {
        "FS_GCS_ENABLE": LiveParam(name="FS_GCS_ENABLE", current_value=1.0, definition=None),
    }
    snapshot = compute_safety_snapshot(live_params)
    assert len(snapshot.params) == 1
    assert snapshot.params[0].documented is False


def test_always_produced_even_when_nothing_matches():
    snapshot = compute_safety_snapshot({})
    assert snapshot.params == []
    lines = snapshot.as_text().split("\n")
    assert lines[2] == "(no safety-relevant parameters found on this vehicle)"


def test_as_json_round_trips():
    live_params = {
        "FENCE_ENABLE": LiveParam(name="FENCE_ENABLE", current_value=1.0, definition=_def("FENCE_ENABLE")),
    }
    snapshot = compute_safety_snapshot(live_params)
    parsed = json.loads(snapshot.as_json())
    assert parsed["params"][0] == {"name": "FENCE_ENABLE", "current_value": 1.0, "documented": True}
    assert "timestamp" in parsed
    assert snapshot.as_json().startswith('{\n  "timestamp"')  # indent=2, not compact or differently indented


def test_snapshot_timestamp_is_timezone_aware_utc():
    snapshot = compute_safety_snapshot({})
    assert snapshot.timestamp.tzinfo is not None


def test_as_text_lines_are_sorted_and_show_value_and_documented_flag():
    live_params = {
        "FENCE_ENABLE": LiveParam(name="FENCE_ENABLE", current_value=1.0, definition=_def("FENCE_ENABLE")),
        "BATT_LOW_VOLT": LiveParam(name="BATT_LOW_VOLT", current_value=10.5, definition=None),
    }
    text = compute_safety_snapshot(live_params).as_text()
    lines = text.split("\n")

    assert lines[1] == "-" * 50
    # Alphabetically: BATT_LOW_VOLT before FENCE_ENABLE.
    batt_line = next(line for line in lines if line.startswith("BATT_LOW_VOLT"))
    fence_line = next(line for line in lines if line.startswith("FENCE_ENABLE"))
    assert lines.index(batt_line) < lines.index(fence_line)
    assert batt_line == f"{'BATT_LOW_VOLT':<24} = 10.5  [undocumented for this firmware]"
    assert fence_line == f"{'FENCE_ENABLE':<24} = 1.0"
