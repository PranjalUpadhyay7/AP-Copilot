#!/usr/bin/env python3
"""Run benchmark jobs with limited parallelism (free-tier APIs rate-limit per account)."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-parallel", type=int, default=3)
    ap.add_argument("jobs", nargs="+")
    args = ap.parse_args()
    running: list[subprocess.Popen] = []
    for job in args.jobs:
        while len([p for p in running if p.poll() is None]) >= args.max_parallel:
            time.sleep(5)
        argv = shlex.split(job)
        log = argv[argv.index("--jsonl") + 1].replace(".jsonl", ".log") if "--jsonl" in argv else None
        out = open(log, "a") if log else None  # noqa: SIM115 -- must stay open for the child process
        running.append(subprocess.Popen([sys.executable, str(BACKEND / "scripts" / "run_benchmark.py"), *argv],
                                        cwd=BACKEND, stdout=out, stderr=subprocess.STDOUT))
    for p in running:
        p.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
