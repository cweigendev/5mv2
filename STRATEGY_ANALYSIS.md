# Crypto Bot Strategy Analysis: eknih vs stingo43

## Cross-Bot Comparison

| Dimension | eknih (Bot 1) | stingo43 (Bot 2) | Our Target |
|---|---|---|---|
| **Profit** | $4,544 (0.88% ROI) | $50,068 (46.66% ROI) | Hybrid approach |
| **Primary Strategy** | Spread capture (99% both-sides) | Directional + hedging (8% both-sides) | Directional-first, spread when available |
| **Assets** | BTC only | BTC, ETH, SOL, XRP | Multi-asset |
| **Median Clip Size** | 7 shares @ $0.44 | 15 shares @ $0.15 | 10-20 shares, price-dependent |
| **Execution Speed** | 76% within 2s | 98% within 2s | Target 99%+ within 1s |
| **Market Win Rate** | 65.0% | 54.7% | Target 55%+ |
| **Trade Win Rate** | 46.2% | 32.8% | N/A (trade win rate misleading) |
| **Min Edge Threshold** | ~6% | ~35% | 20%+ (tunable) |
| **Paired Cost Avg** | $0.9677 | $0.7020 | < $0.95 |
| **Per-Market Budget** | ~$350 median | ~$60 median | $100-200 (configurable) |

## 8 Overlapping Best Practices (Alpha Signals)

### 1. Fair-Value Model: Spot Price vs Reference Price
Both bots compute real-time fair probability using BTC's distance from the interval reference price, adjusted for time remaining and volatility. This is THE core signal.

### 2. Edge-Based Entry Only
Neither bot enters without positive edge (`fair_value - market_ask > threshold`). eknih uses ~6% minimum, stingo43 uses ~35%. Higher thresholds = fewer trades but much higher ROI.

### 3. Burst/Clip Execution
Both split positions into many small child orders fired in rapid succession (<2s gaps). This minimizes market impact and handles partial fills gracefully.

### 4. Paired-Cost Discipline
When buying both sides, both enforce `up_vwap + down_vwap < $1.00`. This creates guaranteed profit on matched portions regardless of outcome.

### 5. Stale Price Sniping
Both detect when Polymarket prices lag behind spot price movements and exploit the mispricing before other participants update.

### 6. Per-Market Budget Caps
Both cap total exposure per market to prevent runaway losses on any single interval.

### 7. Mid-Interval Entry Timing
Both prefer entering after the interval begins (not at the edges), waiting for price to establish direction before committing capital.

### 8. Fully Automated WebSocket-Driven Execution
Both run on real-time WebSocket feeds from exchanges (Binance) and Polymarket's CLOB with sub-second decision cycles.

## Why stingo43 Makes 11x More Money

1. **Higher edge threshold (35% vs 6%)**: Fewer but far more profitable trades
2. **Buying cheap contracts ($0.15 median)**: Deep OTM options that pay 6-7x when correct
3. **Multi-asset diversification**: 4 coins = 4x the opportunity surface
4. **Aggressive directional conviction**: Up to 57x capital ratios on high-conviction bets
5. **Lower paired cost ($0.70 vs $0.97)**: Much wider spread capture when hedging

## Critical Lesson

eknih's spread-capture strategy is *safe* but low-ROI. stingo43's directional approach with selective hedging is *aggressive* but massively more profitable. Our bot should be directional-first (like stingo43) with spread-capture as a secondary mode (like eknih) when both sides are cheap enough.
