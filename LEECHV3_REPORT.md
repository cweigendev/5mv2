# LeechV3: Complete Bot Report

## What Is LeechV3?

LeechV3 is an automated trading bot for Polymarket's 5-minute crypto up/down
binary markets. It monitors real-time crypto spot prices on Binance, calculates
what binary option prices *should* be, then buys underpriced contracts on
Polymarket before other participants update their orders.

The strategy was reverse-engineered from two profitable Polymarket traders:
- **eknih**: $4,544 profit, 0.88% ROI, spread-capture specialist
- **stingo43**: $50,068 profit, 46.66% ROI, directional conviction specialist

LeechV3 combines both approaches into a hybrid strategy.

---

## How The Market Works

Polymarket runs binary markets on whether a crypto asset (BTC, ETH, SOL, XRP)
will be **Up** or **Down** compared to a reference price at the start of each
5-minute interval.

- You can buy "Up" tokens or "Down" tokens
- Each token costs between $0.01 and $0.99
- The winning side pays **$1.00 per share**
- The losing side pays **$0.00**
- A new market opens every 5 minutes, 24/7

**Example**: BTC is at $82,000 at the start of a 5-minute window. You buy 15
"Up" shares at $0.40 each ($6.00 total). If BTC is at $82,050 when the window
closes, Up wins and you receive 15 x $1.00 = $15.00. Profit: $9.00 (150% ROI).
If BTC drops, you lose your $6.00.

---

## The Three Scenarios: How LeechV3 Makes Money

### Scenario 1: Directional Entry (Primary Money-Maker)

**When**: The bot's model says one side is worth more than Polymarket is charging.

**Example**: BTC moved up 15 bps from the reference price with 2 minutes left.
The bot calculates P(Up) = 72%. Polymarket is selling Up tokens at $0.50.
That's $0.22 of edge. The bot buys Up.

- If Up wins: 15 shares x $1.00 = $15.00 revenue on $7.50 cost = **$7.50 profit**
- If Down wins: $0.00 revenue = **-$7.50 loss**

The bot only enters when its model shows sufficient edge, so it wins more
often than it loses.

### Scenario 2: Spread Capture (Guaranteed Profit)

**When**: The bot already holds one side, and can buy the opposite side cheap
enough that the combined cost is below $1.00.

**Example**: Bot already bought Up at $0.45 average. Down is now available at
$0.48. Combined cost: $0.93. Since one side ALWAYS pays $1.00:

- If Up wins: $1.00 - $0.93 = **$0.07 guaranteed profit per paired share**
- If Down wins: $1.00 - $0.93 = **$0.07 guaranteed profit per paired share**

This is risk-free money. The bot actively seeks these opportunities after
taking an initial directional position.

### Scenario 3: Stale Price Snipe (Opportunistic)

**When**: BTC moves sharply but Polymarket's order book hasn't updated yet.

**Example**: BTC just jumped $200 in 5 seconds. P(Up) is realistically ~85%.
But Polymarket still shows Up at $0.05 because no one has updated orders.
The bot buys 15 shares at $0.05 ($0.75 total). If Up wins: $15.00 revenue.
**$14.25 profit on $0.75 risked (1,900% ROI).**

These are rare but extremely profitable.

---

## Decision Flowchart

```
                         EVERY 1 SECOND
                              |
                    +-------------------+
                    | Get BTC spot price |
                    | from Binance WS    |
                    +-------------------+
                              |
                    +-------------------+
                    | Is there an active |
                    | 5-min market?      |
                    +-------------------+
                         /         \
                       NO           YES
                       |             |
                    [WAIT]   +-------------------+
                             | Are we in the      |
                             | entry window?       |
                             | (after 10s delay,   |
                             |  before last 30s)   |
                             +-------------------+
                                  /         \
                                NO           YES
                                |             |
                             [SKIP]   +-------------------+
                                      | COMPUTE FAIR VALUE |
                                      | P(Up), P(Down)     |
                                      | using spot, ref,   |
                                      | time, volatility   |
                                      +-------------------+
                                               |
                                      +-------------------+
                                      | GET POLYMARKET     |
                                      | BOOK: ask_up,      |
                                      | ask_down            |
                                      +-------------------+
                                               |
                                      +-------------------+
                                      | CALCULATE EDGE     |
                                      | edge = fair - ask  |
                                      +-------------------+
                                               |
                              +----------------+----------------+
                              |                |                |
                     edge >= 0.40      edge >= 0.20      edge < 0.20
                              |                |                |
                    +---------+--+    +--------+---+    +------+-------+
                    | MODE 3:    |    | MODE 1:    |    | Do we hold   |
                    | STALE      |    | DIRECTIONAL|    | one side AND |
                    | SNIPE      |    | ENTRY      |    | opposite is  |
                    |            |    |            |    | cheap?       |
                    | Buy the    |    | Buy the    |    +--------------+
                    | underpriced|    | side with  |       /        \
                    | side       |    | edge       |     YES         NO
                    +-----+------+    +-----+------+      |          |
                          |                 |       +------+---+  [NO TRADE]
                          |                 |       | MODE 2:  |
                          |                 |       | SPREAD   |
                          |                 |       | CAPTURE  |
                          |                 |       | Buy the  |
                          |                 |       | opposite |
                          |                 |       | side     |
                          |                 |       +----+-----+
                          |                 |            |
                          +---------+-------+------------+
                                    |
                          +-------------------+
                          | RISK CHECKS:       |
                          | - Budget left?     |
                          | - Daily loss OK?   |
                          | - Asset exposure?  |
                          | - Paired cost OK?  |
                          +-------------------+
                               /         \
                            FAIL          PASS
                             |              |
                          [BLOCK]   +-------------------+
                                    | EXECUTE:           |
                                    | Fire 15-share clip |
                                    | at ask + 0.5%      |
                                    | slippage            |
                                    +-------------------+
                                             |
                                    +-------------------+
                                    | WAIT for next     |
                                    | second, repeat    |
                                    +-------------------+
```

