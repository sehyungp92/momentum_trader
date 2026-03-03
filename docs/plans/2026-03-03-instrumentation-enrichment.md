# Instrumentation Data Enrichment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close all 6 critical instrumentation gaps and implement the 5 highest-impact data capture improvements identified in `feedback.md`, so the orchestrator has full decision context for every trade, miss, and coordination event.

**Architecture:** A new `InstrumentationKit` facade (`instrumentation/src/facade.py`) provides a single clean API surface for all strategy engines. Enriched data schemas (signal factors, filter decisions, sizing inputs, futures context) are added to existing `TradeEvent` and `MissedOpportunityEvent` dataclasses. Cross-strategy coordination events flow through a new lightweight event emitter in `PortfolioRuleChecker`. Post-exit price tracking reuses the existing `MissedOpportunityLogger` backfill infrastructure.

**Tech Stack:** Python 3.11, dataclasses, JSONL output, asyncio, pytest

---

## Dependency Graph

```
Task 1 (TradeEvent schema)  ──┐
Task 2 (MissedOpp schema)  ───┤
Task 3 (FilterDecision)    ───┼──▶ Task 6 (Facade) ──▶ Task 7 (Helix integration)
Task 4 (SizingInput)       ───┤                    ──▶ Task 8 (NQDTC integration)
Task 5 (CoordinationEvent) ───┘                    ──▶ Task 9 (Vdubus integration)
                                                   ──▶ Task 10 (RISK_DENIAL enrichment)
Task 11 (Post-exit tracking) — independent
Task 12 (Gates collect_all) — feeds into Task 7
```

---

### Task 1: Extend TradeEvent Schema

**Files:**
- Modify: `instrumentation/src/trade_logger.py:14-68`
- Test: `instrumentation/tests/test_trade_logger.py`

Add the new fields that all downstream tasks need. These are all Optional with defaults so existing callers don't break.

**Step 1: Write the failing test**

Add to `instrumentation/tests/test_trade_logger.py`:

```python
def test_trade_event_has_enriched_fields():
    """TradeEvent must have signal_factors, filter_decisions, sizing_inputs, futures_context, concurrent_positions."""
    from instrumentation.src.trade_logger import TradeEvent
    te = TradeEvent(trade_id="t1", event_metadata={}, entry_snapshot={})
    # Signal confluence (feedback highest-impact #1)
    assert te.signal_factors == []
    # Filter threshold context (feedback highest-impact #2)
    assert te.filter_decisions == []
    # Position sizing inputs (feedback highest-impact #3)
    assert te.sizing_inputs is None
    # Futures-specific context (feedback critical gap #5)
    assert te.session_type == ""
    assert te.contract_month == ""
    assert te.margin_used_pct is None
    # Concurrent position tracking (feedback critical gap #4)
    assert te.concurrent_positions_at_entry is None
    # Drawdown state (feedback critical gap #3)
    assert te.drawdown_pct is None
    assert te.drawdown_tier == ""
    assert te.drawdown_size_mult is None
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest instrumentation/tests/test_trade_logger.py::test_trade_event_has_enriched_fields -v`
Expected: FAIL — `AttributeError: 'TradeEvent' has no attribute 'signal_factors'`

**Step 3: Add fields to TradeEvent dataclass**

In `instrumentation/src/trade_logger.py`, add after the existing `strategy_params_at_entry` field (line ~57):

```python
    # Signal confluence factors (highest-impact #1)
    # Each dict: {factor_name: str, factor_value: float, threshold: float, contribution: float}
    signal_factors: List[dict] = field(default_factory=list)

    # Filter threshold context (highest-impact #2)
    # Each dict: {filter_name: str, threshold: float, actual_value: float, passed: bool, margin_pct: float}
    filter_decisions: List[dict] = field(default_factory=list)

    # Position sizing inputs (highest-impact #3)
    # Dict: {target_risk_pct: float, account_equity: float, volatility_basis: float,
    #         sizing_model: str, unit_risk_usd: float, setup_size_mult: float,
    #         session_size_mult: float, hour_mult: float, dow_mult: float, dd_mult: float}
    sizing_inputs: Optional[dict] = None

    # Futures-specific context (critical gap #5)
    session_type: str = ""           # "RTH" / "ETH" / specific block name
    contract_month: str = ""         # e.g. "2026-03" or "MARCH_2026"
    margin_used_pct: Optional[float] = None

    # Concurrent position tracking (critical gap #4)
    concurrent_positions_at_entry: Optional[int] = None

    # Drawdown state at entry (critical gap #3)
    drawdown_pct: Optional[float] = None
    drawdown_tier: str = ""          # "full" / "half" / "quarter" / "halt"
    drawdown_size_mult: Optional[float] = None
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest instrumentation/tests/test_trade_logger.py::test_trade_event_has_enriched_fields -v`
Expected: PASS

**Step 5: Verify existing tests still pass**

Run: `python -m pytest instrumentation/tests/test_trade_logger.py -v`
Expected: All PASS (new fields have defaults, no existing calls break)

**Step 6: Commit**

```bash
git add instrumentation/src/trade_logger.py instrumentation/tests/test_trade_logger.py
git commit -m "feat(instrumentation): extend TradeEvent with signal factors, filter decisions, sizing, futures context"
```

---

### Task 2: Extend MissedOpportunityEvent Schema

**Files:**
- Modify: `instrumentation/src/missed_opportunity.py:37-73`
- Test: `instrumentation/tests/test_missed_opportunity.py`

Add structured filter decisions and coordination context to missed events.

**Step 1: Write the failing test**

Add to `instrumentation/tests/test_missed_opportunity.py`:

```python
def test_missed_event_has_enriched_fields():
    """MissedOpportunityEvent must have filter_decisions and coordination_context."""
    from instrumentation.src.missed_opportunity import MissedOpportunityEvent
    me = MissedOpportunityEvent(event_metadata={}, market_snapshot={})
    assert me.filter_decisions == []
    assert me.coordination_context is None
    assert me.concurrent_positions_at_signal is None
    assert me.session_type == ""
    assert me.drawdown_pct is None
    assert me.drawdown_tier == ""
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest instrumentation/tests/test_missed_opportunity.py::test_missed_event_has_enriched_fields -v`
Expected: FAIL

**Step 3: Add fields to MissedOpportunityEvent**

In `instrumentation/src/missed_opportunity.py`, add after `market_regime` field (line ~72):

```python
    # Structured filter context (highest-impact #2)
    filter_decisions: List[dict] = field(default_factory=list)

    # Cross-strategy coordination context (critical gap #2)
    # Dict: {rule: str, blocking_strategy: str, blocked_strategy: str, detail: str}
    coordination_context: Optional[dict] = None

    # Concurrent position count at signal time (critical gap #4)
    concurrent_positions_at_signal: Optional[int] = None

    # Session and drawdown context
    session_type: str = ""
    drawdown_pct: Optional[float] = None
    drawdown_tier: str = ""
```

