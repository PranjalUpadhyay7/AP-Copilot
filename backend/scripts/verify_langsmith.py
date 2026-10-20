#!/usr/bin/env python3
"""Check that LangSmith tracing works end to end."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import os

from app.orchestrator.tracing import PROJECT_DEV, configure_tracing, trace_metadata


def _project() -> str:
    return os.environ.get("LANGCHAIN_PROJECT", PROJECT_DEV)


def _client():
    from langsmith import Client

    return Client()


def probe() -> int:
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda

    if not configure_tracing(_project()):
        print("Tracing is OFF: set LANGCHAIN_TRACING_V2=true in backend/.env", file=sys.stderr)
        return 1
    tool = RunnableLambda(lambda x: {"echo": x}, name="probe_tool")
    model = GenericFakeChatModel(messages=iter([AIMessage(content="probe reply")]))
    meta = {**trace_metadata("ProbeVehicle", "0.0.0"), "probe": True}
    tool.invoke("ping", config={"metadata": meta})
    model.invoke("hello", config={"metadata": meta, "run_name": "probe_llm"})

    from langchain_core.tracers.langchain import wait_for_all_tracers

    wait_for_all_tracers()
    client = _client()
    for _ in range(10):  # ingestion is async
        runs = list(client.list_runs(project_name=_project(), filter='eq(metadata_key, "probe")', limit=10))
        names = {r.name for r in runs}
        if {"probe_tool", "probe_llm"} <= names:
            print(f"OK: probe runs arrived in project '{_project()}':", sorted(names))
            print("metadata on a run:", {k: v for k, v in (runs[0].extra or {}).get("metadata", {}).items() if k in meta})
            return 0
        time.sleep(3)
    print("Probe runs did not appear in LangSmith within 30s -- check key/project/network.", file=sys.stderr)
    return 1


def inspect() -> int:
    client = _client()
    roots = list(client.list_runs(project_name=_project(), is_root=True, limit=1))
    if not roots:
        print(f"No runs in project '{_project()}' yet -- send one chat turn first.", file=sys.stderr)
        return 1
    root = roots[0]
    print(f"latest root run: {root.name}  id={root.id}  status={root.status}")
    print(f"  total tokens: {root.total_tokens}  prompt: {root.prompt_tokens}  completion: {root.completion_tokens}")
    print(f"  metadata: {(root.extra or {}).get('metadata', {})}")
    children = list(client.list_runs(project_name=_project(), trace_id=root.trace_id))
    by_type: dict[str, int] = {}
    for r in children:
        by_type[r.run_type] = by_type.get(r.run_type, 0) + 1
    print("  runs by type:", by_type)
    for r in sorted(children, key=lambda r: r.start_time):
        if r.run_type == "tool":
            print(f"  tool: {r.name}  inputs={str(r.inputs)[:100]}  outputs={str(r.outputs)[:100]}")
        elif r.run_type == "llm":
            print(f"  llm: {r.name}  tokens={r.total_tokens}")
    return 0


if __name__ == "__main__":
    raise SystemExit(inspect() if "--inspect" in sys.argv else probe())
