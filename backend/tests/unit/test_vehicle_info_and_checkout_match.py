from app.knowledge import metadata_fetcher as mf
from app.models.vehicle import VehicleVersionInfo
from app.orchestrator import tools
from app.orchestrator.tools import RuntimeContext


def _ver(git_hash):
    return VehicleVersionInfo(
        vehicle_type="ArduCopter", mav_type=2, board_type=0, flight_sw_version="4.4.4", git_hash=git_hash,
    )


def _patch(monkeypatch, head, calls):
    monkeypatch.setattr(mf, "_current_head_commit", lambda root: head)
    monkeypatch.setattr(mf, "generate_definitions_from_local_checkout", lambda *a, **k: calls.append(1) or {})
    monkeypatch.setattr(mf, "fetch_definitions_from_git_source", lambda *a, **k: None)
    monkeypatch.setattr(mf, "fetch_definitions_from_public_source", lambda *a, **k: None)


def test_mismatched_checkout_is_not_used_for_a_different_firmware(monkeypatch, tmp_path):
    calls = []
    _patch(monkeypatch, "cee87141ce87514838df491e2ac4780d85b08fb3", calls)
    cache = mf.MetadataCache(tmp_path)
    assert mf.get_param_definitions(_ver("aaaaaaaa"), cache=cache, ardupilot_root=tmp_path) is None
    assert calls == [] and cache.get("ArduCopter", "aaaaaaaa") is None  # nothing cached under the wrong version


def test_matching_checkout_or_trusted_simulation_is_used(monkeypatch, tmp_path):
    calls = []
    _patch(monkeypatch, "cee87141ce87514838df491e2ac4780d85b08fb3", calls)
    mf.get_param_definitions(_ver("cee87141"), cache=mf.MetadataCache(tmp_path / "a"), ardupilot_root=tmp_path)
    mf.get_param_definitions(
        _ver("zzzzzzzz"), cache=mf.MetadataCache(tmp_path / "b"), ardupilot_root=tmp_path, trust_local_checkout=True,
    )
    assert len(calls) == 2


def test_vehicle_line_states_firmware_and_notfound_suggests_renamed_param():
    ctx = RuntimeContext(
        session_id="s", vehicle_client=None, audit_logger=None, board_name="CUBEORANGE",
        live_params={"CAM_FEEDBAK_PIN": object(), "CAM_FEEDBAK_POL": object(), "ATC_ANG_RLL_P": object()},
        vehicle_info={"vehicle_type": "ArduCopter", "firmware_version": "4.4.4", "git_hash": "abc12345"},
    )
    line = tools._vehicle_context_line(ctx)
    assert "ArduCopter firmware 4.4.4" in line and "abc12345" in line and "CUBEORANGE" in line
    msg = tools._get_current_param(ctx, "CAM1_FEEDBAK_PIN")
    assert msg.startswith("NotFound:") and "CAM_FEEDBAK_PIN" in msg
    assert "Similar" not in tools._get_current_param(ctx, "TOTALLY_BOGUS")
    assert tools._vehicle_context_line(RuntimeContext(
        session_id="s", vehicle_client=None, live_params={}, audit_logger=None)) == ""


def test_frame_label_names_the_vehicle_kind_not_the_firmware():
    from pymavlink import mavutil

    m = mavutil.mavlink
    assert mf.frame_label(m.MAV_TYPE_QUADROTOR) == "Quadcopter"
    assert mf.frame_label(m.MAV_TYPE_HEXAROTOR) == "Hexacopter"
    assert mf.frame_label(m.MAV_TYPE_FIXED_WING) == "Plane"
    assert mf.frame_label(m.MAV_TYPE_GROUND_ROVER) == "Rover"
    assert mf.frame_label(9999) is None


def test_vehicle_line_leads_with_the_frame_label():
    ctx = RuntimeContext(
        session_id="s", vehicle_client=None, live_params={}, audit_logger=None,
        vehicle_info={"vehicle_type": "ArduCopter", "firmware_version": "4.6.3", "frame_label": "Quadcopter"},
    )
    assert "Quadcopter running ArduCopter firmware 4.6.3" in tools._vehicle_context_line(ctx)


def test_documented_but_absent_param_is_explained_as_needing_its_parent_and_a_reboot():
    from types import SimpleNamespace

    live = {"CAM1_TYPE": SimpleNamespace(current_value=0.0)}
    ctx = RuntimeContext(
        session_id="s", vehicle_client=None, audit_logger=None, live_params=live,
        definitions={"CAM1_FEEDBAK_PIN": object(), "CAM1_TYPE": object()},
        vehicle_info={"vehicle_type": "ArduCopter", "firmware_version": "4.6.3"},
    )
    msg = tools._get_current_param(ctx, "CAM1_FEEDBAK_PIN")
    assert msg.startswith("NotFound:") and "IS documented for this firmware (4.6.3)" in msg
    assert "CAM1_TYPE=0" in msg and "Reboot button" in msg
    # a name this firmware does not document at all keeps the plain message
    assert "documented" not in tools._get_current_param(ctx, "TOTALLY_BOGUS")
    # no definitions (read-only session): no hint, no crash
    ctx.definitions = None
    assert "documented" not in tools._get_current_param(ctx, "CAM1_FEEDBAK_PIN")


def test_prompt_points_reboot_requests_at_the_reboot_button():
    from app.orchestrator.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_VERSION

    assert "**Reboot** button" in SYSTEM_PROMPT and "cannot reboot, arm, disarm" in SYSTEM_PROMPT
    assert SYSTEM_PROMPT_VERSION == "1.10.0"
