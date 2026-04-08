"""
Risk manager: enforces position limits, budget caps, and circuit breakers.

Both eknih and stingo43 demonstrate disciplined risk management:
- Per-market budget caps
- Paired-cost discipline (never buy second side if combined > threshold)
- Automated execution with consistent sizing
"""

import time
from dataclasses import dataclass, field


@dataclass
class MarketPosition:
    market_id: str
    asset: str
    up_shares: float = 0.0
    down_shares: float = 0.0
    up_spend: float = 0.0
    down_spend: float = 0.0
    up_vwap: float = 0.0
    down_vwap: float = 0.0

    @property
    def total_spend(self) -> float:
        return self.up_spend + self.down_spend

    @property
    def paired_cost(self) -> float:
        if self.up_vwap > 0 and self.down_vwap > 0:
            return self.up_vwap + self.down_vwap
        return float("inf")

    @property
    def held_side(self) -> str | None:
        if self.up_spend > 0 and self.down_spend == 0:
            return "up"
        elif self.down_spend > 0 and self.up_spend == 0:
            return "down"
        elif self.up_spend > 0 and self.down_spend > 0:
            return "up" if self.up_spend > self.down_spend else "down"
        return None

    def record_fill(self, side: str, shares: float, price: float) -> None:
        cost = shares * price
        if side == "up":
            total_cost = self.up_spend + cost
            total_shares = self.up_shares + shares
            self.up_vwap = total_cost / total_shares if total_shares > 0 else 0
            self.up_shares = total_shares
            self.up_spend = total_cost
        else:
            total_cost = self.down_spend + cost
            total_shares = self.down_shares + shares
            self.down_vwap = total_cost / total_shares if total_shares > 0 else 0
            self.down_shares = total_shares
            self.down_spend = total_cost


class RiskManager:
    def __init__(
        self,
        per_market_budget: float = 150.0,
        max_daily_loss: float = 500.0,
        max_concurrent_markets: int = 10,
        max_asset_exposure: float = 1000.0,
        max_paired_cost: float = 0.95,
        consecutive_loss_cooldown: int = 5,
        cooldown_duration_seconds: int = 300,
    ):
        self.per_market_budget = per_market_budget
        self.max_daily_loss = max_daily_loss
        self.max_concurrent_markets = max_concurrent_markets
        self.max_asset_exposure = max_asset_exposure
        self.max_paired_cost = max_paired_cost
        self.consecutive_loss_cooldown = consecutive_loss_cooldown
        self.cooldown_duration_seconds = cooldown_duration_seconds

        # State
        self.positions: dict[str, MarketPosition] = {}
        self.session_pnl: float = 0.0
        self.consecutive_losses: int = 0
        self.cooldown_until: float = 0.0
        self.resolved_markets: int = 0
        self.won_markets: int = 0

    def can_enter_market(self, market_id: str, asset: str) -> tuple[bool, str]:
        """Check if we're allowed to enter a new market."""
        # Circuit breaker: session P&L
        if self.session_pnl < -self.max_daily_loss:
            return False, f"Session loss limit hit: ${self.session_pnl:.2f}"

        # Cooldown after consecutive losses
        if time.time() < self.cooldown_until:
            remaining = self.cooldown_until - time.time()
            return False, f"In cooldown for {remaining:.0f}s after {self.consecutive_loss_cooldown} consecutive losses"

        # Max concurrent markets
        active = sum(1 for p in self.positions.values() if p.total_spend > 0)
        if active >= self.max_concurrent_markets:
            return False, f"At max concurrent markets: {active}/{self.max_concurrent_markets}"

        # Per-asset exposure
        asset_exposure = sum(
            p.total_spend for p in self.positions.values() if p.asset == asset
        )
        if asset_exposure >= self.max_asset_exposure:
            return False, f"Asset {asset} exposure limit: ${asset_exposure:.2f}/{self.max_asset_exposure:.2f}"

        return True, "OK"

    def can_add_to_position(
        self, market_id: str, side: str, shares: int, price: float
    ) -> tuple[bool, str]:
        """Check if we can add to an existing position in a market."""
        pos = self.positions.get(market_id)
        if pos is None:
            return True, "New market"

        additional_cost = shares * price
        if pos.total_spend + additional_cost > self.per_market_budget:
            return False, f"Market budget exceeded: ${pos.total_spend:.2f} + ${additional_cost:.2f} > ${self.per_market_budget:.2f}"

        # Check paired cost discipline
        if side == "up" and pos.down_vwap > 0:
            projected_paired = price + pos.down_vwap
            if projected_paired > self.max_paired_cost:
                return False, f"Paired cost too high: {projected_paired:.4f} > {self.max_paired_cost}"
        elif side == "down" and pos.up_vwap > 0:
            projected_paired = pos.up_vwap + price
            if projected_paired > self.max_paired_cost:
                return False, f"Paired cost too high: {projected_paired:.4f} > {self.max_paired_cost}"

        return True, "OK"

    def record_fill(
        self, market_id: str, asset: str, side: str, shares: float, price: float
    ) -> None:
        """Record a filled order."""
        if market_id not in self.positions:
            self.positions[market_id] = MarketPosition(
                market_id=market_id, asset=asset
            )
        self.positions[market_id].record_fill(side, shares, price)

    def record_market_resolution(self, market_id: str, pnl: float) -> None:
        """Record the outcome of a resolved market."""
        self.session_pnl += pnl
        self.resolved_markets += 1

        if pnl > 0:
            self.won_markets += 1
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.consecutive_loss_cooldown:
                self.cooldown_until = time.time() + self.cooldown_duration_seconds

        # Clean up position
        self.positions.pop(market_id, None)

    @property
    def win_rate(self) -> float:
        if self.resolved_markets == 0:
            return 0.0
        return self.won_markets / self.resolved_markets

    @property
    def total_exposure(self) -> float:
        return sum(p.total_spend for p in self.positions.values())
