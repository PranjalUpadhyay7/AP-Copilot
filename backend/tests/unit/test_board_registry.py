from app.knowledge.board_registry import parse_board_types, resolve_board_name
from app.knowledge.rag_store import DocChunk
from app.orchestrator import tools
from app.orchestrator.tools import RuntimeContext

SAMPLE = """# comment
TARGET_HW_PX4_FMU_V2                    9
AP_HW_DURANDAL                        139
AP_HW_CUBEORANGE                      140
AP_HW_CUBEORANGE                      999
not a line
"""


def test_parse_strips_prefix_skips_junk_first_id_wins():
    assert parse_board_types(SAMPLE) == {9: "PX4_FMU_V2", 139: "DURANDAL", 140: "CUBEORANGE", 999: "CUBEORANGE"}


def test_resolve_from_local_checkout(tmp_path):
    reg = tmp_path / "Tools/AP_Bootloader"
    reg.mkdir(parents=True)
    (reg / "board_types.txt").write_text(SAMPLE)
    assert resolve_board_name(140 << 16, str(tmp_path)) == "CUBEORANGE"
    assert resolve_board_name(0, str(tmp_path)) is None  # unknown board id 0


def test_hardware_query_adds_board_scoped_wiki_search(monkeypatch):
    calls = []

    def fake_search(query, index, k=5):
        calls.append(query)
        return [DocChunk(source=f"page:{len(calls)}", text=query, score=0.5, source_type="wiki")]

    monkeypatch.setattr(tools, "search_wiki_docs", fake_search)
    ctx = RuntimeContext(
        session_id="s", vehicle_client=None, live_params={}, audit_logger=None,
        wiki_index=object(), board_name="CUBEORANGE",
    )
    tools._search_ardupilot_docs(ctx, "how do I wire the GPS port")
    assert calls == ["how do I wire the GPS port", "CUBEORANGE how do I wire the GPS port"]
    calls.clear()
    tools._search_ardupilot_docs(ctx, "what does ATC_ANG_RLL_P do")
    assert calls == ["what does ATC_ANG_RLL_P do"]  # not hardware-flavored: no extra search


def _stats_ctx(monkeypatch):
    mk = lambda score, src="s", t="official": [DocChunk(source=src, text="t", score=score, source_type=t)]
    monkeypatch.setattr(tools, "search_ardupilot_docs", lambda q, idx: mk(0.9, "P") if "hit" in q else [])
    monkeypatch.setattr(tools, "search_wiki_docs", lambda q, idx, k=5: mk(0.5, "W", "wiki") if "hit" in q else [])
    monkeypatch.setattr(tools, "search_web_docs", lambda q: mk(0.2, "web", "web"))
    monkeypatch.setattr(tools, "verify_against_official", lambda r, idx: r)
    monkeypatch.setattr(tools, "_official_lexical_index", lambda i: i)
    return RuntimeContext(
        session_id="s", vehicle_client=None, live_params={}, audit_logger=None, rag_index=object(), wiki_index=object(),
    )


def test_retrieval_stats_count_tiers_and_explicit_web_calls(monkeypatch):
    ctx = _stats_ctx(monkeypatch)
    tools._search_ardupilot_docs(ctx, "hit")
    tools._search_ardupilot_docs(ctx, "miss")  # no automatic web fallback any more
    assert ctx.retrieval_stats.tiers["web"].calls == 0
    tools._search_web(ctx, "miss")
    d = ctx.retrieval_stats.as_dict()
    assert d["searches"] == 2 and d["both_local_tiers_hit"] == 1
    assert d["web_fallback_rate"] == 0.5 and d["tiers"]["web"]["calls"] == 1
    assert d["tiers"]["official"]["hit_rate"] == 0.5 and d["tiers"]["wiki"]["calls"] == 2


def test_alternate_queries_are_all_searched_and_merged(monkeypatch):
    ctx = _stats_ctx(monkeypatch)
    results = tools._search_ardupilot_docs(ctx, "camera strobe", ["camera feedback hit", "camera feedback hit", "  "])
    assert [(c.source, c.source_type) for c in results] == [("P", "official"), ("W", "wiki")]  # found only via the alternate
    assert ctx.retrieval_stats.searches == 1  # one tool call, however many variants
    many = [f"alt{i} hit" for i in range(10)]
    ctx2 = _stats_ctx(monkeypatch)
    tools._search_ardupilot_docs(ctx2, "q", many)
    assert ctx2.retrieval_stats.tiers["official"].calls == tools.MAX_QUERY_VARIANTS


def test_search_web_reports_empty_and_is_a_registered_tool(monkeypatch):
    ctx = _stats_ctx(monkeypatch)
    monkeypatch.setattr(tools, "search_web_docs", lambda q: [])
    assert "No web results" in tools._search_web(ctx, "x")
    names = {t.name for t in tools.build_tools(ctx)}
    assert {"search_web", "search_ardupilot_docs"} <= names


def test_strobe_flash_hotshoe_expand_to_camera_feedback_terms():
    assert "camera feedback" in tools._expand_query("camera strobe output to pixhawk")
    assert tools._expand_query("hot shoe signal").startswith("hot shoe signal")
    assert tools._expand_query("what is RTL_ALT") == "what is RTL_ALT"


def test_model_argument_quirks_are_coerced_not_crashed_on():
    assert tools._as_int("10", 5, 1, 50) == 10 and tools._as_int(10.0, 5, 1, 50) == 10
    assert tools._as_int("banana", 5, 1, 50) == 5 and tools._as_int(None, 5, 1, 50) == 5
    assert tools._as_int(999, 5, 1, 50) == 50 and tools._as_int(-3, 5, 1, 50) == 1
    assert tools._as_str_list(["a", " ", 3]) == ["a", "3"] and tools._as_str_list("camera feedback") == ["camera feedback"]
    assert tools._as_str_list('["x", "y"]') == ["x", "y"] and tools._as_str_list("[broken") == ["[broken"]
    assert tools._as_str_list(None) == [] and tools._as_str_list({"k": 1}) == []

    from types import SimpleNamespace

    seen = {}
    client = SimpleNamespace(recent_status_messages=lambda n: seen.setdefault("n", n) and [{"text": "PreArm: x"}])
    ctx = RuntimeContext(session_id="s", vehicle_client=client, live_params={}, audit_logger=None)
    # through the real StructuredTool, exactly as a model's call arrives
    tool = next(t for t in tools.build_tools(ctx) if t.name == "get_recent_status_messages")
    assert tool.invoke({"count": "7"}) == [{"text": "PreArm: x"}] and seen["n"] == 7
    # a bare string where a list is expected must not be searched one character at a time
    ctx2 = _stats_ctx_for_alternates()
    assert len(tools._search_ardupilot_docs(ctx2, "q", "camera feedback")) >= 0
    assert ctx2.retrieval_stats.tiers["official"].calls == 2  # the query + ONE alternate, not 15 letters


def _stats_ctx_for_alternates():
    from app.knowledge.rag_store import LexicalIndex

    return RuntimeContext(
        session_id="s", vehicle_client=None, live_params={}, audit_logger=None,
        rag_index=LexicalIndex([("RTL_ALT", "return altitude"), ("CAM1_FEEDBAK_PIN", "camera feedback pin")]),
    )
