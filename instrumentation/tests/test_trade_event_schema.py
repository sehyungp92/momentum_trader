"""Tests for MFE/MAE and exit_efficiency fields in TradeEvent schema."""
from instrumentation.src.trade_logger import TradeEvent


def test_trade_event_has_mfe_mae_fields():
    te = TradeEvent(trade_id="t1", event_metadata={}, entry_snapshot={})
    assert te.mfe_r is None
    assert te.mae_r is None
    assert te.mfe_price is None
    assert te.mae_price is None


def test_trade_event_has_exit_efficiency():
    te = TradeEvent(trade_id="t1", event_metadata={}, entry_snapshot={},
                    mfe_r=2.0, pnl_pct=1.5, entry_price=21000.0)
    assert te.exit_efficiency is None  # computed at exit, not set at init


def test_trade_event_mfe_mae_in_dict():
    te = TradeEvent(trade_id="t1", event_metadata={}, entry_snapshot={},
                    mfe_r=1.5, mae_r=0.3)
    d = te.to_dict()
    assert d["mfe_r"] == 1.5
    assert d["mae_r"] == 0.3


def test_trade_event_exit_efficiency_in_dict():
    te = TradeEvent(trade_id="t1", event_metadata={}, entry_snapshot={},
                    exit_efficiency=0.75)
    d = te.to_dict()
    assert d["exit_efficiency"] == 0.75


def test_trade_event_mfe_mae_defaults_none_in_dict():
    te = TradeEvent(trade_id="t1", event_metadata={}, entry_snapshot={})
    d = te.to_dict()
    assert d["mfe_r"] is None
    assert d["mae_r"] is None
    assert d["mfe_price"] is None
    assert d["mae_price"] is None
    assert d["exit_efficiency"] is None