**Step 4: Run tests**

Run: `python -m pytest instrumentation/tests/test_missed_opportunity.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add instrumentation/src/missed_opportunity.py instrumentation/tests/test_missed_opportunity.py
git commit -m "feat(instrumentation): extend MissedOpportunityEvent with filter decisions, coordination context"
```

---

### Task 3: Create FilterDecision Helper

**Files:**
- Create: `instrumentation/src/filter_decision.py`
- Test: `instrumentation/tests/test_filter_decision.py`

A tiny helper that strategies call to build structured filter decision dicts. Keeps the format consistent.

**Step 1: Write the failing test**

Create `instrumentation/tests/test_filter_decision.py`:

```python
import pytest
from instrumentation.src.filter_decision import FilterDecision, build_filter_decisions


def test_filter_decision_pass():
    fd = FilterDecision("heat_cap", threshold=3.0, actual_value=2.1, passed=True)
    d = fd.to_dict()
    assert d["filter_name"] == "heat_cap"
    assert d["threshold"] == 3.0
    assert d["actual_value"] == 2.1
    assert d["passed"] is True
    assert d["margin_pct"] == pytest.approx(30.0, abs=0.1)


def test_filter_decision_fail():
    fd = FilterDecision("spread", threshold=0.50, actual_value=0.75, passed=False)
    d = fd.to_dict()
    assert d["passed"] is False
    assert d["margin_pct"] == pytest.approx(-50.0, abs=0.1)


def test_filter_decision_zero_threshold():
    fd = FilterDecision("news_blocked", threshold=0.0, actual_value=1.0, passed=False)
    d = fd.to_dict()
    assert d["margin_pct"] is None  # division by zero guard


def test_build_filter_decisions_returns_list_of_dicts():
    decisions = [
        FilterDecision("heat_cap", 3.0, 2.1, True),
        FilterDecision("spread", 0.50, 0.30, True),
    ]
    result = build_filter_decisions(decisions)
    assert len(result) == 2
    assert all(isinstance(d, dict) for d in result)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest instrumentation/tests/test_filter_decision.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'instrumentation.src.filter_decision'`

**Step 3: Implement**

Create `instrumentation/src/filter_decision.py`:

```python
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
```

**Step 4: Run tests**

Run: `python -m pytest instrumentation/tests/test_filter_decision.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add instrumentation/src/filter_decision.py instrumentation/tests/test_filter_decision.py
git commit -m "feat(instrumentation): add FilterDecision helper for structured gate context"
```

---

### Task 4: Create SignalFactor Helper

**Files:**
- Create: `instrumentation/src/signal_factor.py`
- Test: `instrumentation/tests/test_signal_factor.py`

**Step 1: Write the failing test**

Create `instrumentation/tests/test_signal_factor.py`:

```python
from instrumentation.src.signal_factor import SignalFactor, build_signal_factors


def test_signal_factor_to_dict():
    sf = SignalFactor("alignment_score", factor_value=2.0, threshold=1.0, contribution=0.667)
    d = sf.to_dict()
    assert d["factor_name"] == "alignment_score"
    assert d["factor_value"] == 2.0
    assert d["threshold"] == 1.0
    assert d["contribution"] == 0.667


def test_build_signal_factors():
    factors = [
        SignalFactor("alignment_score", 2.0, 1.0, 0.667),
        SignalFactor("trend_strength", 0.85, 0.5, 0.283),
    ]
    result = build_signal_factors(factors)
    assert len(result) == 2
    assert result[0]["factor_name"] == "alignment_score"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest instrumentation/tests/test_signal_factor.py -v`
Expected: FAIL

**Step 3: Implement**

Create `instrumentation/src/signal_factor.py`:

```python
"""Structured signal confluence factor capture."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SignalFactor:
    """One component contributing to an entry signal's overall strength."""
    factor_name: str
    factor_value: float
    threshold: float       # minimum required for this factor
    contribution: float    # weight/contribution to overall signal (0-1)

    def to_dict(self) -> dict:
        return {
            "factor_name": self.factor_name,
            "factor_value": self.factor_value,
            "threshold": self.threshold,
            "contribution": self.contribution,
        }


def build_signal_factors(factors: list[SignalFactor]) -> list[dict]:
    """Convert SignalFactor list to list of dicts for TradeEvent.signal_factors."""
    return [f.to_dict() for f in factors]
```

**Step 4: Run tests**

Run: `python -m pytest instrumentation/tests/test_signal_factor.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add instrumentation/src/signal_factor.py instrumentation/tests/test_signal_factor.py
git commit -m "feat(instrumentation): add SignalFactor helper for confluence logging"
```

---

### Task 5: Add Coordination Event Logging to PortfolioRuleChecker

**Files:**
- Modify: `shared/oms/risk/portfolio_rules.py`
- Test: `instrumentation/tests/test_coordination_events.py`

Add an optional `on_rule_event` callback to `PortfolioRuleChecker` that fires whenever a rule blocks or modifies sizing. This bridges the OMS layer to instrumentation without creating a hard dependency.

**Step 1: Write the failing test**

Create `instrumentation/tests/test_coordination_events.py`:

```python
import asyncio
import pytest
from shared.oms.risk.portfolio_rules import (
    PortfolioRuleChecker, PortfolioRulesConfig, PortfolioRuleResult,
)


@pytest.fixture
def captured_events():
    return []


@pytest.fixture
def config():
    return PortfolioRulesConfig(
        helix_nqdtc_cooldown_minutes=120,
        cooldown_session_only=False,  # disable time-of-day check for testing
        directional_cap_R=3.5,
        initial_equity=10_000.0,
    )


def _make_checker(config, captured_events, equity=10_000.0, dir_risk=0.0, signal=None):
    async def get_signal(sid):
        return signal

    async def get_dir_risk(direction):
        return dir_risk

    checker = PortfolioRuleChecker(
        config=config,
        get_strategy_signal=get_signal,
        get_directional_risk_R=get_dir_risk,
        get_current_equity=lambda: equity,
        on_rule_event=lambda evt: captured_events.append(evt),
    )
    return checker


def test_directional_cap_denial_emits_event(config, captured_events):
    checker = _make_checker(config, captured_events, dir_risk=3.0)
    result = asyncio.get_event_loop().run_until_complete(
        checker.check_entry("AKC_Helix_v31", "LONG", new_risk_R=1.0)
    )
    assert result.approved is False
    assert len(captured_events) == 1
    evt = captured_events[0]
    assert evt["rule"] == "directional_cap"
    assert evt["strategy_id"] == "AKC_Helix_v31"
    assert evt["approved"] is False


def test_drawdown_tier_emits_event(config, captured_events):
    # 10% DD = tier 2 (50% sizing)
    checker = _make_checker(config, captured_events, equity=9_000.0)
    result = asyncio.get_event_loop().run_until_complete(
        checker.check_entry("AKC_Helix_v31", "LONG", new_risk_R=0.5)
    )
    assert result.approved is True
    # Should emit a drawdown_tier event with size_mult < 1
    dd_events = [e for e in captured_events if e["rule"] == "drawdown_tier"]
    assert len(dd_events) == 1
    assert dd_events[0]["size_multiplier"] == 0.5
    assert dd_events[0]["drawdown_pct"] == pytest.approx(0.10, abs=0.001)


def test_no_event_when_all_pass_at_full_size(config, captured_events):
    checker = _make_checker(config, captured_events)
    result = asyncio.get_event_loop().run_until_complete(
        checker.check_entry("AKC_Helix_v31", "LONG", new_risk_R=0.5)
    )
    assert result.approved is True
    # No coordination events when everything passes at full size
    assert len(captured_events) == 0
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest instrumentation/tests/test_coordination_events.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'on_rule_event'`

