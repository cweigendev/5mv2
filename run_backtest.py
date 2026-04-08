#!/usr/bin/env python3
"""
Run backtests against real Binance historical data (or synthetic fallback).

Usage:
    python run_backtest.py                          # Default: BTC, last 24h
    python run_backtest.py --assets BTC ETH SOL XRP # Multi-asset
    python run_backtest.py --hours 72               # 3 days of data
    python run_backtest.py --edge 0.10              # Lower edge threshold
    python run_backtest.py --preset aggressive       # Use aggressive config
    python run_backtest.py --sweep                   # Parameter sweep
    python run_backtest.py --synthetic               # Force synthetic data
"""

import argparse
import asyncio
import logging
import time

from src.backtest.data_fetcher import BinanceDataFetcher
from src.backtest.price_interpolator import interpolate_candles
from src.backtest.synthetic_data import generate_candles, generate_multi_asset
from src.backtest.simulator import Backtester, BacktestResult
from src.core.config import BotConfig
from src.core.logger import setup_logging

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run backtest with Binance data")
    parser.add_argument(
        "--assets", nargs="+", default=["BTC"],
        help="Assets to backtest (e.g., BTC ETH SOL XRP)",
    )
    parser.add_argument(
        "--hours", type=int, default=24,
        help="Hours of history to fetch (default: 24)",
    )
    parser.add_argument(
        "--interval", default="1s", choices=["1s", "1m"],
        help="Candle interval (1s is more accurate but slower to fetch)",
    )
    parser.add_argument(
        "--edge", type=float, default=None,
        help="Override minimum edge threshold",
    )
    parser.add_argument(
        "--budget", type=float, default=None,
        help="Override per-market budget",
    )
    parser.add_argument(
        "--clip-size", type=int, default=None,
        help="Override clip size",
    )
    parser.add_argument(
        "--paired-cost", type=float, default=None,
        help="Override max paired cost",
    )
    parser.add_argument(
        "--preset", choices=["conservative", "moderate", "aggressive"],
        default="moderate",
        help="Config preset",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for book simulation",
    )
    parser.add_argument(
        "--sweep", action="store_true",
        help="Run parameter sweep across edge thresholds",
    )
    parser.add_argument(
        "--synthetic", action="store_true",
        help="Use synthetic data (no network required)",
    )
    parser.add_argument(
        "--interpolate", action="store_true",
        help="Interpolate 1m candles to 1s with realistic microstructure",
    )
    return parser.parse_args()


PRESETS = {
    "conservative": {
        "min_edge_threshold": 0.30,
        "per_market_budget": 50.0,
        "default_clip_size": 10,
        "max_paired_cost": 0.90,
    },
    "moderate": {
        "min_edge_threshold": 0.20,
        "per_market_budget": 150.0,
        "default_clip_size": 15,
        "max_paired_cost": 0.95,
    },
    "aggressive": {
        "min_edge_threshold": 0.10,
        "per_market_budget": 500.0,
        "default_clip_size": 25,
        "max_paired_cost": 0.98,
    },
}


def make_config(args) -> BotConfig:
    """Build config from args and presets."""
    preset = PRESETS[args.preset]
    config = BotConfig(
        min_edge_threshold=preset["min_edge_threshold"],
        per_market_budget=preset["per_market_budget"],
        default_clip_size=preset["default_clip_size"],
        max_paired_cost=preset["max_paired_cost"],
    )

    if args.edge is not None:
        config.min_edge_threshold = args.edge
    if args.budget is not None:
        config.per_market_budget = args.budget
    if args.clip_size is not None:
        config.default_clip_size = args.clip_size
    if args.paired_cost is not None:
        config.max_paired_cost = args.paired_cost

    return config


async def fetch_live_data(
    assets: list[str], hours: int, interval: str,
) -> dict:
    """Try to fetch from Binance API."""
    fetcher = BinanceDataFetcher()
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (hours * 3600 * 1000)

    data = {}
    for asset in assets:
        symbol = f"{asset.upper()}USDT"
        logger.info(f"Fetching {symbol} data ({hours}h, {interval} candles)...")

        try:
            if interval == "1s":
                candles = await fetcher.fetch_1s_candles(symbol, start_ms, end_ms)
            else:
                candles = await fetcher.fetch_1m_candles(symbol, start_ms, end_ms)

            if candles:
                data[asset] = candles
                span_h = (candles[-1].timestamp - candles[0].timestamp) / 3600000
                logger.info(f"  Got {len(candles)} candles spanning {span_h:.1f}h")
            else:
                logger.warning(f"  No data for {symbol}")
        except Exception as e:
            logger.warning(f"  Failed to fetch {symbol}: {e}")

    return data