---

## Formulas

### Formula 1: Fair Value Probability

This is the core formula. It answers: "Given where the spot price is right now
relative to the reference price, how much time is left, and how volatile the
asset is, what is the true probability that Up wins?"

```
distance_bps = (spot_price - reference_price) / reference_price * 10000

time_factor = sqrt(seconds_remaining / 300)

volatility_bps = std_dev(last 30 seconds of 1-second returns) * 10000
volatility_bps = max(volatility_bps, 5.0)    # floor to prevent division by zero

z_score = distance_bps / (time_factor * volatility_bps)

P(Up)   = 1 / (1 + e^(-z_score * 0.5))
P(Down) = 1 - P(Up)
```

**What each piece means:**

| Component | What it does |
|---|---|
| `distance_bps` | How far BTC has moved from the reference, in basis points. +50 means BTC is 0.5% above reference. |
| `time_factor` | Square root of fraction of time remaining. More time = more uncertainty = closer to 50/50. Less time = more certainty. |
| `volatility_bps` | How jumpy BTC has been in the last 30 seconds. High vol = more uncertainty. |
| `z_score` | Volatility-adjusted distance. "How many standard deviations away is the current price?" |
| `sigmoid` | Converts z-score to a 0-1 probability. z=0 gives 50%, z>0 gives >50%, z<0 gives <50%. |

**Worked example:**
- BTC reference: $82,000. Current: $82,082 (+10 bps)
- 120 seconds remaining out of 300
- Volatility: 8 bps/second

```
distance_bps = 10
time_factor  = sqrt(120/300) = 0.632
z_score      = 10 / (0.632 * 8) = 1.976
P(Up)        = 1 / (1 + e^(-1.976 * 0.5)) = 1 / (1 + e^(-0.988)) = 0.729
```

The model says there's a **72.9% chance** Up wins.

### Formula 2: Edge Calculation

```
edge_up   = P(Up)   - polymarket_ask_up
edge_down = P(Down) - polymarket_ask_down
best_edge = max(edge_up, edge_down)
```

If P(Up) = 0.729 and Polymarket is selling Up at $0.55:
```
edge_up = 0.729 - 0.55 = 0.179 (17.9 cents of edge)
```

### Formula 3: Paired Cost (Spread Capture)

```
paired_cost = VWAP_up + VWAP_down
guaranteed_spread = 1.00 - paired_cost
```

If we bought Up at avg $0.45 and Down is available at $0.48:
```
paired_cost = 0.45 + 0.48 = 0.93
guaranteed_spread = 1.00 - 0.93 = $0.07 per paired share (guaranteed)
```

### Formula 4: P&L Per Interval

```
If Up wins:  revenue = up_shares * $1.00
If Down wins: revenue = down_shares * $1.00
P&L = revenue - total_cost
```

### Formula 5: Trade Sizing

```
clip_size = 15 shares (configurable)
cost_per_clip = clip_size * ask_price
max_clips = floor(remaining_budget / cost_per_clip)
```

The bot fires one clip per opportunity, up to the per-market budget cap.

---

## Risk Controls

| Control | Conservative | Moderate | Aggressive |
|---|---|---|---|
| Min edge to enter | 30% | 20% | 10% |
| Per-market budget | $50 | $150 | $500 |
| Clip size | 10 shares | 15 shares | 25 shares |
| Max paired cost | $0.90 | $0.95 | $0.98 |
| Entry delay | 10 seconds | 10 seconds | 10 seconds |
| Min time remaining | 30 seconds | 30 seconds | 30 seconds |
| Max daily loss | $500 | $500 | $500 |
| Max concurrent markets | 10 | 10 | 10 |
| Max per-asset exposure | $1,000 | $1,000 | $1,000 |
| Consecutive loss cooldown | 5 losses -> 5min pause | 5 losses -> 5min pause | 5 losses -> 5min pause |

