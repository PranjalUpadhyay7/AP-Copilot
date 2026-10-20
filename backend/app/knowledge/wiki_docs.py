"""Full ArduPilot documentation-site memory."""
from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from pathlib import Path

from app.knowledge.rag_store import VEHICLE_DOC_SLUG, DocChunk, EmbeddingIndex

logger = logging.getLogger(__name__)

WIKI_REPO_URL = "https://github.com/ArduPilot/ardupilot_wiki.git"

_AP_COPILOT_HOME = Path(os.environ.get("AP_COPILOT_HOME", Path.home() / ".ap-copilot"))
DEFAULT_WIKI_SRC_DIR = _AP_COPILOT_HOME / "wiki_src"
DEFAULT_WIKI_INDEX_ROOT = _AP_COPILOT_HOME / "wiki_index_cache"

WIKI_RELIABILITY = 0.65

_COMMON_SLUG = "common"
_ALL_SLUGS = (*VEHICLE_DOC_SLUG.values(), _COMMON_SLUG)

DEFAULT_SYNC_INTERVAL_S = float(os.environ.get("AP_COPILOT_WIKI_SYNC_INTERVAL_S", str(6 * 3600)))

_ENABLED = os.environ.get("AP_COPILOT_WIKI_SYNC", "0") == "1"

_INDEX_CACHE: dict[str, tuple[EmbeddingIndex | None, float]] = {}


def sync_wiki_repo(repo_dir: str | Path = DEFAULT_WIKI_SRC_DIR, *, timeout: float = 120.0) -> str | None:
    """Shallow-clone or fast-forward the ardupilot_wiki repository."""
    repo_dir = Path(repo_dir)
    try:
        if not (repo_dir / ".git").exists():
            repo_dir.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "clone", "--depth", "1", WIKI_REPO_URL, str(repo_dir)],
                check=True, capture_output=True, text=True, timeout=timeout,
            )
        else:
            subprocess.run(
                ["git", "-C", str(repo_dir), "fetch", "--depth", "1", "origin"],
                check=True, capture_output=True, text=True, timeout=timeout,
            )
            subprocess.run(
                ["git", "-C", str(repo_dir), "reset", "--hard", "origin/HEAD"],
                check=True, capture_output=True, text=True, timeout=30,
            )
        result = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        logger.warning("ardupilot_wiki sync failed, wiki doc tier unavailable this session: %s", e)
        return None


_UNDERLINE_RE = re.compile(r"^([=\-~^\"'`#*+.:_])\1{2,}\s*$")
_DIRECTIVE_RE = re.compile(r"^\s*\.\.\s+\S")  # ".. directive::" / ".. comment"
_INLINE_MARKUP_RE = re.compile(r"[*`]{1,2}")  # strip **bold**/``code``/*emph* markers, keep the text
_ROLE_RE = re.compile(r":[a-z:]+:`([^`]*)`")  # :ref:`label` / :doc:`text <target>` -> label text
_LINK_RE = re.compile(r"`([^`<]+)\s*<[^>]+>`_+")  # `Text <url>`_ -> Text


def _clean_line(line: str) -> str:
    line = _ROLE_RE.sub(lambda m: m.group(1).split("<")[0].strip(), line)
    line = _LINK_RE.sub(r"\1", line)
    line = _INLINE_MARKUP_RE.sub("", line)
    return line


def parse_rst_sections(text: str) -> list[tuple[str, str]]:
    """Splits reST source into `(heading, body_text)` pairs, in document order."""
    lines = text.splitlines()
    sections: list[tuple[str, list[str]]] = [("", [])]
    i = 0
    in_directive_block = False
    while i < len(lines):
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""

        if line.strip() and _UNDERLINE_RE.match(nxt) and len(nxt.strip()) >= max(3, len(line.strip()) * 0.5):
            sections.append((line.strip(), []))
            i += 2
            in_directive_block = False
            continue

        if _DIRECTIVE_RE.match(line):
            in_directive_block = True
            i += 1
            continue
        if in_directive_block:
            if line.strip() == "" or line.startswith((" ", "\t")):
                i += 1
                continue
            in_directive_block = False

        sections[-1][1].append(_clean_line(line))
        i += 1

    return [(heading, "\n".join(body).strip()) for heading, body in sections if "\n".join(body).strip()]


def _doc_url(vehicle_slug: str, rel_path: Path, anchor: str | None = None) -> str:
    stem = rel_path.with_suffix("").as_posix()
    url = f"https://ardupilot.org/{vehicle_slug}/docs/{stem}.html"
    if anchor:
        url += f"#{anchor.lower().replace(' ', '-')}"
    return url


