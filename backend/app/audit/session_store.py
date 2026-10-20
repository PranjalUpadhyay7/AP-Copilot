"""Browsable session history."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from sqlmodel import Field, Session, SQLModel, create_engine, select

from app.orchestrator.checkpointer import DEFAULT_CHECKPOINT_DB


class SessionRecord(SQLModel, table=True):
    session_id: str = Field(primary_key=True)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    vehicle_type: str
    firmware_version: str
    read_only: bool = False


class SessionStore:
    """Browsable session history; transcripts come from the LangGraph checkpointer."""
    def __init__(self, db_path: str | Path):
        url = "sqlite://" if str(db_path) == ":memory:" else f"sqlite:///{db_path}"
        engine_kwargs = {"connect_args": {"check_same_thread": False}}
        self._engine = create_engine(url, **engine_kwargs)
        SQLModel.metadata.create_all(self._engine)

    def start(self, session_id: str, vehicle_type: str, firmware_version: str, read_only: bool) -> None:
        with Session(self._engine) as session:
            session.add(SessionRecord(
                session_id=session_id, vehicle_type=vehicle_type,
                firmware_version=firmware_version, read_only=read_only,
            ))
            session.commit()

    def end(self, session_id: str) -> None:
        with Session(self._engine) as session:
            record = session.get(SessionRecord, session_id)
            if record is not None:
                record.ended_at = datetime.now(UTC)
                session.add(record)
                session.commit()

    def end_orphans(self) -> int:
        """Marks every still-"open" session as ended."""
        with Session(self._engine) as session:
            open_sessions = list(session.exec(select(SessionRecord).where(SessionRecord.ended_at == None)))
            for record in open_sessions:
                record.ended_at = datetime.now(UTC)
                session.add(record)
            session.commit()
            return len(open_sessions)

    def list_sessions(self) -> list[SessionRecord]:
        with Session(self._engine) as session:
            statement = select(SessionRecord).order_by(SessionRecord.started_at.desc())
            return list(session.exec(statement))

    def get(self, session_id: str) -> SessionRecord | None:
        with Session(self._engine) as session:
            return session.get(SessionRecord, session_id)


_ROLE_BY_MESSAGE_TYPE = {HumanMessage: "user", AIMessage: "assistant", ToolMessage: "tool"}


def _serialize_message(message) -> dict:
    role = next((r for cls, r in _ROLE_BY_MESSAGE_TYPE.items() if isinstance(message, cls)), "unknown")
    entry = {"role": role, "content": str(message.content)}
    if isinstance(message, ToolMessage):
        entry["tool_name"] = message.name
    return entry


def load_messages(session_id: str, checkpoint_db: str | Path = DEFAULT_CHECKPOINT_DB) -> list:
    """The raw LangChain messages of a session, from the persistent checkpointer."""
    conn = sqlite3.connect(str(checkpoint_db), check_same_thread=False)
    try:
        checkpoint_tuple = SqliteSaver(conn).get_tuple({"configurable": {"thread_id": session_id}})
        if checkpoint_tuple is None:
            return []
        return list(checkpoint_tuple.checkpoint.get("channel_values", {}).get("messages", []))
    finally:
        conn.close()


def get_transcript(session_id: str, checkpoint_db: str | Path = DEFAULT_CHECKPOINT_DB) -> list[dict]:
    conn = sqlite3.connect(str(checkpoint_db), check_same_thread=False)
    try:
        saver = SqliteSaver(conn)
        checkpoint_tuple = saver.get_tuple({"configurable": {"thread_id": session_id}})
        if checkpoint_tuple is None:
            return []
        messages = checkpoint_tuple.checkpoint.get("channel_values", {}).get("messages", [])
        return [_serialize_message(m) for m in messages]
    finally:
        conn.close()
