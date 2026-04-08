"""
Backtester: replays historical Binance data through the strategy engine.

Simulates 5-minute intervals, generates synthetic Polymarket books,
runs the full strategy pipeline, and tracks P&L with realistic assumptions.
"""

import logging
import math
from dataclasses import dataclass, field

from .data_fetcher import Candle
from .book_simulator import BookSimulator, SimulatedBook
from ..strategy.fair_value import FairValueModel
from ..strategy.edge_calculator import EdgeCalculator, OpportunityType
from ..strategy.risk_manager import RiskManager
from ..core.config import BotConfig

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 300  # 5 minutes


@dataclass
class Trade:
    """A simulated trade in the backtest."""
    interval_start: int
    timestamp: int
    side: str
    shares: float
    price: float
    edge: float
    fair_value: float
    mode: str


@dataclass
class IntervalResult:
    """Result of one 5-minute interval."""
    interval_start: int
    asset: str
    reference_price: float
    final_price: float
    winner: str  # "up" or "down"
    trades: list[Trade] = field(default_factory=list)
    up_shares: float = 0.0
    up_spend: float = 0.0
    down_shares: float = 0.0
    down_spend: float = 0.0

    @property
    def total_spend(self) -> float:
        return self.up_spend + self.down_spend

    @property
    def pnl(self) -> float:
        """Compute P&L based on which side won."""
        if self.winner == "up":
            # Up shares pay $1 each, down shares are worthless
            revenue = self.up_shares * 1.0
        else:
            revenue = self.down_shares * 1.0
        return revenue - self.total_spend

    @property
    def up_vwap(self) -> float:
        return self.up_spend / self.up_shares if self.up_shares > 0 else 0

    @property
    def down_vwap(self) -> float:
        return self.down_spend / self.down_shares if self.down_shares > 0 else 0

    @property
    def paired_cost(self) -> float:
        if self.up_vwap > 0 and self.down_vwap > 0:
            return self.up_vwap + self.down_vwap
        return float("inf")


