#!/usr/bin/env python3
"""
Realistic backtest using REAL 1-minute price data (CryptoCompare via curl).

Data pipeline:
  1. Load real 1-minute OHLCV from data/cache/real_{ASSET}_7d.csv
  2. Interpolate each 1-minute candle into 60 realistic 1-second ticks
     (non-smooth: jumps, fat tails, OHLC-respecting, not linear)
  3. Run the strategy engine second-by-second over 5-minute intervals
  4. Track P&L per interval, aggregate results

What's real:
  - The 1-minute OHLCV prices (actual market data from CryptoCompare)
  - The 5-minute interval outcomes (which side wins)
  - Price volatility, trends, and microstructure

What's still simulated:
  - The Polymarket order book (generated from fair value + noise/spread/staleness)
  - Fill execution (fill at ask + 0.5% slippage)

Usage:
    python run_real_backtest.py                             # All 4 assets, 7d
    python run_real_backtest.py --assets BTC                # BTC only
    python run_real_backtest.py --preset aggressive         # Aggressive config
    python run_real_backtest.py --sweep                     # Parameter sweep
    python run_real_backtest.py --no-interpolate            # Raw 1m (faster, less accurate)
"""

import argparse
import csv
import logging
import math
import time
from pathlib import Path

from src.backtest.data_fetcher import Candle
from src.backtest.price_interpolator import interpolate_candles
from src.backtest.simulator import Backtester, BacktestResult
from src.core.config import BotConfig
from src.core.logger import setup_logging

logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Backtest with real price data")
    parser.add_argument("--assets", nargs="+", default=["BTC", "ETH", "SOL", "XRP"])
    parser.add_argument("--data-dir", default="data/cache", help="Directory with CSV files")
    parser.add_argument("--edge", type=float, default=None)
    parser.add_argument("--budget", type=float, default=None)
    parser.add_argument("--clip-size", type=int, default=None)
    parser.add_argument("--paired-cost", type=float, default=None)
    parser.add_argument("--preset", choices=["conservative", "moderate", "aggressive"], default="moderate")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--no-interpolate", action="store_true", help="Skip 1m→1s interpolation")
    return parser.parse_args()


PRESETS = {
    "conservative": {"min_edge_threshold": 0.30, "per_market_budget": 50.0, "default_clip_size": 10, "max_paired_cost": 0.90},
    "moderate":     {"min_edge_threshold": 0.20, "per_market_budget": 150.0, "default_clip_size": 15, "max_paired_cost": 0.95},
    "aggressive":   {"min_edge_threshold": 0.10, "per_market_budget": 500.0, "default_clip_size": 25, "max_paired_cost": 0.98},
}


def make_config(args):
    p = PRESETS[args.preset]
    config = BotConfig(**{k: v for k, v in p.items()})
    if args.edge is not None: config.min_edge_threshold = args.edge
    if args.budget is not None: config.per_market_budget = args.budget
    if args.clip_size is not None: config.default_clip_size = args.clip_size
    if args.paired_cost is not None: config.max_paired_cost = args.paired_cost
    return config


def load_csv(path: Path) -> list[Candle]:
    """Load candles from a CSV file."""
    candles = []
    with open(path) as f:
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
    return sorted(candles, key=lambda c: c.timestamp)


def load_all_data(assets: list[str], data_dir: str, interpolate: bool = True) -> dict[str, list[Candle]]:
    """Load real data for all assets, optionally interpolate to 1s."""
    data_path = Path(data_dir)
    result = {}

    for asset in assets:
        # Try different file patterns
        candidates = [
            data_path / f"real_{asset}_7d.csv",
            data_path / f"real_{asset}_24h.csv",
            data_path / f"{asset}_1m.csv",
        ]
        csv_path = None
        for c in candidates:
            if c.exists():
                csv_path = c
                break

        if csv_path is None:
            logger.warning(f"No data file found for {asset} in {data_dir}")
            continue

        candles_1m = load_csv(csv_path)
        logger.info(f"Loaded {asset}: {len(candles_1m)} 1-minute candles from {csv_path.name}")

        if interpolate and candles_1m:
            t0 = time.time()
            candles = interpolate_candles(candles_1m, base_seed=42)
            elapsed = time.time() - t0
            logger.info(f"  Interpolated: {len(candles_1m)} 1m → {len(candles)} 1s candles ({elapsed:.1f}s)")
        else:
            candles = candles_1m

        result[asset] = candles

    return result


