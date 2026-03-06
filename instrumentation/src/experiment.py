"""Experiment A/B tracking infrastructure (#20).

Provides structured experiment metadata definitions and a registry
that loads from YAML config. The experiment_id/experiment_variant fields
already exist on TradeEvent and propagate through the system; this adds
the registry and definition layer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger("instrumentation.experiment")

_DEFAULT_CONFIG_PATH = Path("instrumentation/config/experiments.yaml")


@dataclass
class ExperimentMetadata:
    """Definition of a single A/B experiment."""
    experiment_id: str
    hypothesis: str
    variants: list[str]
    start_date: str
    strategy_type: str
    primary_metric: str = "sharpe"
    secondary_metrics: list[str] = field(default_factory=lambda: ["win_rate", "avg_pnl"])
    end_date: Optional[str] = None
    min_trades_per_variant: int = 30


class ExperimentRegistry:
    """Loads experiment definitions from YAML and provides lookup.

    Usage:
        registry = ExperimentRegistry()
        exp = registry.get("exp_001")
        active = registry.active_experiments()
    """

    def __init__(self, config_path: Optional[Path] = None):
        self._path = config_path or _DEFAULT_CONFIG_PATH
        self._experiments: dict[str, ExperimentMetadata] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            logger.debug("No experiments config at %s", self._path)
            return
        try:
            with open(self._path) as f:
                raw = yaml.safe_load(f) or {}
            for exp_id, data in raw.get("experiments", {}).items():
                self._experiments[exp_id] = ExperimentMetadata(
                    experiment_id=exp_id,
                    hypothesis=data.get("hypothesis", ""),
                    variants=data.get("variants", []),
                    start_date=data.get("start_date", ""),
                    strategy_type=data.get("strategy_type", ""),
                    primary_metric=data.get("primary_metric", "sharpe"),
                    secondary_metrics=data.get("secondary_metrics", ["win_rate", "avg_pnl"]),
                    end_date=data.get("end_date"),
                    min_trades_per_variant=data.get("min_trades_per_variant", 30),
                )
            if self._experiments:
                logger.info("Loaded %d experiment definitions", len(self._experiments))
        except Exception as e:
            logger.warning("Failed to load experiments config: %s", e)

    def get(self, experiment_id: str) -> Optional[ExperimentMetadata]:
        return self._experiments.get(experiment_id)

    def active_experiments(self, as_of: Optional[str] = None) -> list[ExperimentMetadata]:
        """Return experiments that are currently active (started, not ended)."""
        ref = as_of or date.today().isoformat()
        result = []
        for exp in self._experiments.values():
            if exp.start_date and exp.start_date <= ref:
                if exp.end_date is None or exp.end_date >= ref:
                    result.append(exp)
        return result

    def all_experiments(self) -> list[ExperimentMetadata]:
        return list(self._experiments.values())
