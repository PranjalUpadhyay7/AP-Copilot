import ast
from pathlib import Path

from app.knowledge.firmware_sync import parse_ls_remote, sync_release_metadata
from app.knowledge.metadata_fetcher import MetadataCache
from app.models.params import ParamDefinition

LS = (
    "aaaaaaaa11111111111111111111111111111111\trefs/tags/Copter-4.6.0\n"          # annotated: tag object
    "bbbbbbbb22222222222222222222222222222222\trefs/tags/Copter-4.6.0^{}\n"       # peeled commit wins
    "cccccccc33333333333333333333333333333333\trefs/tags/Plane-4.5.1\n"
    "dddddddd44444444444444444444444444444444\trefs/tags/Copter-4.6.0-beta1\n"    # not stable
    "eeeeeeee55555555555555555555555555555555\trefs/tags/Copter-3.6.0\n"          # below min version
    "ffffffff66666666666666666666666666666666\trefs/heads/master\n"
)


def _defs():
    return {"X": ParamDefinition(name="X", vehicle_types=["ArduCopter"], firmware_version="4.6.0", description="d")}


def test_parse_keeps_only_stable_tags_and_peels_annotated():
    assert parse_ls_remote(LS) == {
        "Copter-4.6.0": "bbbbbbbb22222222222222222222222222222222",
        "Plane-4.5.1": "cccccccc33333333333333333333333333333333",
        "Copter-3.6.0": "eeeeeeee55555555555555555555555555555555",
    }


def test_sync_caches_under_live_key_skips_old_and_is_incremental(tmp_path):
    cache = MetadataCache(tmp_path)
    calls = []

    def fetch(vehicle_type, info):
        calls.append(info.git_hash)
        return _defs()

    tags = parse_ls_remote(LS)
    r = sync_release_metadata(cache=cache, tags=tags, fetch=fetch)
    assert sorted(r["cached"]) == ["Copter-4.6.0", "Plane-4.5.1"]
    assert r["skipped"] == ["Copter-3.6.0"]
    assert cache.get("ArduCopter", "bbbbbbbb") is not None  # 8-char live key
    assert cache.get("ArduPlane", "cccccccc") is not None
    assert calls[0] == "bbbbbbbb22222222222222222222222222222222"  # full SHA used to fetch

    calls.clear()
    sync_release_metadata(cache=cache, tags=tags, fetch=fetch)
    assert calls == []  # nothing re-fetched


def test_failed_tag_is_retried_not_marked_done(tmp_path):
    cache = MetadataCache(tmp_path)
    tags = {"Plane-4.5.1": "c" * 40}
    assert sync_release_metadata(cache=cache, tags=tags, fetch=lambda *_: None)["failed"] == ["Plane-4.5.1"]
    assert sync_release_metadata(cache=cache, tags=tags, fetch=lambda *_: _defs())["cached"] == ["Plane-4.5.1"]


def test_firmware_sync_has_no_llm_deps():
    tree = ast.parse((Path(__file__).resolve().parents[2] / "app/knowledge/firmware_sync.py").read_text())
    roots = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            roots |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            roots.add(n.module.split(".")[0])
    assert not roots & {"langchain", "langgraph", "openai", "langsmith"}


def test_short_vehicle_hash_is_resolved_to_the_release_commit_before_fetching(monkeypatch, tmp_path):
    import subprocess

    from app.knowledge import firmware_sync, metadata_fetcher
    from app.models.vehicle import VehicleVersionInfo

    full = "92b0cd788ec29406f26c6f9c31d5ceedbd1cc538"
    monkeypatch.setattr(firmware_sync, "list_release_tags", lambda url=None: {"Copter-4.6.3": full, "Plane-4.6.3": "f" * 40})
    fetched = []

    def fake_run(cmd, **kw):
        fetched.append(cmd)
        if "fetch" in cmd:
            raise subprocess.CalledProcessError(1, cmd)  # stop after recording the fetch target
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(metadata_fetcher.subprocess, "run", fake_run)
    info = VehicleVersionInfo(vehicle_type="ArduCopter", mav_type=2, board_type=0, flight_sw_version="4.6.3", git_hash="92b0cd78")
    assert metadata_fetcher.fetch_definitions_from_git_source("ArduCopter", info, tmp_root=tmp_path) is None
    assert any(full in c for cmd in fetched for c in cmd)  # the full SHA, not the 8-char one reached git

    # a short hash that is not an official release commit is not guessed at
    fetched.clear()
    info2 = info.model_copy(update={"git_hash": "deadbeef"})
    assert metadata_fetcher.fetch_definitions_from_git_source("ArduCopter", info2, tmp_root=tmp_path) is None
    assert fetched == []
