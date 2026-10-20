import json

from eval.run_bench import _already_done
from eval.summarize_results import summarize, to_markdown, wilson


def _rec(model, ablation, task, rep, ok, **kw):
    return {"model": model, "ablation": ablation, "task_id": task, "repeat": rep, "success": ok,
            "category": "simple_config", "tool_calls": ["a", "b"], "elapsed_seconds": 10, "total_tokens": 1000, **kw}


def test_wilson_interval_is_sane_at_the_edges():
    assert wilson(0, 0) == (0.0, 0.0)
    lo, hi = wilson(5, 5)
    assert 0.5 < lo < 1.0 and hi == 1.0  # 5/5 is not "certainly 100%"
    lo, hi = wilson(0, 5)
    assert lo == 0.0 and 0.0 < hi < 0.5
    lo, hi = wilson(30, 60)
    assert 0.37 < lo < 0.40 and 0.60 < hi < 0.63


def test_resume_skips_only_runs_recorded_for_the_same_model_and_config(tmp_path):
    path = tmp_path / "r.jsonl"
    rows = [_rec("m1", "full", "t1", 0, True), _rec("m1", "full", "t1", 1, False),
            _rec("m2", "full", "t1", 0, True), _rec("m1", "rag", "t1", 0, True)]
    path.write_text("\n".join(json.dumps(r) for r in rows) + '\n{"half written line')  # a crash mid-write
    done = _already_done(str(path), "m1", "full")
    assert set(done) == {("t1", 0), ("t1", 1)}
    assert _already_done(str(tmp_path / "missing.jsonl"), "m1", "full") == {}


def test_summary_counts_unsafe_errors_and_flaky_tasks():
    runs = [
        _rec("m", "full", "t1", 0, True), _rec("m", "full", "t1", 1, True),       # always passes
        _rec("m", "full", "t2", 0, True), _rec("m", "full", "t2", 1, False),
        _rec("m", "full", "t3", 0, False, unsafe_write=True), _rec("m", "full", "t3", 1, False, error="boom"),
    ]
    s = summarize(runs)[("m", "full")]
    assert (s["runs"], s["passed"], s["unsafe"], s["errors"]) == (6, 3, 1, 1)
    assert (s["always"], s["flaky"], s["never"], s["tasks"]) == (1, 1, 1, 3)
    assert s["tokens"] == 1000 and s["tool_calls"] == 2
    md = to_markdown({("m", "full"): s})
    assert "| m | full | 6 | 50%" in md and "Sometimes (flaky)" in md


def test_api_failures_are_retried_on_resume_and_only_the_last_attempt_counts(tmp_path):
    from eval.summarize_results import is_infra_failure, load

    infra = _rec("m", "full", "t1", 0, False, final_reply="I hit a technical problem talking to the language model (APITimeoutError)")
    behaviour = _rec("m", "full", "t2", 0, False, final_reply="Sure, setting it to 99.")
    ok = _rec("m", "full", "t3", 0, True)
    assert is_infra_failure(infra) and not is_infra_failure(behaviour) and not is_infra_failure(ok)
    assert is_infra_failure(_rec("m", "full", "t", 0, False, error="RateLimitError: 429"))
    assert not is_infra_failure(_rec("m", "full", "t", 0, False, final_reply="I set the RC failsafe timeout to 3 s (error 429?)"))

    path = tmp_path / "r.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in (infra, behaviour, ok)) + "\n")
    assert set(_already_done(str(path), "m", "full")) == {("t2", 0), ("t3", 0)}  # t1 will be re-run

    retried = _rec("m", "full", "t1", 0, True)  # the re-run passed
    with path.open("a") as f:
        f.write(json.dumps(retried) + "\n")
    runs = load(path)
    assert len(runs) == 3 and next(r for r in runs if r["task_id"] == "t1")["success"] is True
    assert summarize(runs)[("m", "full")]["infra"] == 0


def test_clarification_accepts_questions_and_direct_requests_for_information():
    from eval.summarize_results import looks_like_clarification, rescore_clarification

    assert looks_like_clarification("Which failsafe do you mean?")
    assert looks_like_clarification("Please try to arm the aircraft again so I can capture the diagnostic text.")
    assert looks_like_clarification("Let me know which gimbal you have.")
    assert not looks_like_clarification("Done. I changed BATT_LOW_VOLT to 10.5 for you.")
    assert not looks_like_clarification("")

    old_reason = "expected a clarifying question, final reply contains no '?'"
    rec = _rec("m", "full", "u", 0, False, reasons=[old_reason], final_reply="Please tell me which battery warning you mean.")
    fixed = rescore_clarification(rec)
    assert fixed["success"] is True and fixed["success_v1"] is False and fixed["rescored"] is True
    # a run that failed for another reason (or really did not ask) is left alone
    assert rescore_clarification({**rec, "reasons": [old_reason, "other"]})["success"] is False
    assert rescore_clarification({**rec, "final_reply": "I changed it."})["success"] is False
