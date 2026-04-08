"""
Market lifecycle manager: discovers, tracks, and manages 5-minute up/down markets.

Parses Polymarket market slugs to extract interval metadata (asset, epoch, duration).
Tracks market state transitions: PENDING → ACTIVE → EXPIRED → RESOLVED.
"""

import logging
import re
import time
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class MarketState(Enum):
    PENDING = "pending"      # Market exists but interval hasn't started
    ACTIVE = "active"        # Interval in progress, trading allowed
    EXPIRED = "expired"      # Interval ended, awaiting resolution
    RESOLVED = "resolved"    # Outcome determined


@dataclass
class MarketInfo:
    market_id: str
    slug: str
    asset: str                    # "BTC", "ETH", "SOL", "XRP"
    interval_start: int           # Unix epoch when interval begins
    interval_duration: int        # Duration in seconds (300 for 5-min)
    up_token_id: str
    down_token_id: str
    reference_price: float | None = None  # Spot price at interval start
    state: MarketState = MarketState.PENDING
    resolved_winner: str | None = None    # "up" or "down" after resolution

    @property
    def interval_end(self) -> int:
        return self.interval_start + self.interval_duration

    @property
    def seconds_remaining(self) -> float:
        return max(0, self.interval_end - time.time())

    @property
    def seconds_elapsed(self) -> float:
        return max(0, time.time() - self.interval_start)

    @property
    def is_active(self) -> bool:
        now = time.time()
        return self.interval_start <= now <= self.interval_end


# Pattern: btc-updown-5m-1773733500 or eth-updown-15m-1774154700
SLUG_PATTERN = re.compile(
    r"^(btc|eth|sol|xrp)-updown-(\d+)m-(\d+)$", re.IGNORECASE
)


class MarketTracker:
    """Discovers and manages the lifecycle of 5-minute up/down markets."""

    def __init__(self, target_assets: list[str] | None = None):
        self.target_assets = {a.upper() for a in (target_assets or ["BTC", "ETH", "SOL", "XRP"])}
        self.markets: dict[str, MarketInfo] = {}

    def parse_slug(self, slug: str) -> tuple[str, int, int] | None:
        """
        Parse a market slug into (asset, duration_seconds, start_epoch).

        Returns None if the slug doesn't match our target pattern.
        """
        match = SLUG_PATTERN.match(slug)
        if not match:
            return None

        asset = match.group(1).upper()
        duration_minutes = int(match.group(2))
        start_epoch = int(match.group(3))

        if asset not in self.target_assets:
            return None

        return asset, duration_minutes * 60, start_epoch

    def register_market(
        self,
        market_id: str,
        slug: str,
        up_token_id: str,
        down_token_id: str,
    ) -> MarketInfo | None:
        """Register a new market if it matches our target pattern."""
        if market_id in self.markets:
            return self.markets[market_id]

        parsed = self.parse_slug(slug)
        if parsed is None:
            return None

        asset, duration, start_epoch = parsed

        info = MarketInfo(
            market_id=market_id,
            slug=slug,
            asset=asset,
            interval_start=start_epoch,
            interval_duration=duration,
            up_token_id=up_token_id,
            down_token_id=down_token_id,
        )
        self.markets[market_id] = info
        logger.info(f"Registered market: {slug} ({asset}, {duration}s, starts {start_epoch})")
        return info

    def set_reference_price(self, market_id: str, price: float) -> None:
        """Set the reference (opening) price for a market's interval."""
        if market_id in self.markets:
            self.markets[market_id].reference_price = price

    def update_states(self) -> list[MarketInfo]:
        """Update all market states based on current time. Returns newly active markets."""
        newly_active = []
        now = time.time()

        for info in list(self.markets.values()):
            if info.state == MarketState.PENDING and now >= info.interval_start:
                info.state = MarketState.ACTIVE
                newly_active.append(info)
                logger.info(f"Market now ACTIVE: {info.slug}")

            elif info.state == MarketState.ACTIVE and now > info.interval_end:
                info.state = MarketState.EXPIRED
                logger.info(f"Market EXPIRED: {info.slug}")

        return newly_active

    def resolve_market(self, market_id: str, winner: str) -> None:
        """Mark a market as resolved with the winning side."""
        if market_id in self.markets:
            self.markets[market_id].state = MarketState.RESOLVED
            self.markets[market_id].resolved_winner = winner

    def get_active_markets(self) -> list[MarketInfo]:
        """Get all currently active (tradeable) markets."""
        return [m for m in self.markets.values() if m.state == MarketState.ACTIVE]

    def cleanup_resolved(self, max_age_seconds: int = 600) -> None:
        """Remove resolved markets older than max_age_seconds."""
        now = time.time()
        to_remove = [
            mid
            for mid, info in self.markets.items()
            if info.state == MarketState.RESOLVED
            and now - info.interval_end > max_age_seconds
        ]
        for mid in to_remove:
            del self.markets[mid]
