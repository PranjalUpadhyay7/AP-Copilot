import subprocess
from unittest.mock import MagicMock, patch

from app.knowledge import wiki_docs
from app.knowledge.rag_store import DocChunk


def test_parse_rst_sections_splits_by_heading():
    text = (
        "Intro paragraph before any heading.\n\n"
        "Compass Calibration\n"
        "====================\n\n"
        "Rotate the vehicle through all axes until complete.\n"
    )
    sections = wiki_docs.parse_rst_sections(text)
    headings = [h for h, _ in sections]
    assert "Compass Calibration" in headings
    body = dict(sections)["Compass Calibration"]
    assert "Rotate the vehicle" in body


def test_parse_rst_sections_strips_directives_and_inline_markup():
    text = (
        "Setup\n"
        "-----\n\n"
        ".. image:: ../images/setup.png\n"
        "   :width: 400px\n\n"
        "This is **important** and uses ``ARMING_SKIPCHK``. See :ref:`compass-cal`.\n"
    )
    sections = wiki_docs.parse_rst_sections(text)
    body = dict(sections)["Setup"]
    assert "image::" not in body
    assert "**" not in body
    assert "ARMING_SKIPCHK" in body
    assert "compass-cal" in body  # role text kept, markup stripped


def test_parse_rst_sections_whole_page_when_no_headings():
    sections = wiki_docs.parse_rst_sections("Just one plain paragraph, no heading at all.\n")
    assert len(sections) == 1
    assert sections[0][0] == ""


def test_sync_wiki_repo_clones_when_repo_missing(tmp_path):
    repo_dir = tmp_path / "wiki"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="abc123\n")
        result = wiki_docs.sync_wiki_repo(repo_dir)

    assert result == "abc123"
    clone_call = mock_run.call_args_list[0].args[0]
    assert clone_call[:2] == ["git", "clone"]
    assert wiki_docs.WIKI_REPO_URL in clone_call


def test_sync_wiki_repo_fetches_and_resets_when_repo_present(tmp_path):
    repo_dir = tmp_path / "wiki"
    (repo_dir / ".git").mkdir(parents=True)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="def456\n")
        result = wiki_docs.sync_wiki_repo(repo_dir)

    assert result == "def456"
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert any("fetch" in c for c in calls)
    assert any("reset" in c for c in calls)
    assert not any(c[:2] == ["git", "clone"] for c in calls)


def test_sync_wiki_repo_returns_none_on_failure_not_raises(tmp_path):
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "git")):
        assert wiki_docs.sync_wiki_repo(tmp_path / "wiki") is None


def test_sync_wiki_repo_returns_none_on_timeout_not_raises(tmp_path):
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 60)):
        assert wiki_docs.sync_wiki_repo(tmp_path / "wiki") is None


def _write_wiki_fixture(repo_dir):
    copter_docs = repo_dir / "copter" / "source" / "docs"
    copter_docs.mkdir(parents=True)
    (copter_docs / "compass-calibration.rst").write_text(
        "Compass Calibration\n"
        "====================\n\n"
        "Rotate the copter slowly through all orientations until each compass "
        "reports calibration complete, then review the fitness report.\n"
    )
    common_docs = repo_dir / "common" / "source" / "docs"
    common_docs.mkdir(parents=True)
    (common_docs / "common-glossary.rst").write_text(
        "Glossary\n"
        "========\n\n"
        "EKF: Extended Kalman Filter, used for state estimation across every "
        "vehicle type this project supports.\n"
    )


def test_ingest_wiki_docs_reads_vehicle_and_common_dirs(tmp_path):
    _write_wiki_fixture(tmp_path)
    by_slug = wiki_docs.ingest_wiki_docs(tmp_path)

    assert any("Rotate the copter slowly" in text for _, text, _, _ in by_slug["copter"])
    assert any("Extended Kalman Filter" in text for _, text, _, _ in by_slug["common"])
    assert by_slug["plane"] == []  # no plane docs in this fixture, must not crash

    source, _, rel_path, _ = by_slug["copter"][0]
    assert "compass-calibration" in source.lower() or "Compass Calibration" in source
    assert rel_path == "compass-calibration.rst"


