"""
5-Minute Crypto Up/Down Trading Bot — Entry Point

Hybrid strategy combining:
- stingo43's directional conviction (46.66% ROI)
- eknih's spread capture discipline (65% market win rate)
- Both bots' stale price sniping, burst execution, and risk management

Usage:
    python main.py                    # Run with default config
    python main.py --config config/aggressive.yaml
    python main.py --paper            # Paper trading mode (no real orders)
"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from src.core.config import BotConfig
from src.core.event_loop import TradingBot
from src.core.logger import setup_logging, TradeLogger

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="5m Crypto Up/Down Bot")
    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to JSON config file",
    )
    parser.add_argument(
        "--paper", action="store_true",
        help="Paper trading mode (log trades but don't execute)",
    )
    parser.add_argument(
        "--assets", nargs="+", default=None,
        help="Override which assets to trade (e.g., --assets BTC ETH)",
    )
    parser.add_argument(
        "--edge", type=float, default=None,
        help="Override minimum edge threshold",
    )
    parser.add_argument(
        "--budget", type=float, default=None,
        help="Override per-market budget",
    )
    return parser.parse_args()


async def run(config: BotConfig, paper: bool = False) -> None:
    trade_logger = TradeLogger(db_path=config.trade_log_db)
    bot = TradingBot(config)

    # Handle graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(bot.stop()))

    try:
        logger.info("=" * 60)
        logger.info("5-Minute Crypto Up/Down Bot")
        logger.info(f"  Assets: {config.assets}")
        logger.info(f"  Min edge: {config.min_edge_threshold}")
        logger.info(f"  Budget/market: ${config.per_market_budget}")
        logger.info(f"  Clip size: {config.default_clip_size}")
        logger.info(f"  Paper mode: {paper}")
        logger.info("=" * 60)

        await bot.start()

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        await bot.stop()
        stats = trade_logger.get_session_stats()
        logger.info(f"Session stats: {stats}")
        trade_logger.close()


def main() -> None:
    args = parse_args()

    # Load or create config
    if args.config:
        config = BotConfig.from_file(args.config)
    else:
        config = BotConfig()

    # Apply CLI overrides
    if args.assets:
        config.assets = [a.upper() for a in args.assets]
    if args.edge is not None:
        config.min_edge_threshold = args.edge
    if args.budget is not None:
        config.per_market_budget = args.budget

    setup_logging(config.log_level)
    asyncio.run(run(config, paper=args.paper))


if __name__ == "__main__":
    main()
