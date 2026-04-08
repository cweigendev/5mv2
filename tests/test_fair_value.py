"""Tests for the fair value probability model."""

import math
from src.strategy.fair_value import FairValueModel


def test_equal_price_gives_fifty_fifty():
    """When spot = reference, fair probability should be ~50/50."""
    model = FairValueModel()
    prob_up, prob_down = model.compute(
        spot_price=50000.0,
        reference_price=50000.0,
        seconds_remaining=150,
    )
    assert abs(prob_up - 0.5) < 0.01
    assert abs(prob_down - 0.5) < 0.01


def test_higher_spot_favors_up():
    """When spot > reference, P(Up) should be > 0.5."""
    model = FairValueModel()
    # Feed some prices to build volatility
    for p in [50000 + i * 10 for i in range(31)]:
        model.update_price(p)
    prob_up, prob_down = model.compute(
        spot_price=50300.0,
        reference_price=50000.0,
        seconds_remaining=150,
    )
    assert prob_up > 0.5
    assert prob_down < 0.5


def test_lower_spot_favors_down():
    """When spot < reference, P(Down) should be > 0.5."""
    model = FairValueModel()
    for p in [50000 - i * 10 for i in range(31)]:
        model.update_price(p)
    prob_up, prob_down = model.compute(
        spot_price=49700.0,
        reference_price=50000.0,
        seconds_remaining=150,
    )
    assert prob_up < 0.5
    assert prob_down > 0.5


def test_probabilities_sum_to_one():
    """Fair probabilities must always sum to 1.0."""
    model = FairValueModel()
    for spot, ref, remaining in [
        (50100, 50000, 200),
        (49800, 50000, 60),
        (50000, 50000, 1),
        (51000, 50000, 300),
    ]:
        up, down = model.compute(spot, ref, remaining)
        assert abs(up + down - 1.0) < 1e-10


def test_less_time_means_more_extreme():
    """With less time remaining and same distance, probability should be more extreme."""
    model = FairValueModel()
    up_early, _ = model.compute(50100, 50000, 250)
    up_late, _ = model.compute(50100, 50000, 30)
    # With less time and still up, probability of staying up should be higher
    assert up_late > up_early


def test_reset_clears_state():
    model = FairValueModel()
    model.update_price(50000)
    model.update_price(50100)
    assert len(model._returns_buffer) > 0
    model.reset()
    assert len(model._returns_buffer) == 0
    assert model._last_price is None