def get_synthetic_data(
    assets: list[str], hours: int, interval: str, seed: int,
    interpolate: bool = False,
) -> dict:
    """Generate synthetic price data calibrated to real crypto parameters."""
    # If interpolating, generate 1m then upscale to 1s
    if interpolate and interval == "1s":
        logger.info(f"Generating synthetic 1m data + interpolating to 1s: {assets}, {hours}h")
        data = {}
        for i, asset in enumerate(assets):
            candles_1m = generate_candles(
                asset=asset,
                hours=hours,
                interval_seconds=60,
                start_epoch=1712500000,
                seed=seed + i,
            )
            candles_1s = interpolate_candles(candles_1m, base_seed=seed + i * 1000)
            data[asset] = candles_1s
            logger.info(f"  {asset}: {len(candles_1m)} 1m candles → {len(candles_1s)} 1s candles")
        return data

    interval_s = 1 if interval == "1s" else 60
    logger.info(f"Generating synthetic data: {assets}, {hours}h, {interval} candles")

    data = {}
    for i, asset in enumerate(assets):
        candles = generate_candles(
            asset=asset,
            hours=hours,
            interval_seconds=interval_s,
            start_epoch=1712500000,
            seed=seed + i,
        )
        data[asset] = candles
        logger.info(f"  {asset}: {len(candles)} candles generated")

    return data


def print_combined(results: list[BacktestResult]) -> None:
    """Print combined multi-asset summary."""
    total_pnl = sum(r.total_pnl for r in results)
    total_spent = sum(r.total_spent for r in results)
    total_traded = sum(len(r.traded_intervals) for r in results)
    total_wins = sum(len(r.winning_intervals) for r in results)
    total_trades = sum(r.total_trades for r in results)

    print("=" * 60)
    print("COMBINED RESULTS (ALL ASSETS)")
    print("=" * 60)
    print(f"Assets:             {[r.asset for r in results]}")
    print(f"Total P&L:          ${total_pnl:,.2f}")
    print(f"Total deployed:     ${total_spent:,.2f}")
    if total_spent > 0:
        print(f"ROI:                {total_pnl/total_spent:.2%}")
    if total_traded > 0:
        print(f"Win rate:           {total_wins/total_traded:.1%} ({total_wins}/{total_traded})")
    print(f"Total trades:       {total_trades}")
    print()


async def run_single(args) -> None:
    """Run a single backtest."""
    config = make_config(args)
    backtester = Backtester(config)

    # Try live data first, fall back to synthetic
    data = {}
    if not args.synthetic:
        data = await fetch_live_data(args.assets, args.hours, args.interval)

    if not data:
        if not args.synthetic:
            logger.info("Live data unavailable. Falling back to synthetic data.")
        data = get_synthetic_data(args.assets, args.hours, args.interval, args.seed, args.interpolate)

    all_results: list[BacktestResult] = []
    for asset, candles in data.items():
        logger.info(f"\nRunning backtest for {asset}...")
        result = backtester.run(candles, asset=asset, seed=args.seed)
        all_results.append(result)
        print(result.summary())
        print()

    if len(all_results) > 1:
        print_combined(all_results)


async def run_sweep(args) -> None:
    """Run parameter sweep across edge thresholds and budgets."""
    # Get data once
    data = {}
    if not args.synthetic:
        data = await fetch_live_data(args.assets, args.hours, args.interval)
    if not data:
        if not args.synthetic:
            logger.info("Live data unavailable. Using synthetic data for sweep.")
        data = get_synthetic_data(args.assets, args.hours, args.interval, args.seed, getattr(args, 'interpolate', False))

    edge_values = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
    budget_values = [50, 100, 150, 250]

    print(f"\n{'='*90}")
    print("PARAMETER SWEEP")
    print(f"{'='*90}")
    print(f"{'Edge':>8} {'Budget':>8} {'Asset':>6} {'P&L':>12} {'ROI':>8} {'WinRate':>8} {'Traded':>8} {'Trades':>8}")
    print("-" * 90)

    best_roi = -999
    best_params = None

    for edge in edge_values:
        for budget in budget_values:
            config = BotConfig(
                min_edge_threshold=edge,
                per_market_budget=budget,
                default_clip_size=args.clip_size or 15,
                max_paired_cost=args.paired_cost or 0.95,
            )
            backtester = Backtester(config)

            for asset, candles in data.items():
                result = backtester.run(candles, asset=asset, seed=args.seed)
                traded = len(result.traded_intervals)
                if traded > 0:
                    print(
                        f"{edge:>8.2f} {budget:>8.0f} {asset:>6} "
                        f"${result.total_pnl:>11,.2f} {result.roi:>7.2%} "
                        f"{result.win_rate:>7.1%} {traded:>8} {result.total_trades:>8}"
                    )
                    if result.roi > best_roi and traded >= 10:
                        best_roi = result.roi
                        best_params = (edge, budget, asset)

    print(f"{'='*90}")
    if best_params:
        print(f"\nBEST: edge={best_params[0]}, budget=${best_params[1]}, "
              f"asset={best_params[2]}, ROI={best_roi:.2%}")


async def main() -> None:
    args = parse_args()
    setup_logging("INFO")

    if args.sweep:
        await run_sweep(args)
    else:
        await run_single(args)


if __name__ == "__main__":
    asyncio.run(main())
