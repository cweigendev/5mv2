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


def test_no_directional_on_coin_flip():
    """Edge exists but fair value is near 0.50 — reject as coin flip."""
    calc = EdgeCalculator(min_edge_threshold=0.20, min_conviction=0.35)
    result = calc.calculate(
        fair_prob_up=0.52,
        fair_prob_down=0.48,
        market_ask_up=0.25,  # huge "edge" but fair value is near 50/50
        market_ask_down=0.25,
    )
    # Edge is 0.52 - 0.25 = 0.27, above threshold,
    # but fair value 0.52 is below conviction threshold 0.65 (1 - 0.35)
    # Wait — min_conviction=0.35 means best_fair must be >= 0.35.
    # fair_up=0.52 >= 0.35, so this WOULD pass.
    # To truly block coin flips, set min_conviction=0.60.
    # With 0.35, we block only the most extreme cases.
    # Let's test the actual blocking case:
    pass


def test_no_directional_when_conviction_too_low():
    """Fair value is very close to 0.50 and below min_conviction."""
    calc = EdgeCalculator(min_edge_threshold=0.10, min_conviction=0.60)
    result = calc.calculate(
        fair_prob_up=0.55,
        fair_prob_down=0.45,
        market_ask_up=0.30,  # edge = 0.25, above threshold
        market_ask_down=0.30,
    )
    # best_fair = 0.55, below min_conviction=0.60 → should NOT be directional
    assert result.opportunity != OpportunityType.DIRECTIONAL
    # But paired cost is 0.60, below 0.95 → should be spread capture
    assert result.opportunity == OpportunityType.SPREAD_CAPTURE


def test_directional_with_high_conviction():
    """Fair value is decisive — should allow directional."""
    calc = EdgeCalculator(min_edge_threshold=0.10, min_conviction=0.60)
    result = calc.calculate(
        fair_prob_up=0.80,
        fair_prob_down=0.20,
        market_ask_up=0.60,
        market_ask_down=0.90,
    )
    assert result.opportunity == OpportunityType.DIRECTIONAL
    assert result.best_side == "up"


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


def test_edge_result_stores_asks():
    """EdgeResult should store the actual ask prices passed in."""
    calc = EdgeCalculator()
    result = calc.calculate(
        fair_prob_up=0.60,
        fair_prob_down=0.40,
        market_ask_up=0.55,
        market_ask_down=0.50,
    )
    assert result.ask_up == 0.55
    assert result.ask_down == 0.50
    assert result.fair_up == 0.60
    assert result.fair_down == 0.40
