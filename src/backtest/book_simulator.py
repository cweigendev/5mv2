"""
Simulated Polymarket book model for backtesting.

We don't have historical Polymarket order book data, so we model what the
book *would have looked like* based on spot price movements. The model:

1. Takes the "true" probability from our fair value model as the anchor
2. Adds realistic spread, noise, and staleness to simulate market conditions
3. Produces simulated best_ask for Up and Down tokens

Key calibration points from the bot reports:
- eknih median buy price: $0.44 (near-fair)
- stingo43 median buy price: $0.15 (deep OTM)
- Both found stale prices at $0.01 occasionally
- Typical spread: 2-5 cents on liquid markets
"""

import math
import random
from dataclasses import dataclass


@dataclass
class SimulatedBook:
    """Simulated order book for one 5-minute market at a point in time."""
    up_best_bid: float
    up_best_ask: float
    down_best_bid: float
    down_best_ask: float
    is_stale: bool = False  # Whether the book is lagging behind reality

    @property
    def up_mid(self) -> float:
        return (self.up_best_bid + self.up_best_ask) / 2

    @property
    def down_mid(self) -> float:
        return (self.down_best_bid + self.down_best_ask) / 2


class BookSimulator:
    """
    Generates realistic simulated Polymarket order books from fair value.

    Models several real-world phenomena:
    - Bid-ask spread (wider when vol is high or liquidity is thin)
    - Book staleness (prices not updating for several seconds)
    - Noise/mispricing (random deviations from fair value)
    - Price floors at $0.01 (Polymarket minimum tick)
    """

    def __init__(
        self,
        base_spread: float = 0.03,
        staleness_prob: float = 0.02,
        staleness_duration_range: tuple[int, int] = (3, 15),
        noise_std: float = 0.02,
        min_price: float = 0.01,
        max_price: float = 0.99,
        seed: int | None = None,
    ):
        """
        Args:
            base_spread: Base half-spread around fair value (each side).
            staleness_prob: Probability per second that the book becomes stale.
            staleness_duration_range: (min, max) seconds a stale book persists.
            noise_std: Standard deviation of random noise added to prices.
            min_price: Minimum price (Polymarket tick).
            max_price: Maximum price.
            seed: Random seed for reproducibility.
        """
        self.base_spread = base_spread
        self.staleness_prob = staleness_prob
        self.staleness_duration_range = staleness_duration_range
        self.noise_std = noise_std
        self.min_price = min_price
        self.max_price = max_price
        self.rng = random.Random(seed)

        # Staleness state
        self._stale_until: float = 0
        self._stale_fair_up: float = 0.5
        self._stale_fair_down: float = 0.5

    def generate(
        self,
        fair_prob_up: float,
        fair_prob_down: float,
        seconds_remaining: float,
        current_time: float = 0,
        volatility_bps: float = 10.0,
    ) -> SimulatedBook:
        """
        Generate a simulated order book snapshot.

        Args:
            fair_prob_up: True P(Up) from fair value model.
            fair_prob_down: True P(Down).
            seconds_remaining: Seconds until market expires.
            current_time: Current timestamp (for staleness tracking).
            volatility_bps: Current volatility in bps (widens spread).

        Returns:
            SimulatedBook with bid/ask for both sides.
        """
        is_stale = False

        # Check if book is currently stale
        if current_time < self._stale_until:
            # Use stale (old) fair values
            fair_up = self._stale_fair_up
            fair_down = self._stale_fair_down
            is_stale = True
        else:
            fair_up = fair_prob_up
            fair_down = fair_prob_down

            # Maybe go stale now
            if self.rng.random() < self.staleness_prob:
                duration = self.rng.randint(*self.staleness_duration_range)
                self._stale_until = current_time + duration
                self._stale_fair_up = fair_up
                self._stale_fair_down = fair_down

        # Compute spread: wider when volatile or near expiry
        vol_factor = max(1.0, volatility_bps / 10.0)
        time_factor = 1.0 + max(0, (60 - seconds_remaining) / 60) * 0.5  # wider near expiry
        half_spread = self.base_spread * vol_factor * time_factor

        # Add noise
        noise_up = self.rng.gauss(0, self.noise_std)
        noise_down = self.rng.gauss(0, self.noise_std)

        # Build book
        up_mid = fair_up + noise_up
        down_mid = fair_down + noise_down

        up_bid = self._clamp(up_mid - half_spread)
        up_ask = self._clamp(up_mid + half_spread)
        down_bid = self._clamp(down_mid - half_spread)
        down_ask = self._clamp(down_mid + half_spread)

        # Ensure bid < ask
        if up_bid >= up_ask:
            up_bid = max(self.min_price, up_ask - 0.01)
        if down_bid >= down_ask:
            down_bid = max(self.min_price, down_ask - 0.01)

        return SimulatedBook(
            up_best_bid=round(up_bid, 4),
            up_best_ask=round(up_ask, 4),
            down_best_bid=round(down_bid, 4),
            down_best_ask=round(down_ask, 4),
            is_stale=is_stale,
        )

    def _clamp(self, price: float) -> float:
        return max(self.min_price, min(self.max_price, price))

    def reset(self) -> None:
        """Reset staleness state for a new simulation."""
        self._stale_until = 0
        self._stale_fair_up = 0.5
        self._stale_fair_down = 0.5
