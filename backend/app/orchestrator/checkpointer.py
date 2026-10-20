"""Persistent checkpointer config."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

DEFAULT_CHECKPOINT_DB = Path(os.environ.get("AP_COPILOT_HOME", Path.home() / ".ap-copilot")) / "graph_checkpoints.sqlite3"


def open_checkpointer(db_path: str | Path = DEFAULT_CHECKPOINT_DB) -> tuple[SqliteSaver, sqlite3.Connection]:
    """Open a SQLite-backed LangGraph checkpointer for long-lived use."""
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    return SqliteSaver(conn), conn


@contextmanager
def get_checkpointer(db_path: str | Path = DEFAULT_CHECKPOINT_DB):
    saver, conn = open_checkpointer(db_path)
    try:
        yield saver
    finally:
        conn.close()
