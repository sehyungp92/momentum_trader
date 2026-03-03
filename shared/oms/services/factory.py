"""OMS factory for proper initialization with all dependencies."""
import logging
from typing import Optional

import asyncpg

from ..config.risk_config import RiskConfig, StrategyRiskConfig
from ..engine.fill_processor import FillProcessor
from ..events.bus import EventBus
from ..execution.router import ExecutionRouter
from ..intent.handler import IntentHandler
from ..models.order import OrderRole, OrderSide
from ..models.position import Position
from ..models.risk_state import StrategyRiskState, PortfolioRiskState
from ..persistence.in_memory import InMemoryRepository
from ..persistence.repository import OMSRepository
from ..reconciliation.orchestrator import ReconciliationOrchestrator
from ..risk.calendar import EventCalendar
from ..risk.gateway import RiskGateway
from .oms_service import OMSService

logger = logging.getLogger(__name__)


async def build_oms_service(
    adapter,  # IBKRExecutionAdapter
    strategy_id: str,
    unit_risk_dollars: float,
    daily_stop_R: float = 2.0,
    heat_cap_R: float = 1.25,
    portfolio_daily_stop_R: float = 3.0,
    calendar: Optional[EventCalendar] = None,
    recon_interval_s: float = 120.0,
    db_pool: Optional[asyncpg.Pool] = None,
    portfolio_rules_config=None,  # Optional[PortfolioRulesConfig]
    get_current_equity: Optional[callable] = None,
) -> OMSService:
    """Build a fully wired OMS service.

    Args:
        adapter: IBKRExecutionAdapter instance
        strategy_id: Strategy identifier
        unit_risk_dollars: Dollar risk per 1R unit for position sizing
        daily_stop_R: Strategy daily stop in R units
        heat_cap_R: Portfolio heat cap in R units
        portfolio_daily_stop_R: Portfolio daily stop in R units
        calendar: Optional event calendar for blackouts
        recon_interval_s: Reconciliation interval in seconds
        db_pool: Optional asyncpg pool for PostgreSQL persistence.
                 If provided, uses OMSRepository; otherwise InMemoryRepository.

    Returns:
        Fully initialized OMSService ready for start()
    """
    # Event bus
    bus = EventBus()

    # Repository: use PostgreSQL if pool provided, otherwise in-memory
    if db_pool is not None:
        repo = OMSRepository(db_pool)
        logger.info(f"Using PostgreSQL repository for strategy {strategy_id}")
    else:
        repo = InMemoryRepository()
        logger.info(f"Using in-memory repository for strategy {strategy_id}")

    # Risk configuration
    strat_cfg = StrategyRiskConfig(
        strategy_id=strategy_id,
        daily_stop_R=daily_stop_R,
        unit_risk_dollars=unit_risk_dollars,
    )
    risk_config = RiskConfig(
        heat_cap_R=heat_cap_R,
        portfolio_daily_stop_R=portfolio_daily_stop_R,
        strategy_configs={strategy_id: strat_cfg},
    )

    # Event calendar (empty if not provided)
    if calendar is None:
        calendar = EventCalendar()

    # Risk state providers
    from datetime import date
    strategy_risk_states: dict[str, StrategyRiskState] = {}
    portfolio_risk_state = PortfolioRiskState(trade_date=date.today())
    # Track open positions per strategy for exit P&L computation
    open_positions: dict[str, dict] = {}

    async def get_strategy_risk(sid: str) -> StrategyRiskState:
        # L1 fix: reset risk state at date boundary
        today = date.today()
        if sid in strategy_risk_states:
            existing = strategy_risk_states[sid]
            if existing.trade_date != today:
                logger.info(f"Date boundary detected for {sid}: resetting daily risk state")
                strategy_risk_states[sid] = StrategyRiskState(
                    strategy_id=sid, trade_date=today,
                    open_risk_dollars=existing.open_risk_dollars,
                    open_risk_R=existing.open_risk_R,
                )
        if sid not in strategy_risk_states:
            strategy_risk_states[sid] = StrategyRiskState(strategy_id=sid, trade_date=today)
        return strategy_risk_states[sid]

    async def get_portfolio_risk() -> PortfolioRiskState:
        # L1 fix: reset portfolio risk state at date boundary
        today = date.today()
        if portfolio_risk_state.trade_date != today:
            logger.info("Date boundary detected: resetting portfolio daily risk state")
            # Weekly reset on Monday (weekday 0)
            if today.weekday() == 0:
                logger.info("Monday weekly reset: weekly_R %.2f → 0.0",
                            portfolio_risk_state.weekly_realized_R)
                portfolio_risk_state.weekly_realized_pnl = 0.0
                portfolio_risk_state.weekly_realized_R = 0.0
            portfolio_risk_state.trade_date = today
            portfolio_risk_state.daily_realized_pnl = 0.0
            portfolio_risk_state.daily_realized_R = 0.0
            portfolio_risk_state.strategy_daily_pnl = {}
            portfolio_risk_state.halted = False
            portfolio_risk_state.halt_reason = ""
        portfolio_risk_state.pending_entry_risk_R = await repo.get_pending_entry_risk_R(
            unit_risk_dollars
        )
        return portfolio_risk_state

    async def get_working_order_count(sid: str) -> int:
        return await repo.count_working_orders(sid)

    # Fill processor for OMS order state updates
    fill_proc = FillProcessor(repo)

    # Portfolio rules checker (cross-strategy coordination via shared DB)
    portfolio_checker = None
    if portfolio_rules_config is not None and db_pool is not None:
        from ..persistence.postgres import PgStore as _PgStore
        from ..risk.portfolio_rules import PortfolioRuleChecker

        _pg = _PgStore(db_pool)
        portfolio_checker = PortfolioRuleChecker(
            config=portfolio_rules_config,
            get_strategy_signal=_pg.get_strategy_signal,
            get_directional_risk_R=_pg.get_directional_risk_R,
            get_current_equity=get_current_equity or (lambda: 10_000.0),
        )
        logger.info("Portfolio rules enabled for %s", strategy_id)

    # Risk gateway
    risk_gateway = RiskGateway(
        config=risk_config,
        calendar=calendar,
        get_strategy_risk=get_strategy_risk,
        get_portfolio_risk=get_portfolio_risk,
        get_working_order_count=get_working_order_count,
        portfolio_checker=portfolio_checker,
    )

    # Execution router
    router = ExecutionRouter(adapter, repo)

    # Intent handler
    handler = IntentHandler(risk_gateway, router, repo, bus)

    # Reconciler
    reconciler = ReconciliationOrchestrator(adapter, repo, bus)

    # C4 fix: Order timeout monitor for stuck ROUTED / CANCEL_REQUESTED states
    from ..engine.timeout_monitor import OrderTimeoutMonitor
    timeout_monitor = OrderTimeoutMonitor(repo, bus)

    # Wire adapter callbacks to bus (with risk state updates)
    _wire_adapter_callbacks(
        adapter, bus, repo, fill_proc, router,
        strategy_risk_states, portfolio_risk_state, unit_risk_dollars, open_positions,
    )

    # Build OMS service
    oms = OMSService(
        intent_handler=handler,
        bus=bus,
        reconciler=reconciler,
        router=router,
        recon_interval_s=recon_interval_s,
        timeout_monitor=timeout_monitor,
    )

    logger.info(f"OMS factory built for strategy {strategy_id}")
    return oms


