"""Knowledge/RAG Layer."""
from __future__ import annotations

import logging
import math
import re
import uuid
from typing import Literal

from pydantic import BaseModel

from app.models.params import ParamDefinition

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-z0-9]+")

VEHICLE_DOC_SLUG = {
    "ArduCopter": "copter",
    "ArduPlane": "plane",
    "Rover": "rover",
    "ArduSub": "sub",
    "AntennaTracker": "antennatracker",
    "Blimp": "blimp",
}

_INSTANCE_TOKEN_RE = re.compile(r"^([a-z]+)\d+$")


def _stem(tok: str) -> str:
    if not tok.isalpha() or len(tok) < 5:
        return tok
    if tok.endswith("ies"):
        return tok[:-3] + "y"
    if tok.endswith("ly"):
        return tok[:-2]
    if tok.endswith(("sses", "xes")):
        return tok[:-2]
    if tok.endswith("s") and not tok.endswith(("ss", "us", "is")):
        return tok[:-1]
    return tok


_QUERY_STOPWORDS = frozenset(
    ["a", "an", "the", "of", "to", "in", "on", "at", "for", "from", "by", "with", "as", "is", "are", "was", "were", "be", "been", "do", "does", "did", "can", "could", "should", "would", "will", "i", "me", "my", "we", "you", "your", "it", "its", "this", "that", "these", "those", "which", "what", "when", "where", "how", "why", "who", "and", "or", "if", "then", "than", "so", "use", "used", "using", "get", "set", "make", "want", "need", "please"]
)


def _tokenize(text: str, *, query: bool = False) -> list[str]:
    tokens: list[str] = []
    for tok in _WORD_RE.findall(text.lower()):
        if query and tok in _QUERY_STOPWORDS:
            continue
        tok = _stem(tok)
        tokens.append(tok)
        m = _INSTANCE_TOKEN_RE.match(tok)
        if m:
            tokens.append(m.group(1))
    return tokens


_QUERY_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), extra)
    for pattern, extra in (
        (r"\b(strobe|flash|hot[- ]?shoe)\b", "camera feedback hotshoe pin feedbak"),
        (r"\bcamera\b", "CAM"),
        (r"\b(climb(s|ing)?|ascen[dt]\w*|rise|rising)\b", "ascending vertical velocity speed up"),
        (r"\bdescen[dt]\w*|\bsink(ing)?\b", "descent vertical velocity speed down"),
        (r"\b(return(ing)?[- ]to[- ]launch|return(ing)? home|go(ing)? home)\b", "RTL"),
        (r"\b(radio|transmitter|remote control|rc (signal|link))\b", "RC"),
        # In ArduCopter "radio/RC signal lost" is the throttle failsafe.
        (r"\b(radio|transmitter|rc)\b[^.]{0,30}\b(lost|loss|lose|drop\w*|fail\w*)\b|\b(lost|loss of)\b[^.]{0,20}\b(radio|transmitter|rc|signal)\b",
         "throttle failsafe FS_THR_ENABLE"),
        (r"\bfail[- ]?safes?\b", "FS"),
        (r"\bbatter(y|ies)\b", "BATT"),
        (r"\bgeo[- ]?fence\b", "FENCE"),
        # "which messages/data are logged" -> ArduPilot's "bitmap of on-board log types to enable"
        (r"\b(messages?|data|dataflash)\b[^.]{0,25}\blog(s|ged|ging)?\b|\blog(s|ged|ging)?\b[^.]{0,25}\b(messages?|data)\b",
         "bitmap log types enable"),
        (r"\bpre[- ]?arm\b", "ARMING"),
        (r"\b(kill switch|emergency stop|motor stop)\b", "Motor Emergency Stop RC OPTION"),
    )
)


def expand_query(query: str) -> str:
    extra = [expansion for pattern, expansion in _QUERY_ALIASES if pattern.search(query)]
    return " ".join([query, *extra])


