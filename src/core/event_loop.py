"""
Main event loop: the orchestrator that wires everything together.

Every ~1 second:
1. Ingest latest spot prices from Binance
2. Ingest latest book state from Polymarket
3. For each active market: compute fair value, check entry conditions
4. If entry triggered → send clips to order manager
5. Track P&L and enforce risk limits
"""

import asyncio
import logging
import time

from ..core.config import BotConfig
from ..feeds.binance_ws import BinanceFeed
from ..feeds.polymarket_ws import PolymarketFeed
from ..feeds.market_tracker import MarketTracker, MarketState
from ..strategy.fair_value import FairValueModel
from ..strategy.edge_calculator import EdgeCalculator
from ..strategy.entry_logic import EntryLogic
from ..strategy.risk_manager import RiskManager
from ..execution.order_manager import OrderManager
from ..execution.polymarket_client import PolymarketClient

logger = logging.getLogger(__name__)


class TradingBot:
    """Main trading bot orchestrator."""

    def __init__(self, config: BotConfig):
        self.config = config

        # Data feeds
        self.binance = BinanceFeed(
            symbols=config.binance_symbols,
            ws_base_url=config.binance_ws_url,
        )
        self.polymarket_feed = PolymarketFeed(ws_url=config.polymarket_ws_url)
        self.market_tracker = MarketTracker(target_assets=config.assets)

        # Strategy
        self.fair_value_models: dict[str, FairValueModel] = {}
        for asset in config.assets:
            self.fair_value_models[asset] = FairValueModel(
                min_volatility_bps=config.min_volatility_bps,
                sigmoid_scale=config.sigmoid_scale,
                volatility_window=config.volatility_window_seconds,
            )

        self.edge_calculator = EdgeCalculator(
            min_edge_threshold=config.min_edge_threshold,
            stale_snipe_threshold=config.stale_snipe_threshold,
            max_paired_cost=config.max_paired_cost,
        )

        self.entry_logic = EntryLogic(
            min_edge_threshold=config.min_edge_threshold,
            default_clip_size=config.default_clip_size,
            per_market_budget=config.per_market_budget,
            min_seconds_remaining=config.min_seconds_remaining,
            entry_delay_seconds=config.entry_delay_seconds,
            max_paired_cost=config.max_paired_cost,
        )

        self.risk_manager = RiskManager(
            per_market_budget=config.per_market_budget,
            max_daily_loss=config.max_daily_loss,
            max_concurrent_markets=config.max_concurrent_markets,
            max_asset_exposure=config.max_asset_exposure,
            max_paired_cost=config.max_paired_cost,
            consecutive_loss_cooldown=config.consecutive_loss_cooldown,
            cooldown_duration_seconds=config.cooldown_duration_seconds,
        )

        # Execution
        self.poly_client = PolymarketClient(api_url=config.polymarket_api_url)
        self.order_manager = OrderManager(
            polymarket_client=self.poly_client,
            default_clip_size=config.default_clip_size,
            inter_clip_delay_ms=config.inter_clip_delay_ms,
        )

        self._running = False

    async def start(self) -> None:
        """Start all feeds and the main trading loop."""
        self._running = True
        logger.info(f"Starting bot with assets: {self.config.assets}")
        logger.info(f"Edge threshold: {self.config.min_edge_threshold}, budget/market: ${self.config.per_market_budget}")

        # Register price callbacks for volatility tracking
        for asset in self.config.assets:
            symbol = f"{asset.lower()}usdt"
            model = self.fair_value_models[asset]
            self.binance.on_price(symbol, self._make_price_callback(model))

        # Start feeds and trading loop concurrently
        await asyncio.gather(
            self.binance.start(),
            self.polymarket_feed.start(),
            self._market_discovery_loop(),
            self._trading_loop(),
        )

    def _make_price_callback(self, model: FairValueModel):
        async def callback(symbol: str, price: float):
            model.update_price(price)
        return callback

    async def _market_discovery_loop(self) -> None:
        """Periodically discover new 5-minute markets from Polymarket."""
        while self._running:
            try:
                markets = await self.poly_client.get_active_markets()
                for m in markets:
                    slug = m.get("slug", "")
                    market_id = m.get("id", "")
                    tokens = m.get("tokens", [])

                    if len(tokens) >= 2:
                        up_token = tokens[0].get("token_id", "")
                        down_token = tokens[1].get("token_id", "")

                        info = self.market_tracker.register_market(
                            market_id=market_id,
                            slug=slug,
                            up_token_id=up_token,
                            down_token_id=down_token,
                        )
                        if info:
                            self.polymarket_feed.register_market(
                                market_id, up_token, down_token
                            )
                            await self.polymarket_feed.subscribe_market(market_id)

            except Exception as e:
                logger.error(f"Market discovery error: {e}")

            await asyncio.sleep(30)  # Check for new markets every 30s

    async def _trading_loop(self) -> None:
        """Main trading loop — runs every second."""
        # Wait for initial data
        await asyncio.sleep(5)

        while self._running:
            loop_start = time.time()

            try:
                # Update market states
                newly_active = self.market_tracker.update_states()

                # Set reference prices for newly active markets
                for info in newly_active:
                    symbol = f"{info.asset.lower()}usdt"
                    ref_price = self.binance.get_price(symbol)
                    if ref_price:
                        self.market_tracker.set_reference_price(info.market_id, ref_price)

                # Process each active market
                for info in self.market_tracker.get_active_markets():
                    await self._process_market(info)

                # Cleanup old resolved markets
                self.market_tracker.cleanup_resolved()

            except Exception as e:
                logger.error(f"Trading loop error: {e}")

            # Aim for 1-second tick rate
            elapsed = time.time() - loop_start
            sleep_time = max(0, 1.0 - elapsed)
            await asyncio.sleep(sleep_time)

    async def _process_market(self, info) -> None:
        """Evaluate and potentially trade in a single market."""
        # Get current spot price
        symbol = f"{info.asset.lower()}usdt"
        spot_price = self.binance.get_price(symbol)
        if not spot_price or not info.reference_price:
            return

        # Get current book state
        book = self.polymarket_feed.get_book(info.market_id)
        if not book:
            return

        # Compute fair value
        model = self.fair_value_models[info.asset]
        fair_up, fair_down = model.compute(
            spot_price=spot_price,
            reference_price=info.reference_price,
            seconds_remaining=info.seconds_remaining,
        )

        # Calculate edge
        edge_result = self.edge_calculator.calculate(
            fair_prob_up=fair_up,
            fair_prob_down=fair_down,
            market_ask_up=book.up.best_ask,
            market_ask_down=book.down.best_ask,
        )

        # Check risk limits
        can_enter, reason = self.risk_manager.can_enter_market(
            info.market_id, info.asset
        )
        if not can_enter:
            return

        # Get existing position info
        pos = self.risk_manager.positions.get(info.market_id)
        held_side = pos.held_side if pos else None
        held_vwap = None
        if pos:
            held_vwap = pos.up_vwap if held_side == "up" else pos.down_vwap

        # Evaluate entry
        signal = self.entry_logic.evaluate(
            edge_result=edge_result,
            seconds_remaining=info.seconds_remaining,
            market_spend=pos.total_spend if pos else 0.0,
            held_side=held_side,
            held_vwap=held_vwap,
        )

        if signal and signal.should_enter:
            # Final risk check on this specific order
            can_add, add_reason = self.risk_manager.can_add_to_position(
                info.market_id, signal.side, signal.size_shares, signal.limit_price
            )
            if not can_add:
                logger.debug(f"Risk blocked: {add_reason}")
                return

            # Select token ID
            token_id = info.up_token_id if signal.side == "up" else info.down_token_id

            logger.info(
                f"ENTRY: {info.slug} {signal.side} {signal.size_shares}@{signal.limit_price:.4f} "
                f"mode={signal.mode.value} | {signal.reason}"
            )

            # Execute via clip orders
            clips = await self.order_manager.execute_entry(
                market_id=info.market_id,
                token_id=token_id,
                side=signal.side,
                total_shares=signal.size_shares,
                limit_price=signal.limit_price,
            )

            # Record fills in risk manager (simplified — real impl would use fill callbacks)
            for clip in clips:
                if clip.filled_size > 0:
                    self.risk_manager.record_fill(
                        market_id=info.market_id,
                        asset=info.asset,
                        side=signal.side,
                        shares=clip.filled_size,
                        price=clip.filled_avg_price,
                    )

    async def stop(self) -> None:
        """Gracefully shut down all components."""
        self._running = False
        logger.info("Shutting down...")
        await asyncio.gather(
            self.binance.stop(),
            self.polymarket_feed.stop(),
            self.poly_client.close(),
        )
        logger.info(
            f"Session summary: P&L=${self.risk_manager.session_pnl:.2f}, "
            f"Win rate={self.risk_manager.win_rate:.1%}, "
            f"Markets={self.risk_manager.resolved_markets}"
        )