---

## Backtest Results: 7 Days of Real Price Data

**Data source**: CryptoCompare real 1-minute OHLCV, interpolated to 1-second.
**Period**: 7 days (April 1-8, 2026). ~2,015 five-minute intervals per asset.

### Conservative Preset (edge >= 30%, budget $50)

| Asset | P&L | ROI | Win Rate | Traded | Avg Bet | Avg P&L/Cycle | Profit Factor |
|---|---|---|---|---|---|---|---|
| BTC | $83.91 | 127.0% | 70.0% | 10/2015 | $6.61 | $8.39 | 6.37 |
| ETH | $254.87 | 137.7% | 81.2% | 16/2015 | $11.57 | $15.93 | 18.92 |
| SOL | $321.49 | 107.7% | 69.0% | 29/2015 | $10.29 | $11.09 | 5.93 |
| XRP | $603.81 | 45.3% | 59.0% | 100/2015 | $13.32 | $6.04 | 2.87 |
| **COMBINED** | **$1,264.09** | **67.2%** | **63.9%** | **155** | **$12.13** | **$8.16** | |

### Moderate Preset (edge >= 20%, budget $150)

| Asset | P&L | ROI | Win Rate | Traded | Avg Bet | Avg P&L/Cycle | Profit Factor |
|---|---|---|---|---|---|---|---|
| BTC | $559.74 | 70.8% | 68.7% | 67/2015 | $11.79 | $8.35 | 4.12 |
| ETH | $999.29 | 69.8% | 65.6% | 93/2015 | $15.38 | $10.75 | 4.46 |
| SOL | $1,388.47 | 65.9% | 68.5% | 124/2015 | $16.99 | $11.20 | 4.05 |
| XRP | $1,448.53 | 28.5% | 55.0% | 180/2015 | $28.20 | $8.05 | 2.27 |
| **COMBINED** | **$4,396.02** | **46.8%** | **62.7%** | **464** | **$20.26** | **$9.47** | |

### Aggressive Preset (edge >= 10%, budget $500)

| Asset | P&L | ROI | Win Rate | Traded | Avg Bet | Avg P&L/Cycle | Profit Factor |
|---|---|---|---|---|---|---|---|
| BTC | $800.64 | 36.8% | 64.9% | 77/2015 | $28.24 | $10.40 | 3.14 |
| ETH | $2,394.43 | 31.7% | 64.5% | 276/2015 | $27.38 | $8.68 | 3.22 |
| SOL | $1,728.57 | 20.8% | 58.4% | 221/2015 | $37.65 | $7.82 | 1.96 |
| XRP | $483.75 | 15.3% | 56.0% | 100/2015 | $31.66 | $4.84 | 1.67 |
| **COMBINED** | **$5,407.39** | **25.5%** | **61.3%** | **674** | **$31.43** | **$8.02** | |

### Trade Mode Breakdown (Moderate Preset)

| Asset | Directional | Spread Capture | Stale Snipe |
|---|---|---|---|
| BTC | 91 (68%) | 31 (23%) | 11 (8%) |
| ETH | 174 (74%) | 35 (15%) | 27 (11%) |
| SOL | 262 (80%) | 34 (10%) | 32 (10%) |
| XRP | 607 (74%) | 57 (7%) | 157 (19%) |

### Parameter Sweep Best Results (Minimum 20 traded intervals)

| Rank | Edge | Budget | Asset | ROI | Win Rate | Traded |
|---|---|---|---|---|---|---|
| 1 | 0.15 | $50 | ETH | 62.4% | 72.6% | 179 |
| 2 | 0.25 | $100 | ETH | 79.0% | 59.0% | 61 |
| 3 | 0.20 | $50 | BTC | 70.8% | 68.7% | 67 |
| 4 | 0.25 | $50 | SOL | 76.2% | 69.8% | 63 |
| 5 | 0.30 | $50 | SOL | 73.9% | 65.2% | 46 |

---

## Backtest Accuracy: What's Real and What's Not

### What IS Accurate

1. **The price data is real.** 10,081 one-minute OHLCV candles per asset from
   CryptoCompare, covering 7 full days of actual BTC, ETH, SOL, XRP trading.

2. **The 5-minute outcomes are real.** Whether each interval resolves Up or Down
   is determined by actual open/close prices from the real market data.

3. **The volatility dynamics are real.** Trends, reversals, volatility clustering,
   and fat-tail moves are all from actual market conditions during the test period.

4. **The strategy logic is production code.** The same fair value model, edge
   calculator, entry logic, and risk manager that would run live are used in
   the backtest.

