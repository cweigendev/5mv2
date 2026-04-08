"""
Real historical data fetcher using CryptoCompare (free, no auth needed).

CryptoCompare provides real 1-minute OHLCV data, up to 2000 candles per request.
We chain multiple requests to build multi-day datasets, then use the price
interpolator to generate realistic 1-second resolution.
"""

import asyncio
import csv
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import aiohttp

from .data_fetcher import Candle

logger = logging.getLogger(__name__)

CC_BASE = "https://min-api.cryptocompare.com/data/v2"
MAX_LIMIT = 2000  # Max candles per request


class CryptoCompareDataFetcher:
    """Fetches real 1-minute candle data from CryptoCompare."""

    def __init__(self, cache_dir: str = "data/cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def fetch_minutes(
        self,
        symbol: str,
        hours: int = 24,
        end_time: int | None = None,
    ) -> list[Candle]:
        """
        Fetch 1-minute OHLCV candles from CryptoCompare.

        Args:
            symbol: Crypto symbol (BTC, ETH, SOL, XRP).
            hours: Number of hours of history.
            end_time: End timestamp (unix seconds). Defaults to now.

        Returns:
            List of Candle objects at 1-minute resolution, sorted by time.
        """
        cache_key = f"cc_{symbol}_{hours}h_{end_time or 'now'}"
        cache_path = self.cache_dir / f"{cache_key}.csv"

        if cache_path.exists():
            logger.info(f"Loading cached {symbol} data: {cache_path.name}")
            return self._load_cache(cache_path)

        total_minutes = hours * 60
        if end_time is None:
            end_time = int(time.time())

        all_candles: list[Candle] = []

        async with aiohttp.ClientSession() as session:
            # Work backwards from end_time, fetching chunks of up to 2000 minutes
            current_end = end_time
            remaining = total_minutes

            while remaining > 0:
                limit = min(remaining, MAX_LIMIT)

                candles = await self._fetch_chunk(
                    session, symbol, limit, current_end
                )

                if not candles:
                    logger.warning(f"No more data for {symbol} at ts={current_end}")
                    break

                all_candles.extend(candles)
                remaining -= len(candles)

                # Move end_time back
                earliest = min(c.timestamp_s for c in candles)
                current_end = earliest - 1

                logger.info(
                    f"  {symbol}: fetched {len(candles)} candles, "
                    f"total {len(all_candles)}/{total_minutes}, "
                    f"remaining {remaining}"
                )

                # Rate limit: CryptoCompare free tier allows ~50 req/sec
                await asyncio.sleep(0.3)

        # Sort chronologically
        all_candles.sort(key=lambda c: c.timestamp)

        # Deduplicate by timestamp
        seen = set()
        deduped = []
        for c in all_candles:
            if c.timestamp not in seen:
                seen.add(c.timestamp)
                deduped.append(c)
        all_candles = deduped

        logger.info(f"Total: {len(all_candles)} 1-minute candles for {symbol}")

        if all_candles:
            self._save_cache(cache_path, all_candles)

        return all_candles

    async def _fetch_chunk(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
        limit: int,
        to_ts: int,
    ) -> list[Candle]:
        """Fetch a single chunk of minute candles."""
        params = {
            "fsym": symbol.upper(),
            "tsym": "USD",
            "limit": limit,
            "toTs": to_ts,
        }

        for attempt in range(4):
            try:
                async with session.get(
                    f"{CC_BASE}/histominute",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 429:
                        wait = 2 ** (attempt + 1)
                        logger.warning(f"Rate limited, waiting {wait}s...")
                        await asyncio.sleep(wait)
                        continue

                    if resp.status != 200:
                        text = await resp.text()
                        logger.error(f"CryptoCompare error {resp.status}: {text[:200]}")
                        await asyncio.sleep(2 ** attempt)
                        continue

                    data = await resp.json()

                    if data.get("Response") != "Success":
                        logger.error(f"API error: {data.get('Message', 'unknown')}")
                        return []

                    raw = data.get("Data", {}).get("Data", [])
                    candles = []
                    for k in raw:
                        # Skip empty candles (volume = 0 and open = close = high = low)
                        if k.get("volumefrom", 0) == 0 and k.get("open") == k.get("close"):
                            continue
                        candles.append(Candle(
                            timestamp=int(k["time"]) * 1000,  # Convert to ms
                            open=float(k["open"]),
                            high=float(k["high"]),
                            low=float(k["low"]),
                            close=float(k["close"]),
                            volume=float(k.get("volumefrom", 0)),
                        ))
                    return candles

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"Request failed (attempt {attempt+1}): {e}")
                await asyncio.sleep(2 ** attempt)

        return []

    async def fetch_multi_asset(
        self,
        assets: list[str],
        hours: int = 24,
    ) -> dict[str, list[Candle]]:
        """Fetch data for multiple assets."""
        result = {}
        for asset in assets:
            candles = await self.fetch_minutes(asset, hours=hours)
            if candles:
                result[asset] = candles
                span_h = (candles[-1].timestamp - candles[0].timestamp) / 3600000
                logger.info(f"  {asset}: {len(candles)} candles, {span_h:.1f}h span")
            else:
                logger.warning(f"  {asset}: no data")
            await asyncio.sleep(0.5)  # Be nice to the API
        return result

    def _save_cache(self, path: Path, candles: list[Candle]) -> None:
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
            for c in candles:
                writer.writerow([c.timestamp, c.open, c.high, c.low, c.close, c.volume])
        logger.info(f"Cached {len(candles)} candles to {path.name}")

    def _load_cache(self, path: Path) -> list[Candle]:
        candles = []
        with open(path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                candles.append(Candle(
                    timestamp=int(row["timestamp"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                ))
        logger.info(f"Loaded {len(candles)} candles from cache")
        return candles
