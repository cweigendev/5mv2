"""
Edge calculation: the core decision signal.

Edge = fair_value - market_ask. Both eknih and stingo43 only enter
when edge exceeds their threshold. This module computes edge for
both sides and classifies the opportunity type.
"""

from dataclasses import dataclass
from enum import Enum


class OpportunityType(Enum):
    NONE = "none"
    DIRECTIONAL = "directional"       # One side has edge above threshold
    SPREAD_CAPTURE = "spread_capture"  # Both sides can be bought < $1.00 combined
    STALE_SNIPE = "stale_snipe"       # Extreme edge suggesting stale book


@dataclass
class EdgeResult:
    up_edge: float        # fair_prob_up - market_ask_up
    down_edge: float      # fair_prob_down - market_ask_down
    best_side: str        # "up" or "down" — whichever has more edge
    best_edge: float      # The larger edge
    paired_cost: float    # market_ask_up + market_ask_down
    opportunity: OpportunityType
    fair_up: float        # The fair value P(Up) used to compute edge
    fair_down: float      # The fair value P(Down)
    ask_up: float         # The actual market ask for Up
    ask_down: float       # The actual market ask for Down


# Minimum fair value conviction to consider a directional entry.
# If fair value is between 0.35 and 0.65, the model isn't confident
# enough — it's basically a coin flip with noise.
MIN_DIRECTIONAL_CONVICTION = 0.35


class EdgeCalculator:
    def __init__(
        self,
        min_edge_threshold: float = 0.20,
        stale_snipe_threshold: float = 0.40,
        max_paired_cost: float = 0.95,
        min_conviction: float = MIN_DIRECTIONAL_CONVICTION,
    ):
        self.min_edge_threshold = min_edge_threshold
        self.stale_snipe_threshold = stale_snipe_threshold
        self.max_paired_cost = max_paired_cost
        self.min_conviction = min_conviction

    def calculate(
        self,
        fair_prob_up: float,
        fair_prob_down: float,
        market_ask_up: float,
        market_ask_down: float,
    ) -> EdgeResult:
        """
        Calculate edge for both sides and classify the opportunity.

        Args:
            fair_prob_up: Model's estimated P(Up wins).
            fair_prob_down: Model's estimated P(Down wins).
            market_ask_up: Best ask price for Up token on Polymarket.
            market_ask_down: Best ask price for Down token on Polymarket.

        Returns:
            EdgeResult with edge values and opportunity classification.
        """
        up_edge = fair_prob_up - market_ask_up
        down_edge = fair_prob_down - market_ask_down
        paired_cost = market_ask_up + market_ask_down

        if up_edge >= down_edge:
            best_side = "up"
            best_edge = up_edge
        else:
            best_side = "down"
            best_edge = down_edge

        # Fair value conviction: how far is fair value from 0.50?
        best_fair = fair_prob_up if best_side == "up" else fair_prob_down

        # Classify opportunity type
        opportunity = OpportunityType.NONE

        if best_edge >= self.stale_snipe_threshold:
            opportunity = OpportunityType.STALE_SNIPE
        elif best_edge >= self.min_edge_threshold and best_fair >= self.min_conviction:
            # Only enter directional trades when the model has real conviction,
            # not when edge comes from noise on a coin-flip fair value.
            opportunity = OpportunityType.DIRECTIONAL
        elif paired_cost < self.max_paired_cost and market_ask_up > 0 and market_ask_down > 0:
            opportunity = OpportunityType.SPREAD_CAPTURE

        return EdgeResult(
            up_edge=up_edge,
            down_edge=down_edge,
            best_side=best_side,
            best_edge=best_edge,
            paired_cost=paired_cost,
            opportunity=opportunity,
            fair_up=fair_prob_up,
            fair_down=fair_prob_down,
            ask_up=market_ask_up,
            ask_down=market_ask_down,
        )