def _task_exception_handler(task: "asyncio.Task") -> None:
    """C5 fix: Log exceptions from fire-and-forget callback tasks.

    Without this, exceptions in adapter callbacks are silently swallowed,
    which can cause fills/acks/rejects to be lost.
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            f"CRITICAL: Unhandled exception in OMS callback task: {exc}",
            exc_info=exc,
        )


def _wire_adapter_callbacks(
    adapter, bus: EventBus, repo, fill_proc: FillProcessor, router,
    strategy_risk_states, portfolio_risk_state, unit_risk_dollars, open_positions,
) -> None:
    """Wire IBKRExecutionAdapter callbacks to OMS event bus.

    Callbacks look up the order from the repository to get the strategy_id,
    then emit appropriate events to the bus for strategy routing.
    Also wires FillProcessor for OMS order state and updates risk state.
    """
    import asyncio
    from ..models.events import OMSEvent, OMSEventType
    from ..models.order import OrderStatus
    from ..engine.state_machine import transition
    from datetime import datetime, date, timezone

    # C5 fix: store task references to prevent GC and enable exception handling
    _background_tasks: set[asyncio.Task] = set()

    def _create_tracked_task(coro) -> asyncio.Task:
        """Create an asyncio task with exception handler and prevent GC."""
        task = asyncio.create_task(coro)
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        task.add_done_callback(_task_exception_handler)
        return task

    def _get_running_loop():
        """Get the running event loop, or None if not in async context."""
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return None

    # H7 fix: retry config for pacing errors
    MAX_PACING_RETRIES = 3
    PACING_RETRY_BASE_DELAY_S = 2.0

    def on_ack(oms_order_id: str, broker_ref) -> None:
        """Handle order acknowledgment from broker."""
        loop = _get_running_loop()
        if loop is None:
            logger.debug(f"Adapter ack (no loop): {oms_order_id}")
            return

        async def _emit_ack():
            order = await repo.get_order(oms_order_id)
            if order:
                # C6 fix: use state machine transition instead of direct assignment
                if transition(order, OrderStatus.ACKED):
                    order.broker_order_id = broker_ref.broker_order_id if hasattr(broker_ref, 'broker_order_id') else int(broker_ref)
                    order.last_update_at = datetime.now(timezone.utc)
                    await repo.save_order(order)
                    bus.emit_order_event(order)
                    logger.debug(f"Adapter ack emitted: {oms_order_id} for {order.strategy_id}")
                else:
                    logger.warning(
                        f"Adapter ack: invalid transition for {oms_order_id} "
                        f"(current status={order.status.value})"
                    )
            else:
                logger.warning(f"Adapter ack for unknown order: {oms_order_id}")

        _create_tracked_task(_emit_ack())

    def on_reject(oms_order_id: str, reason: str, error_code: int, retryable: bool) -> None:
        """Handle order rejection from broker."""
        loop = _get_running_loop()
        if loop is None:
            logger.warning(f"Adapter reject (no loop): {oms_order_id} - {reason}")
            return

        async def _emit_reject():
            order = await repo.get_order(oms_order_id)
            if not order:
                logger.warning(f"Adapter reject for unknown order: {oms_order_id} - {reason}")
                return

            # H7 fix: retry for retryable pacing errors
            if retryable and error_code > 0:
                retry_count = getattr(order, '_retry_count', 0)
                if retry_count < MAX_PACING_RETRIES:
                    order._retry_count = retry_count + 1
                    delay = PACING_RETRY_BASE_DELAY_S * (2 ** retry_count)
                    logger.warning(
                        f"Retryable reject for {oms_order_id} (code={error_code}): "
                        f"retry {retry_count + 1}/{MAX_PACING_RETRIES} in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
                    # Re-route through the execution router
                    try:
                        # Reset status to RISK_APPROVED for re-routing
                        order.status = OrderStatus.RISK_APPROVED
                        order.last_update_at = datetime.now(timezone.utc)
                        await repo.save_order(order)
                        await router.route(order)
                        return
                    except Exception as e:
                        logger.error(f"Retry failed for {oms_order_id}: {e}")

            # Terminal rejection
            if transition(order, OrderStatus.REJECTED):
                order.rejection_reason = reason
                order.last_update_at = datetime.now(timezone.utc)
                await repo.save_order(order)
                bus.emit_order_event(order)
                logger.warning(f"Adapter reject emitted: {oms_order_id} for {order.strategy_id} - {reason}")
            else:
                logger.warning(
                    f"Adapter reject: invalid transition for {oms_order_id} "
                    f"(current status={order.status.value})"
                )

        _create_tracked_task(_emit_reject())

    def on_fill(
        oms_order_id: str,
        exec_id: str,
        price: float,
        qty: float,
        timestamp,
        commission: float,
    ) -> None:
        """Handle fill from broker - update OMS order state, risk state, emit event."""
        loop = _get_running_loop()
        if loop is None:
            logger.info(f"Adapter fill (no loop): {oms_order_id} {qty}@{price}")
            return

        async def _emit_fill():
            order = await repo.get_order(oms_order_id)
            if not order:
                logger.warning(f"Adapter fill for unknown order: {oms_order_id}")
                return

            # 1. Update OMS order state (filled_qty, status, avg_fill_price)
            fill_ts = timestamp if isinstance(timestamp, datetime) else datetime.now(timezone.utc)
            await fill_proc.process_fill(oms_order_id, exec_id, price, qty, fill_ts, commission)

            # 2. Emit fill event to strategy
            fill_data = {
                "exec_id": exec_id,
                "price": price,
                "qty": qty,
                "timestamp": timestamp.isoformat() if hasattr(timestamp, 'isoformat') else str(timestamp),
                "commission": commission,
                "client_order_id": getattr(order, 'client_order_id', ""),
            }
            bus.emit_fill_event(order.strategy_id, oms_order_id, fill_data)

            # 3. Update risk state
            sid = order.strategy_id
            if sid not in strategy_risk_states:
                strategy_risk_states[sid] = StrategyRiskState(
                    strategy_id=sid, trade_date=date.today()
                )
            strat_risk = strategy_risk_states[sid]

            if order.role == OrderRole.ENTRY and order.risk_context:
                risk_per_contract = (
                    order.risk_context.risk_dollars / order.qty if order.qty > 0 else 0
                )
                fill_risk = risk_per_contract * qty
                fill_risk_R = fill_risk / unit_risk_dollars if unit_risk_dollars > 0 else 0

                strat_risk.open_risk_dollars += fill_risk
                strat_risk.open_risk_R += fill_risk_R
                portfolio_risk_state.open_risk_dollars += fill_risk
                portfolio_risk_state.open_risk_R += fill_risk_R

                # Track entry for exit P&L computation
                pos = open_positions.get(sid)
                pv = order.instrument.point_value if order.instrument else 1.0
                if pos is None:
                    open_positions[sid] = {
                        "entry_price": price,
                        "risk_per_contract_R": fill_risk_R / qty if qty > 0 else 0,
                        "point_value": pv,
                        "side": order.side,
                        "open_qty": qty,
                    }
                else:
                    old_total = pos["entry_price"] * pos["open_qty"]
                    pos["open_qty"] += qty
                    pos["entry_price"] = (old_total + price * qty) / pos["open_qty"]

                # Write cross-strategy signal to shared DB
                if db_pool is not None:
                    try:
                        from ..persistence.postgres import PgStore as _PgS
                        _pg_sig = _PgS(db_pool)
                        direction = "LONG" if order.side == OrderSide.BUY else "SHORT"
                        await _pg_sig.upsert_strategy_signal(sid, direction, fill_ts)
                    except Exception as e:
                        logger.warning("Failed to write strategy signal: %s", e)

            elif order.role in (OrderRole.EXIT, OrderRole.STOP, OrderRole.TP):
                pos = open_positions.get(sid)
                if pos:
                    # Reduce open risk
                    released_R = pos["risk_per_contract_R"] * qty
                    released_dollars = released_R * unit_risk_dollars

                    strat_risk.open_risk_R = max(0, strat_risk.open_risk_R - released_R)
                    strat_risk.open_risk_dollars = max(0, strat_risk.open_risk_dollars - released_dollars)
                    portfolio_risk_state.open_risk_R = max(0, portfolio_risk_state.open_risk_R - released_R)
                    portfolio_risk_state.open_risk_dollars = max(0, portfolio_risk_state.open_risk_dollars - released_dollars)

                    # Compute realized P&L
                    pv = pos["point_value"]
                    if pos["side"] == OrderSide.BUY:
                        pnl = (price - pos["entry_price"]) * pv * qty
                    else:
                        pnl = (pos["entry_price"] - price) * pv * qty

                    pnl_R = pnl / unit_risk_dollars if unit_risk_dollars > 0 else 0
                    strat_risk.daily_realized_pnl += pnl
                    strat_risk.daily_realized_R += pnl_R
                    portfolio_risk_state.daily_realized_pnl += pnl
                    portfolio_risk_state.daily_realized_R += pnl_R
                    # Consolidated weekly tracking
                    portfolio_risk_state.weekly_realized_pnl += pnl
                    portfolio_risk_state.weekly_realized_R += pnl_R
                    # Per-strategy daily breakdown
                    if portfolio_risk_state.strategy_daily_pnl is None:
                        portfolio_risk_state.strategy_daily_pnl = {}
                    portfolio_risk_state.strategy_daily_pnl[sid] = (
                        portfolio_risk_state.strategy_daily_pnl.get(sid, 0.0) + pnl
                    )

                    pos["open_qty"] = max(0, pos["open_qty"] - qty)
                    if pos["open_qty"] <= 0:
                        del open_positions[sid]

            # 4. Update OMS position for FLATTEN handler and reconciliation
            instr_sym = order.instrument.symbol if order.instrument else ""
            pos_data = open_positions.get(sid)
            if pos_data:
                net = pos_data["open_qty"] if pos_data["side"] == OrderSide.BUY else -pos_data["open_qty"]
                oms_pos = Position(
                    account_id=order.account_id,
                    instrument_symbol=instr_sym,
                    strategy_id=sid,
                    net_qty=net,
                    avg_price=pos_data["entry_price"],
                    realized_pnl=strat_risk.daily_realized_pnl,
                    open_risk_dollars=strat_risk.open_risk_dollars,
                    open_risk_R=strat_risk.open_risk_R,
                    last_update_at=fill_ts,
                )
            else:
                oms_pos = Position(
                    account_id=order.account_id,
                    instrument_symbol=instr_sym,
                    strategy_id=sid,
                    net_qty=0,
                    realized_pnl=strat_risk.daily_realized_pnl,
                    last_update_at=fill_ts,
                )
            await repo.save_position(oms_pos)

            logger.info(f"Adapter fill processed: {oms_order_id} {qty}@{price} for {sid}")

        _create_tracked_task(_emit_fill())

    def on_status(oms_order_id: str, status: str, remaining: float) -> None:
        """Handle status update from broker."""
        loop = _get_running_loop()
        if loop is None:
            logger.debug(f"Adapter status (no loop): {oms_order_id} {status}")
            return

        async def _emit_status():
            order = await repo.get_order(oms_order_id)
            if order:
                # Map broker status string to OrderStatus
                status_map = {
                    "Submitted": OrderStatus.WORKING,
                    "PreSubmitted": OrderStatus.ROUTED,
                    "Filled": OrderStatus.FILLED,
                    "Cancelled": OrderStatus.CANCELLED,
                    "ApiCancelled": OrderStatus.CANCELLED,
                    "PendingCancel": OrderStatus.CANCEL_REQUESTED,
                }
                new_status = status_map.get(status)
                if new_status and new_status != order.status:
                    # C6 fix: use state machine transition instead of direct assignment
                    if transition(order, new_status):
                        order.remaining_qty = int(remaining)
                        order.last_update_at = datetime.now(timezone.utc)
                        await repo.save_order(order)
                        bus.emit_order_event(order)
                        logger.debug(f"Adapter status emitted: {oms_order_id} {status} for {order.strategy_id}")
                    else:
                        logger.warning(
                            f"Adapter status: invalid transition for {oms_order_id} "
                            f"{order.status.value} -> {new_status.value}"
                        )
            else:
                logger.debug(f"Adapter status for unknown order: {oms_order_id} {status}")

        _create_tracked_task(_emit_status())

    adapter.on_ack = on_ack
    adapter.on_reject = on_reject
    adapter.on_fill = on_fill
    adapter.on_status = on_status