def _source_files(repo_dir: Path, slug: str) -> list[Path]:
    base = repo_dir / slug / "source" / "docs"
    if not base.is_dir():
        return []
    return sorted(base.rglob("*.rst"))


def ingest_wiki_docs(repo_dir: str | Path = DEFAULT_WIKI_SRC_DIR) -> dict[str, list[tuple[str, str, str, str]]]:
    """Split wiki pages into sections and embed them."""
    repo_dir = Path(repo_dir)
    by_slug: dict[str, list[tuple[str, str, str, str]]] = {}
    for slug in _ALL_SLUGS:
        chunks: list[tuple[str, str, str, str]] = []
        for path in _source_files(repo_dir, slug):
            rel = path.relative_to(repo_dir / slug / "source" / "docs")
            try:
                text = path.read_text(errors="ignore")
            except OSError as e:
                logger.warning("skipping unreadable wiki source %s: %s", path, e)
                continue
            for heading, body in parse_rst_sections(text):
                if len(body) < 40:  # skip near-empty stubs/nav fragments
                    continue
                title = f"{rel.stem}: {heading}" if heading else rel.stem
                chunks.append((title, body, rel.as_posix(), heading))
        by_slug[slug] = chunks
    return by_slug


def _documents_for_vehicle(
    by_slug: dict[str, list[tuple[str, str, str, str]]], vehicle_slug: str,
) -> list[tuple[str, str, str | None]]:
    docs: list[tuple[str, str, str | None]] = []
    for slug, chunks in ((vehicle_slug, by_slug.get(vehicle_slug, [])), (_COMMON_SLUG, by_slug.get(_COMMON_SLUG, []))):
        site_slug = vehicle_slug if slug == _COMMON_SLUG else slug
        for title, text, rel_path, heading in chunks:
            docs.append((title, text, _doc_url(site_slug, Path(rel_path), heading or None)))
    return docs


def _rebuild_if_stale(persist_path: Path, collection_name: str, current_hash: str) -> None:
    marker = persist_path / f"{collection_name}.commit"
    if marker.exists() and marker.read_text().strip() == current_hash:
        return
    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(persist_path))
        try:
            client.delete_collection(collection_name)
        except Exception as e:  # noqa: BLE001 -- didn't exist yet, nothing to drop
            logger.debug("no existing wiki collection %s to drop: %s", collection_name, e)
    except Exception as e:  # noqa: BLE001
        logger.warning("could not reset stale wiki collection %s, leaving as-is: %s", collection_name, e)
        return
    persist_path.mkdir(parents=True, exist_ok=True)
    marker.write_text(current_hash)


def get_wiki_index(
    vehicle_slug: str,
    *,
    repo_dir: str | Path = DEFAULT_WIKI_SRC_DIR,
    index_root: str | Path = DEFAULT_WIKI_INDEX_ROOT,
    sync_interval_s: float = DEFAULT_SYNC_INTERVAL_S,
    force_sync: bool = False,
) -> EmbeddingIndex | None:
    """Top-level entry point session_manager calls."""
    if not _ENABLED or vehicle_slug not in VEHICLE_DOC_SLUG.values():
        return None

    cached = _INDEX_CACHE.get(vehicle_slug)
    now = time.time()
    if cached is not None and not force_sync and (now - cached[1]) < sync_interval_s:
        return cached[0]

    commit = sync_wiki_repo(repo_dir)
    if commit is None:
        _INDEX_CACHE[vehicle_slug] = (cached[0] if cached else None, now)
        return cached[0] if cached else None

    index_root = Path(index_root)
    by_slug = ingest_wiki_docs(repo_dir)
    documents = _documents_for_vehicle(by_slug, vehicle_slug)
    if not documents:
        _INDEX_CACHE[vehicle_slug] = (None, now)
        return None

    _rebuild_if_stale(index_root, vehicle_slug, commit)
    index = EmbeddingIndex(documents, persist_path=str(index_root), collection_name=vehicle_slug)
    result = index if index.available else None
    _INDEX_CACHE[vehicle_slug] = (result, now)
    return result


def search_wiki_docs(query: str, index: EmbeddingIndex, k: int = 5) -> list[DocChunk]:
    return [
        chunk.model_copy(update={"source_type": "wiki", "reliability_score": WIKI_RELIABILITY})
        for chunk in index.search(query, k=k)
    ]
