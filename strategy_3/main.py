"""Vdubus NQ v4.0 — entry point that wires IB session, OMS, and engine."""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

logger = logging.getLogger("vdubnq_3")


async def main() -> None:
    """Wire up IB session, OMS, instruments, and start the engine."""
    from shared.ibkr_core.config.loader import IBKRConfig
    from shared.ibkr_core.client.session import IBSession
    from shared.ibkr_core.mapping.contract_factory import ContractFactory
    from shared.ibkr_core.adapters.execution_adapter import IBKRExecutionAdapter
    from shared.oms.services.factory import build_oms_service
    from shared.oms.risk.calculator import RiskCalculator
    from shared.services.bootstrap import bootstrap_database

    from .config import STRATEGY_ID, BASE_RISK_PCT, HEAT_CAP_MULT, build_instruments
    from .engine import VdubNQv4Engine

    # 1. Load IBKR config
    config_dir = Path(__file__).resolve().parent.parent / "config"
    ibkr_config = IBKRConfig(config_dir)
    logger.info("IBKR config: %s:%d", ibkr_config.profile.host, ibkr_config.profile.port)

    # 2. Connect IB session
    session = IBSession(ibkr_config)
    await session.start()
    await session.wait_ready()
    logger.info("IB session connected")

    # 3. Execution adapter
    contract_factory = ContractFactory(
        ib=session.ib, templates=ibkr_config.contracts, routes=ibkr_config.routes,
    )
    adapter = IBKRExecutionAdapter(
        session=session, contract_factory=contract_factory,
        account=ibkr_config.profile.account_id,
    )

    # 4. Bootstrap database
    bootstrap_ctx = await bootstrap_database()
    trade_recorder = bootstrap_ctx.trade_recorder

    # 5. Register instruments
    instruments = build_instruments()
    logger.info("Registered %d instruments", len(instruments))

    # 6. Fetch equity
    equity = 100_000.0
    try:
        accounts = session.ib.managedAccounts()
        if accounts:
            summary = await session.ib.accountSummaryAsync(accounts[0])
            for item in summary:
                if item.tag == "NetLiquidation" and item.currency == "USD":
                    equity = float(item.value)
                    logger.info("Equity: $%.2f", equity)
                    break
    except Exception:
        logger.warning("Using default equity $%.2f", equity)

    # 7. Build OMS
    unit_risk = RiskCalculator.compute_unit_risk_dollars(
        nav=equity, unit_risk_pct=BASE_RISK_PCT)

    # Portfolio v4 cross-strategy rules
    from shared.oms.risk.portfolio_rules import PortfolioRulesConfig
    portfolio_rules = PortfolioRulesConfig(initial_equity=equity)

    oms = await build_oms_service(
        adapter=adapter,
        strategy_id=STRATEGY_ID,
        unit_risk_dollars=unit_risk,
        daily_stop_R=2.5,
        heat_cap_R=3.5,
        portfolio_daily_stop_R=1.5,  # v6: tightened from 2.5
        db_pool=bootstrap_ctx.pool,
        portfolio_rules_config=portfolio_rules,
        get_current_equity=lambda: equity,
    )
    await oms.start()
    logger.info("OMS started")

    # Instrumentation
    instr = None
    try:
        from instrumentation.src.bootstrap import InstrumentationManager
        instr = InstrumentationManager(oms, STRATEGY_ID, strategy_type="vdubus")
        await instr.start()
    except Exception as e:
        logger.warning("Instrumentation init failed (non-fatal): %s", e)

    # 8. Create and start engine
    engine = VdubNQv4Engine(
        ib_session=session,
        oms_service=oms,
        instruments=instruments,
        trade_recorder=trade_recorder,
        equity=equity,
        instrumentation=instr,
    )
    await engine.start()

    # 9. Start heartbeat
    heartbeat_task = None
    if bootstrap_ctx.has_db:
        from shared.services.heartbeat import emit_heartbeat

        async def _heartbeat_loop():
            while True:
                try:
                    await emit_heartbeat(bootstrap_ctx.pg_store, STRATEGY_ID, mode="RUNNING")
                except Exception as e:
                    logger.warning("Heartbeat failed: %s", e)
                await asyncio.sleep(30)

        heartbeat_task = asyncio.create_task(_heartbeat_loop())

    # 10. Wait for shutdown
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    logger.info("VdubNQv4 (strategy_3) running — Ctrl+C to stop")
    try:
        await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass

    if heartbeat_task:
        heartbeat_task.cancel()

    # 10. Graceful shutdown
    logger.info("Shutting down")
    if instr:
        try:
            await instr.stop()
        except Exception as e:
            logger.warning("Instrumentation shutdown error: %s", e)
    await engine.stop()
    await oms.stop()
    await session.stop()
    if bootstrap_ctx.has_db:
        from shared.services.bootstrap import shutdown_database
        await shutdown_database(bootstrap_ctx)
    logger.info("Shutdown complete")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


if __name__ == "__main__":
    _setup_logging()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
