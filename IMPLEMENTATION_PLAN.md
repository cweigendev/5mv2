# Implementation Plan: 5-Minute Crypto Up/Down Bot

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Main Event Loop                       │
│                  (async orchestrator)                    │
└──────────┬──────────────┬───────────────┬───────────────┘
           │              │               │
    ┌──────▼──────┐ ┌────▼─────┐  ┌──────▼──────┐
    │  Data Feeds │ │  Engine  │  │  Execution  │
    │  (ingest)   │ │  (brain) │  │  (orders)   │
    └──────┬──────┘ └────┬─────┘  └──────┬──────┘
           │              │               │
    ┌──────▼──────┐ ┌────▼─────┐  ┌──────▼──────┐
    │ Binance WS  │ │Fair Value│  │ Polymarket  │
    │ Polymarket  │ │  Model   │  │  CLOB API   │
    │ WS + REST   │ │          │  │             │
    └─────────────┘ └──────────┘  └─────────────┘
```

## Module Breakdown

### Phase 1: Data Infrastructure (Week 1)

#### Module 1: `src/feeds/binance_ws.py` — Spot Price Feed
- Connect to Binance WebSocket for BTC/USDT, ETH/USDT, SOL/USDT, XRP/USDT
- 1-second OHLCV resolution
- Maintain rolling 30s window of 1s returns for volatility calculation
- Auto-reconnect with exponential backoff
- Record reference price at interval start (second 1)

#### Module 2: `src/feeds/polymarket_ws.py` — Polymarket Book Feed
- Connect to Polymarket CLOB WebSocket
- Track all active 5-minute up/down markets
- Record best bid, best ask, mid price, spread, depth for Up and Down tokens every tick
- Parse market slug to extract: asset, interval epoch, duration

#### Module 3: `src/feeds/market_tracker.py` — Market Lifecycle Manager
- Discover new 5-minute markets as they open
- Track interval metadata: start epoch, expiry epoch, reference price
- Manage market state: PENDING → ACTIVE → TRADING → CLOSED
- Calculate `seconds_remaining` for each active market

### Phase 2: Strategy Engine (Week 2)

#### Module 4: `src/strategy/fair_value.py` — Fair Value Model
Core formula (derived from both bots):
```python
def compute_fair_value(btc_current, btc_ref, seconds_remaining, volatility_bps):
    distance_bps = (btc_current - btc_ref) / btc_ref * 10000
    time_factor = sqrt(seconds_remaining / 300)
    z_score = distance_bps / (time_factor * max(volatility_bps, 5))
    fair_prob_up = 1 / (1 + exp(-z_score * 0.5))
    fair_prob_down = 1 - fair_prob_up
    return fair_prob_up, fair_prob_down
```
- Volatility = rolling 30s std of 1s returns × 10000 (in bps)
- Recalculate every tick (~1s)

#### Module 5: `src/strategy/edge_calculator.py` — Edge Detection
```python
def calculate_edge(fair_prob, market_ask):
    return fair_prob - market_ask
```
- Compute edge for both Up and Down sides
- Flag "stale price" opportunities (edge > 0.40 suggests market hasn't updated)
- Track edge history per market for analytics

#### Module 6: `src/strategy/entry_logic.py` — Entry Decision Engine
Hybrid strategy combining both bots' approaches:

```
MODE 1: DIRECTIONAL (primary, stingo43-inspired)
  IF edge > MIN_EDGE_THRESHOLD (default 0.20):
    IF seconds_remaining in valid window:
      IF market_budget not exhausted:
        → BUY the side with edge
        → Size based on edge magnitude

MODE 2: SPREAD CAPTURE (secondary, eknih-inspired)
  IF we hold one side AND opposite side available:
    IF paired_cost (our_vwap + opposite_ask) < 0.95:
      → BUY opposite side to lock in spread

MODE 3: STALE PRICE SNIPE (opportunistic)
  IF edge > 0.40 AND price < 0.10:
    → Aggressive buy, likely stale book
    → Smaller size (higher risk of stale data)
```

#### Module 7: `src/strategy/risk_manager.py` — Risk Controls
- Per-market budget cap: configurable, default $150
- Per-asset exposure limit
- Total portfolio exposure limit
- Paired-cost discipline: never buy second side if combined > $0.95
- Session P&L circuit breaker (stop if drawdown exceeds threshold)
- Cooldown after N consecutive losses

### Phase 3: Execution Layer (Week 2-3)

#### Module 8: `src/execution/order_manager.py` — Order Execution
- Clip-based execution: split target position into child orders
- Default clip size: 10-20 shares (configurable per asset)
- Inter-clip delay: 0-500ms (minimize impact while maintaining speed)
- Track fills, partial fills, rejects
- VWAP tracking per side per market

#### Module 9: `src/execution/polymarket_client.py` — Polymarket API Client
- REST API for order placement, cancellation, balance queries
- WebSocket for order status updates
- Authentication / signing (Polymarket uses EIP-712 signatures)
- Rate limiting and retry logic

### Phase 4: Infrastructure (Week 3)

#### Module 10: `src/core/config.py` — Configuration
```python
@dataclass
class BotConfig:
    # Assets
    assets: list = ["BTC", "ETH", "SOL", "XRP"]
    
    # Entry thresholds
    min_edge_threshold: float = 0.20      # Minimum edge to enter
    stale_snipe_threshold: float = 0.40   # Edge suggesting stale price
    max_paired_cost: float = 0.95         # Max combined cost for spread capture
    
    # Sizing
    default_clip_size: int = 15           # Shares per child order
    inter_clip_delay_ms: int = 100        # ms between child orders
    per_market_budget: float = 150.0      # Max spend per market
    
    # Timing
    min_seconds_remaining: int = 30       # Don't enter with < 30s left
    entry_delay_seconds: int = 10         # Wait N seconds into interval
    
    # Risk
    max_daily_loss: float = 500.0         # Session circuit breaker
    max_concurrent_markets: int = 10      # Max markets active at once
    max_asset_exposure: float = 1000.0    # Max $ per asset
