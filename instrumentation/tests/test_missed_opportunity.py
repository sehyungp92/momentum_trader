import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
from instrumentation.src.missed_opportunity import (
    MissedOpportunityLogger, MissedOpportunityEvent, SimulationPolicy,
)
from instrumentation.src.market_snapshot import MarketSnapshotService, MarketSnapshot


def _mock_snapshot_service():
    service = MagicMock(spec=MarketSnapshotService)
    service.capture_now.return_value = MarketSnapshot(
        snapshot_id="test_snap", symbol="NQ",
        timestamp="2026-03-01T10:00:00Z",
        bid=20500.0, ask=20500.50, mid=20500.25, spread_bps=0.24,
        last_trade_price=20500.25, atr_14=85.0,
    )
    return service


class TestSimulationPolicy:
    def test_defaults(self):
        p = SimulationPolicy()
        assert p.entry_fill_model == "mid"
        assert p.slippage_bps == 5.0
        assert p.fees_included is True

    def test_to_dict(self):
        p = SimulationPolicy(entry_fill_model="next_trade", slippage_bps=2.0)
        d = p.to_dict()
        assert d["entry_fill_model"] == "next_trade"
        assert d["slippage_bps"] == 2.0


class TestMissedOpportunityLogger:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config = {
            "bot_id": "test_bot",
            "data_dir": self.tmpdir,
            "data_source_id": "test",
        }
        self.snap_service = _mock_snapshot_service()
        self.logger = MissedOpportunityLogger(self.config, self.snap_service)

    def test_log_missed_returns_event(self):
        event = self.logger.log_missed(
            pair="NQ", side="LONG",
            signal="Class M bullish", signal_id="class_m_bull",
            signal_strength=0.75, blocked_by="volume_filter",
            block_reason="Volume below threshold",
            strategy_type="helix", market_regime="trending_up",
        )
        assert event.pair == "NQ"
        assert event.side == "LONG"
        assert event.blocked_by == "volume_filter"
        assert event.signal_strength == 0.75

    def test_log_missed_writes_file(self):
        self.logger.log_missed(
            pair="NQ", side="LONG",
            signal="test", signal_id="test_sig",
            signal_strength=0.5, blocked_by="risk_cap",
        )
        files = list(Path(self.tmpdir).joinpath("missed").glob("*.jsonl"))
        assert len(files) == 1
        data = json.loads(files[0].read_text().strip())
        assert data["blocked_by"] == "risk_cap"

    def test_assumption_tags_present(self):
        event = self.logger.log_missed(
            pair="NQ", side="LONG",
            signal="test", signal_id="test_sig",
            signal_strength=0.5, blocked_by="risk",
        )
        assert len(event.assumption_tags) > 0

    def test_hypothetical_entry_price_computed(self):
        event = self.logger.log_missed(
            pair="NQ", side="LONG",
            signal="test", signal_id="test_sig",
            signal_strength=0.5, blocked_by="filter",
        )
        assert event.hypothetical_entry_price > 0

    def test_simulation_policy_attached(self):
        event = self.logger.log_missed(
            pair="NQ", side="LONG",
            signal="test", signal_id="test_sig",
            signal_strength=0.5, blocked_by="filter",
        )
        assert event.simulation_policy is not None
        assert isinstance(event.simulation_policy, dict)

    def test_backfill_status_pending(self):
        event = self.logger.log_missed(
            pair="NQ", side="LONG",
            signal="test", signal_id="test_sig",
            signal_strength=0.5, blocked_by="filter",
        )
        assert event.backfill_status == "pending"

    def test_event_metadata_present(self):
        event = self.logger.log_missed(
            pair="NQ", side="LONG",
            signal="test", signal_id="test_sig",
            signal_strength=0.5, blocked_by="filter",
        )
        assert event.event_metadata
        assert "event_id" in event.event_metadata

    def test_failure_does_not_crash(self):
        """Missed opportunity logger must never crash."""
        self.snap_service.capture_now.side_effect = Exception("broken")
        event = self.logger.log_missed(
            pair="NQ", side="LONG",
            signal="test", signal_id="test_sig",
            signal_strength=0.5, blocked_by="filter",
        )
        # Should return a minimal event, not crash
        assert isinstance(event, MissedOpportunityEvent)

    def test_pending_backfill_queued(self):
        self.logger.log_missed(
            pair="NQ", side="LONG",
            signal="test", signal_id="test_sig",
            signal_strength=0.5, blocked_by="filter",
        )
        assert len(self.logger._pending_backfills) == 1

    def test_to_dict(self):
        event = self.logger.log_missed(
            pair="NQ", side="LONG",
            signal="test", signal_id="test_sig",
            signal_strength=0.5, blocked_by="filter",
        )
        d = event.to_dict()
        assert isinstance(d, dict)
        assert d["pair"] == "NQ"
        assert "assumption_tags" in d
