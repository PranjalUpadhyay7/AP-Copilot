from __future__ import annotations

from pathlib import Path

from app.knowledge.metadata_fetcher import (
    _current_head_commit,
    _locate_param_source,
    attach_github_source_urls,
)
from app.knowledge.metadata_parser import extract_param_suffixes
from app.models.params import ParamDefinition


def _def(name: str) -> ParamDefinition:
    return ParamDefinition(name=name, vehicle_types=["ArduCopter"], firmware_version="4.6.0", description="d")


def test_extract_param_suffixes_strips_the_real_group_prefix():
    raw_json = {
        "json": {"version": 0},
        "ATC_": {"ATC_ANG_RLL_P": {"Description": "d"}},
        "GPS": {"GPS_TYPE": {"Description": "d"}, "GPS_HDOP_GOOD": {"Description": "d"}},
        "": {"LOG_BITMASK": {"Description": "d"}},
    }
    suffixes = extract_param_suffixes(raw_json)
    assert suffixes["ATC_ANG_RLL_P"] == "ANG_RLL_P"
    assert suffixes["GPS_TYPE"] == "_TYPE"
    assert suffixes["GPS_HDOP_GOOD"] == "_HDOP_GOOD"
    assert suffixes["LOG_BITMASK"] == "LOG_BITMASK"  # root group: no prefix to strip


def test_locate_param_source_finds_a_unique_match(tmp_path: Path):
    vehicle_dir = tmp_path / "ArduCopter"
    vehicle_dir.mkdir()
    (vehicle_dir / "Parameters.cpp").write_text(
        "line one\nline two\n    // @Param: ANG_RLL_P\n    // @DisplayName: x\n",
    )
    assert _locate_param_source(tmp_path, "ArduCopter", "ANG_RLL_P") == ("ArduCopter/Parameters.cpp", 3)


def test_locate_param_source_matches_tagged_at_param_form(tmp_path: Path):
    lib_dir = tmp_path / "libraries" / "SomeLib"
    lib_dir.mkdir(parents=True)
    (lib_dir / "SomeLib.cpp").write_text("    // @Param{Plane, Copter}: AUTOENABLE\n")
    assert _locate_param_source(tmp_path, "ArduCopter", "AUTOENABLE") == (
        "libraries/SomeLib/SomeLib.cpp", 1,
    )


def test_locate_param_source_returns_none_when_genuinely_ambiguous(tmp_path: Path):
    (tmp_path / "libraries" / "LibA").mkdir(parents=True)
    (tmp_path / "libraries" / "LibB").mkdir(parents=True)
    (tmp_path / "libraries" / "LibA" / "LibA.cpp").write_text("// @Param: ENABLE\n")
    (tmp_path / "libraries" / "LibB" / "LibB.cpp").write_text("// @Param: ENABLE\n")
    assert _locate_param_source(tmp_path, "ArduCopter", "ENABLE") is None


def test_locate_param_source_returns_none_when_not_found(tmp_path: Path):
    (tmp_path / "ArduCopter").mkdir()
    assert _locate_param_source(tmp_path, "ArduCopter", "DOES_NOT_EXIST") is None


def test_locate_param_source_only_searches_vehicle_and_libraries_dirs(tmp_path: Path):
    (tmp_path / "ArduPlane").mkdir()
    (tmp_path / "ArduPlane" / "Parameters.cpp").write_text("// @Param: SOME_PLANE_ONLY_PARAM\n")
    assert _locate_param_source(tmp_path, "ArduCopter", "SOME_PLANE_ONLY_PARAM") is None


def test_attach_github_source_urls_builds_the_exact_blob_line_url(tmp_path: Path):
    vehicle_dir = tmp_path / "ArduCopter"
    vehicle_dir.mkdir()
    (vehicle_dir / "Parameters.cpp").write_text("x\n// @Param: ANG_RLL_P\n")

    definitions = {"ATC_ANG_RLL_P": _def("ATC_ANG_RLL_P")}
    suffixes = {"ATC_ANG_RLL_P": "ANG_RLL_P"}
    attach_github_source_urls(definitions, tmp_path, "ArduCopter", "deadbeef", suffixes)

    url = definitions["ATC_ANG_RLL_P"].github_source_url
    assert url == "https://github.com/ArduPilot/ardupilot/blob/deadbeef/ArduCopter/Parameters.cpp#L2"


def test_attach_github_source_urls_leaves_unlocatable_params_as_none(tmp_path: Path):
    (tmp_path / "ArduCopter").mkdir()
    definitions = {"MYSTERY_PARAM": _def("MYSTERY_PARAM")}
    attach_github_source_urls(definitions, tmp_path, "ArduCopter", "deadbeef", {"MYSTERY_PARAM": "MYSTERY_PARAM"})
    assert definitions["MYSTERY_PARAM"].github_source_url is None


def test_current_head_commit_returns_none_outside_a_git_repo(tmp_path: Path):
    assert _current_head_commit(tmp_path) is None


def test_current_head_commit_reads_the_real_head(tmp_path: Path):
    import subprocess

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True, capture_output=True)
    (tmp_path / "f.txt").write_text("x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "x"], check=True, capture_output=True)

    head = _current_head_commit(tmp_path)
    assert head is not None
    assert len(head) == 40