```

#### Module 11: `src/core/event_loop.py` — Main Orchestrator
```
Every tick (~1 second):
  1. Ingest latest spot prices from Binance
  2. Ingest latest book state from Polymarket
  3. For each active market:
     a. Compute fair value
     b. Calculate edge for both sides
     c. Check entry conditions
     d. If entry triggered → send to order manager
     e. Check if spread capture available
  4. Update P&L tracking
  5. Check risk limits
```

#### Module 12: `src/core/logger.py` — Logging & Analytics
- Every trade: timestamp, market, side, price, size, edge, fair_value
- Every market: entry time, exit/resolution, P&L, strategy mode used
- Aggregate: daily P&L, win rate by asset, win rate by strategy mode
- SQLite database for trade history

### Phase 5: Testing & Simulation (Week 3-4)

#### Module 13: `src/backtest/simulator.py` — Backtester
- Replay historical Polymarket book data + Binance price data
- Simulate fills at historical ask prices
- Track simulated P&L with realistic assumptions:
  - Slippage model
  - Partial fill rates
  - Polymarket fees

#### Module 14: `src/backtest/paper_trader.py` — Paper Trading
- Connect to live feeds but simulate order execution
- Log what would have been traded
- Compare paper P&L to live market outcomes
- Run for minimum 48 hours before going live

## Configuration: Tunable Parameters

| Parameter | Conservative | Moderate | Aggressive |
|---|---|---|---|
| `min_edge_threshold` | 0.30 | 0.20 | 0.10 |
| `per_market_budget` | $50 | $150 | $500 |
| `default_clip_size` | 10 | 15 | 25 |
| `max_paired_cost` | 0.90 | 0.95 | 0.98 |
| `max_daily_loss` | $200 | $500 | $2000 |
| `assets` | BTC only | BTC, ETH | BTC, ETH, SOL, XRP |

## Key Decision: Price Threshold from Decision Trees

Both bots' decision trees reveal that **price** is the #1 splitting feature:
- eknih: Win trades cluster at price > $0.495 (buy expensive = buy favorites)
- stingo43: Win trades cluster at price > $0.49 similarly

**Our approach**: Focus on buying contracts priced $0.05-$0.30 (cheap, high-payout) when edge > 20%, similar to stingo43's profitable pattern. Use spread capture on contracts priced $0.40-$0.60 when both sides available cheap.

## Tech Stack

- **Language**: Python 3.11+
- **Async**: `asyncio` + `aiohttp` for WebSocket connections
- **Data**: `numpy` for calculations, `sqlite3` for trade logging
- **Config**: `dataclasses` + YAML/JSON config files
- **Testing**: `pytest` + `pytest-asyncio`

## File Structure

```
5mv2/
├── src/
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py          # Bot configuration
│   │   ├── event_loop.py      # Main orchestrator
│   │   └── logger.py          # Trade logging + analytics
│   ├── feeds/
│   │   ├── __init__.py
│   │   ├── binance_ws.py      # Binance spot price feed
│   │   ├── polymarket_ws.py   # Polymarket CLOB feed
│   │   └── market_tracker.py  # Market lifecycle management
│   ├── strategy/
│   │   ├── __init__.py
│   │   ├── fair_value.py      # Fair value probability model
│   │   ├── edge_calculator.py # Edge computation
│   │   ├── entry_logic.py     # Entry decision engine
│   │   └── risk_manager.py    # Risk controls
│   ├── execution/
│   │   ├── __init__.py
│   │   ├── order_manager.py   # Clip-based order execution
│   │   └── polymarket_client.py # Polymarket API client
│   └── backtest/
│       ├── __init__.py
│       ├── simulator.py       # Historical backtester
│       └── paper_trader.py    # Live paper trading
├── config/
│   ├── default.yaml           # Default configuration
│   └── aggressive.yaml        # Aggressive preset
├── tests/
│   ├── test_fair_value.py
│   ├── test_edge_calculator.py
│   ├── test_entry_logic.py
│   └── test_risk_manager.py
├── STRATEGY_ANALYSIS.md       # This analysis
├── IMPLEMENTATION_PLAN.md     # This plan
├── requirements.txt
└── main.py                    # Entry point
```

## Implementation Order (Critical Path)

```
Week 1: GET DATA FLOWING
  Day 1-2: Binance WebSocket feed (spot prices for 4 assets)
  Day 3-4: Polymarket WebSocket feed (book data for 5m markets)
  Day 5:   Market tracker (discover + track active markets)

Week 2: BUILD THE BRAIN
  Day 1:   Fair value model
  Day 2:   Edge calculator
  Day 3-4: Entry logic (3 modes: directional, spread, snipe)
  Day 5:   Risk manager

Week 3: EXECUTE TRADES
  Day 1-2: Polymarket API client (auth, order placement)
  Day 3-4: Order manager (clip execution, fill tracking)
  Day 5:   Main event loop (wire everything together)

Week 4: VALIDATE
  Day 1-2: Paper trading mode
  Day 3-4: Run paper trading, analyze results
  Day 5:   Go live with conservative settings
```
