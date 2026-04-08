"""Tests for realistic intra-minute price interpolation."""

from src.backtest.data_fetcher import Candle
from src.backtest.price_interpolator import interpolate_candle_to_seconds, interpolate_candles


def make_candle(ts=1000000, o=100, h=102, l=98, c=101, v=1000):
    return Candle(timestamp=ts * 1000, open=o, high=h, low=l, close=c, volume=v)


def test_produces_60_candles():
    candle = make_candle()
    result = interpolate_candle_to_seconds(candle, seed=42)
    assert len(result) == 60


def test_starts_at_open_ends_at_close():
    candle = make_candle(o=100, c=105)
    result = interpolate_candle_to_seconds(candle, seed=42)
    assert result[0].open == 100
    assert result[-1].close == 105


def test_stays_mostly_within_range():
    candle = make_candle(o=100, h=110, l=95, c=103)
    result = interpolate_candle_to_seconds(candle, seed=42)
    prices = [c.close for c in result]
    # Allow small margin for realism
    margin = (110 - 95) * 0.05
    assert all(p >= 95 - margin for p in prices), f"Below low: {min(prices)}"
    assert all(p <= 110 + margin for p in prices), f"Above high: {max(prices)}"


def test_not_smooth_linear():
    """Verify the path isn't just a straight line from open to close."""
    candle = make_candle(o=100, h=105, l=95, c=100)
    result = interpolate_candle_to_seconds(candle, seed=42)
    prices = [c.close for c in result]

    # Check variance — a straight line would have near-zero variance
    mean = sum(prices) / len(prices)
    variance = sum((p - mean) ** 2 for p in prices) / len(prices)
    # With h=105, l=95, there should be meaningful variance
    assert variance > 0.5, f"Path too smooth, variance={variance}"


def test_different_seeds_different_paths():
    candle = make_candle()
    path1 = [c.close for c in interpolate_candle_to_seconds(candle, seed=1)]
    path2 = [c.close for c in interpolate_candle_to_seconds(candle, seed=2)]
    # Paths should differ
    assert path1 != path2


def test_interpolate_multiple_candles():
    candles = [
        make_candle(ts=1000000, o=100, h=102, l=98, c=101),
        make_candle(ts=1000060, o=101, h=104, l=99, c=103),
    ]
    result = interpolate_candles(candles)
    assert len(result) == 120  # 60 * 2
    # First candle starts at 100
    assert result[0].open == 100
    # Second candle ends at 103
    assert result[-1].close == 103
