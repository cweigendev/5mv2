"""
Polymarket CLOB WebSocket feed for real-time order book data.

Tracks best bid/ask for Up and Down tokens on active 5-minute markets.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class BookState:
    """Current order book state for one side (Up or Down) of a market."""
    best_bid: float = 0.0
    best_ask: float = 1.0
    bid_size: float = 0.0
    ask_size: float = 0.0
    last_update: float = 0.0

    @property
    def mid(self) -> float:
        return (self.best_bid + self.best_ask) / 2

    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid


@dataclass
class MarketBook:
    """Combined book state for a 5-minute up/down market."""
    market_id: str
    up: BookState = field(default_factory=BookState)
    down: BookState = field(default_factory=BookState)


class PolymarketFeed:
    """Real-time order book feed from Polymarket's CLOB WebSocket."""

    def __init__(self, ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"):
        self.ws_url = ws_url

        # Active market books: market_id → MarketBook
        self.books: dict[str, MarketBook] = {}

        # Token ID → (market_id, side) mapping
        self._token_map: dict[str, tuple[str, str]] = {}

        # Subscribed market IDs
        self._subscribed: set[str] = set()

        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._running = False

    def register_market(
        self,
        market_id: str,
        up_token_id: str,
        down_token_id: str,
    ) -> None:
        """Register a market's token IDs for book tracking."""
        self.books[market_id] = MarketBook(market_id=market_id)
        self._token_map[up_token_id] = (market_id, "up")
        self._token_map[down_token_id] = (market_id, "down")

    async def start(self) -> None:
        """Connect to Polymarket WebSocket and start receiving book updates."""
        self._running = True

        while self._running:
            try:
                self._session = aiohttp.ClientSession()
                self._ws = await self._session.ws_connect(self.ws_url)
                logger.info("Connected to Polymarket WS")

                # Subscribe to registered markets
                for market_id in self._subscribed:
                    await self._subscribe(market_id)

                async for msg in self._ws:
                    if not self._running:
                        break
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        self._handle_message(msg.data)
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error(f"Polymarket WS error: {msg.data}")
                        break

            except Exception as e:
                logger.error(f"Polymarket WS connection error: {e}")
            finally:
                await self._cleanup()

            if self._running:
                logger.info("Reconnecting to Polymarket in 2s...")
                await asyncio.sleep(2)

    async def subscribe_market(self, market_id: str) -> None:
        """Subscribe to book updates for a market."""
        self._subscribed.add(market_id)
        if self._ws and not self._ws.closed:
            await self._subscribe(market_id)

    async def _subscribe(self, market_id: str) -> None:
        """Send subscription message for a market."""
        msg = json.dumps({
            "type": "subscribe",
            "market": market_id,
            "channel": "book",
        })
        await self._ws.send_str(msg)
        logger.debug(f"Subscribed to market: {market_id}")

    def _handle_message(self, raw: str) -> None:
        """Process a single WebSocket message."""
        try:
            data = json.loads(raw)
            event_type = data.get("type", "")

            if event_type in ("book", "book_update"):
                token_id = data.get("asset_id", "")
                if token_id in self._token_map:
                    market_id, side = self._token_map[token_id]
                    self._update_book(market_id, side, data)

        except (json.JSONDecodeError, ValueError) as e:
            logger.debug(f"Failed to parse Polymarket message: {e}")

    def _update_book(self, market_id: str, side: str, data: dict) -> None:
        """Update the book state for one side of a market."""
        book = self.books.get(market_id)
        if not book:
            return

        state = book.up if side == "up" else book.down

        bids = data.get("bids", [])
        asks = data.get("asks", [])

        if bids:
            best = max(bids, key=lambda x: float(x.get("price", 0)))
            state.best_bid = float(best.get("price", 0))
            state.bid_size = float(best.get("size", 0))

        if asks:
            best = min(asks, key=lambda x: float(x.get("price", 1)))
            state.best_ask = float(best.get("price", 1))
            state.ask_size = float(best.get("size", 0))

        state.last_update = time.time()

    def get_book(self, market_id: str) -> MarketBook | None:
        return self.books.get(market_id)

    async def _cleanup(self) -> None:
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
        self._ws = None
        self._session = None

    async def stop(self) -> None:
        self._running = False
        await self._cleanup()
