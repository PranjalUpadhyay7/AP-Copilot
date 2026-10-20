#!/usr/bin/env python3
"""Pre-cache parameter metadata for official firmware releases."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.knowledge.firmware_sync import sync_release_metadata


def main() -> int:
    try:
        result = sync_release_metadata()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        print(f"Could not list release tags from the ArduPilot repo: {e}", file=sys.stderr)
        return 1
    for status, tags in result.items():
        print(f"{status}: {len(tags)}" + (f" ({', '.join(tags)})" if status == "failed" and tags else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
