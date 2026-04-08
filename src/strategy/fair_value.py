"""
Fair value probability model for 5-minute crypto up/down markets.

Derived from overlapping patterns in eknih and stingo43 strategies.
Both bots estimate P(Up) using: spot price distance from reference,
time remaining, and recent volatility, then convert via sigmoid.
"""

import math
from collections import deque


class FairValueModel:
    """Computes the fair probability of Up/Down for a 5-minute binary market."""

    def __init__(
        self,
        min_volatility_bps: float = 1.0,
        sigmoid_scale: float = 0.5,
        volatility_window: int = 30,
        interval_duration: int = 300,
    ):
        self.min_volatility_bps = min_volatility_bps
        self.sigmoid_scale = sigmoid_scale
        self.volatility_window = volatility_window
        self.interval_duration = interval_duration

        # Rolling window of 1-second returns (in bps) for volatility
        self._returns_buffer: deque[float] = deque(maxlen=volatility_window)
        self._last_price: float | None = None

    def update_price(self, price: float) -> None:
        """Feed a new 1-second spot price tick. Updates volatility estimate."""
        if self._last_price is not None and self._last_price > 0:
            ret_bps = (price - self._last_price) / self._last_price * 10000
            self._returns_buffer.append(ret_bps)
        self._last_price = price

    @property
    def volatility_bps(self) -> float:
        """Rolling standard deviation of 1-second returns in basis points.

        Uses median absolute deviation (MAD) instead of std dev to resist
        single-tick outliers that would otherwise dominate a 30-sample window.
        """
        if len(self._returns_buffer) < 5:
            return self.min_volatility_bps

        sorted_returns = sorted(self._returns_buffer)
        median = sorted_returns[len(sorted_returns) // 2]
        abs_devs = sorted(abs(r - median) for r in sorted_returns)
        mad = abs_devs[len(abs_devs) // 2]

        # MAD to std dev conversion. Standard factor is 1.4826 for normal
        # distributions, but crypto returns have fat tails, so we use ~1.2.
        vol = mad * 1.2
        return max(vol, self.min_volatility_bps)

    def compute(
        self,
        spot_price: float,
        reference_price: float,
        seconds_remaining: float,
    ) -> tuple[float, float]:
        """
        Compute fair probabilities for Up and Down.

        Args:
            spot_price: Current asset price (e.g., BTC/USDT).
            reference_price: Price at interval start (second 1).
            seconds_remaining: Seconds until market expiry.

        Returns:
            (fair_prob_up, fair_prob_down) each in [0, 1].
        """
        if reference_price <= 0 or seconds_remaining <= 0:
            return 0.5, 0.5

        # Distance from reference in basis points
        distance_bps = (spot_price - reference_price) / reference_price * 10000

        # Time factor: sqrt of fraction of interval remaining.
        # More time remaining = more uncertainty = probabilities closer to 0.5.
        # Less time remaining = price is "locked in" = probabilities more extreme.
        time_factor = math.sqrt(seconds_remaining / self.interval_duration)

        # Volatility-adjusted z-score
        vol = self.volatility_bps
        z_score = distance_bps / (time_factor * vol)

        # Sigmoid conversion to probability
        fair_prob_up = 1.0 / (1.0 + math.exp(-z_score * self.sigmoid_scale))
        fair_prob_down = 1.0 - fair_prob_up

        return fair_prob_up, fair_prob_down

    def reset(self) -> None:
        """Reset state for a new interval."""
        self._returns_buffer.clear()
        self._last_price = None
