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
        # Get experiment tracking from manager's config
        self._experiment_id = None
        self._experiment_variant = None
        if manager:
            try:
                config = getattr(manager, '_config', {})
                self._experiment_id = config.get("experiment_id")
                self._experiment_variant = config.get("experiment_variant")
            except Exception:
                pass

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
        portfolio_state: Optional[dict] = None,
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
                strategy_params=strategy_params or {},
                expected_entry_price=expected_entry_price,
                market_regime=regime,
                bar_id=bar_id,
                exchange_timestamp=exchange_timestamp,
                entry_latency_ms=entry_latency_ms,
                portfolio_state=portfolio_state,
            )

            # Patch enriched fields onto the TradeEvent stored in _open_trades
            trade = self._mgr.trade_logger._open_trades.get(trade_id)
            if trade:
                trade.signal_factors = signal_factors or []
                trade.filter_decisions = filter_decisions or []
                trade.sizing_inputs = sizing_inputs
                trade.portfolio_state_at_entry = portfolio_state
                trade.session_type = session_type
                trade.contract_month = contract_month
                trade.margin_used_pct = margin_used_pct
                trade.concurrent_positions_at_entry = concurrent_positions
                trade.drawdown_pct = drawdown_pct
                trade.drawdown_tier = drawdown_tier
                trade.drawdown_size_mult = drawdown_size_mult
                trade.experiment_id = self._experiment_id
                trade.experiment_variant = self._experiment_variant

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
        mfe_r: Optional[float] = None,
        mae_r: Optional[float] = None,
        mfe_price: Optional[float] = None,
        mae_price: Optional[float] = None,
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
                mfe_r=mfe_r,
                mae_r=mae_r,
                mfe_price=mfe_price,
                mae_price=mae_price,
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

            # Enrich strategy_params with context that doesn't have dedicated fields yet
            enriched_params = dict(strategy_params or {})
            if concurrent_positions is not None:
                enriched_params["_concurrent_positions"] = concurrent_positions
            if session_type:
                enriched_params["_session_type"] = session_type
            if drawdown_pct is not None:
                enriched_params["_drawdown_pct"] = drawdown_pct
                enriched_params["_drawdown_tier"] = drawdown_tier
            if filter_decisions:
                enriched_params["_filter_decisions"] = filter_decisions
            if coordination_context:
                enriched_params["_coordination_context"] = coordination_context

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
