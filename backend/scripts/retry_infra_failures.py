#!/usr/bin/env python3
"""Re-run benchmark runs that failed because of the API (rate limit, timeout...), not the model."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from eval.summarize_results import is_infra_failure


def plan(folder: Path) -> list[dict]:
    jobs = []
    for path in sorted(folder.glob("*.jsonl")):
        latest: dict[tuple, dict] = {}
        for line in path.read_text().splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            latest[(rec["model"], rec.get("ablation", "full"), rec["task_id"], rec["repeat"])] = rec
        cells: dict[tuple, list] = defaultdict(list)
        for (model, ablation, task, repeat), rec in latest.items():
            if is_infra_failure(rec):
                cells[(model, ablation)].append((task, repeat))
        for (model, ablation), items in cells.items():
            jobs.append({
                "file": path, "model": model, "ablation": ablation,
                "tasks": sorted({t for t, _ in items}), "repeats": max(r for _, r in items) + 1,
            })
    return jobs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folder")
    ap.add_argument("--parallel", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--match", default=None, help="only retry models whose id contains this text")
    args = ap.parse_args()
    jobs = [j for j in plan(Path(args.folder)) if not args.match or args.match in j["model"]]
    for j in jobs:
        print(f"{j['file'].name}: {j['model']} [{j['ablation']}] retry {len(j['tasks'])} task(s) up to repeat {j['repeats']}")
    if args.dry_run or not jobs:
        print("nothing to retry" if not jobs else "(dry run)")
        return 0
    running: list[subprocess.Popen] = []
    for j in jobs:
        while len(running) >= args.parallel:
            running = [p for p in running if p.poll() is None]
            if len(running) >= args.parallel:
                running[0].wait()
        cmd = [sys.executable, str(BACKEND / "scripts" / "run_benchmark.py"), "--models", j["model"], "--ablation", j["ablation"],
               "--repeats", str(j["repeats"]), "--tasks", *j["tasks"], "--jsonl", str(j["file"]), "--resume"]
        running.append(subprocess.Popen(cmd, cwd=BACKEND))
    for p in running:
        p.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