def print_data_summary(data: dict[str, list[Candle]]):
    """Print what real data we loaded."""
    print("\n" + "=" * 70)
    print("DATASET SUMMARY — REAL PRICE DATA")
    print("=" * 70)

    for asset, candles in data.items():
        if not candles:
            continue
        span_h = (candles[-1].timestamp - candles[0].timestamp) / 3600000
        n_intervals = int(span_h * 12)
        first_p = candles[0].close
        last_p = candles[-1].close
        change_pct = (last_p - first_p) / first_p * 100

        # Compute realized volatility
        returns = []
        step = max(1, len(candles) // 5000)  # Sample for speed
        for i in range(step, len(candles), step):
            if candles[i - step].close > 0:
                ret = (candles[i].close - candles[i - step].close) / candles[i - step].close
                returns.append(ret)
        vol_bps = 0
        if returns:
            vol_bps = math.sqrt(sum(r * r for r in returns) / len(returns)) * 10000

        resolution = "1s" if len(candles) > n_intervals * 300 * 0.5 else "1m"

        print(f"  {asset}:")
        print(f"    Source:        data/cache/real_{asset}_7d.csv")
        print(f"    Candles:       {len(candles):,} ({resolution} resolution)")
        print(f"    Time span:     {span_h:.1f} hours ({span_h/24:.1f} days)")
        print(f"    5m intervals:  ~{n_intervals:,}")
        print(f"    Price:         ${first_p:,.2f} → ${last_p:,.2f} ({change_pct:+.2f}%)")
        print(f"    Volatility:    ~{vol_bps:.1f} bps/tick")
    print()


def print_combined(results: list[BacktestResult]):
    total_pnl = sum(r.total_pnl for r in results)
    total_spent = sum(r.total_spent for r in results)
    total_traded = sum(len(r.traded_intervals) for r in results)
    total_wins = sum(len(r.winning_intervals) for r in results)
    total_trades = sum(r.total_trades for r in results)

    print("=" * 70)
    print("COMBINED RESULTS — REAL PRICE DATA")
    print("=" * 70)
    print(f"Assets:             {[r.asset for r in results]}")
    print(f"Total P&L:          ${total_pnl:,.2f}")
    print(f"Total deployed:     ${total_spent:,.2f}")
    if total_spent > 0:
        print(f"ROI:                {total_pnl / total_spent:.2%}")
    if total_traded > 0:
        print(f"Win rate:           {total_wins}/{total_traded} ({total_wins / total_traded:.1%})")
    print(f"Total trades:       {total_trades}")
    print()
    print("CAVEAT: Polymarket book is simulated. Interval outcomes are real.")
    print()


def run_single(args):
    config = make_config(args)
    data = load_all_data(args.assets, args.data_dir, not args.no_interpolate)
    if not data:
        logger.error("No data loaded. Run fetch_data.sh first.")
        return

    print_data_summary(data)

    backtester = Backtester(config)
    all_results = []

    for asset, candles in data.items():
        logger.info(f"Running backtest: {asset}...")
        result = backtester.run(candles, asset=asset, seed=args.seed)
        all_results.append(result)
        print(result.summary())
        print()

    if len(all_results) > 1:
        print_combined(all_results)


def run_sweep(args):
    data = load_all_data(args.assets, args.data_dir, not args.no_interpolate)
    if not data:
        logger.error("No data loaded. Run fetch_data.sh first.")
        return

    print_data_summary(data)

    edge_values = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
    budget_values = [50, 100, 150, 250]

    print(f"\n{'=' * 95}")
    print("PARAMETER SWEEP — REAL PRICE DATA")
    print(f"{'=' * 95}")
    print(f"{'Edge':>8} {'Budget':>8} {'Asset':>6} {'P&L':>12} {'ROI':>8} {'WinRate':>8} {'Traded':>8} {'Trades':>8}")
    print("-" * 95)

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
                    if result.roi > best_roi and traded >= 20:
                        best_roi = result.roi
                        best_params = (edge, budget, asset, traded)

    print(f"{'=' * 95}")
    if best_params:
        print(f"\nBEST: edge={best_params[0]}, budget=${best_params[1]}, "
              f"asset={best_params[2]}, ROI={best_roi:.2%} ({best_params[3]} intervals)")
    print("\nCAVEAT: Polymarket book is simulated. Interval outcomes are real.")


def main():
    args = parse_args()
    setup_logging("INFO")

    if args.sweep:
        run_sweep(args)
    else:
        run_single(args)


if __name__ == "__main__":
    main()