_FAMILY_NUMBER_RE = re.compile(r"\d+")


def family_key(name: str) -> str:
    first, sep, rest = name.partition("_")
    first = re.sub(r"^(BATT)[A-G]$", r"\1", first)
    first = _FAMILY_NUMBER_RE.sub("", first)
    return first + sep + _FAMILY_NUMBER_RE.sub("#", rest)


def _instance_rank(name: str) -> tuple[int, int, str]:
    first = name.partition("_")[0]
    m = _FAMILY_NUMBER_RE.search(first)
    if m:
        return (1, int(m.group()), name)
    if re.fullmatch(r"BATT[A-G]", first):
        return (2, 0, name)
    return (0, 0, name)


def collapse_families(chunks: list[DocChunk]) -> list[DocChunk]:
    """Keep one result per numbered parameter family (CAM1_, CAM2_, ...)."""
    groups: dict[str, list[DocChunk]] = {}
    for chunk in chunks:
        groups.setdefault(family_key(chunk.source), []).append(chunk)
    collapsed: list[DocChunk] = []
    for members in groups.values():
        best = max(members, key=lambda c: c.ranking_score)
        names = sorted({c.source for c in members}, key=_instance_rank)
        primary = next(c for c in members if c.source == names[0]) if len(names) > 1 else best
        rep = primary.model_copy(update={"score": best.score})
        if len(names) > 1:
            rep = rep.model_copy(update={"text": f"{rep.text} | Same parameter for other instances: {', '.join(names[1:4])}"})
        collapsed.append(rep)
    return sorted(collapsed, key=lambda c: c.ranking_score, reverse=True)


def param_doc_url(name: str, vehicle_types: list[str]) -> str | None:
    for vt in vehicle_types:
        slug = VEHICLE_DOC_SLUG.get(vt)
        if slug:
            return f"https://ardupilot.org/{slug}/docs/parameters.html#{name}"
    return None


class DocChunk(BaseModel):
    source: str  # the parameter name (or web result title) this text came from
    text: str
    score: float
    source_type: Literal["official", "wiki", "web"] = "official"
    reliability_score: float = 1.0
    source_url: str | None = None

    @property
    def ranking_score(self) -> float:
        return self.score * self.reliability_score


_BM25_K1 = 1.5
_BM25_B = 0.75


class LexicalIndex:
    """BM25 keyword index over parameter documentation."""
    def __init__(self, documents: list[tuple[str, str] | tuple[str, str, str | None]]):
        normalized = [(d[0], d[1], d[2] if len(d) > 2 else None) for d in documents]
        self._docs = [
            (source, text, url, _tokenize(text)) for source, text, url in normalized
        ]
        self._doc_freq: dict[str, int] = {}
        for _, _, _, tokens in self._docs:
            for term in set(tokens):
                self._doc_freq[term] = self._doc_freq.get(term, 0) + 1
        self._avg_doc_len = (
            sum(len(tokens) for _, _, _, tokens in self._docs) / len(self._docs)
            if self._docs else 0.0
        )
        self._n_docs = len(self._docs)

    def _idf(self, term: str) -> float:
        n_qi = self._doc_freq.get(term, 0)
        if n_qi == 0:
            return 0.0
        return math.log((self._n_docs - n_qi + 0.5) / (n_qi + 0.5) + 1)

    def _bm25_score(self, query_terms: list[str], tokens: list[str]) -> float:
        if not tokens:
            return 0.0
        doc_len = len(tokens)
        term_counts: dict[str, int] = {}
        for t in tokens:
            term_counts[t] = term_counts.get(t, 0) + 1

        score = 0.0
        for term in query_terms:
            freq = term_counts.get(term, 0)
            if freq == 0:
                continue
            idf = self._idf(term)
            numerator = freq * (_BM25_K1 + 1)
            denominator = freq + _BM25_K1 * (1 - _BM25_B + _BM25_B * doc_len / self._avg_doc_len)
            score += idf * (numerator / denominator)
        return score

    def search(self, query: str, k: int = 5) -> list[DocChunk]:
        query_terms = _tokenize(query, query=True)
        if not query_terms:
            return []

        scored: list[DocChunk] = []
        for source, text, url, tokens in self._docs:
            raw_score = self._bm25_score(query_terms, tokens)
            if raw_score <= 0:
                continue
            score = raw_score / (raw_score + 1.0)
            scored.append(DocChunk(source=source, text=text, score=score, source_url=url))

        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[:k]