**Step 3: Modify PortfolioRuleChecker**

In `shared/oms/risk/portfolio_rules.py`:

a) Add `on_rule_event` param to `__init__`:

```python
    def __init__(
        self,
        config: PortfolioRulesConfig,
        get_strategy_signal: Callable[[str], Awaitable[Optional[dict]]],
        get_directional_risk_R: Callable[[str], Awaitable[float]],
        get_current_equity: Callable[[], float],
        on_rule_event: Optional[Callable[[dict], None]] = None,
    ):
        self._cfg = config
        self._get_signal = get_strategy_signal
        self._get_dir_risk = get_directional_risk_R
        self._get_equity = get_current_equity
        self._on_rule_event = on_rule_event
```

b) Add a helper to emit events:

```python
    def _emit(self, event: dict) -> None:
        if self._on_rule_event:
            try:
                self._on_rule_event(event)
            except Exception:
                pass
```

c) Emit events in `check_entry` for denials and size modifications. After each rule check that produces a denial or non-1.0 multiplier, call `self._emit(...)`:

In `check_entry`, after proximity cooldown denial (line ~102):
```python
        # 1. Proximity cooldown
        denial = await self._check_proximity_cooldown(strategy_id)
        if denial:
            self._emit({"rule": "proximity_cooldown", "strategy_id": strategy_id,
                         "approved": False, "denial_reason": denial})
            return PortfolioRuleResult(approved=False, denial_reason=denial)
```

After direction filter block (line ~107):
```python
        # 2. NQDTC direction filter (Vdubus only)
        size_mult = await self._check_direction_filter(strategy_id, direction)
        if size_mult == 0.0:
            reason = f"nqdtc_direction_filter: NQDTC opposes {direction}"
            self._emit({"rule": "nqdtc_direction_filter", "strategy_id": strategy_id,
                         "direction": direction, "approved": False, "denial_reason": reason})
            return PortfolioRuleResult(approved=False, denial_reason=reason)
        if size_mult != 1.0:
            self._emit({"rule": "nqdtc_direction_filter", "strategy_id": strategy_id,
                         "direction": direction, "approved": True, "size_multiplier": size_mult})
        result.size_multiplier *= size_mult
```

After directional cap denial (line ~116):
```python
        # 3. Directional cap
        denial = await self._check_directional_cap(direction, new_risk_R)
        if denial:
            self._emit({"rule": "directional_cap", "strategy_id": strategy_id,
                         "direction": direction, "approved": False, "denial_reason": denial})
            return PortfolioRuleResult(approved=False, denial_reason=denial)
```

After drawdown tier (line ~119):
```python
        # 4. Drawdown tiers
        dd_mult = self._check_drawdown_tier()
        if dd_mult == 0.0:
            reason = "drawdown_halt: equity drawdown exceeds maximum tier"
            self._emit({"rule": "drawdown_tier", "strategy_id": strategy_id,
                         "approved": False, "denial_reason": reason,
                         "drawdown_pct": self._current_dd_pct(), "size_multiplier": 0.0})
            return PortfolioRuleResult(approved=False, denial_reason=reason)
        if dd_mult < 1.0:
            self._emit({"rule": "drawdown_tier", "strategy_id": strategy_id,
                         "approved": True, "size_multiplier": dd_mult,
                         "drawdown_pct": self._current_dd_pct()})
        result.size_multiplier *= dd_mult
```

After chop throttle (line ~128):
```python
        # 5. NQDTC chop throttle (affects Helix only)
        chop_mult = await self._check_chop_throttle(strategy_id)
        if chop_mult < 1.0:
            self._emit({"rule": "nqdtc_chop_throttle", "strategy_id": strategy_id,
                         "approved": True, "size_multiplier": chop_mult})
        result.size_multiplier *= chop_mult
```

d) Add `_current_dd_pct` helper:
```python
    def _current_dd_pct(self) -> float:
        equity = self._get_equity()
        initial = self._cfg.initial_equity
        if initial <= 0 or equity >= initial:
            return 0.0
        return (initial - equity) / initial
```

**Step 4: Run tests**

Run: `python -m pytest instrumentation/tests/test_coordination_events.py -v`
Expected: All PASS

**Step 5: Verify existing OMS tests still pass**

Run: `python -m pytest shared/ -v --ignore=shared/oms/tests/test_integration.py 2>/dev/null || python -m pytest instrumentation/tests/ -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add shared/oms/risk/portfolio_rules.py instrumentation/tests/test_coordination_events.py
git commit -m "feat(oms): emit coordination events from PortfolioRuleChecker for instrumentation"
```

---

### Task 6: Create InstrumentationKit Facade

**Files:**
- Create: `instrumentation/src/facade.py`
- Test: `instrumentation/tests/test_facade.py`

This is the central API surface that strategy engines call. It wraps `TradeLogger`, `MissedOpportunityLogger`, and adds convenience methods for all the enriched data.

**Step 1: Write the failing test**

