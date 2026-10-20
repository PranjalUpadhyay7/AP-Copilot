import sqlite3

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver

from app.audit.session_store import SessionStore, get_transcript


def test_start_and_list(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite3")
    store.start("s1", "ArduCopter", "4.6.0", read_only=False)
    store.start("s2", "ArduPlane", "4.6.0", read_only=True)

    sessions = store.list_sessions()
    assert {s.session_id for s in sessions} == {"s1", "s2"}
    assert all(s.ended_at is None for s in sessions)


def test_end_sets_ended_at(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite3")
    store.start("s1", "ArduCopter", "4.6.0", read_only=False)
    assert store.get("s1").ended_at is None

    store.end("s1")
    assert store.get("s1").ended_at is not None


def test_end_unknown_session_is_a_noop(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite3")
    store.end("does-not-exist")  # must not raise


def test_list_sessions_newest_first(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite3")
    store.start("older", "ArduCopter", "4.6.0", read_only=False)
    store.start("newer", "ArduCopter", "4.6.0", read_only=False)
    sessions = store.list_sessions()
    assert sessions[0].session_id == "newer"


def test_get_transcript_reads_from_persistent_checkpointer(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    config = {"configurable": {"thread_id": "s1", "checkpoint_ns": ""}}
    checkpoint = {
        "v": 1, "id": "c1", "ts": "2024-01-01T00:00:00Z",
        "channel_values": {"messages": [
            HumanMessage(content="set BATT_LOW_VOLT to 10.5"),
            AIMessage(content="Let me check that parameter first."),
            ToolMessage(content="found it", name="get_current_param", tool_call_id="tc1"),
        ]},
        "channel_versions": {}, "versions_seen": {},
    }
    saver.put(config, checkpoint, {"source": "input", "step": 1, "writes": {}}, {})
    conn.close()

    transcript = get_transcript("s1", checkpoint_db=db_path)
    assert [m["role"] for m in transcript] == ["user", "assistant", "tool"]
    assert transcript[0]["content"] == "set BATT_LOW_VOLT to 10.5"
    assert transcript[2]["tool_name"] == "get_current_param"


def test_get_transcript_unknown_session_returns_empty(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    SqliteSaver(conn).setup()
    conn.close()

    assert get_transcript("no-such-session", checkpoint_db=db_path) == []
