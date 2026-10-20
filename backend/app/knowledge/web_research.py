"""Secondary, advisory-only web research memory."""
from __future__ import annotations

import html
import logging
import os
import re
import urllib.parse

import httpx

from app.knowledge.rag_store import DocChunk, LexicalIndex

logger = logging.getLogger(__name__)

DEFAULT_WEB_RELIABILITY = 0.35
UNVERIFIED_WEB_RELIABILITY = 0.15


_DDG_URL = "https://html.duckduckgo.com/html/"
_DDG_LINK_RE = re.compile(r'class="result__a"[^>]*href="([^"]+)"')
_DDG_SNIPPET_RE = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _ddg_query(q: str, timeout: float) -> list[DocChunk]:
    try:
        resp = httpx.post(
            _DDG_URL, data={"q": q},
            headers={"User-Agent": "Mozilla/5.0 (ap-copilot)"}, timeout=timeout, follow_redirects=True,
        )
        resp.raise_for_status()
    except Exception as e:  # noqa: BLE001
        logger.warning("built-in web search failed, degrading to no web results: %s", e)
        return []
    chunks = []
    for link, snippet in zip(_DDG_LINK_RE.findall(resp.text), _DDG_SNIPPET_RE.findall(resp.text), strict=False):
        if "uddg=" in link:  # DDG redirect wrapper -> real target
            link = urllib.parse.unquote(urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get("uddg", [link])[0])
        text = html.unescape(_TAG_RE.sub("", snippet)).strip()
        if text:
            chunks.append(DocChunk(
                source=link.rsplit("/", 1)[-1] or link, text=text, score=1.0, source_type="web",
                reliability_score=DEFAULT_WEB_RELIABILITY, source_url=link,
            ))
    return chunks


def _duckduckgo_search(query: str, k: int, timeout: float) -> list[DocChunk]:
    chunks = _ddg_query(f"ardupilot {query} site:ardupilot.org", timeout)
    if not chunks:
        chunks = [c for c in _ddg_query(f"ardupilot {query}", timeout) if "ardupilot" in (c.source_url or "").lower()]
    return chunks[:k]


def search_web_docs(query: str, k: int = 3, *, timeout: float = 8.0) -> list[DocChunk]:
    """Advisory ardupilot.org search; returns nothing unless enabled."""
    url = os.environ.get("AP_COPILOT_WEB_SEARCH_URL")
    if not url and os.environ.get("AP_COPILOT_WEB_SEARCH") == "1":
        return _duckduckgo_search(query, k, timeout)
    if not url:
        logger.info(
            "no web search backend configured (AP_COPILOT_WEB_SEARCH_URL unset); "
            "web research memory returns nothing for %r", query,
        )
        return []

    headers = {}
    key = os.environ.get("AP_COPILOT_WEB_SEARCH_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"

    try:
        resp = httpx.get(url, params={"q": query, "k": k}, headers=headers, timeout=timeout)
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except Exception as e:  # noqa: BLE001
        logger.warning("web search request failed, degrading to no web results: %s", e)
        return []

    return [
        DocChunk(
            source=r.get("title") or r.get("url") or "web result",
            text=r["snippet"],
            score=1.0,
            source_type="web",
            reliability_score=DEFAULT_WEB_RELIABILITY,
            source_url=r.get("url"),
        )
        for r in results[:k]
        if r.get("snippet")
    ]


def verify_against_official(web_chunks: list[DocChunk], official_index: LexicalIndex) -> list[DocChunk]:
    verified: list[DocChunk] = []
    for chunk in web_chunks:
        official_hits = official_index.search(chunk.text, k=1)
        if official_hits:
            verified.append(chunk)
        else:
            verified.append(chunk.model_copy(update={
                "text": f"[unverified against official docs] {chunk.text}",
                "reliability_score": min(chunk.reliability_score, UNVERIFIED_WEB_RELIABILITY),
            }))
    return verified
