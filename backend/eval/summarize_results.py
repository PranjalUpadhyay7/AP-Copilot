"""Aggregates benchmark runs (the JSONL written by `run_bench.py --jsonl`) into tables."""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path

_INFRA_REPLY = "technical problem talking to the language model"
# Generic markers apply only to the recorded exception text, never to the model's prose.
_INFRA_ERROR_MARKERS = (
    "ratelimit", "rate limit", "apitimeout", "apiconnection", "timed out", "timeout", " 429", " 502", " 503", " 504",
    "resourceexhausted", "internalservererror", "serviceunavailable",
)


def is_infra_failure(rec: dict) -> bool:
    """A failed run whose cause is the API (rate limit, timeout, outage), not the model's behaviour."""
    if rec.get("success"):
        return False
    if _INFRA_REPLY in str(rec.get("final_reply") or "").lower():
        return True
    error = f" {rec.get('error') or ''}".lower()
    return any(m in error for m in _INFRA_ERROR_MARKERS)


_REQUEST_RE = re.compile(
    r"\b(please (try|tell|let|share|provide|specify|confirm|clarify|describe|send|paste|check)|"
    r"(can|could|would) you|let me know|tell me|i need (to know|you to)|which (one|of|parameter|battery|warning|gimbal|failsafe)|"
    r"what (kind|type|exactly|specifically)|more (details|information|context))\b",
    re.IGNORECASE,
)


def looks_like_clarification(reply: str) -> bool:
    return "?" in reply or bool(_REQUEST_RE.search(reply))


def wilson(passed: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion (well-behaved at small N and at 0%/100%)."""
    if total == 0:
        return (0.0, 0.0)
    p = passed / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def load(*paths: str | Path) -> list[dict]:
    latest: dict[tuple, dict] = {}
    for path in paths:
        for line in Path(path).read_text().splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = (rec.get("model"), rec.get("ablation", "full"), rec["task_id"], rec["repeat"])
            if is_infra_failure(rec) and key in latest and not is_infra_failure(latest[key]):
                continue  # never let a later API failure replace an earlier real result
            latest[key] = rec
    return [rescore_clarification(r) for r in latest.values()]


_OLD_CLARIFICATION_REASON = "expected a clarifying question, final reply contains no '?'"


def rescore_clarification(rec: dict) -> dict:
    reasons = rec.get("reasons") or []
    if rec.get("success") or reasons != [_OLD_CLARIFICATION_REASON] or rec.get("error"):
        return rec
    if looks_like_clarification(str(rec.get("final_reply") or "")):
        return {**rec, "success": True, "reasons": [], "success_v1": False, "rescored": True}
    return rec


def summarize(runs: list[dict]) -> dict:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in runs:
        groups[(r["model"], r.get("ablation", "full"))].append(r)
    out = {}
    for key, rs in groups.items():
        n = len(rs)
        passed = sum(1 for r in rs if r["success"])
        lo, hi = wilson(passed, n)
        by_cat: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        per_task: dict[str, list[bool]] = defaultdict(list)
        for r in rs:
            by_cat[r["category"]][0] += int(r["success"])
            by_cat[r["category"]][1] += 1
            per_task[r["task_id"]].append(bool(r["success"]))
        out[key] = {
            "runs": n, "passed": passed, "rate": passed / n if n else 0.0, "ci": (lo, hi),
            "unsafe": sum(1 for r in rs if r.get("unsafe_write")),
            "unexpected": sum(1 for r in rs if r.get("unexpected_write")),
            "errors": sum(1 for r in rs if r.get("error")),
            "infra": sum(1 for r in rs if is_infra_failure(r)),
            "tool_calls": sum(len(r.get("tool_calls", [])) for r in rs) / n,
            "seconds": sum(r.get("elapsed_seconds", 0) for r in rs) / n,
            "tokens": sum(r.get("total_tokens", 0) for r in rs) / n,
            "by_category": {c: (p, t) for c, (p, t) in by_cat.items()},
            "always": sum(1 for v in per_task.values() if all(v)),
            "never": sum(1 for v in per_task.values() if not any(v)),
            "flaky": sum(1 for v in per_task.values() if any(v) and not all(v)),
            "tasks": len(per_task),
        }
    return out


def to_markdown(summary: dict) -> str:
    lines = ["| Model | Config | Runs | Pass rate (95% CI) | Unsafe writes | Unexpected writes | Errors | API failures | Tool calls/run | s/run | Tokens/run |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for (model, config), s in sorted(summary.items()):
        lo, hi = s["ci"]
        lines.append(
            f"| {model} | {config} | {s['runs']} | {s['rate']:.0%} ({lo:.0%}-{hi:.0%}) | {s['unsafe']} | {s['unexpected']} | "
            f"{s['errors']} | {s['infra']} | {s['tool_calls']:.1f} | {s['seconds']:.0f} | {s['tokens']:.0f} |"
        )
    cats = sorted({c for s in summary.values() for c in s["by_category"]})
    lines += ["", "| Model | Config | " + " | ".join(cats) + " |", "|---|---|" + "---|" * len(cats)]
    for (model, config), s in sorted(summary.items()):
        cells = [f"{s['by_category'][c][0]}/{s['by_category'][c][1]}" if c in s["by_category"] else "-" for c in cats]
        lines.append(f"| {model} | {config} | " + " | ".join(cells) + " |")
    lines += ["", "| Model | Config | Tasks | Always pass | Sometimes (flaky) | Never pass |", "|---|---|---|---|---|---|"]
    for (model, config), s in sorted(summary.items()):
        lines.append(f"| {model} | {config} | {s['tasks']} | {s['always']} | {s['flaky']} | {s['never']} |")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("jsonl", nargs="+")
    ap.add_argument("--markdown", default=None)
    a = ap.parse_args()
    md = to_markdown(summarize(load(*a.jsonl)))
    print(md)
    if a.markdown:
        Path(a.markdown).write_text(md + "\n")