def test_documents_for_vehicle_merges_vehicle_and_common():
    by_slug = {
        "copter": [("A", "copter text", "a.rst", "")],
        "common": [("B", "common text", "b.rst", "")],
        "plane": [("C", "plane text", "c.rst", "")],
    }
    docs = wiki_docs._documents_for_vehicle(by_slug, "copter")
    assert docs == [
        ("A", "copter text", "https://ardupilot.org/copter/docs/a.html"),
        ("B", "common text", "https://ardupilot.org/copter/docs/b.html"),
    ]


def test_documents_for_vehicle_cites_common_docs_under_the_asking_vehicles_own_site():
    by_slug = {"common": [("Compass Calibration", "text", "common-compass-calibration.rst", "")]}

    copter_docs = wiki_docs._documents_for_vehicle(by_slug, "copter")
    plane_docs = wiki_docs._documents_for_vehicle(by_slug, "plane")

    assert copter_docs[0][2] == "https://ardupilot.org/copter/docs/common-compass-calibration.html"
    assert plane_docs[0][2] == "https://ardupilot.org/plane/docs/common-compass-calibration.html"
    assert "ardupilot.org/common/" not in copter_docs[0][2]


def test_get_wiki_index_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(wiki_docs, "_ENABLED", False)
    assert wiki_docs.get_wiki_index("copter") is None


def test_get_wiki_index_unknown_vehicle_slug_returns_none(monkeypatch):
    monkeypatch.setattr(wiki_docs, "_ENABLED", True)
    assert wiki_docs.get_wiki_index("not-a-real-vehicle") is None


def test_get_wiki_index_sync_failure_returns_none_without_cached_index(monkeypatch, tmp_path):
    monkeypatch.setattr(wiki_docs, "_ENABLED", True)
    monkeypatch.setattr(wiki_docs, "_INDEX_CACHE", {})
    monkeypatch.setattr(wiki_docs, "sync_wiki_repo", lambda *a, **k: None)

    result = wiki_docs.get_wiki_index("copter", repo_dir=tmp_path / "wiki", index_root=tmp_path / "idx")
    assert result is None


def test_get_wiki_index_builds_and_caches_within_interval(monkeypatch, tmp_path):
    monkeypatch.setattr(wiki_docs, "_ENABLED", True)
    monkeypatch.setattr(wiki_docs, "_INDEX_CACHE", {})
    monkeypatch.setattr(wiki_docs, "sync_wiki_repo", lambda *a, **k: "commit-1")

    fake_index = MagicMock()
    fake_index.available = True
    mock_embedding_index_cls = MagicMock(return_value=fake_index)
    monkeypatch.setattr(wiki_docs, "EmbeddingIndex", mock_embedding_index_cls)

    def fake_ingest(repo_dir):
        return {"copter": [("Compass", "text", "compass.rst", "")], "common": []}

    monkeypatch.setattr(wiki_docs, "ingest_wiki_docs", fake_ingest)
    monkeypatch.setattr(wiki_docs, "_rebuild_if_stale", lambda *a, **k: None)

    first = wiki_docs.get_wiki_index("copter", repo_dir=tmp_path / "wiki", index_root=tmp_path / "idx")
    assert first is fake_index
    assert mock_embedding_index_cls.call_count == 1

    second = wiki_docs.get_wiki_index("copter", repo_dir=tmp_path / "wiki", index_root=tmp_path / "idx")
    assert second is fake_index
    assert mock_embedding_index_cls.call_count == 1


def test_search_wiki_docs_retags_source_type_and_reliability():
    fake_index = MagicMock()
    fake_index.search.return_value = [
        DocChunk(source="Compass Calibration", text="rotate through all axes", score=0.9),
    ]

    results = wiki_docs.search_wiki_docs("compass cal", fake_index)

    assert len(results) == 1
    assert results[0].source_type == "wiki"
    assert results[0].reliability_score == wiki_docs.WIKI_RELIABILITY
    assert results[0].text == "rotate through all axes"
