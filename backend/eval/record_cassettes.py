#!/usr/bin/env python3
"""Record real-NIM-response cassettes for a set of benchmark tasks."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.orchestrator.graph import build_graph
from app.orchestrator.nim_client import get_nim_chat_model
from eval.cassette import CASSETTE_DIR, CassetteChatModel
from eval.run_bench import _build_context, load_tasks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", nargs="+", required=True, help="task IDs to record")
    args = parser.parse_args()

    tasks = load_tasks(args.tasks)
    if len(tasks) != len(args.tasks):
        found = {t.id for t in tasks}
        missing = set(args.tasks) - found
        print(f"Unknown task id(s): {sorted(missing)}", file=sys.stderr)
        return 1

    real_model = get_nim_chat_model()

    for task in tasks:
        cassette_path = CASSETTE_DIR / f"{task.id}.json"
        cassette_model = CassetteChatModel(path=cassette_path, mode="record", underlying=real_model)
        context, _vehicle_client = _build_context(task)
        graph = build_graph(context, cassette_model, MemorySaver())

        config = {"configurable": {"thread_id": f"record-{task.id}"}, "recursion_limit": 60}
        result = graph.invoke(
            {
                "messages": [HumanMessage(content=task.prompt)],
                "session_id": f"record-{task.id}",
                "pending_proposal": None,
                "pending_tool_call_id": None,
                "remaining_tool_calls": None,
            },
            config=config,
        )
        while "__interrupt__" in result:
            result = graph.invoke(Command(resume={"decision": "confirm"}), config=config)

        cassette_model.save()
        print(f"Recorded {task.id} -> {cassette_path} ({cassette_model.recorded_count} AIMessage(s))")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
