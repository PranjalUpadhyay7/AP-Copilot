from app.knowledge.rag_store import (
    DocChunk,
    HybridIndex,
    LexicalIndex,
    collapse_families,
    expand_query,
    family_key,
    search_ardupilot_docs,
)


def test_family_key_groups_numbered_and_lettered_instances():
    assert family_key("CAM1_FEEDBAK_PIN") == family_key("CAM2_FEEDBAK_PIN") == "CAM_FEEDBAK_PIN"
    assert family_key("BATT_FS_LOW_ACT") == family_key("BATT2_FS_LOW_ACT") == family_key("BATTC_FS_LOW_ACT")
    assert family_key("RC1_OPTION") == family_key("RC16_OPTION")
    assert family_key("BTN_FUNC1") == family_key("BTN_FUNC4") != family_key("BTN_PIN1")
    assert family_key("RTL_ALT") != family_key("RTL_ALT_FINAL")  # different parameters stay different


def test_collapse_keeps_one_result_per_family_with_the_primary_instance_and_lists_the_rest():
    chunks = [DocChunk(source=s, text="t", score=sc) for s, sc in
              [("BATT3_LOW_MAH", 0.9), ("BATT_LOW_MAH", 0.8), ("BATT2_LOW_MAH", 0.7), ("RTL_ALT", 0.5)]]
    out = collapse_families(chunks)
    assert [c.source for c in out] == ["BATT_LOW_MAH", "RTL_ALT"]  # primary instance represents the family
    assert out[0].score == 0.9 and "BATT2_LOW_MAH" in out[0].text and "BATT3_LOW_MAH" in out[0].text


def test_sim_parameters_are_dropped_unless_the_query_asks_for_simulation():
    index = LexicalIndex([("SIM_BARO_FREEZE", "freeze the baro altitude"), ("RTL_ALT", "return altitude baro")])
    assert [c.source for c in search_ardupilot_docs("baro altitude", index)] == ["RTL_ALT"]
    assert "SIM_BARO_FREEZE" in [c.source for c in search_ardupilot_docs("simulated baro freeze", index)]


def test_aliases_append_ardupilot_vocabulary_without_touching_the_users_words():
    assert expand_query("return to launch altitude").startswith("return to launch altitude")
    assert "RTL" in expand_query("return to launch altitude")
    assert "throttle failsafe FS_THR_ENABLE" in expand_query("what if the radio signal is lost")
    assert "feedback" in expand_query("camera strobe output")
    assert expand_query("what is RTL_ALT") == "what is RTL_ALT"


class _FakeIndex:
    def __init__(self, chunks):
        self._chunks = chunks

    def search(self, query, k=5):
        return self._chunks[:k]


def test_rrf_counts_a_source_once_per_list_even_if_it_has_many_chunks():
    flood = [DocChunk(source="RC1_OPTION", text=f"RC1_OPTION = {i}: RTL", score=0.5) for i in range(30)]
    answer = DocChunk(source="RTL_ALT", text="RTL_ALT: return altitude", score=0.4)
    lexical = _FakeIndex([answer, *flood])  # the real answer is rank 1 of its list
    embedding = _FakeIndex([answer, *flood])
    hybrid = HybridIndex.__new__(HybridIndex)
    hybrid.lexical, hybrid.embedding = lexical, embedding
    ranked = hybrid.search("return altitude", k=2)
    assert [c.source for c in ranked] == ["RTL_ALT", "RC1_OPTION"]