@dataclass
class BacktestResult:
    """Aggregate backtest results."""
    asset: str
    config: dict
    intervals: list[IntervalResult] = field(default_factory=list)

    @property
    def total_pnl(self) -> float:
        return sum(i.pnl for i in self.intervals)

    @property
    def total_spent(self) -> float:
        return sum(i.total_spend for i in self.intervals)

    @property
    def roi(self) -> float:
        return self.total_pnl / self.total_spent if self.total_spent > 0 else 0

    @property
    def traded_intervals(self) -> list[IntervalResult]:
        return [i for i in self.intervals if i.total_spend > 0]

    @property
    def winning_intervals(self) -> list[IntervalResult]:
        return [i for i in self.traded_intervals if i.pnl > 0]

    @property
    def win_rate(self) -> float:
        traded = len(self.traded_intervals)
        return len(self.winning_intervals) / traded if traded > 0 else 0

    @property
    def total_trades(self) -> int:
        return sum(len(i.trades) for i in self.intervals)

    def summary(self) -> str:
        traded = self.traded_intervals
        wins = self.winning_intervals
        losses = [i for i in traded if i.pnl <= 0]

        avg_win = sum(i.pnl for i in wins) / len(wins) if wins else 0
        avg_loss = sum(i.pnl for i in losses) / len(losses) if losses else 0

        # Mode breakdown
        mode_trades = {}
        mode_pnl = {}
        for interval in traded:
            for t in interval.trades:
                mode_trades[t.mode] = mode_trades.get(t.mode, 0) + 1

        lines = [
            f"{'='*60}",
            f"BACKTEST RESULTS: {self.asset}",
            f"{'='*60}",
            f"Total intervals:    {len(self.intervals)}",
            f"Traded intervals:   {len(traded)}",
            f"Total trades:       {self.total_trades}",
            f"",
            f"Total P&L:          ${self.total_pnl:,.2f}",
            f"Total deployed:     ${self.total_spent:,.2f}",
            f"ROI:                {self.roi:.2%}",
            f"",
            f"Win rate:           {self.win_rate:.1%} ({len(wins)}/{len(traded)})",
            f"Avg win:            ${avg_win:,.2f}",
            f"Avg loss:           ${avg_loss:,.2f}",
            f"Profit factor:      {abs(sum(i.pnl for i in wins) / sum(i.pnl for i in losses)):.2f}" if losses and sum(i.pnl for i in losses) != 0 else "Profit factor:      N/A",
            f"",
            f"Trades by mode:     {mode_trades}",
        ]

        # Equity curve checkpoints
        if traded:
            cumulative = 0
            checkpoints = max(1, len(traded) // 5)
            lines.append(f"")
            lines.append(f"Equity curve (every {checkpoints} intervals):")
            for idx, interval in enumerate(traded):
                cumulative += interval.pnl
                if (idx + 1) % checkpoints == 0 or idx == len(traded) - 1:
                    lines.append(f"  After {idx+1} intervals: ${cumulative:,.2f}")

        return "\n".join(lines)


class Backtester:
    """
    Replays historical candle data through the strategy engine.

    For each 5-minute interval:
    1. Set reference price from first candle
    2. Each second: update fair value, generate simulated book, check entries
    3. At interval end: determine winner, compute P&L
    """

    def __init__(self, config: BotConfig | None = None):
        self.config = config or BotConfig()

    def run(
        self,
        candles: list[Candle],
        asset: str = "BTC",
        seed: int = 42,
    ) -> BacktestResult:
        """
        Run a backtest over historical candle data.

        Args:
            candles: List of 1s or 1m candles, sorted by timestamp.
            asset: Asset name for logging.
            seed: Random seed for book simulation reproducibility.

        Returns:
            BacktestResult with full P&L breakdown.
        """
        if not candles:
            return BacktestResult(asset=asset, config={})

        config = self.config
        result = BacktestResult(
            asset=asset,
            config={
                "min_edge": config.min_edge_threshold,
                "budget": config.per_market_budget,
                "clip_size": config.default_clip_size,
                "max_paired_cost": config.max_paired_cost,
            },
        )

        # Initialize components
        fv_model = FairValueModel(
            min_volatility_bps=config.min_volatility_bps,
            sigmoid_scale=config.sigmoid_scale,
            volatility_window=config.volatility_window_seconds,
        )
        edge_calc = EdgeCalculator(
            min_edge_threshold=config.min_edge_threshold,
            stale_snipe_threshold=config.stale_snipe_threshold,
            max_paired_cost=config.max_paired_cost,
        )
        book_sim = BookSimulator(seed=seed)
        risk_mgr = RiskManager(
            per_market_budget=config.per_market_budget,
            max_daily_loss=config.max_daily_loss,
            max_concurrent_markets=config.max_concurrent_markets,
            max_asset_exposure=config.max_asset_exposure,
            max_paired_cost=config.max_paired_cost,
            consecutive_loss_cooldown=config.consecutive_loss_cooldown,
            cooldown_duration_seconds=config.cooldown_duration_seconds,
        )

        # Build time-indexed price map (timestamp_s → close price)
        price_map: dict[int, float] = {}
        for c in candles:
            price_map[c.timestamp_s] = c.close

        # Determine time range
        start_ts = candles[0].timestamp_s
        end_ts = candles[-1].timestamp_s

        # Align to 5-minute boundaries
        interval_start = start_ts - (start_ts % INTERVAL_SECONDS) + INTERVAL_SECONDS

        total_intervals = 0
        traded_intervals = 0

        while interval_start + INTERVAL_SECONDS <= end_ts:
            total_intervals += 1
            interval_end = interval_start + INTERVAL_SECONDS

            # Get reference price (first second of interval)
            ref_price = None
            for offset in range(10):  # Look within first 10s for a price
                if (interval_start + offset) in price_map:
                    ref_price = price_map[interval_start + offset]
                    break

            if ref_price is None:
                interval_start += INTERVAL_SECONDS
                continue

            # Get final price to determine winner
            final_price = None
            for offset in range(10):
                if (interval_end - offset) in price_map:
                    final_price = price_map[interval_end - offset]
                    break

            if final_price is None:
                interval_start += INTERVAL_SECONDS
                continue

            winner = "up" if final_price >= ref_price else "down"

            # Create interval result
            interval = IntervalResult(
                interval_start=interval_start,
                asset=asset,
                reference_price=ref_price,
                final_price=final_price,
                winner=winner,
            )

            # Reset models for this interval
            fv_model.reset()
            book_sim.reset()

            # Warm up volatility model with a few seconds before interval
            for warmup_t in range(max(start_ts, interval_start - 30), interval_start):
                if warmup_t in price_map:
                    fv_model.update_price(price_map[warmup_t])

            market_id = f"{asset.lower()}-sim-{interval_start}"

            # Check risk before entering this interval
            can_enter, _ = risk_mgr.can_enter_market(market_id, asset)
            if not can_enter:
                result.intervals.append(interval)
                interval_start += INTERVAL_SECONDS
                continue

            # Simulate each second of the interval
            for t in range(INTERVAL_SECONDS):
                current_ts = interval_start + t
                seconds_remaining = INTERVAL_SECONDS - t

                # Timing filter
                if t < config.entry_delay_seconds:
                    # Still in entry delay, just update volatility
                    if current_ts in price_map:
                        fv_model.update_price(price_map[current_ts])
                    continue

                if seconds_remaining < config.min_seconds_remaining:
                    break

                # Get current price
                spot = price_map.get(current_ts)
                if spot is None:
                    continue

                fv_model.update_price(spot)

                # Compute fair value
                fair_up, fair_down = fv_model.compute(spot, ref_price, seconds_remaining)

                # Generate simulated book
                book = book_sim.generate(
                    fair_prob_up=fair_up,
                    fair_prob_down=fair_down,
                    seconds_remaining=seconds_remaining,
                    current_time=current_ts,
                    volatility_bps=fv_model.volatility_bps,
                )

                # Calculate edge
                edge_result = edge_calc.calculate(
                    fair_prob_up=fair_up,
                    fair_prob_down=fair_down,
                    market_ask_up=book.up_best_ask,
                    market_ask_down=book.down_best_ask,
                )

                # Budget check
                if interval.total_spend >= config.per_market_budget:
                    continue

                remaining_budget = config.per_market_budget - interval.total_spend

                # Determine what to trade.
                # The edge calculator already filters for conviction
                # (rejects coin-flip entries where fair value is near 0.50).
                best_side = edge_result.best_side
                best_edge = edge_result.best_edge
                ask = edge_result.ask_up if best_side == "up" else edge_result.ask_down
                mode = edge_result.opportunity.value

                # Prevent double-entry: don't buy the same side twice.
                # Only allow adding to existing position via spread capture (opposite side).
                if edge_result.opportunity in (OpportunityType.DIRECTIONAL, OpportunityType.STALE_SNIPE):
                    if best_side == "up" and interval.up_shares > 0:
                        continue
                    if best_side == "down" and interval.down_shares > 0:
                        continue

                # Spread capture: only if we hold one side, the edge calculator
                # flagged SPREAD_CAPTURE, AND the paired cost is actually cheap.
                if edge_result.opportunity == OpportunityType.SPREAD_CAPTURE:
                    if interval.up_shares > 0 and interval.down_shares > 0:
                        continue  # Already have both sides, skip
                    elif interval.up_shares > 0 or interval.down_shares > 0:
                        held_side = "up" if interval.up_spend > interval.down_spend else "down"
                        held_vwap = interval.up_vwap if held_side == "up" else interval.down_vwap
                        opposite = "down" if held_side == "up" else "up"
                        opposite_ask = edge_result.ask_down if opposite == "down" else edge_result.ask_up

                        if held_vwap + opposite_ask < config.max_paired_cost:
                            best_side = opposite
                            ask = opposite_ask
                            mode = "spread_capture"
                            best_edge = (1.0 - held_vwap - opposite_ask)
                        else:
                            continue  # Paired cost too high
                    else:
                        continue  # No position to hedge — can't spread capture
                elif edge_result.opportunity == OpportunityType.NONE:
                    continue

                # Size the trade: compute fill price FIRST, then size to budget.
                slippage = 0.005  # 0.5% slippage on simulated fills
                fill_price = min(ask * (1 + slippage), 0.99)

                if fill_price <= 0:
                    continue

                shares = min(
                    config.default_clip_size,
                    int(remaining_budget / fill_price),
                )

                if shares <= 0:
                    continue

                cost = shares * fill_price

                # Record trade
                trade = Trade(
                    interval_start=interval_start,
                    timestamp=current_ts,
                    side=best_side,
                    shares=shares,
                    price=fill_price,
                    edge=best_edge,
                    fair_value=fair_up if best_side == "up" else fair_down,
                    mode=mode,
                )
                interval.trades.append(trade)

                if best_side == "up":
                    interval.up_shares += shares
                    interval.up_spend += cost
                else:
                    interval.down_shares += shares
                    interval.down_spend += cost

            # Interval done — record result
            result.intervals.append(interval)

            if interval.total_spend > 0:
                traded_intervals += 1
                risk_mgr.record_market_resolution(market_id, interval.pnl)

            interval_start += INTERVAL_SECONDS

        logger.info(
            f"Backtest complete: {total_intervals} intervals, "
            f"{traded_intervals} traded, P&L=${result.total_pnl:,.2f}"
        )

        return result
