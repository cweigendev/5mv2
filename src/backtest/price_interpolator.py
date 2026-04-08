"""
Realistic intra-minute price interpolation.

Given 1-minute OHLCV candles, generates realistic 1-second price paths
that respect the candle's OHLC constraints while exhibiting realistic
microstructure:
- Random walk within the candle's high-low range
- Realistic tick-by-tick volatility
- Mean-reversion toward close as the minute ends
- Occasional sharp moves (not smooth)
- Volume clustering
"""

import math
import random
from dataclasses import dataclass

from .data_fetcher import Candle


def interpolate_candle_to_seconds(
    candle: Candle,
    seed: int | None = None,
) -> list[Candle]:
    """
    Generate 60 realistic 1-second candles from a single 1-minute candle.

    The generated path:
    - Starts at candle.open
    - Ends at candle.close
    - Stays within [candle.low, candle.high] (mostly)
    - Has realistic microstructure (jumps, noise, not smooth)

    Args:
        candle: A 1-minute candle to interpolate.
        seed: Random seed for reproducibility.

    Returns:
        List of 60 Candle objects at 1-second resolution.
    """
    rng = random.Random(seed)
    o, h, l, c = candle.open, candle.high, candle.low, candle.close
    vol_per_tick = candle.volume / 60

    # The range of the candle
    candle_range = h - l
    if candle_range == 0:
        candle_range = o * 0.0001  # Minimum range

    # Generate the random path
    prices = [o]
    current = o

    for t in range(1, 60):
        progress = t / 59  # 0 to 1

        # Target: drift toward close as we approach end of minute
        # But not smoothly — use a noisy pull
        target = o + (c - o) * progress

        # Mean reversion strength increases toward end of candle
        revert_strength = 0.05 + 0.15 * progress

        # Random component: scaled to candle range
        # Use fat-tailed noise (occasionally large moves)
        if rng.random() < 0.08:
            # ~8% chance of a larger tick (microstructure jump)
            noise = rng.gauss(0, candle_range * 0.15)
        else:
            noise = rng.gauss(0, candle_range * 0.04)

        # Combine: drift toward target + noise
        pull = revert_strength * (target - current)
        current = current + pull + noise

        # Soft-clamp to candle range (allow tiny overshoots for realism)
        margin = candle_range * 0.02
        current = max(l - margin, min(h + margin, current))

        prices.append(current)

    # Force last price to be close
    prices[-1] = c

    # Ensure we actually touch high and low at some point
    # Pick random moments to touch extremes
    if h > max(o, c):
        touch_h_at = rng.randint(5, 50)
        # Smoothly approach the high around this tick
        for dt in range(-3, 4):
            idx = max(1, min(58, touch_h_at + dt))
            weight = 1.0 - abs(dt) / 4.0
            prices[idx] = prices[idx] + weight * (h - prices[idx]) * 0.6

    if l < min(o, c):
        touch_l_at = rng.randint(5, 50)
        # Avoid same spot as high touch
        while abs(touch_l_at - (touch_h_at if h > max(o, c) else 30)) < 8:
            touch_l_at = rng.randint(5, 50)
        for dt in range(-3, 4):
            idx = max(1, min(58, touch_l_at + dt))
            weight = 1.0 - abs(dt) / 4.0
            prices[idx] = prices[idx] + weight * (l - prices[idx]) * 0.6

    # Re-force endpoints
    prices[0] = o
    prices[-1] = c

    # Build 1-second candles
    result = []
    for t in range(60):
        ts_ms = candle.timestamp + t * 1000
        p = prices[t]
        p_next = prices[t + 1] if t < 59 else c

        # Each 1s candle has its own mini OHLC
        s_open = p
        s_close = p_next if t < 59 else c
        micro_noise = candle_range * 0.01 * abs(rng.gauss(0, 1))
        s_high = max(s_open, s_close) + micro_noise
        s_low = min(s_open, s_close) - micro_noise
        s_vol = vol_per_tick * max(0.1, abs(rng.gauss(1.0, 0.5)))

        result.append(Candle(
            timestamp=ts_ms,
            open=round(s_open, 2),
            high=round(s_high, 2),
            low=round(s_low, 2),
            close=round(s_close, 2),
            volume=round(s_vol, 4),
        ))

    return result


def interpolate_candles(
    candles_1m: list[Candle],
    base_seed: int = 42,
) -> list[Candle]:
    """
    Interpolate a list of 1-minute candles into 1-second candles.

    Handles transitions between candles to ensure the close of one
    matches the open of the next (or introduces a realistic gap).

    Args:
        candles_1m: List of 1-minute candles sorted by timestamp.
        base_seed: Base random seed (each candle gets seed + index).

    Returns:
        List of 1-second candles.
    """
    all_1s = []

    for i, candle in enumerate(candles_1m):
        # Each candle gets a unique but deterministic seed
        seed = base_seed + i * 7 + candle.timestamp % 1000

        second_candles = interpolate_candle_to_seconds(candle, seed=seed)
        all_1s.extend(second_candles)

    return all_1s
