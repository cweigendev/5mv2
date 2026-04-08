"""
Binance WebSocket feed for real-time spot prices.

Connects to Binance's trade stream for each configured asset,
providing 1-second price ticks used by the fair value model.
"""

import asyncio
import json
import logging
import time
from collections import defaultdict

import aiohttp

logger = logging.getLogger(__name__)


class BinanceFeed:
    """Real-time spot price feed from Binance WebSocket API."""

    def __init__(self, symbols: list[str], ws_base_url: str = "wss://stream.binance.com:9443/ws"):
        self.symbols = [s.lower() for s in symbols]
        self.ws_base_url = ws_base_url

        # Latest price per symbol: {"btcusdt": 84321.50, ...}
        self.prices: dict[str, float] = {}

        # Timestamp of last update per symbol
        self.last_update: dict[str, float] = {}

        # Callbacks: symbol → list of async callables
        self._callbacks: dict[str, list] = defaultdict(list)

        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._running = False

    def on_price(self, symbol: str, callback) -> None:
        """Register a callback for price updates on a symbol."""
        self._callbacks[symbol.lower()].append(callback)

    async def start(self) -> None:
        """Connect to Binance and start receiving price updates."""
        self._running = True
        streams = "/".join(f"{s}@trade" for s in self.symbols)
        url = f"{self.ws_base_url}/{streams}"

        while self._running:
            try:
                self._session = aiohttp.ClientSession()
                self._ws = await self._session.ws_connect(url)
                logger.info(f"Connected to Binance WS: {self.symbols}")

                async for msg in self._ws:
                    if not self._running:
                        break
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await self._handle_message(msg.data)
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error(f"Binance WS error: {msg.data}")
                        break

            except Exception as e:
                logger.error(f"Binance WS connection error: {e}")
            finally:
                await self._cleanup()

            if self._running:
                logger.info("Reconnecting to Binance in 2s...")
                await asyncio.sleep(2)

    async def _handle_message(self, raw: str) -> None:
        """Process a single WebSocket message."""
        try:
            data = json.loads(raw)
            symbol = data.get("s", "").lower()
            price = float(data.get("p", 0))

            if symbol and price > 0:
                self.prices[symbol] = price
                self.last_update[symbol] = time.time()

                for cb in self._callbacks.get(symbol, []):
                    await cb(symbol, price)

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.debug(f"Failed to parse Binance message: {e}")

    async def _cleanup(self) -> None:
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
        self._ws = None
        self._session = None

    async def stop(self) -> None:
        """Disconnect from Binance."""
        self._running = False
        await self._cleanup()

    def get_price(self, symbol: str, max_age_seconds: float = 5.0) -> float | None:
        """Get the latest price for a symbol, or None if stale.

        Args:
            symbol: Trading pair (e.g., "btcusdt").
            max_age_seconds: Maximum age of price data before considered stale.
                Set to 0 to skip staleness check (used in backtesting).
        """
        symbol = symbol.lower()
        price = self.prices.get(symbol)
        if price is None:
            return None
        if max_age_seconds > 0:
            age = time.time() - self.last_update.get(symbol, 0)
            if age > max_age_seconds:
                logger.warning(f"Binance price for {symbol} is {age:.1f}s stale, skipping")
                return None
        return price
