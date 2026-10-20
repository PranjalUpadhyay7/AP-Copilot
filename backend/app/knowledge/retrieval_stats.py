"""Per-session retrieval counters for each knowledge tier."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TierStats:
    """Calls, hits, latency and best score for one tier."""
    calls: int = 0
    hits: int = 0  # calls that returned at least one chunk
    total_latency_s: float = 0.0
    total_best_score: float = 0.0  # sum of each hit-call's best ranking_score

    def record(self, latency_s: float, best_score: float | None) -> None:
        self.calls += 1
        self.total_latency_s += latency_s
        if best_score is not None:
            self.hits += 1
            self.total_best_score += best_score

    def as_dict(self) -> dict[str, float | int]:
        return {
            "calls": self.calls,
            "hit_rate": self.hits / self.calls if self.calls else 0.0,
            "avg_latency_ms": 1000 * self.total_latency_s / self.calls if self.calls else 0.0,
            "avg_best_score": self.total_best_score / self.hits if self.hits else 0.0,
        }


@dataclass
class RetrievalStats:
    searches: int = 0
    web_fallbacks: int = 0  # times the LLM chose to call search_web
    both_local_tiers_hit: int = 0  # searches where official AND wiki each returned something
    tiers: dict[str, TierStats] = field(default_factory=lambda: {t: TierStats() for t in ("official", "wiki", "web")})

    def as_dict(self) -> dict:
        return {
            "searches": self.searches,
            "web_fallback_rate": self.web_fallbacks / self.searches if self.searches else 0.0,
            "both_local_tiers_hit": self.both_local_tiers_hit,
            "tiers": {name: t.as_dict() for name, t in self.tiers.items()},
        }
