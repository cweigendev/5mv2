"""
Entry decision engine: determines WHEN and HOW MUCH to trade.

Hybrid strategy combining:
- stingo43's directional conviction (high edge -> aggressive entry)
- eknih's spread capture discipline (both sides < $1.00 combined)
- Both bots' stale price sniping behavior
"""

from dataclasses import dataclass
from .edge_calculator import EdgeResult, OpportunityType


@dataclass
class EntrySignal:
    should_enter: bool
    side: str               # "up" or "down"
    size_shares: int        # Number of shares to buy
    limit_price: float      # Max price to pay
    mode: OpportunityType   # Which strategy mode triggered this
    reason: str             # Human-readable reason for logging


class EntryLogic:
    def __init__(
        self,
        min_edge_threshold: float = 0.20,
        default_clip_size: int = 15,
        per_market_budget: float = 150.0,
        min_seconds_remaining: int = 30,
        entry_delay_seconds: int = 5,
        max_paired_cost: float = 0.95,
        interval_duration: int = 300,
    ):
        self.min_edge_threshold = min_edge_threshold
        self.default_clip_size = default_clip_size
        self.per_market_budget = per_market_budget
        self.min_seconds_remaining = min_seconds_remaining
        self.entry_delay_seconds = entry_delay_seconds
        self.max_paired_cost = max_paired_cost
        self.interval_duration = interval_duration

    def evaluate(
        self,
        edge_result: EdgeResult,
        seconds_remaining: float,
        market_spend: float,
        held_side: str | None = None,
        held_vwap: float | None = None,
    ) -> EntrySignal | None:
        """
        Evaluate whether to enter a position.

        Args:
            edge_result: Current edge calculation for this market.
            seconds_remaining: Seconds until market expires.
            market_spend: Total USD already spent in this market.
            held_side: "up" or "down" if we already hold a position, None otherwise.
            held_vwap: VWAP of our existing position (for spread capture calc).

        Returns:
            EntrySignal if we should trade, None if we should stay out.
        """
        # --- Timing filters ---
        seconds_elapsed = self.interval_duration - seconds_remaining
        if seconds_remaining < self.min_seconds_remaining:
            return None
        if seconds_elapsed < self.entry_delay_seconds:
            return None

        # --- Budget filter ---
        remaining_budget = self.per_market_budget - market_spend
        if remaining_budget <= 0:
            return None

        # --- Mode 1: Stale Price Snipe ---
        if edge_result.opportunity == OpportunityType.STALE_SNIPE:
            side = edge_result.best_side
            ask = edge_result.ask_up if side == "up" else edge_result.ask_down
            size = min(self.default_clip_size, int(remaining_budget / max(ask, 0.01)))
            if size > 0:
                return EntrySignal(
                    should_enter=True,
                    side=side,
                    size_shares=size,
                    limit_price=ask,
                    mode=OpportunityType.STALE_SNIPE,
                    reason=f"Stale snipe: edge={edge_result.best_edge:.3f} on {side}",
                )

        # --- Mode 2: Directional Entry ---
        if edge_result.opportunity == OpportunityType.DIRECTIONAL:
            side = edge_result.best_side
            ask = edge_result.ask_up if side == "up" else edge_result.ask_down
            size = min(self.default_clip_size, int(remaining_budget / max(ask, 0.01)))
            if size > 0:
                return EntrySignal(
                    should_enter=True,
                    side=side,
                    size_shares=size,
                    limit_price=ask,
                    mode=OpportunityType.DIRECTIONAL,
                    reason=f"Directional: edge={edge_result.best_edge:.3f} on {side}",
                )

        # --- Mode 3: Spread Capture (only if we already hold one side) ---
        if (
            edge_result.opportunity == OpportunityType.SPREAD_CAPTURE
            and held_side is not None
            and held_vwap is not None
        ):
            opposite = "down" if held_side == "up" else "up"
            opposite_ask = edge_result.ask_down if opposite == "down" else edge_result.ask_up
            paired_cost = held_vwap + opposite_ask

            if paired_cost < self.max_paired_cost:
                size = min(
                    self.default_clip_size,
                    int(remaining_budget / max(opposite_ask, 0.01)),
                )
                if size > 0:
                    return EntrySignal(
                        should_enter=True,
                        side=opposite,
                        size_shares=size,
                        limit_price=opposite_ask,
                        mode=OpportunityType.SPREAD_CAPTURE,
                        reason=f"Spread capture: paired_cost={paired_cost:.4f}",
                    )

        return None