_EMBEDDING_ADD_BATCH_SIZE = 2000


def _add_documents_in_batches(collection, documents: list[tuple[str, str, str | None]]) -> None:
    for start in range(0, len(documents), _EMBEDDING_ADD_BATCH_SIZE):
        chunk = documents[start:start + _EMBEDDING_ADD_BATCH_SIZE]
        collection.add(
            ids=[str(start + i) for i in range(len(chunk))],
            documents=[text for _, text, _ in chunk],
            metadatas=[{"source": source, "url": url or ""} for source, text, url in chunk],
        )


class EmbeddingIndex:
    """Optional chromadb-backed semantic index over the same official corpus."""

    def __init__(
        self,
        documents: list[tuple[str, str, str | None]],
        *,
        persist_path: str | None = None,
        collection_name: str | None = None,
    ):
        self.available = False
        self._collection = None
        if not documents:
            return
        try:
            import chromadb

            if persist_path:
                client = chromadb.PersistentClient(path=persist_path)
                name = collection_name or "ap-copilot"
                self._collection = client.get_or_create_collection(name=name)
                if self._collection.count() == 0:
                    _add_documents_in_batches(self._collection, documents)
            else:
                client = chromadb.EphemeralClient()
                self._collection = client.create_collection(name=f"ap-copilot-{uuid.uuid4().hex}")
                _add_documents_in_batches(self._collection, documents)
            self.available = True
        except Exception as e:  # noqa: BLE001
            logger.warning("embeddings index unavailable, hybrid retrieval will be lexical-only: %s", e)

    def search(self, query: str, k: int = 5) -> list[DocChunk]:
        if not self.available:
            return []
        try:
            results = self._collection.query(query_texts=[query], n_results=k)
        except Exception as e:  # noqa: BLE001
            logger.warning("embeddings query failed, degrading to lexical-only for this query: %s", e)
            return []

        docs = (results.get("documents") or [[]])[0]
        metas = (results.get("metadatas") or [[]])[0]
        distances = (results.get("distances") or [[]])[0]
        chunks = []
        for text, meta, dist in zip(docs, metas, distances):
            score = max(0.0, 1.0 - dist)  # cosine distance -> similarity in [0, 1]
            chunks.append(DocChunk(
                source=meta.get("source", "?"), text=text, score=score,
                source_url=meta.get("url") or None,
            ))
        return chunks


_RRF_K = 60  # standard default (Cormack et al. 2009's own choice, widely reused as-is)


class HybridIndex:
    """Lexical and embedding results merged with reciprocal rank fusion."""
    def __init__(self, lexical: LexicalIndex, embedding: EmbeddingIndex | None = None):
        self.lexical = lexical
        self.embedding = embedding

    def search(self, query: str, k: int = 5) -> list[DocChunk]:
        pool_size = max(k * 4, 20, k)
        lexical_results = self.lexical.search(query, k=pool_size)
        embedding_results = self.embedding.search(query, k=pool_size) if self.embedding is not None else []

        rrf_scores: dict[str, float] = {}
        chunks_by_source: dict[str, DocChunk] = {}
        for results in (lexical_results, embedding_results):
            # A source earns rank credit once per list, at its best rank
            seen: set[str] = set()
            rank = 0
            for chunk in results:
                if chunk.source in seen:
                    continue
                seen.add(chunk.source)
                rank += 1
                weight = _PER_VALUE_WEIGHT if chunk.text.startswith(f"{chunk.source} = ") else 1.0
                rrf_scores[chunk.source] = rrf_scores.get(chunk.source, 0.0) + weight / (_RRF_K + rank)
                chunks_by_source.setdefault(chunk.source, chunk)

        fused = [
            chunks_by_source[source].model_copy(update={"score": rrf_score})
            for source, rrf_score in rrf_scores.items()
        ]
        ranked = sorted(fused, key=lambda c: c.ranking_score, reverse=True)
        return ranked[:k]


