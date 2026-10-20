from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.orchestrator.graph import build_graph
from eval.cassette import CASSETTE_DIR, CassetteChatModel
from eval.run_bench import _build_context, load_tasks, run_task, score_task

CASSETTES = sorted(p.stem for p in Path(CASSETTE_DIR).glob("*.json"))


@pytest.mark.parametrize("task_id", CASSETTES)
def test_recorded_conversation_still_passes(task_id):
    [task] = load_tasks([task_id])
    context, vehicle = _build_context(task)
    graph = build_graph(context, CassetteChatModel(path=CASSETTE_DIR / f"{task_id}.json"), MemorySaver())
    run = run_task(graph, task, vehicle)
    scored = score_task(task, run, context.live_params)
    assert scored["success"], (scored, run.get("error"))
