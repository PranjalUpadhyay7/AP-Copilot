#!/usr/bin/env python3
"""Launcher for long benchmark runs: `python scripts/run_benchmark.py <run_bench.py args>`."""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv

os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")  # set before load_dotenv: .env must not turn it back on
os.environ.setdefault("NIM_MAX_RETRIES", "8")  # free tiers rate-limit in sliding windows: back off longer
load_dotenv(BACKEND / ".env")

from eval.run_bench import main

if __name__ == "__main__":
    raise SystemExit(main())