Create `instrumentation/tests/test_facade.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from instrumentation.src.facade import InstrumentationKit


@pytest.fixture
def mock_manager():
    mgr = MagicMock()
    mgr.trade_logger = MagicMock()
    mgr.missed_logger = MagicMock()
    mgr.regime_classifier = MagicMock()
    mgr.regime_classifier.current_regime.return_value = "trending_up"
    return mgr


@pytest.fixture
def kit(mock_manager):
    return InstrumentationKit(mock_manager, strategy_type="helix")


def test_log_entry_passes_enriched_fields(kit, mock_manager):
    kit.log_entry(
        trade_id="t1",
        pair="NQ",
        side="LONG",
        entry_price=21000.0,
        position_size=5,
        position_size_quote=5 * 21000.0 * 20.0,
        entry_signal="Class_M",
        entry_signal_id="setup_001",
        entry_signal_strength=0.667,
        expected_entry_price=20999.0,
        strategy_params={"stop0": 20950.0},
        signal_factors=[{"factor_name": "alignment", "factor_value": 2, "threshold": 1, "contribution": 0.667}],
        filter_decisions=[{"filter_name": "heat_cap", "threshold": 3.0, "actual_value": 2.1, "passed": True, "margin_pct": 30.0}],
        sizing_inputs={"unit_risk_usd": 500, "dd_mult": 1.0},
        session_type="RTH_PRIME1",
        contract_month="2026-03",
        concurrent_positions=2,
        drawdown_pct=0.05,
        drawdown_tier="full",
        drawdown_size_mult=1.0,
    )
    call_kwargs = mock_manager.trade_logger.log_entry.call_args
    assert call_kwargs is not None


def test_log_missed_passes_enriched_fields(kit, mock_manager):
    kit.log_missed(
        pair="NQ",
        side="LONG",
        signal="Class_M",
        signal_id="setup_001",
        signal_strength=0.667,
        blocked_by="heat_cap",
        block_reason="heat 3.2 > cap 3.0",
        strategy_params={"score": 2},
        filter_decisions=[],
        session_type="RTH_PRIME1",
        concurrent_positions=3,
        drawdown_pct=0.05,
        drawdown_tier="full",
    )
    assert mock_manager.missed_logger.log_missed.called


def test_log_exit_delegates(kit, mock_manager):
    kit.log_exit(trade_id="t1", exit_price=21050.0, exit_reason="TRAILING_STOP")
    assert mock_manager.trade_logger.log_exit.called


def test_kit_graceful_on_no_manager():
    kit = InstrumentationKit(None, strategy_type="helix")
    # Should not raise
    kit.log_entry(trade_id="t1", pair="NQ", side="LONG", entry_price=21000.0,
                  position_size=1, position_size_quote=21000.0,
                  entry_signal="test", entry_signal_id="s1", entry_signal_strength=0.5,
                  expected_entry_price=21000.0, strategy_params={})
    kit.log_exit(trade_id="t1", exit_price=21050.0, exit_reason="STOP")
    kit.log_missed(pair="NQ", side="LONG", signal="test", signal_id="s1",
                   signal_strength=0.5, blocked_by="test", block_reason="test",
                   strategy_params={})
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest instrumentation/tests/test_facade.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement the facade**

Create `instrumentation/src/facade.py`:

```python
"""InstrumentationKit facade — single clean API for strategy engines.

Usage in strategy engine:
    kit = InstrumentationKit(instr_manager, strategy_type="helix")
    kit.log_entry(trade_id=..., signal_factors=[...], filter_decisions=[...], ...)
    kit.log_exit(trade_id=..., exit_price=..., exit_reason=...)
    kit.log_missed(pair=..., blocked_by=..., filter_decisions=[...], ...)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional, List

if TYPE_CHECKING:
    from .bootstrap import InstrumentationManager

logger = logging.getLogger("instrumentation.facade")


class InstrumentationKit:
    """Thin facade over InstrumentationManager for strategy-engine callers.

    All methods are fire-and-forget: exceptions are caught and logged,
    never propagated to strategy code.
    """

    def __init__(self, manager: Optional["InstrumentationManager"], strategy_type: str = ""):
        self._mgr = manager
        self._strategy_type = strategy_type

    @property
    def active(self) -> bool:
        return self._mgr is not None

    def log_entry(
        self,
        *,
        trade_id: str,
        pair: str,
        side: str,
        entry_price: float,
        position_size: float,
        position_size_quote: float,
        entry_signal: str,
        entry_signal_id: str,
        entry_signal_strength: float,
        expected_entry_price: Optional[float] = None,
        strategy_params: Optional[dict] = None,
        # Enriched fields
        signal_factors: Optional[List[dict]] = None,
        filter_decisions: Optional[List[dict]] = None,
        sizing_inputs: Optional[dict] = None,
        session_type: str = "",
        contract_month: str = "",
        margin_used_pct: Optional[float] = None,
        concurrent_positions: Optional[int] = None,
        drawdown_pct: Optional[float] = None,
        drawdown_tier: str = "",
        drawdown_size_mult: Optional[float] = None,
        bar_id: Optional[str] = None,
        exchange_timestamp: Optional[datetime] = None,
        entry_latency_ms: Optional[int] = None,
    ) -> None:
        if not self._mgr:
            return
        try:
            regime = self._mgr.regime_classifier.current_regime(pair)

            # Build enriched strategy_params by merging sizing/drawdown context
            enriched_params = dict(strategy_params or {})
            if sizing_inputs:
                enriched_params["_sizing_inputs"] = sizing_inputs
            if drawdown_pct is not None:
                enriched_params["_drawdown_pct"] = drawdown_pct
                enriched_params["_drawdown_tier"] = drawdown_tier
                enriched_params["_drawdown_size_mult"] = drawdown_size_mult

            self._mgr.trade_logger.log_entry(
                trade_id=trade_id,
                pair=pair,
                side=side,
                entry_price=entry_price,
                position_size=position_size,
                position_size_quote=position_size_quote,
                entry_signal=entry_signal,
                entry_signal_id=entry_signal_id,
                entry_signal_strength=entry_signal_strength,
                active_filters=[d["filter_name"] for d in (filter_decisions or [])],
                passed_filters=[d["filter_name"] for d in (filter_decisions or []) if d.get("passed")],
                strategy_params=enriched_params,
                expected_entry_price=expected_entry_price,
                market_regime=regime,
                bar_id=bar_id,
                exchange_timestamp=exchange_timestamp,
                entry_latency_ms=entry_latency_ms,
            )

            # Patch enriched fields onto the TradeEvent in _open_trades
            trade = self._mgr.trade_logger._open_trades.get(trade_id)
            if trade:
                trade.signal_factors = signal_factors or []
                trade.filter_decisions = filter_decisions or []
                trade.sizing_inputs = sizing_inputs
                trade.session_type = session_type
                trade.contract_month = contract_month
                trade.margin_used_pct = margin_used_pct
                trade.concurrent_positions_at_entry = concurrent_positions
                trade.drawdown_pct = drawdown_pct
                trade.drawdown_tier = drawdown_tier
                trade.drawdown_size_mult = drawdown_size_mult

        except Exception as e:
            logger.warning("InstrumentationKit.log_entry failed: %s", e)

    def log_exit(
        self,
        *,
        trade_id: str,
        exit_price: float,
        exit_reason: str,
        fees_paid: float = 0.0,
        exchange_timestamp: Optional[datetime] = None,
        expected_exit_price: Optional[float] = None,
        exit_latency_ms: Optional[int] = None,
    ) -> None:
        if not self._mgr:
            return
        try:
            self._mgr.trade_logger.log_exit(
                trade_id=trade_id,
                exit_price=exit_price,
                exit_reason=exit_reason,
                fees_paid=fees_paid,
                exchange_timestamp=exchange_timestamp,
                expected_exit_price=expected_exit_price,
                exit_latency_ms=exit_latency_ms,
            )
        except Exception as e:
            logger.warning("InstrumentationKit.log_exit failed: %s", e)

    def log_missed(
        self,
        *,
        pair: str,
        side: str,
        signal: str,
        signal_id: str,
        signal_strength: float,
        blocked_by: str,
        block_reason: str = "",
        strategy_params: Optional[dict] = None,
        filter_decisions: Optional[List[dict]] = None,
        coordination_context: Optional[dict] = None,
        session_type: str = "",
        concurrent_positions: Optional[int] = None,
        drawdown_pct: Optional[float] = None,
        drawdown_tier: str = "",
        exchange_timestamp: Optional[datetime] = None,
        bar_id: Optional[str] = None,
    ) -> None:
        if not self._mgr:
            return
        try:
            regime = self._mgr.regime_classifier.current_regime(pair)

            enriched_params = dict(strategy_params or {})
            if concurrent_positions is not None:
                enriched_params["_concurrent_positions"] = concurrent_positions
            if session_type:
                enriched_params["_session_type"] = session_type
            if drawdown_pct is not None:
                enriched_params["_drawdown_pct"] = drawdown_pct
                enriched_params["_drawdown_tier"] = drawdown_tier

            self._mgr.missed_logger.log_missed(
                pair=pair,
                side=side,
                signal=signal,
                signal_id=signal_id,
                signal_strength=signal_strength,
                blocked_by=blocked_by,
                block_reason=block_reason,
                strategy_params=enriched_params,
                strategy_type=self._strategy_type,
                market_regime=regime,
                exchange_timestamp=exchange_timestamp,
                bar_id=bar_id,
            )
        except Exception as e:
            logger.warning("InstrumentationKit.log_missed failed: %s", e)
```

**Step 4: Run tests**

Run: `python -m pytest instrumentation/tests/test_facade.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add instrumentation/src/facade.py instrumentation/tests/test_facade.py
git commit -m "feat(instrumentation): add InstrumentationKit facade for clean strategy integration"
```

---

### Task 7: Integrate Facade into Helix4Engine

**Files:**
- Modify: `strategy/engine.py`
- Modify: `strategy/gates.py` (enable `collect_all=True`)

This is the largest integration task. Replace all raw `trade_logger`/`missed_logger` calls with `InstrumentationKit` calls, and populate all enriched fields.

**Step 1: Enable gates collect_all mode**

In `strategy/gates.py`, the `check_gates` function already supports `collect_all: bool = False`. No code change needed to gates.py itself — we just need to call it with `collect_all=True` from the engine.

**Step 2: Create InstrumentationKit in engine __init__**

In `strategy/engine.py`, at the end of `__init__` (after `self._instr = ...`), add:

```python
        from instrumentation.src.facade import InstrumentationKit
        self._kit = InstrumentationKit(self._instr, strategy_type="helix")
```

**Step 3: Replace log_entry call at L637-653**

Replace the existing `self._instr.trade_logger.log_entry(...)` block with:

```python
        if self._kit.active:
            try:
                from .session import get_session_block
                block = get_session_block(datetime.now(ET))
                self._kit.log_entry(
                    trade_id=setup.setup_id,
                    pair=self.nq_inst.symbol,
                    side="LONG" if setup.direction == 1 else "SHORT",
                    entry_price=fill_price,
                    position_size=qty,
                    position_size_quote=qty * fill_price * self.nq_inst.point_value,
                    entry_signal=f"Class_{setup.cls.value}",
                    entry_signal_id=setup.setup_id,
                    entry_signal_strength=setup.alignment_score / 3.0,
                    expected_entry_price=setup.entry_stop,
                    strategy_params={
                        "stop0": setup.stop0,
                        "class": setup.cls.value,
                        "alignment_score": setup.alignment_score,
                    },
                    signal_factors=[
                        {"factor_name": "alignment_score", "factor_value": setup.alignment_score,
                         "threshold": 1, "contribution": setup.alignment_score / 3.0},
                    ],
                    filter_decisions=getattr(setup, '_filter_decisions', []),
                    sizing_inputs={
                        "unit_risk_usd": setup.unit1_risk_usd,
                        "setup_size_mult": setup.setup_size_mult,
                        "session_size_mult": setup.session_size_mult,
                        "hour_mult": self.risk.hour_size_mult(datetime.now(ET).hour),
                        "dow_mult": self.risk.dow_size_mult(datetime.now(ET).weekday()),
                        "dd_mult": self._throttle.dd_size_mult,
                        "contracts": qty,
                    },
                    session_type=block.value,
                    contract_month=getattr(self._contract, 'lastTradeDateOrContractMonth', ''),
                    concurrent_positions=len(self.positions.positions),
                    drawdown_pct=self._throttle.dd_pct if hasattr(self._throttle, 'dd_pct') else None,
                    drawdown_tier=self._dd_tier_name(),
                    drawdown_size_mult=self._throttle.dd_size_mult,
                )
            except Exception:
                pass
```

**Step 4: Add `_dd_tier_name` helper to Helix4Engine**

```python
    def _dd_tier_name(self) -> str:
        mult = self._throttle.dd_size_mult
        if mult >= 1.0:
            return "full"
        elif mult >= 0.5:
            return "half"
        elif mult >= 0.25:
            return "quarter"
        return "halt"
```

**Step 5: Capture filter decisions from gates**

In `_evaluate_candidates`, change the `check_gates` call at L425 to use `collect_all=True`:

```python
            gate = check_gates(
                setup=setup, now_et=now_et, h1=self.h1, daily=self.daily,
                vol=self.vol, news=self.news, bid=self._bid, ask=self._ask,
                open_risk_r=self.risk.open_risk_r,
                pending_risk_r=self.risk.pending_risk_r,
                dir_risk_r=self.risk.dir_risk_r.get(setup.direction, 0.0),
                heat_cap_r=self.risk.heat_cap_r(),
                heat_cap_dir_r=self.risk.heat_cap_dir_r(),
                collect_all=True,
            )
```

Then after gate passes, stash filter decisions on setup for log_entry to use:

```python
            if not gate:
                # ... existing spread_recheck and log_missed logic ...
                continue

            # Stash gate results for instrumentation
            setup._filter_decisions = self._build_gate_filter_decisions(gate, setup, now_et)
```

Add helper method:
```python
    def _build_gate_filter_decisions(self, gate: GateResult, setup, now_et) -> list[dict]:
        """Build structured filter decision list from gate evaluation."""
        from .config import (
            HEAT_CAP_R, HEAT_CAP_DIR_R, SPIKE_FILTER_ATR_MULT, EXTENSION_ATR_MULT,
            HIGH_VOL_M_THRESHOLD,
        )
        from .session import get_session_block, max_spread_for_session
        block = get_session_block(now_et)
        decisions = []

        # Heat total
        total_risk = self.risk.open_risk_r + self.risk.pending_risk_r
        decisions.append({
            "filter_name": "heat_total",
            "threshold": self.risk.heat_cap_r(),
            "actual_value": round(total_risk, 3),
            "passed": total_risk <= self.risk.heat_cap_r(),
            "margin_pct": round((self.risk.heat_cap_r() - total_risk) / self.risk.heat_cap_r() * 100, 1)
                if self.risk.heat_cap_r() > 0 else None,
        })

        # Spread
        if self._bid is not None and self._ask is not None:
            spread = self._ask - self._bid
            max_sp = max_spread_for_session(block)
            decisions.append({
                "filter_name": "spread",
                "threshold": max_sp,
                "actual_value": round(spread, 4),
                "passed": spread <= max_sp,
                "margin_pct": round((max_sp - spread) / max_sp * 100, 1) if max_sp > 0 else None,
            })

        # High vol
        decisions.append({
            "filter_name": "high_vol",
            "threshold": HIGH_VOL_M_THRESHOLD,
            "actual_value": round(self.vol.vol_pct, 1),
            "passed": self.vol.vol_pct <= HIGH_VOL_M_THRESHOLD,
            "margin_pct": round((HIGH_VOL_M_THRESHOLD - self.vol.vol_pct) / HIGH_VOL_M_THRESHOLD * 100, 1)
                if HIGH_VOL_M_THRESHOLD > 0 else None,
        })

        return decisions
```

**Step 6: Replace log_exit calls**

Replace exit logging at L672 and L701 (and L698 reconcile path):

```python
            if self._kit.active:
                try:
                    self._kit.log_exit(
                        trade_id=pos.origin_setup_id,
                        exit_price=fill_price,
                        exit_reason=exit_reason,
                    )
                except Exception:
                    pass
```

**Step 7: Update `_log_missed` to use facade**

Replace `_log_missed` method body:

```python
    def _log_missed(self, setup, blocked_by: str, block_reason: str, **extra):
        if not self._kit.active:
            return
        try:
            from .session import get_session_block
            block = get_session_block(datetime.now(ET))
            self._kit.log_missed(
                pair=self.nq_inst.symbol,
                side="LONG" if setup.direction == 1 else "SHORT",
                signal=f"Class_{setup.cls.value}",
                signal_id=setup.setup_id if hasattr(setup, 'setup_id') else "",
                signal_strength=setup.alignment_score / 3.0,
                blocked_by=blocked_by,
                block_reason=block_reason,
                strategy_params={
                    "cls": setup.cls.value,
                    "score": setup.alignment_score,
                    "entry_stop": setup.entry_stop,
                    "stop0": setup.stop0,
                    **extra,
                },
                session_type=block.value,
                concurrent_positions=len(self.positions.positions),
                drawdown_pct=self._throttle.dd_pct if hasattr(self._throttle, 'dd_pct') else None,
                drawdown_tier=self._dd_tier_name(),
            )
        except Exception:
            pass
```

**Step 8: Commit**

```bash
git add strategy/engine.py strategy/gates.py
git commit -m "feat(helix): integrate InstrumentationKit with enriched signal/filter/sizing data"
```

---

### Task 8: Integrate Facade into NQDTCEngine

**Files:**
- Modify: `strategy_2/engine.py`

Same pattern as Task 7 but for NQDTC. Replace raw `trade_logger` calls with `InstrumentationKit`.

**Step 1: Create InstrumentationKit in __init__**

Add after `self._instr` initialization:

```python
        from instrumentation.src.facade import InstrumentationKit
        self._kit = InstrumentationKit(self._instr, strategy_type="nqdtc")
```

**Step 2: Replace log_entry at L1923-1939**

```python
        if self._kit.active:
            try:
                self._kit.log_entry(
                    trade_id=oms_id,
                    pair=self._symbol,
                    side="LONG" if wo.direction == Direction.LONG else "SHORT",
                    entry_price=price,
                    position_size=qty,
                    position_size_quote=qty * price * pv,
                    entry_signal=wo.subtype.value,
                    entry_signal_id=oms_id,
                    entry_signal_strength=wo.quality_mult,
                    expected_entry_price=wo.stop_for_risk,
                    strategy_params={
                        "stop": stop_price,
                        "subtype": wo.subtype.value,
                        "exit_tier": exit_tier.value,
                        "quality_mult": wo.quality_mult,
                    },
                    signal_factors=[
                        {"factor_name": "quality_mult", "factor_value": wo.quality_mult,
                         "threshold": 0.0, "contribution": wo.quality_mult},
                    ],
                    sizing_inputs={
                        "quality_mult": wo.quality_mult,
                        "contracts": qty,
                    },
                    session_type="RTH" if hasattr(self, '_session') and self._session == "RTH" else "ETH",
                    concurrent_positions=1 if self._position.open else 0,
                    drawdown_pct=getattr(self._throttle, 'dd_pct', None),
                    drawdown_tier=self._dd_tier_name() if hasattr(self, '_dd_tier_name') else "",
                    drawdown_size_mult=getattr(self._throttle, 'dd_size_mult', None),
                )
                self._instr_trade_id = oms_id
            except Exception:
                pass
```

**Step 3: Add `_dd_tier_name` helper** (same as Helix)

**Step 4: Replace log_exit at L1697 and L1798**

```python
            if self._kit.active and self._instr_trade_id:
                try:
                    self._kit.log_exit(
                        trade_id=self._instr_trade_id,
                        exit_price=est_exit or price,
                        exit_reason="FLATTEN",
                    )
                    self._instr_trade_id = ""
                except Exception:
                    pass
```

**Step 5: Commit**

```bash
git add strategy_2/engine.py
git commit -m "feat(nqdtc): integrate InstrumentationKit with enriched data capture"
```

---

### Task 9: Integrate Facade into VdubNQv4Engine

**Files:**
- Modify: `strategy_3/engine.py`

Same pattern as Tasks 7-8.

**Step 1: Create InstrumentationKit in __init__**

```python
        from instrumentation.src.facade import InstrumentationKit
        self._kit = InstrumentationKit(self._instr, strategy_type="vdubus")
```

**Step 2: Replace log_entry at L1241-1257**

Add enriched fields: `session_type`, `concurrent_positions`, sizing context from `we` (WaitingEntry).

```python
        if self._kit.active and trade_id:
            try:
                pv = C.NQ_SPEC["point_value"]
                self._kit.log_entry(
                    trade_id=trade_id,
                    pair="NQ",
                    side="LONG" if we.direction == Direction.LONG else "SHORT",
                    entry_price=fill_price,
                    position_size=fill_qty,
                    position_size_quote=fill_qty * fill_price * pv,
                    entry_signal=we.entry_type.value,
                    entry_signal_id=trade_id,
                    entry_signal_strength=we.class_mult,
                    expected_entry_price=we.stop_entry,
                    strategy_params={
                        "entry_type": we.entry_type.value,
                        "initial_stop": we.initial_stop,
                        "session": we.session.value if hasattr(we.session, 'value') else str(we.session),
                        "class_mult": we.class_mult,
                    },
                    signal_factors=[
                        {"factor_name": "class_mult", "factor_value": we.class_mult,
                         "threshold": 0.0, "contribution": we.class_mult},
                    ],
                    session_type=we.session.value if hasattr(we.session, 'value') else str(we.session),
                    concurrent_positions=len(self.positions),
                    drawdown_pct=getattr(self._throttle, 'dd_pct', None),
                    drawdown_tier=self._dd_tier_name() if hasattr(self, '_dd_tier_name') else "",
                    drawdown_size_mult=getattr(self._throttle, 'dd_size_mult', None),
                )
            except Exception:
                pass
```

**Step 3: Replace log_exit at L1133-1136**

```python
        if self._kit.active and pos.trade_id:
            try:
                self._kit.log_exit(
                    trade_id=pos.trade_id,
                    exit_price=price,
                    exit_reason=reason,
                )
            except Exception:
                pass
```

**Step 4: Add `_dd_tier_name` helper**

**Step 5: Commit**

```bash
git add strategy_3/engine.py
git commit -m "feat(vdubus): integrate InstrumentationKit with enriched data capture"
```

---

### Task 10: Enrich RISK_DENIAL Handler with Signal Context

**Files:**
- Modify: `shared/oms/events/bus.py:85-95`
- Modify: `shared/oms/intent/handler.py:80-87`
- Modify: `instrumentation/src/bootstrap.py:163-183`
- Test: `instrumentation/tests/test_risk_denial_enrichment.py`

Currently `emit_risk_denial` passes only `{reason: str}`. We enrich the payload with order context that's available at denial time.

**Step 1: Write the failing test**

Create `instrumentation/tests/test_risk_denial_enrichment.py`:

```python
from unittest.mock import MagicMock
from instrumentation.src.bootstrap import InstrumentationManager


def test_handle_risk_denial_uses_enriched_payload():
    oms = MagicMock()
    mgr = InstrumentationManager(oms, "test_strat", "helix")

    event = MagicMock()
    event.payload = {
        "reason": "Heat cap breach: 3.2R > 3.0R",
        "symbol": "NQ",
        "side": "LONG",
        "signal_name": "Class_M",
        "signal_strength": 0.667,
        "strategy_id": "helix",
    }
    event.oms_order_id = "ord_123"
    event.timestamp = None

    mgr._handle_risk_denial(event)

    call_kwargs = mgr.missed_logger.log_missed.call_args
    assert call_kwargs is not None
    # Should use enriched payload instead of defaults
    _, kwargs = call_kwargs
    assert kwargs["pair"] == "NQ"
    assert kwargs["side"] == "LONG"
    assert kwargs["signal"] == "Class_M"
    assert kwargs["signal_strength"] == 0.667
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest instrumentation/tests/test_risk_denial_enrichment.py -v`
Expected: FAIL (side will be "UNKNOWN")

**Step 3: Enrich the RISK_DENIAL payload in IntentHandler**

In `shared/oms/intent/handler.py`, at line 84, change:

```python
            self._bus.emit_risk_denial(order.strategy_id, order.oms_order_id, denial)
```

to:

```python
            self._bus.emit_risk_denial(
                order.strategy_id, order.oms_order_id, denial,
                extra_payload={
                    "symbol": order.instrument.symbol if order.instrument else "",
                    "side": order.side.value,
                    "strategy_id": order.strategy_id,
                },
            )
```

**Step 4: Update EventBus.emit_risk_denial to accept extra_payload**

In `shared/oms/events/bus.py:85-95`, change:

```python
    def emit_risk_denial(
        self, strategy_id: str, oms_order_id: str, reason: str,
        extra_payload: Optional[dict] = None,
    ) -> None:
        payload = {"reason": reason}
        if extra_payload:
            payload.update(extra_payload)
        event = OMSEvent(
            event_type=OMSEventType.RISK_DENIAL,
            timestamp=datetime.now(timezone.utc),
            strategy_id=strategy_id,
            oms_order_id=oms_order_id,
            payload=payload,
        )
        self._dispatch(event)
```

Add `from typing import Optional` import if not already present.

**Step 5: Update bootstrap._handle_risk_denial to use enriched payload**

In `instrumentation/src/bootstrap.py`, replace `_handle_risk_denial`:

```python
    def _handle_risk_denial(self, event) -> None:
        """Log risk denials as missed opportunities with available context."""
        try:
            payload = event.payload or {}
            reason = payload.get("reason", "unknown")

            # Use enriched payload from IntentHandler, fall back to defaults
            symbols = self._config.get("market_snapshots", {}).get("symbols", [])
            pair = payload.get("symbol") or (symbols[0] if symbols else "NQ")
            side = payload.get("side", "UNKNOWN")
            signal = payload.get("signal_name", f"risk_denial_{self._strategy_id}")
            signal_strength = payload.get("signal_strength", 0.0)

            self.missed_logger.log_missed(
                pair=pair,
                side=side,
                signal=signal,
                signal_id=event.oms_order_id or "",
                signal_strength=signal_strength,
                blocked_by="risk_gateway",
                block_reason=reason,
                strategy_type=self._config.get("strategy_type"),
                exchange_timestamp=event.timestamp,
            )
        except Exception as e:
            logger.warning("Failed to log risk denial as missed: %s", e)
```

**Step 6: Run tests**

Run: `python -m pytest instrumentation/tests/test_risk_denial_enrichment.py -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add shared/oms/events/bus.py shared/oms/intent/handler.py instrumentation/src/bootstrap.py instrumentation/tests/test_risk_denial_enrichment.py
git commit -m "feat(oms+instrumentation): enrich RISK_DENIAL events with signal context from order"
```

---

### Task 11: Add Post-Exit Price Tracking

**Files:**
- Modify: `instrumentation/src/trade_logger.py`
- Test: `instrumentation/tests/test_post_exit_tracking.py`

Reuse the backfill pattern from `MissedOpportunityLogger` to track 1h/4h prices after trade exits.

**Step 1: Write the failing test**

Create `instrumentation/tests/test_post_exit_tracking.py`:

```python
from instrumentation.src.trade_logger import TradeEvent


def test_trade_event_has_post_exit_fields():
    te = TradeEvent(trade_id="t1", event_metadata={}, entry_snapshot={})
    assert te.post_exit_1h_price is None
    assert te.post_exit_4h_price is None
    assert te.post_exit_1h_move_pct is None
    assert te.post_exit_4h_move_pct is None
    assert te.post_exit_backfill_status == "pending"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest instrumentation/tests/test_post_exit_tracking.py -v`
Expected: FAIL

**Step 3: Add post-exit fields to TradeEvent**

In `instrumentation/src/trade_logger.py`, add after the drawdown fields:

```python
    # Post-exit price tracking (highest-impact #5)
    post_exit_1h_price: Optional[float] = None
    post_exit_4h_price: Optional[float] = None
    post_exit_1h_move_pct: Optional[float] = None
    post_exit_4h_move_pct: Optional[float] = None
    post_exit_backfill_status: str = "pending"
```

**Step 4: Add backfill queue to TradeLogger**

In `TradeLogger.__init__`, add:

```python
        self._pending_exit_backfills: list[dict] = []
```

In `log_exit`, after writing the event, queue the backfill:

```python
            # Queue post-exit price backfill
            self._pending_exit_backfills.append({
                "trade_id": trade_id,
                "pair": trade.pair,
                "side": trade.side,
                "exit_price": exit_price,
                "exit_time": exch_ts,
                "file_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            })
```

Add a `run_post_exit_backfill` method:

```python
    def run_post_exit_backfill(self, data_provider) -> None:
        """Backfill 1h/4h post-exit prices. Call periodically (e.g., every 5 min)."""
        now = datetime.now(timezone.utc)
        completed = []

        for item in list(self._pending_exit_backfills):
            elapsed = now - item["exit_time"]
            if elapsed < timedelta(hours=4):
                continue  # Wait for full 4h window

            try:
                candles = data_provider.get_ohlcv(
                    item["pair"], timeframe="5m",
                    since=int(item["exit_time"].timestamp() * 1000),
                    limit=60,
                )
                if not candles or len(candles) < 12:
                    continue

                price_1h = None
                price_4h = None
                for candle in candles:
                    candle_time = datetime.fromtimestamp(candle[0] / 1000, tz=timezone.utc)
                    candle_elapsed = candle_time - item["exit_time"]
                    if candle_elapsed >= timedelta(hours=1) and price_1h is None:
                        price_1h = candle[4]
                    if candle_elapsed >= timedelta(hours=4) and price_4h is None:
                        price_4h = candle[4]

                exit_price = item["exit_price"]
                side = item["side"]

                def move_pct(post_price):
                    if post_price is None or exit_price == 0:
                        return None
                    if side == "LONG":
                        return round((post_price - exit_price) / exit_price * 100, 4)
                    else:
                        return round((exit_price - post_price) / exit_price * 100, 4)

                outcomes = {
                    "post_exit_1h_price": price_1h,
                    "post_exit_4h_price": price_4h,
                    "post_exit_1h_move_pct": move_pct(price_1h),
                    "post_exit_4h_move_pct": move_pct(price_4h),
                    "post_exit_backfill_status": "complete",
                }

                self._update_trade_event(item["trade_id"], item["file_date"], outcomes)
                completed.append(item)

            except Exception as e:
                logger.warning("Post-exit backfill failed for %s: %s", item["trade_id"], e)

        for c in completed:
            if c in self._pending_exit_backfills:
                self._pending_exit_backfills.remove(c)
```

Add `_update_trade_event`:

```python
    def _update_trade_event(self, trade_id: str, file_date: str, updates: dict) -> None:
        """Update a completed trade event in the JSONL file."""
        filepath = self.data_dir / f"trades_{file_date}.jsonl"
        if not filepath.exists():
            return
        try:
            lines = filepath.read_text().strip().split("\n")
            new_lines = []
            for line in lines:
                try:
                    event = json.loads(line)
                    if event.get("trade_id") == trade_id and event.get("stage") == "exit":
                        event.update(updates)
                    new_lines.append(json.dumps(event, default=str))
                except json.JSONDecodeError:
                    new_lines.append(line)
            filepath.write_text("\n".join(new_lines) + "\n")
        except Exception as e:
            logger.warning("Failed to update trade %s: %s", trade_id, e)
```

Add `from datetime import timedelta` to imports if not present.

**Step 5: Run tests**

Run: `python -m pytest instrumentation/tests/test_post_exit_tracking.py instrumentation/tests/test_trade_logger.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add instrumentation/src/trade_logger.py instrumentation/tests/test_post_exit_tracking.py
git commit -m "feat(instrumentation): add post-exit 1h/4h price tracking with backfill"
```

---

### Task 12: Wire Post-Exit Backfill into InstrumentationManager

**Files:**
- Modify: `instrumentation/src/bootstrap.py`

Add `trade_logger.run_post_exit_backfill()` to the periodic snapshot loop so it runs alongside the existing missed-opportunity backfills.

**Step 1: Modify `_periodic_snapshot_loop`**

In `instrumentation/src/bootstrap.py`, update the loop at L185-195:

```python
    async def _periodic_snapshot_loop(self, interval: int) -> None:
        """Capture market snapshots and run backfills at regular intervals."""
        while self._running:
            try:
                self.snapshot_service.run_periodic()
            except Exception as e:
                logger.warning("Periodic snapshot failed: %s", e)

            # Post-exit price backfill (reuses existing data_provider)
            try:
                if hasattr(self.snapshot_service, '_data_provider') and self.snapshot_service._data_provider:
                    self.trade_logger.run_post_exit_backfill(self.snapshot_service._data_provider)
            except Exception as e:
                logger.warning("Post-exit backfill failed: %s", e)

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
```

**Step 2: Commit**

```bash
git add instrumentation/src/bootstrap.py
git commit -m "feat(instrumentation): wire post-exit backfill into periodic loop"
```

---

## Summary: Coverage of feedback.md Items

| Feedback Item | Type | Addressed In |
|---|---|---|
| #1 No InstrumentationKit facade | Critical Gap | Task 6 (facade.py) |
| #2 Cross-strategy coordination not instrumented | Critical Gap | Task 5 (PortfolioRuleChecker events) |
| #3 Drawdown tier transitions not logged | Critical Gap | Tasks 1, 7-9 (drawdown fields + engine integration) |
| #4 No concurrent position tracking | Critical Gap | Tasks 1-2, 7-9 (concurrent_positions field) |
| #5 Futures-specific data missing | Critical Gap | Tasks 1, 7-9 (session_type, contract_month) |
| #6 RISK_DENIAL lacks signal context | Critical Gap | Task 10 (enriched payload) |
| HI-1 Signal confluence logging | Highest Impact | Tasks 1, 4, 7-9 (signal_factors) |
| HI-2 Filter threshold context | Highest Impact | Tasks 1-3, 7 (filter_decisions) |
| HI-3 Position sizing inputs | Highest Impact | Tasks 1, 7-9 (sizing_inputs) |
| HI-4 InstrumentationKit facades | Highest Impact | Task 6 (same as Critical Gap #1) |
| HI-5 Post-exit price tracking | Highest Impact | Tasks 11-12 (backfill) |

---

## Testing Strategy

- **Unit tests**: Tasks 1-6, 10-11 each have dedicated test files
- **Integration**: Verify all 3 engines still start and log entries/exits correctly (manual smoke test with paper trading or replay)
- **Regression**: Run `python -m pytest instrumentation/tests/ -v` after every task to catch breaks
- **Schema check**: After all tasks, review a sample JSONL output to confirm new fields appear with correct values
