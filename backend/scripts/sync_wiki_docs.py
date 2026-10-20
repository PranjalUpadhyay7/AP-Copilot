#!/usr/bin/env python3
"""Clone and index the ArduPilot wiki."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.knowledge import wiki_docs
from app.knowledge.rag_store import VEHICLE_DOC_SLUG


def main(argv: list[str]) -> int:
    slugs = argv or sorted(VEHICLE_DOC_SLUG.values())

    commit = wiki_docs.sync_wiki_repo(wiki_docs.DEFAULT_WIKI_SRC_DIR)
    if commit is None:
        print("Failed to sync ardupilot_wiki (no network, git error, or timeout) -- see logs.", file=sys.stderr)
        return 1
    print(f"ardupilot_wiki synced to commit {commit}")

    for slug in slugs:
        index = wiki_docs.get_wiki_index(slug, force_sync=True)
        status = "indexed" if index is not None and index.available else "no content / unavailable"
        print(f"  {slug}: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
