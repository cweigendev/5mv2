"""
Polymarket CLOB historical data fetcher.

Pulls historical price/trade data from Polymarket's CLOB API for
5-minute crypto up/down markets. Uses the timeseries and markets
endpoints to get 1-minute resolution price history.
"""

import asyncio
import csv
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import aiohttp

logger = logging.getLogger(__name__)

CLOB_BASE_URL = "https://clob.polymarket.com"
GAMMA_BASE_URL = "https://gamma-api.polymarket.com"


@dataclass
class MarketPricePoint:
    """A single price observation for a market side (Up or Down)."""
    timestamp: int       # Unix timestamp in seconds
    price: float         # Mid-market price (0-1)
    side: str           # "up" or "down"


@dataclass
class MarketHistory:
    """Historical price data for a 5-minute up/down market."""
    market_id: str
    slug: str
    asset: str
    interval_start: int
    up_prices: list[MarketPricePoint]
    down_prices: list[MarketPricePoint]


def load_env() -> dict:
    """Load API credentials from .env file."""
    env = {}
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env[key.strip()] = value.strip()
    return env


class PolymarketDataFetcher:
    """Fetches historical market data from Polymarket's APIs."""

    def __init__(self, cache_dir: str = "data/polymarket_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        creds = load_env()
        self.api_key = creds.get("CLOB_API_KEY", os.environ.get("CLOB_API_KEY", ""))
        self.api_secret = creds.get("CLOB_API_SECRET", os.environ.get("CLOB_API_SECRET", ""))
        self.api_passphrase = creds.get("CLOB_API_PASSPHRASE", os.environ.get("CLOB_API_PASSPHRASE", ""))

    def _auth_headers(self) -> dict:
        return {
            "POLY-API-KEY": self.api_key,
            "POLY-PASSPHRASE": self.api_passphrase,
            "POLY-TIMESTAMP": str(int(time.time())),
        }

    async def fetch_active_5m_markets(self, session: aiohttp.ClientSession) -> list[dict]:
        """Fetch currently active 5-minute crypto up/down markets."""
        markets = []

        # Use Gamma API for market discovery
        params = {
            "active": "true",
            "closed": "false",
            "limit": 100,
        }

        for attempt in range(4):
            try:
                async with session.get(
                    f"{GAMMA_BASE_URL}/markets",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for m in data:
                            slug = m.get("slug", "")
                            if "updown-5m" in slug or "updown-15m" in slug:
                                markets.append(m)
                        logger.info(f"Found {len(markets)} active 5m markets")
                        return markets
                    elif resp.status == 429:
                        wait = 2 ** (attempt + 1)
                        logger.warning(f"Rate limited, waiting {wait}s...")
                        await asyncio.sleep(wait)
                    else:
                        text = await resp.text()
                        logger.warning(f"Gamma API error {resp.status}: {text[:200]}")
                        await asyncio.sleep(2 ** attempt)
            except Exception as e:
                logger.warning(f"Market fetch error (attempt {attempt+1}): {e}")
                await asyncio.sleep(2 ** attempt)

        return markets

    async def fetch_market_prices(
        self,
        session: aiohttp.ClientSession,
        token_id: str,
        start_ts: int | None = None,
        end_ts: int | None = None,
        fidelity: int = 60,  # 60 = 1-minute resolution
    ) -> list[dict]:
        """
        Fetch price timeseries for a specific token.

        Args:
            token_id: The outcome token ID.
            start_ts: Start timestamp (unix seconds).
            end_ts: End timestamp (unix seconds).
            fidelity: Resolution in seconds (60 = 1min).

        Returns:
            List of {t: timestamp, p: price} dicts.
        """
        params = {"fidelity": fidelity}
        if start_ts:
            params["startTs"] = start_ts
        if end_ts:
            params["endTs"] = end_ts

        url = f"{CLOB_BASE_URL}/prices-history"
        params["tokenID"] = token_id

        for attempt in range(4):
            try:
                async with session.get(
                    url,
                    params=params,
                    headers=self._auth_headers(),
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        history = data.get("history", [])
                        logger.debug(f"Got {len(history)} price points for token {token_id[:8]}...")
                        return history
                    elif resp.status == 429:
                        wait = 2 ** (attempt + 1)
                        logger.warning(f"Rate limited on prices, waiting {wait}s...")
                        await asyncio.sleep(wait)
                    else:
                        text = await resp.text()
                        logger.warning(f"Price history error {resp.status}: {text[:200]}")
                        await asyncio.sleep(2 ** attempt)
            except Exception as e:
                logger.warning(f"Price fetch error (attempt {attempt+1}): {e}")
                await asyncio.sleep(2 ** attempt)

        return []

    async def fetch_recent_trades(
        self,
        session: aiohttp.ClientSession,
        token_id: str,
    ) -> list[dict]:
        """Fetch recent trades for a token (last fills)."""
        for attempt in range(4):
            try:
                async with session.get(
                    f"{CLOB_BASE_URL}/trades",
                    params={"asset_id": token_id},
                    headers=self._auth_headers(),
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 429:
                        await asyncio.sleep(2 ** (attempt + 1))
                    else:
                        await asyncio.sleep(2 ** attempt)
            except Exception as e:
                logger.warning(f"Trades fetch error (attempt {attempt+1}): {e}")
                await asyncio.sleep(2 ** attempt)
        return []

    async def fetch_orderbook(
        self,
        session: aiohttp.ClientSession,
        token_id: str,
    ) -> dict:
        """Fetch current order book for a token."""
        for attempt in range(4):
            try:
                async with session.get(
                    f"{CLOB_BASE_URL}/book",
                    params={"token_id": token_id},
                    headers=self._auth_headers(),
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 429:
                        await asyncio.sleep(2 ** (attempt + 1))
                    else:
                        await asyncio.sleep(2 ** attempt)
            except Exception as e:
                logger.warning(f"Book fetch error (attempt {attempt+1}): {e}")
                await asyncio.sleep(2 ** attempt)
        return {}

    async def collect_historical_data(
        self,
        hours: int = 6,
        assets: list[str] | None = None,
    ) -> list[MarketHistory]:
        """
        Collect historical price data for recent 5m markets.

        Args:
            hours: Hours of history to collect.
            assets: Filter by asset (e.g., ["BTC", "ETH"]).

        Returns:
            List of MarketHistory objects with 1-minute price data.
        """
        target_assets = {a.lower() for a in (assets or ["btc", "eth", "sol", "xrp"])}
        results = []

        async with aiohttp.ClientSession() as session:
            # Discover markets
            markets = await self.fetch_active_5m_markets(session)

            for market in markets:
                slug = market.get("slug", "")
                asset = slug.split("-")[0].lower() if "-" in slug else ""

                if asset not in target_assets:
                    continue

                tokens = market.get("tokens", [])
                if len(tokens) < 2:
                    continue

                market_id = market.get("id", "")
                up_token = tokens[0].get("token_id", "")
                down_token = tokens[1].get("token_id", "")

                logger.info(f"Fetching prices for {slug}...")

                now = int(time.time())
                start = now - hours * 3600

                up_raw = await self.fetch_market_prices(
                    session, up_token, start_ts=start, end_ts=now
                )
                await asyncio.sleep(0.3)

                down_raw = await self.fetch_market_prices(
                    session, down_token, start_ts=start, end_ts=now
                )
                await asyncio.sleep(0.3)

                up_prices = [
                    MarketPricePoint(
                        timestamp=int(p.get("t", 0)),
                        price=float(p.get("p", 0.5)),
                        side="up",
                    )
                    for p in up_raw
                ]
                down_prices = [
                    MarketPricePoint(
                        timestamp=int(p.get("t", 0)),
                        price=float(p.get("p", 0.5)),
                        side="down",
                    )
                    for p in down_raw
                ]

                history = MarketHistory(
                    market_id=market_id,
                    slug=slug,
                    asset=asset.upper(),
                    interval_start=0,
                    up_prices=up_prices,
                    down_prices=down_prices,
                )
                results.append(history)

                logger.info(f"  {slug}: {len(up_prices)} up points, {len(down_prices)} down points")

        # Cache results
        self._save_cache(results)
        return results

    def _save_cache(self, histories: list[MarketHistory]) -> None:
        """Save collected data to cache."""
        cache_file = self.cache_dir / f"polymarket_{int(time.time())}.json"
        data = []
        for h in histories:
            data.append({
                "market_id": h.market_id,
                "slug": h.slug,
                "asset": h.asset,
                "up_prices": [{"t": p.timestamp, "p": p.price} for p in h.up_prices],
                "down_prices": [{"t": p.timestamp, "p": p.price} for p in h.down_prices],
            })
        with open(cache_file, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Cached {len(histories)} market histories to {cache_file.name}")
