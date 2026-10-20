from app.knowledge.rag_store import (
    LexicalIndex,
    build_index_from_param_definitions,
    search_ardupilot_docs,
)
from app.models.params import ParamDefinition


def _fixture_index() -> LexicalIndex:
    documents = [
        ("QUIK_OSC_SMAX", "Threshold for oscillation detection. A lower value will lead to a more conservative tune."),
        ("ATC_RAT_RLL_SMAX", "Sets an upper limit on the slew rate produced by the combined P and D gains. If the amplitude of the control output is oscillating."),
        ("COMPASS_CAL_FIT", "This controls the fitness level required for a successful compass calibration. A lower value makes for a stricter fit."),
        ("COMPASS_AUTO_ROT", "When enabled this will automatically check the orientation of compasses on successful compass calibration."),
        ("BATT_LOW_VOLT", "Battery voltage that triggers a low battery failsafe. Set to 0 to disable. If the battery voltage drops below this voltage continuously for more then the period specified by the BATT_LOW_TIMER parameter then the vehicle will perform the failsafe specified by the BATT_FS_LOW_ACT parameter."),
        ("SCHED_LOOP_RATE", "Controls the speed of the main control loop in Hz."),
    ]
    return LexicalIndex(documents)


def test_loiter_oscillation_query_returns_relevant_chunks():
    index = _fixture_index()
    results = search_ardupilot_docs("loiter oscillation", index)
    sources = [r.source for r in results]
    assert "QUIK_OSC_SMAX" in sources or "ATC_RAT_RLL_SMAX" in sources
    assert "SCHED_LOOP_RATE" not in sources


def test_compass_calibration_steps_query_returns_relevant_chunks():
    index = _fixture_index()
    results = search_ardupilot_docs("compass calibration steps", index)
    sources = {r.source for r in results}
    assert "COMPASS_CAL_FIT" in sources or "COMPASS_AUTO_ROT" in sources


def test_battery_failsafe_voltage_query_returns_relevant_chunk():
    index = _fixture_index()
    results = search_ardupilot_docs("battery failsafe voltage", index)
    assert results
    assert results[0].source == "BATT_LOW_VOLT"


def test_no_match_returns_empty():
    index = _fixture_index()
    results = search_ardupilot_docs("xyzzy nonsense query", index)
    assert results == []


def test_results_ranked_by_score_descending():
    index = _fixture_index()
    results = search_ardupilot_docs("battery failsafe voltage", index)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_build_index_from_param_definitions_skips_empty_descriptions():
    definitions = {
        "A": ParamDefinition(name="A", vehicle_types=["ArduCopter"], firmware_version="4.6.0", description="battery failsafe voltage threshold"),
        "B": ParamDefinition(name="B", vehicle_types=["ArduCopter"], firmware_version="4.6.0", description=""),
    }
    index = build_index_from_param_definitions(definitions)
    results = search_ardupilot_docs("battery voltage", index)
    assert [r.source for r in results] == ["A"]


def test_indexed_text_includes_bitmask_bit_definitions_not_just_description():
    definitions = {
        "ARMING_SKIPCHK": ParamDefinition(
            name="ARMING_SKIPCHK", vehicle_types=["ArduCopter"], firmware_version="4.6.0",
            description="Bitmask of arming checks to skip",
            bitmask={0: "All", 1: "Barometer", 2: "Compass"},
        ),
    }
    index = build_index_from_param_definitions(definitions)
    results = search_ardupilot_docs("ARMING_SKIPCHK bit meanings", index)
    assert results
    assert "bit 0=All" in results[0].text


def test_bm25_ranks_rare_specific_term_match_above_common_term_overlap():
    documents = [
        # Shares the query's one rare, specific term.
        ("SPECIFIC_MATCH", "the ARMING_SKIPCHK parameter value threshold"),
        ("COMMON_ONLY", "value threshold value threshold"),
        ("filler1", "some unrelated value threshold text"),
        ("filler2", "another unrelated value threshold entry"),
        ("filler3", "yet another value threshold description"),
    ]
    index = LexicalIndex(documents)
    results = index.search("ARMING_SKIPCHK value threshold", k=5)
    sources = [r.source for r in results]
    assert sources[0] == "SPECIFIC_MATCH"


