"""
Order manager: clip-based execution engine.

Both eknih and stingo43 split orders into small child clips fired
in rapid succession. This minimizes market impact and handles partial fills.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class OrderStatus(Enum):
    PENDING = "pending"
    SENT = "sent"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class ClipOrder:
    order_id: str
    market_id: str
    token_id: str
    side: str           # "up" or "down"
    size: float         # Shares
    limit_price: float
    status: OrderStatus = OrderStatus.PENDING
    filled_size: float = 0.0
    filled_avg_price: float = 0.0
    created_at: float = 0.0
    filled_at: float = 0.0


class OrderManager:
    """
    Manages clip-based order execution.

    Splits a target position into multiple small child orders,
    fired with configurable delay between them.
    """

    def __init__(
        self,
        polymarket_client,
        default_clip_size: int = 15,
        inter_clip_delay_ms: int = 100,
    ):
        self.client = polymarket_client
        self.default_clip_size = default_clip_size
        self.inter_clip_delay_ms = inter_clip_delay_ms

        # Active orders by market
        self.orders: dict[str, list[ClipOrder]] = {}
        self._order_counter = 0

    async def execute_entry(
        self,
        market_id: str,
        token_id: str,
        side: str,
        total_shares: int,
        limit_price: float,
    ) -> list[ClipOrder]:
        """
        Execute an entry by splitting into clip-sized child orders.

        Args:
            market_id: Market identifier.
            token_id: Polymarket token ID to buy.
            side: "up" or "down".
            total_shares: Total shares to acquire.
            limit_price: Maximum price per share.

        Returns:
            List of ClipOrder objects representing the child orders.
        """
        clips = []
        remaining = total_shares

        while remaining > 0:
            clip_size = min(remaining, self.default_clip_size)
            self._order_counter += 1

            order = ClipOrder(
                order_id=f"clip_{self._order_counter}",
                market_id=market_id,
                token_id=token_id,
                side=side,
                size=clip_size,
                limit_price=limit_price,
                created_at=time.time(),
            )

            try:
                result = await self.client.place_order(
                    token_id=token_id,
                    side="BUY",
                    size=clip_size,
                    price=limit_price,
                )
                order.status = OrderStatus.SENT
                order.order_id = result.get("orderID", order.order_id)
                logger.info(
                    f"Clip sent: {side} {clip_size}@{limit_price:.4f} "
                    f"in {market_id} (order={order.order_id})"
                )
            except Exception as e:
                order.status = OrderStatus.REJECTED
                logger.error(f"Clip rejected: {e}")

            clips.append(order)
            remaining -= clip_size

            if remaining > 0:
                await asyncio.sleep(self.inter_clip_delay_ms / 1000.0)

        if market_id not in self.orders:
            self.orders[market_id] = []
        self.orders[market_id].extend(clips)

        return clips

    def record_fill(self, order_id: str, filled_size: float, price: float) -> ClipOrder | None:
        """Record a fill notification for an order."""
        for orders in self.orders.values():
            for order in orders:
                if order.order_id == order_id:
                    order.filled_size += filled_size
                    # Update running average
                    if order.filled_size > 0:
                        prev_total = order.filled_avg_price * (order.filled_size - filled_size)
                        order.filled_avg_price = (prev_total + price * filled_size) / order.filled_size
                    if order.filled_size >= order.size:
                        order.status = OrderStatus.FILLED
                        order.filled_at = time.time()
                    else:
                        order.status = OrderStatus.PARTIALLY_FILLED
                    return order
        return None

    def get_market_fills(self, market_id: str) -> dict[str, dict]:
        """Get aggregate fill info per side for a market."""
        result = {"up": {"shares": 0.0, "cost": 0.0}, "down": {"shares": 0.0, "cost": 0.0}}
        for order in self.orders.get(market_id, []):
            if order.filled_size > 0:
                result[order.side]["shares"] += order.filled_size
                result[order.side]["cost"] += order.filled_size * order.filled_avg_price
        return result

    def cleanup_market(self, market_id: str) -> None:
        """Remove all orders for a resolved market."""
        self.orders.pop(market_id, None)