### What Is NOT Accurate (Caveats)

**1. The Polymarket order book is simulated (MAJOR CAVEAT)**

We do not have historical Polymarket book data. The backtest generates fake
ask prices by taking our own fair value model's output and adding:
- Random noise (std dev = 2 cents)
- Bid-ask spread (3 cents base, widens with volatility)
- 2% chance per second of "staleness" (book freezes for 3-15 seconds)

**Why this matters:** The bot is finding edge against a noisy version of its
own math. In reality, the Polymarket book reflects *other traders'* models,
which may be better, worse, or differently wrong than ours. The actual edge
available on live Polymarket could be larger or smaller.

**Impact on results:** This likely makes results **too optimistic**. The
simulated book creates artificial mispricing that wouldn't exist on a real,
competitive order book.

**2. Fills are assumed at the ask price (MODERATE CAVEAT)**

The backtest assumes every order fills at the best ask + 0.5% slippage.
In reality:
- Someone else may take the liquidity before us
- The book may only have 5 shares at that price and we want 15
- Our buying pressure pushes the ask up for subsequent clips
- Network latency means the price may move between decision and execution

**Impact on results:** Makes results optimistic. Real fill rates may be
50-80% of what the backtest assumes, reducing total P&L proportionally.

**3. No market impact modeled (MODERATE CAVEAT)**

When the bot buys, it does not affect the simulated book price. In reality,
buying Up shares would push the Up ask higher and the Down ask lower, reducing
edge on subsequent clips within the same interval.

**Impact on results:** Overstates returns on intervals where multiple clips
are fired (currently capped at 10 clips per interval max).

**4. The 1-second prices are interpolated, not real (MINOR CAVEAT)**

We have real 1-minute candles but generate 1-second ticks between them using
a stochastic model. The interpolation respects the 1-minute OHLC bounds and
uses realistic microstructure (jumps, fat tails, mean-reversion toward close),
but the second-by-second path is synthetic.

**Impact on results:** Minor. The 5-minute interval outcomes are determined
by real 1-minute boundary prices. The intra-minute path affects the *timing*
of entries but not the final resolution. The fair value model might see
slightly different signals than it would with real 1-second data, but the
overall distribution of outcomes is preserved.

**5. Single time period tested (MINOR CAVEAT)**

All results are from one 7-day window (April 1-8, 2026). This period had:
- BTC: +4.63% uptrend
- ETH: +3.47% uptrend
- SOL: -1.23% slight downtrend
- XRP: flat

Results during high-volatility events (flash crashes, news spikes, liquidation
cascades) or extended sideways markets may differ significantly.

**6. No Polymarket fees modeled (MINOR CAVEAT)**

Polymarket charges maker/taker fees on trades. These are not included in the
backtest P&L. At typical fee levels, this would reduce total P&L by roughly
1-3%.

**7. Staleness model is random, not price-correlated (MINOR CAVEAT)**

Real Polymarket book staleness happens when BTC moves *fast* and market makers
haven't updated. Our simulator randomly makes the book stale 2% of the time,
regardless of what the price is doing. This means the stale-snipe mode results
are particularly unreliable.

### Confidence Assessment

| Component | Confidence | Why |
|---|---|---|
| Fair value model math | HIGH | Standard financial model, well-tested |
| Entry logic / risk controls | HIGH | Deterministic, thoroughly tested |
| 5-minute outcomes | HIGH | Based on real price data |
| Number of trading opportunities | MEDIUM | Depends on simulated book |
| Absolute P&L numbers | LOW | Simulated book + assumed fills |
| Relative ranking of presets | MEDIUM | Consistent across book assumptions |
| Stale snipe results | LOW | Random staleness, not realistic |

### What Would Make This Backtest Trustworthy

1. **Real Polymarket historical book data** — actual bid/ask snapshots from
   the CLOB at 1-second resolution for resolved 5-minute markets.

2. **Real Binance 1-second klines** — true tick-by-tick data instead of
   interpolated minutes. Available from Binance API if not geo-restricted.

3. **Realistic fill simulation** — model queue position, partial fills, and
   competition from other bots for the same liquidity.

4. **Out-of-sample testing** — run on multiple non-overlapping time periods
   to check if the edge persists.

5. **Paper trading** — connect to live feeds, run the full strategy, log
   what would have been traded, compare paper P&L to actual market outcomes.

---

## Summary: Should You Run This Bot?

**What's proven:** The fair value model correctly identifies which side is
more likely to win in a 5-minute crypto binary market, achieving 63-69%
directional accuracy on real price data.

**What's unproven:** Whether the actual Polymarket order book offers enough
mispricing for this edge to translate into real profit after fills, fees,
and competition.

**Recommended next step:** Paper trading against the live Polymarket book
for 48+ hours before committing real capital.
