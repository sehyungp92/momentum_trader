"""Structured filter decision capture for instrumentation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class FilterDecision:
    """One gate/filter evaluation result with threshold context."""
    filter_name: str
    threshold: float
    actual_value: float
    passed: bool

    def margin_pct(self) -> Optional[float]:
        """How far inside (positive) or outside (negative) the threshold, as %.
        Returns None if threshold is zero (boolean filters like news_blocked)."""
        if self.threshold == 0.0:
            return None
        return round((self.threshold - self.actual_value) / self.threshold * 100, 2)

    def to_dict(self) -> dict:
        return {
            "filter_name": self.filter_name,
            "threshold": self.threshold,
            "actual_value": self.actual_value,
            "passed": self.passed,
            "margin_pct": self.margin_pct(),
        }


def build_filter_decisions(decisions: list[FilterDecision]) -> list[dict]:
    """Convert a list of FilterDecision objects to list of dicts for TradeEvent."""
    return [d.to_dict() for d in decisions]