def _document_text(name: str, d: ParamDefinition) -> str:
    parts = [f"{name}: {d.description}"]
    if d.unit:
        parts.append(f"Unit: {d.unit}")
    if d.min_value is not None or d.max_value is not None:
        parts.append(f"Valid range: {d.min_value} to {d.max_value}")
    if d.increment is not None:
        parts.append(f"Increment: {d.increment}")
    if d.values:
        parts.append("Values: " + ", ".join(f"{k}={v}" for k, v in d.values.items()))
    if d.bitmask:
        parts.append("Bitmask bits: " + ", ".join(f"bit {k}={v}" for k, v in d.bitmask.items()))
    if d.reboot_required:
        parts.append("Requires a reboot to take effect.")
    return " | ".join(parts)


_MIN_VALUES_FOR_PER_VALUE_CHUNKS = 20
_PER_VALUE_WEIGHT = 0.5  # fusion credit of a per-value enum chunk relative to a full description


def _per_value_documents(name: str, d: ParamDefinition) -> list[tuple[str, str]]:
    if not d.values or len(d.values) < _MIN_VALUES_FOR_PER_VALUE_CHUNKS:
        return []
    return [(name, f"{name} = {key}: {label}") for key, label in d.values.items()]


def _documents_from_definitions(definitions: dict[str, ParamDefinition]) -> list[tuple[str, str, str | None]]:
    documents = [
        (name, _document_text(name, d), param_doc_url(name, d.vehicle_types))
        for name, d in definitions.items()
        if d.description
    ]
    for name, d in definitions.items():
        url = param_doc_url(name, d.vehicle_types)
        documents.extend((src, text, url) for src, text in _per_value_documents(name, d))
    return documents


def build_index_from_param_definitions(definitions: dict[str, ParamDefinition]) -> LexicalIndex:
    return LexicalIndex(_documents_from_definitions(definitions))


def build_hybrid_index_from_param_definitions(
    definitions: dict[str, ParamDefinition],
    *,
    use_embeddings: bool = True,
    vehicle_type: str | None = None,
    version_key: str | None = None,
    cache_root: str | None = None,
) -> HybridIndex:
    """Build (or load from cache) the search index for one firmware's parameters."""
    documents = _documents_from_definitions(definitions)
    lexical = LexicalIndex(documents)

    embedding = None
    if use_embeddings:
        persist_path = None
        collection_name = None
        if vehicle_type and version_key:
            import os
            from pathlib import Path

            root = Path(cache_root) if cache_root else (
                Path(os.environ.get("AP_COPILOT_HOME", Path.home() / ".ap-copilot")) / "rag_index_cache"
            )
            persist_path = str(root)
            collection_name = f"{vehicle_type}_{version_key}".replace("/", "_")
        embedding = EmbeddingIndex(documents, persist_path=persist_path, collection_name=collection_name)

    return HybridIndex(lexical, embedding)


def search_ardupilot_docs(query: str, index: LexicalIndex | HybridIndex, k: int = 5) -> list[DocChunk]:
    # Search wide, then collapse families so one cannot fill the results
    pool = index.search(expand_query(query), k=max(k * 8, 40))
    if "sim" not in query.lower():
        pool = [c for c in pool if not c.source.startswith("SIM_")]
    return collapse_families(pool)[:k]
