import gzip
import json
from pathlib import Path

import pytest

from app.knowledge.rag_store import (
    build_index_from_param_definitions,
    family_key,
    search_ardupilot_docs,
)
from app.models.params import ParamDefinition
from eval.retrieval_eval import CASES, K

FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "data" / "arducopter_4.6.3_92b0cd78_params.json.gz"

# Real live failures that must stay fixed even without embeddings.
MUST_PASS = {
    "strobe output of a camera feedback to pixhawk so mavlink shows it",
    "camera hotshoe flash feedback polarity",
    "polarity of the camera trigger signal high or low",
    "hardware triggered camera relay output",
    "kill switch",
}
LEXICAL_FLOOR = 21


@pytest.fixture(scope="module")
def index():
    raw = json.loads(gzip.decompress(FIXTURE.read_bytes()))
    return build_index_from_param_definitions({n: ParamDefinition.model_validate(d) for n, d in raw.items()})


def _rank(index, query, expected):
    ranked = [c.source for c in search_ardupilot_docs(query, index, k=K)]
    wanted = {family_key(e) for e in expected}  # results are one per family (SERIAL0_BAUD stands for SERIAL1_BAUD)
    return next((i + 1 for i, s in enumerate(ranked) if family_key(s) in wanted), None)


def test_real_failure_cases_are_found(index):
    misses = [q for q, exp, _ in CASES if q in MUST_PASS and _rank(index, q, exp) is None]
    assert not misses, f"regressed: {misses}"


def test_lexical_hit_rate_does_not_regress(index):
    hits = sum(_rank(index, q, exp) is not None for q, exp, _ in CASES)
    assert hits >= LEXICAL_FLOOR, f"hit@{K} {hits}/{len(CASES)} < floor {LEXICAL_FLOOR}"