def test_bm25_scores_are_bounded_in_zero_one_for_downstream_thresholds():
    documents = [(f"P{i}", "roll angle gain tuning parameter oscillation damping response") for i in range(20)]
    index = LexicalIndex(documents)
    results = index.search("roll angle gain oscillation damping", k=20)
    assert results
    assert all(0.0 < r.score < 1.0 for r in results)


def test_indexed_text_includes_numeric_range_not_just_description():
    definitions = {
        "SCHED_LOOP_RATE": ParamDefinition(
            name="SCHED_LOOP_RATE", vehicle_types=["ArduCopter"], firmware_version="4.6.0",
            description="Main loop rate", min_value=50.0, max_value=1000.0,
        ),
    }
    index = build_index_from_param_definitions(definitions)
    results = search_ardupilot_docs("SCHED_LOOP_RATE minimum value range", index)
    assert results
    assert "50.0" in results[0].text and "1000.0" in results[0].text


def _rcx_option_like_definition(target_key: str = "31", target_label: str = "Motor Emergency Stop") -> ParamDefinition:
    values = {str(i): f"Filler Function {i}" for i in range(40) if str(i) != target_key}
    values[target_key] = target_label
    return ParamDefinition(
        name="RC7_OPTION", vehicle_types=["ArduCopter"], firmware_version="4.6.0",
        description="Function assigned to this RC channel", values=values,
    )


def test_heavily_overloaded_enum_value_is_diluted_in_the_main_document_alone():
    from app.knowledge.rag_store import LexicalIndex, _document_text

    d = _rcx_option_like_definition()
    packed_text = _document_text("RC7_OPTION", d)
    competitor = ("BATT_FS_LOW_ACT", "Battery failsafe action taken in an emergency low-voltage condition.")
    diluted_index = LexicalIndex([("RC7_OPTION", packed_text, None), competitor])
    diluted_results = search_ardupilot_docs("emergency stop", diluted_index)
    diluted_rc_score = next(r.score for r in diluted_results if r.source == "RC7_OPTION")

    focused_index = LexicalIndex([("RC7_OPTION", "RC7_OPTION = 31: Motor Emergency Stop", None), competitor])
    focused_results = search_ardupilot_docs("emergency stop", focused_index)
    focused_rc_score = next(r.score for r in focused_results if r.source == "RC7_OPTION")

    assert focused_rc_score > diluted_rc_score


def test_per_value_chunks_are_generated_only_past_the_real_size_threshold():
    from app.knowledge.rag_store import _per_value_documents

    small = ParamDefinition(
        name="GPS_TYPE", vehicle_types=["ArduCopter"], firmware_version="4.6.0",
        description="GPS type", values={"0": "None", "1": "AUTO"},
    )
    assert _per_value_documents("GPS_TYPE", small) == []

    big = _rcx_option_like_definition()
    chunks = _per_value_documents("RC7_OPTION", big)
    assert len(chunks) == len(big.values)
    assert ("RC7_OPTION", "RC7_OPTION = 31: Motor Emergency Stop") in chunks


def test_emergency_stop_query_now_ranks_the_overloaded_option_param_first():
    definitions = {
        "RC7_OPTION": _rcx_option_like_definition(),
        "BATT_FS_LOW_ACT": ParamDefinition(
            name="BATT_FS_LOW_ACT", vehicle_types=["ArduCopter"], firmware_version="4.6.0",
            description="Battery failsafe action taken in an emergency low-voltage condition.",
        ),
    }
    index = build_index_from_param_definitions(definitions)
    results = search_ardupilot_docs("emergency stop", index)
    assert results
    assert results[0].source == "RC7_OPTION"
