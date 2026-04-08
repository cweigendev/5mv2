"""Bot configuration with conservative defaults derived from eknih + stingo43 analysis."""

from dataclasses import dataclass, field
from pathlib import Path
import json


@dataclass
class BotConfig:
    # Assets to trade
    assets: list[str] = field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP"])

    # Binance trading pairs (derived from assets)
    @property
    def binance_symbols(self) -> list[str]:
        return [f"{asset}USDT" for asset in self.assets]

    # --- Entry Thresholds ---
    # Minimum edge (fair_value - market_ask) to trigger a directional entry.
    # stingo43 uses ~0.35, eknih uses ~0.06. We start moderate.
    min_edge_threshold: float = 0.20

    # Edge above which we suspect a stale/unupdated book — snipe aggressively.
    stale_snipe_threshold: float = 0.40

    # Maximum combined VWAP (up + down) for spread capture mode.
    # eknih avg: 0.9677, stingo43 avg: 0.7020. We use a strict cap.
    max_paired_cost: float = 0.95

    # --- Sizing ---
    # Shares per child order (clip). stingo43: 15, eknih: 7. We split the difference.
    default_clip_size: int = 15

    # Milliseconds between child orders within a burst.
    inter_clip_delay_ms: int = 100

    # Maximum USD spend per market. stingo43 median: $60, eknih median: $350.
    per_market_budget: float = 150.0

    # --- Timing ---
    # Don't enter a market with fewer than this many seconds remaining.
    min_seconds_remaining: int = 30

    # Wait this many seconds into the interval before entering,
    # to let the volatility model warm up with a few data points.
    # Reduced from 10 to 5 — no need to wait longer.
    entry_delay_seconds: int = 5

    # --- Risk ---
    # Stop trading if session P&L drops below this (negative = loss).
    max_daily_loss: float = 500.0

    # Maximum number of markets to be active in simultaneously.
    max_concurrent_markets: int = 10

    # Maximum USD exposure per asset across all active markets.
    max_asset_exposure: float = 1000.0

    # Consecutive market losses before entering cooldown.
    consecutive_loss_cooldown: int = 5

    # Cooldown duration in seconds after consecutive losses.
    cooldown_duration_seconds: int = 300

    # --- Fair Value Model ---
    # Minimum volatility floor in bps (prevents division by near-zero).
    # Lowered from 5.0 to 2.0 — crypto 1s returns are typically 1-20 bps.
    # A floor of 5 made the model overconfident in calm periods.
    min_volatility_bps: float = 2.0

    # Sigmoid scaling factor for z-score → probability conversion.
    sigmoid_scale: float = 0.5

    # Rolling window in seconds for volatility calculation.
    volatility_window_seconds: int = 30

    # --- Execution ---
    # Polymarket API endpoint
    polymarket_api_url: str = "https://clob.polymarket.com"

    # Polymarket WebSocket endpoint
    polymarket_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    # Binance WebSocket endpoint
    binance_ws_url: str = "wss://stream.binance.com:9443/ws"

    # --- Logging ---
    log_level: str = "INFO"
    trade_log_db: str = "trades.db"

    @classmethod
    def from_file(cls, path: str | Path) -> "BotConfig":
        path = Path(path)
        with open(path) as f:
            data = json.load(f)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_file(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        from dataclasses import asdict
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
