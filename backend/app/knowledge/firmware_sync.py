"""Pre-cache parameter metadata for official release tags."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from app.knowledge.metadata_fetcher import (
    DEFAULT_ARDUPILOT_REPO_URL,
    DEFAULT_CACHE_ROOT,
    MetadataCache,
    fetch_definitions_from_git_source,
    fetch_definitions_from_public_source,
)
from app.models.vehicle import VehicleVersionInfo

logger = logging.getLogger(__name__)

# Stable release tags only ("Copter-4.6.0"), not betas/rcs/dev.
_TAG_RE = re.compile(r"^(Copter|Plane|Rover|Sub)-(\d+)\.(\d+)\.(\d+)$")
VEHICLE_TYPE_BY_TAG_PREFIX = {"Copter": "ArduCopter", "Plane": "ArduPlane", "Rover": "Rover", "Sub": "ArduSub"}
LIVE_HASH_LEN = 8
DEFAULT_MIN_VERSION = (4, 0)


def list_release_tags(repo_url: str = DEFAULT_ARDUPILOT_REPO_URL) -> dict[str, str]:
    """tag -> commit SHA via `git ls-remote --tags` (official refs, no scraping)."""
    out = subprocess.run(
        ["git", "ls-remote", "--tags", repo_url], check=True, capture_output=True, text=True, timeout=120,
    ).stdout
    return parse_ls_remote(out)


def parse_ls_remote(text: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for line in text.splitlines():
        sha, _, ref = line.partition("\t")
        if not ref.startswith("refs/tags/"):
            continue
        name = ref.removeprefix("refs/tags/")
        peeled = name.endswith("^{}")
        name = name.removesuffix("^{}")
        if _TAG_RE.match(name) and (peeled or name not in tags):
            tags[name] = sha  # a peeled line is the real commit; it wins
    return tags


def _git_fetch(vehicle_type: str, info: VehicleVersionInfo) -> dict | None:
    return fetch_definitions_from_public_source(vehicle_type, info) or fetch_definitions_from_git_source(
        vehicle_type, info, fetch_timeout=900,
    )


def _marker_path(cache_root: Path) -> Path:
    return cache_root / "synced_tags.json"


def sync_release_metadata(
    *,
    cache: MetadataCache | None = None,
    tags: dict[str, str] | None = None,
    fetch: Callable[[str, VehicleVersionInfo], dict | None] = _git_fetch,
    min_version: tuple[int, int] = DEFAULT_MIN_VERSION,
) -> dict[str, list[str]]:
    """Caches definitions for every not-yet-synced tag >= `min_version`."""
    cache = cache or MetadataCache(DEFAULT_CACHE_ROOT)
    tags = tags if tags is not None else list_release_tags()
    marker = _marker_path(cache.root)
    done: set[str] = set(json.loads(marker.read_text())) if marker.exists() else set()
    result: dict[str, list[str]] = {"cached": [], "failed": [], "skipped": []}

    for tag, sha in sorted(tags.items()):
        prefix, major, minor, patch = _TAG_RE.match(tag).groups()  # type: ignore[union-attr]
        vehicle_type = VEHICLE_TYPE_BY_TAG_PREFIX[prefix]
        version = f"{major}.{minor}.{patch}"
        key = sha[:LIVE_HASH_LEN]
        if tag in done or (int(major), int(minor)) < min_version or cache.get(vehicle_type, key) is not None:
            if cache.get(vehicle_type, key) is not None:
                done.add(tag)
            result["skipped"].append(tag)
            continue
        info = VehicleVersionInfo(
            vehicle_type=vehicle_type, mav_type=0, board_type=0, flight_sw_version=version, git_hash=sha,
        )
        definitions = fetch(vehicle_type, info)
        if not definitions:
            logger.warning("firmware sync: no definitions for %s (%s)", tag, sha)
            result["failed"].append(tag)
            continue
        cache.put(vehicle_type, key, definitions)
        done.add(tag)
        result["cached"].append(tag)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(sorted(done)))
    return result
