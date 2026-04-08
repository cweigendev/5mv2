"""
Binance historical data fetcher.

Pulls 1-second klines from Binance's public REST API for backtesting.
Binance provides klines at 1s resolution via /api/v3/klines.
Data is fetched in chunks and cached locally as CSV to avoid re-downloading.
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

BINANCE_API = "https://api.binance.com"
# Max klines per request
MAX_KLINES = 1000


@dataclass
class Candle:
    """One kline/candle from Binance."""
    timestamp: int      # Open time in ms
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def timestamp_s(self) -> int:
        """Open time in seconds."""
        return self.timestamp // 1000


class BinanceDataFetcher:
    """Fetches and caches historical kline data from Binance."""

    def __init__(self, cache_dir: str = "data/cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int,
        use_cache: bool = True,
    ) -> list[Candle]:
        """
        Fetch klines from Binance for a time range.

        Args:
            symbol: Trading pair e.g. "BTCUSDT"
            interval: Kline interval e.g. "1s", "1m", "5m"
            start_time: Start time in milliseconds
            end_time: End time in milliseconds
            use_cache: Whether to use/save cached data

        Returns:
            List of Candle objects sorted by timestamp.
        """
        cache_key = f"{symbol}_{interval}_{start_time}_{end_time}"
        cache_path = self.cache_dir / f"{cache_key}.csv"

        if use_cache and cache_path.exists():
            logger.info(f"Loading cached data: {cache_path.name}")
            return self._load_cache(cache_path)

        logger.info(
            f"Fetching {symbol} {interval} klines from Binance: "
            f"{self._ms_to_str(start_time)} to {self._ms_to_str(end_time)}"
        )

        candles = []
        current_start = start_time

        async with aiohttp.ClientSession() as session:
            while current_start < end_time:
                params = {
                    "symbol": symbol.upper(),
                    "interval": interval,
                    "startTime": current_start,
                    "endTime": end_time,
                    "limit": MAX_KLINES,
                }

                for attempt in range(4):
                    try:
                        async with session.get(
                            f"{BINANCE_API}/api/v3/klines",
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
                                logger.error(f"Binance API error {resp.status}: {text}")
                                await asyncio.sleep(2 ** attempt)
                                continue

                            data = await resp.json()
                            break
                    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                        logger.warning(f"Request failed (attempt {attempt+1}): {e}")
                        await asyncio.sleep(2 ** attempt)
                        data = []
                else:
                    logger.error("Max retries exceeded, stopping fetch")
                    break

                if not data:
                    break

                for k in data:
                    candles.append(Candle(
                        timestamp=int(k[0]),
                        open=float(k[1]),
                        high=float(k[2]),
                        low=float(k[3]),
                        close=float(k[4]),
                        volume=float(k[5]),
                    ))

                # Move to next chunk
                last_ts = int(data[-1][0])
                if last_ts <= current_start:
                    break
                current_start = last_ts + 1

                # Small delay to be respectful of rate limits
                await asyncio.sleep(0.2)

                if len(candles) % 5000 == 0:
                    logger.info(f"  Fetched {len(candles)} candles so far...")

        logger.info(f"Fetched {len(candles)} total candles for {symbol}")

        if use_cache and candles:
            self._save_cache(cache_path, candles)

        return sorted(candles, key=lambda c: c.timestamp)

    async def fetch_1s_candles(
        self,
        symbol: str,
        start_time: int,
        end_time: int,
    ) -> list[Candle]:
        """Convenience method: fetch 1-second klines."""
        return await self.fetch_klines(symbol, "1s", start_time, end_time)

    async def fetch_1m_candles(
        self,
        symbol: str,
        start_time: int,
        end_time: int,
    ) -> list[Candle]:
        """Fetch 1-minute klines (faster for longer ranges, less granular)."""
        return await self.fetch_klines(symbol, "1m", start_time, end_time)

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

    @staticmethod
    def _ms_to_str(ms: int) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ms / 1000))
