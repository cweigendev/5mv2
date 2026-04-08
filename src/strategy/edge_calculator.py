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


class EdgeCalculator:
    def __init__(
        self,
        min_edge_threshold: float = 0.20,
        stale_snipe_threshold: float = 0.40,
        max_paired_cost: float = 0.95,
    ):
        self.min_edge_threshold = min_edge_threshold
        self.stale_snipe_threshold = stale_snipe_threshold
        self.max_paired_cost = max_paired_cost

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

        # Classify opportunity type
        opportunity = OpportunityType.NONE

        if best_edge >= self.stale_snipe_threshold:
            opportunity = OpportunityType.STALE_SNIPE
        elif best_edge >= self.min_edge_threshold:
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
        )
