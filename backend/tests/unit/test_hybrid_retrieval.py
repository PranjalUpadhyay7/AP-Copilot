from unittest.mock import patch

from app.knowledge.rag_store import (
    DocChunk,
    HybridIndex,
    LexicalIndex,
    build_hybrid_index_from_param_definitions,
    param_doc_url,
)
from app.knowledge.web_research import search_web_docs, verify_against_official
from app.models.params import ParamDefinition


def test_param_doc_url_known_vehicle_type():
    url = param_doc_url("ARMING_SKIPCHK", ["ArduCopter"])
    assert url == "https://ardupilot.org/copter/docs/parameters.html#ARMING_SKIPCHK"


def test_param_doc_url_unknown_vehicle_type_returns_none():
    assert param_doc_url("FOO", ["SomeUnmappedType"]) is None


def test_hybrid_index_falls_back_to_lexical_when_embeddings_unavailable():
    lexical = LexicalIndex([("BATT_LOW_VOLT", "Battery voltage that triggers a low battery failsafe.", None)])
    hybrid = HybridIndex(lexical, embedding=None)
    results = hybrid.search("battery failsafe voltage")
    assert results
    assert results[0].source == "BATT_LOW_VOLT"
    assert results[0].source_type == "official"
    assert results[0].reliability_score == 1.0


def test_build_hybrid_index_degrades_gracefully_without_embeddings():
    defs = {
        "BATT_LOW_VOLT": ParamDefinition(
            name="BATT_LOW_VOLT", vehicle_types=["ArduCopter"], firmware_version="4.6.0",
            description="Battery voltage that triggers a low battery failsafe.",
        )
    }
    index = build_hybrid_index_from_param_definitions(defs, use_embeddings=False)
    results = index.search("battery failsafe")
    assert results and results[0].source == "BATT_LOW_VOLT"
    assert results[0].source_url == "https://ardupilot.org/copter/docs/parameters.html#BATT_LOW_VOLT"


def test_search_web_docs_returns_empty_without_configured_backend(monkeypatch):
    monkeypatch.delenv("AP_COPILOT_WEB_SEARCH_URL", raising=False)
    assert search_web_docs("anything") == []


def test_search_web_docs_request_failure_degrades_to_empty(monkeypatch):
    monkeypatch.setenv("AP_COPILOT_WEB_SEARCH_URL", "https://example.invalid/search")
    with patch("httpx.get", side_effect=RuntimeError("network unavailable")):
        assert search_web_docs("anything") == []


def test_verify_against_official_flags_uncorroborated_web_result():
    official = LexicalIndex([("BATT_LOW_VOLT", "Battery voltage that triggers a low battery failsafe.", None)])
    web_chunk = DocChunk(
        source="some forum post", text="completely unrelated topic about gardening",
        score=1.0, source_type="web", reliability_score=0.35,
    )
    verified = verify_against_official([web_chunk], official)
    assert verified[0].text.startswith("[unverified against official docs]")
    assert verified[0].reliability_score < 0.35


def test_verify_against_official_keeps_corroborated_web_result_unflagged():
    official = LexicalIndex([("BATT_LOW_VOLT", "Battery voltage that triggers a low battery failsafe.", None)])
    web_chunk = DocChunk(
        source="forum", text="Battery voltage failsafe behavior discussion",
        score=1.0, source_type="web", reliability_score=0.35,
    )
    verified = verify_against_official([web_chunk], official)
    assert not verified[0].text.startswith("[unverified")
    assert verified[0].reliability_score == 0.35


class _FakeEmbeddingIndex:
    def __init__(self, ranked_chunks: list[DocChunk]):
        self._ranked_chunks = ranked_chunks

    def search(self, query: str, k: int = 5) -> list[DocChunk]:
        return self._ranked_chunks[:k]


def test_rrf_ranks_a_source_present_in_both_lists_above_one_present_in_only_one():
    lexical = LexicalIndex([
        ("BOTH", "roll angle gain tuning oscillation response parameter value", None),
        ("LEXICAL_ONLY", "roll angle gain tuning response", None),
    ])
    embedding = _FakeEmbeddingIndex([
        DocChunk(source="EMBEDDING_ONLY", text="conceptually similar text", score=0.95, source_type="official"),
        DocChunk(source="BOTH", text="roll angle gain tuning oscillation response parameter value", score=0.80, source_type="official"),
    ])
    hybrid = HybridIndex(lexical, embedding=embedding)

    results = hybrid.search("roll angle gain oscillation", k=3)
    sources = [r.source for r in results]

    assert sources[0] == "BOTH"
    assert set(sources) == {"BOTH", "LEXICAL_ONLY", "EMBEDDING_ONLY"}


def test_official_docs_outrank_higher_relevance_web_docs_via_ranking_score():
    official_chunk = DocChunk(source="BATT_LOW_VOLT", text="official", score=0.4, source_type="official", reliability_score=1.0)
    web_chunk = DocChunk(source="forum", text="web", score=0.9, source_type="web", reliability_score=0.35)
    assert official_chunk.ranking_score > web_chunk.ranking_score


def test_builtin_web_search_is_opt_in_and_parses_ddg_markup(monkeypatch):
    monkeypatch.delenv("AP_COPILOT_WEB_SEARCH_URL", raising=False)
    monkeypatch.delenv("AP_COPILOT_WEB_SEARCH", raising=False)
    assert search_web_docs("x") == []  # off unless AP_COPILOT_WEB_SEARCH=1

    page = (
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fardupilot.org%2Fcopter%2Fdocs%2Fcam.html">t</a>'
        '<a class="result__snippet" href="x">Set <b>CAM1_FEEDBAK_PIN</b> &amp; POL</a>'
    )

    class FakeResp:
        text = page

        def raise_for_status(self):
            pass

    monkeypatch.setenv("AP_COPILOT_WEB_SEARCH", "1")
    monkeypatch.setattr("app.knowledge.web_research.httpx.post", lambda *a, **k: FakeResp())
    [chunk] = search_web_docs("camera strobe")
    assert chunk.source_url == "https://ardupilot.org/copter/docs/cam.html"
    assert chunk.text == "Set CAM1_FEEDBAK_PIN & POL" and chunk.source_type == "web"
