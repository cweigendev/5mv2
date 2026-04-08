"""Tests for risk management controls."""

import time
from src.strategy.risk_manager import RiskManager, MarketPosition


def test_budget_cap_enforced():
    rm = RiskManager(per_market_budget=100.0)
    rm.record_fill("m1", "BTC", "up", 50, 1.80)  # $90 spent
    can, reason = rm.can_add_to_position("m1", "up", 20, 1.0)  # +$20 = $110
    assert not can
    assert "budget" in reason.lower()


def test_concurrent_market_limit():
    rm = RiskManager(max_concurrent_markets=2)
    rm.record_fill("m1", "BTC", "up", 10, 0.50)
    rm.record_fill("m2", "ETH", "up", 10, 0.50)
    can, reason = rm.can_enter_market("m3", "SOL")
    assert not can
    assert "concurrent" in reason.lower()


def test_session_pnl_circuit_breaker():
    rm = RiskManager(max_daily_loss=100.0)
    rm.record_market_resolution("m1", pnl=-60)
    rm.record_market_resolution("m2", pnl=-50)
    # Now at -$110, exceeds $100 limit
    can, reason = rm.can_enter_market("m3", "BTC")
    assert not can
    assert "loss limit" in reason.lower()


def test_paired_cost_discipline():
    rm = RiskManager(max_paired_cost=0.95)
    rm.record_fill("m1", "BTC", "up", 100, 0.50)  # VWAP = 0.50
    can, reason = rm.can_add_to_position("m1", "down", 10, 0.50)  # paired = 1.00
    assert not can
    assert "paired cost" in reason.lower()


def test_paired_cost_allows_cheap():
    rm = RiskManager(max_paired_cost=0.95)
    rm.record_fill("m1", "BTC", "up", 100, 0.50)
    can, reason = rm.can_add_to_position("m1", "down", 10, 0.40)  # paired = 0.90
    assert can


def test_win_rate_tracking():
    rm = RiskManager()
    rm.record_market_resolution("m1", pnl=10)
    rm.record_market_resolution("m2", pnl=-5)
    rm.record_market_resolution("m3", pnl=8)
    assert rm.win_rate == 2 / 3
    assert rm.session_pnl == 13


def test_consecutive_loss_cooldown():
    rm = RiskManager(consecutive_loss_cooldown=3, cooldown_duration_seconds=60)
    rm.record_market_resolution("m1", pnl=-10)
    rm.record_market_resolution("m2", pnl=-10)
    rm.record_market_resolution("m3", pnl=-10)
    can, reason = rm.can_enter_market("m4", "BTC")
    assert not can
    assert "cooldown" in reason.lower()


def test_asset_exposure_limit():
    rm = RiskManager(max_asset_exposure=200.0)
    rm.record_fill("m1", "BTC", "up", 100, 1.50)  # $150
    rm.record_fill("m2", "BTC", "down", 50, 1.20)  # +$60 = $210
    can, reason = rm.can_enter_market("m3", "BTC")
    assert not can
    assert "exposure" in reason.lower()


def test_position_record_fill_vwap():
    pos = MarketPosition(market_id="m1", asset="BTC")
    pos.record_fill("up", 10, 0.40)  # 10 shares @ $0.40
    assert pos.up_vwap == 0.40
    pos.record_fill("up", 10, 0.60)  # 10 more @ $0.60
    assert abs(pos.up_vwap - 0.50) < 0.001  # VWAP should be $0.50
    assert pos.up_shares == 20
    assert abs(pos.up_spend - 10.0) < 0.001
