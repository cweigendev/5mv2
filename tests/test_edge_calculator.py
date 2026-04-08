"""Tests for edge calculation and opportunity classification."""

from src.strategy.edge_calculator import EdgeCalculator, OpportunityType


def test_no_edge_when_ask_above_fair():
    calc = EdgeCalculator(min_edge_threshold=0.20)
    result = calc.calculate(
        fair_prob_up=0.50,
        fair_prob_down=0.50,
        market_ask_up=0.55,
        market_ask_down=0.55,
    )
    assert result.opportunity == OpportunityType.NONE
    assert result.up_edge < 0
    assert result.down_edge < 0


def test_directional_when_edge_above_threshold():
    calc = EdgeCalculator(min_edge_threshold=0.20)
    result = calc.calculate(
        fair_prob_up=0.70,
        fair_prob_down=0.30,
        market_ask_up=0.40,
        market_ask_down=0.80,
    )
    assert result.opportunity == OpportunityType.DIRECTIONAL
    assert result.best_side == "up"
    assert result.best_edge >= 0.20


def test_stale_snipe_on_extreme_edge():
    calc = EdgeCalculator(min_edge_threshold=0.20, stale_snipe_threshold=0.40)
    result = calc.calculate(
        fair_prob_up=0.50,
        fair_prob_down=0.50,
        market_ask_up=0.05,
        market_ask_down=0.05,
    )
    assert result.opportunity == OpportunityType.STALE_SNIPE
    assert result.best_edge >= 0.40


def test_spread_capture_when_cheap_combined():
    calc = EdgeCalculator(min_edge_threshold=0.20, max_paired_cost=0.95)
    result = calc.calculate(
        fair_prob_up=0.50,
        fair_prob_down=0.50,
        market_ask_up=0.45,
        market_ask_down=0.45,
    )
    assert result.paired_cost == 0.90
    assert result.opportunity == OpportunityType.SPREAD_CAPTURE


def test_no_spread_capture_when_expensive():
    calc = EdgeCalculator(min_edge_threshold=0.20, max_paired_cost=0.95)
    result = calc.calculate(
        fair_prob_up=0.50,
        fair_prob_down=0.50,
        market_ask_up=0.50,
        market_ask_down=0.50,
    )
    assert result.paired_cost == 1.00
    assert result.opportunity == OpportunityType.NONE


def test_best_side_selection():
    calc = EdgeCalculator(min_edge_threshold=0.10)
    result = calc.calculate(
        fair_prob_up=0.30,
        fair_prob_down=0.70,
        market_ask_up=0.25,
        market_ask_down=0.40,
    )
    assert result.best_side == "down"
    assert result.best_edge == result.down_edge
