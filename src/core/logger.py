"""
Trade logging and analytics.

Stores every trade and market resolution in SQLite for post-session analysis.
"""

import logging
import sqlite3
import time
from pathlib import Path


def setup_logging(level: str = "INFO") -> None:
    """Configure console + file logging."""
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=log_format,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("bot.log"),
        ],
    )


class TradeLogger:
    """SQLite-backed trade and market resolution logger."""

    def __init__(self, db_path: str = "trades.db"):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                market_id TEXT NOT NULL,
                slug TEXT,
                asset TEXT,
                side TEXT NOT NULL,
                shares REAL NOT NULL,
                price REAL NOT NULL,
                edge REAL,
                fair_value REAL,
                mode TEXT,
                order_id TEXT
            );

            CREATE TABLE IF NOT EXISTS market_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                market_id TEXT NOT NULL,
                slug TEXT,
                asset TEXT,
                winner TEXT,
                up_spend REAL,
                down_spend REAL,
                up_shares REAL,
                down_shares REAL,
                pnl REAL NOT NULL,
                mode TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_trades_market ON trades(market_id);
            CREATE INDEX IF NOT EXISTS idx_trades_asset ON trades(asset);
            CREATE INDEX IF NOT EXISTS idx_results_asset ON market_results(asset);
        """)
        self._conn.commit()

    def log_trade(
        self,
        market_id: str,
        slug: str,
        asset: str,
        side: str,
        shares: float,
        price: float,
        edge: float,
        fair_value: float,
        mode: str,
        order_id: str = "",
    ) -> None:
        self._conn.execute(
            """INSERT INTO trades
               (timestamp, market_id, slug, asset, side, shares, price, edge, fair_value, mode, order_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (time.time(), market_id, slug, asset, side, shares, price, edge, fair_value, mode, order_id),
        )
        self._conn.commit()

    def log_market_result(
        self,
        market_id: str,
        slug: str,
        asset: str,
        winner: str,
        up_spend: float,
        down_spend: float,
        up_shares: float,
        down_shares: float,
        pnl: float,
        mode: str,
    ) -> None:
        self._conn.execute(
            """INSERT INTO market_results
               (timestamp, market_id, slug, asset, winner, up_spend, down_spend, up_shares, down_shares, pnl, mode)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (time.time(), market_id, slug, asset, winner, up_spend, down_spend, up_shares, down_shares, pnl, mode),
        )
        self._conn.commit()

    def get_session_stats(self) -> dict:
        """Get aggregate stats for the current session."""
        cursor = self._conn.execute(
            "SELECT COUNT(*), SUM(pnl), SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) FROM market_results"
        )
        row = cursor.fetchone()
        total = row[0] or 0
        total_pnl = row[1] or 0.0
        wins = row[2] or 0

        return {
            "total_markets": total,
            "total_pnl": total_pnl,
            "win_rate": wins / total if total > 0 else 0.0,
            "wins": wins,
            "losses": total - wins,
        }

    def get_stats_by_asset(self) -> dict:
        cursor = self._conn.execute(
            """SELECT asset, COUNT(*), SUM(pnl), SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)
               FROM market_results GROUP BY asset"""
        )
        result = {}
        for row in cursor:
            asset, count, pnl, wins = row
            result[asset] = {
                "markets": count,
                "pnl": pnl or 0.0,
                "win_rate": (wins or 0) / count if count > 0 else 0.0,
            }
        return result

    def close(self) -> None:
        self._conn.close()
