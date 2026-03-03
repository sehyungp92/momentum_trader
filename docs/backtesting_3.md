Below is a detailed, implementation-oriented spec for how I’d **extensively backtest + optimize + ablate** the v4.0 strategy.

---

# 1) Goals and core questions

## Primary goals

1. **Validate** the strategy edge across regimes and time periods.
2. **Optimize** key variables without overfitting.
3. **Measure marginal value** of each major filter/condition (ablation study).
4. Quantify tradeoffs: **EV vs frequency**, drawdown, tail risk, and robustness.

## Questions you want answered

* Which entry archetype produces most of the edge? (Type A vs Type B vs Flip)
* Does Predator overlay add meaningfully (as size overlay)? or is it cosmetic?
* Does the VWAP cap reduce blow-ups or does it block the best breakouts?
* Does Earn-the-Hold improve total return vs just reduce DD?
* Is 5m micro-trigger worth the complexity (better EV) or does it reduce fills?
* Are event blocks/re-arm conditions genuinely protective or overly conservative?
* Are min/max stop guardrails correctly calibrated for NQ?

---

# 2) Backtest engine architecture

## 2.1 Use Backtrader as the orchestration engine

Backtrader is good for:

* multi-timeframe
* indicator pipelines
* event-driven order simulation
* analyzers + optimization runs

But Backtrader is **not** great at:

* realistic stop-limit fill simulation with partial fills and market microstructure
* futures contract roll mechanics unless you implement continuous futures

So: keep Backtrader as the framework, but implement custom:

* **Execution model**
* **Roll/continuous contract feed**
* **Spread/slippage model**
* **Decision gate logic** tied to ET time

### Recommended approach

* Use Backtrader for the **strategy logic and event timing**
* Use custom `Broker` / `CommissionInfo` / execution hooks for realistic fills

---

# 3) Data: sourcing, integrity, and alignment

## 3.1 Data sources

You have two viable routes:

### Route A: IBKR historical data (practical, but limited)

Pros: easy in your stack, same vendor as live
Cons: pacing limits, incomplete depth/spread, limited history, potential gaps

Use IBKR for:

* NQ 15m, 1h, 5m (optional)
* ES daily (regime) (or SPY daily fallback)
* bid/ask snapshots if you want spread proxy (hard historically)

### Route B: External futures data (better for rigorous research)

Pros: complete history, more reliable, easier to replay with realistic bars
Cons: extra vendor

If you truly want “extensive” optimization and ablations, I’d strongly recommend Route B for data and keep IBKR for live execution. But if you insist on IBKR-only, it’s still doable; it just constrains breadth.

## 3.2 Continuous futures & roll

For backtesting, you must avoid the “contract breaks” problem.

**Spec:**

* Build a **continuous NQ series** with one of:

  * **volume-based roll** (your strategy spec) + optional calendar backstop
  * **calendar roll** (like 2 sessions before LTD)
* Splice series with:

  * **back-adjust** (recommended for signal continuity)
  * or **ratio-adjust** (less common for futures)
* Keep a separate “actual contract mapping” if you want to model IB execution per contract.

**Deliverables:**

* `NQ_continuous_15m.csv`
* `NQ_continuous_1h.csv`
* (optional) `NQ_continuous_5m.csv`
* `ES_daily.csv`

All with consistent timestamps (UTC or ET) and a clear timezone conversion layer.

## 3.3 Timezone and session tagging

Your strategy is time-dependent. You must standardize:

* Convert all timestamps to **America/New_York**
* Build session flags per bar:

  * isRTH, isOpenWindow, isCoreWindow, isEvening, isHardBlock
* Identify 15:50 ET bars precisely (bar close vs bar open conventions)

**Important:** Backtrader bars are typically timestamped at bar open; IB may timestamp at bar end depending on settings. You must enforce a consistent convention in preprocessing.

---

# 4) Execution model (critical for realism)

This strategy uses stop-limit entries + TTL + fallback + partials + trailing + time-gated flatten/hold. A naive “cheat-on-close” backtest will be misleading.

## 4.1 Order types to simulate

* **Stop-limit entry**:

  * triggers if price crosses stop
  * fills if subsequent trading reaches limit
  * partial fills optional (if you have tick or volume; otherwise approximate)
* **TTL cancel**:

  * cancel after N bars if unfilled
* **Teleport skip**:

  * if price trades beyond limit by X ticks without fill → cancel
* **Fallback market**:

  * if triggered but not filled after 1 bar and conditions allow → market fill
* **Stop order** for protective stop
* **Partial take** at +1R:

  * implement as limit at target, assume fill if high/low touches

## 4.2 Slippage and spread

Your spec references:

* SpreadTicks and ExpectedSlipTicks
* Different slippage per window

Because you’re using bar data, do this:

### Simple slippage model (baseline)

* **Market orders:** slip = `slip_ticks_by_window` (1 core, 2 open/evening)
* **Stop orders:** treat as market when triggered + slip
* **Stop-limit entries:** if filled, apply small adverse slip (0–1 tick) OR none
* **Fallback market:** slip like market order

### Spread proxy

If you lack bid/ask history:

* approximate spread = 1 tick in core, 2 ticks in open/evening, 3 ticks in thin overnight
* OR use a volatility-based proxy: `spread_ticks = clamp(1, 4, round(k * ATR15_ticks))`

Then enforce your fallback gate.

**Deliverable:** an `ExecutionAssumptions` module so you can vary models and see sensitivity.

## 4.3 Worst-case stress tests

Because NQ has gaps:

* Add a “gap slippage” stress mode:

  * if bar opens beyond stop level, fill at open plus slip
* For weekend / major events, you can add a probabilistic extra slip regime (optional).

---

# 5) Strategy implementation in Backtrader

## 5.1 Multi-timeframe feeds

* Data0: NQ 15m
* Data1: NQ 1h (resampled from 15m OR separate feed)
* Data2 (optional): NQ 5m
* Data3: ES daily

Backtrader supports resampling; however, for exact replication you might prefer importing prebuilt 1h/daily bars.

## 5.2 Strategy state machine

Implement the strategy as explicit states per position:

* `ACTIVE_RISK` (initial stop)
* `ACTIVE_FREE` (post +1R partial/BE)
* `SWING_HOLD` (after passing 15:50 gate)

Also track:

* daily counters (long/short fills, realized pnl breaker, flip usage)
* working entry orders with TTL/fallback metadata
* the VWAP-A anchor index chosen (timestamp mapping)

## 5.3 Deterministic evaluation schedule

* Evaluate entries on **15m bar close**
* Apply exits/trails every bar
* Run decision gate at **15:50 ET** (triggered by the 15:45–16:00 bar close depending on timestamp convention)

---

# 6) Parameter optimization plan (with bounds)

## 6.1 Define “tunable” parameter block

Group parameters by category and cap the total degrees of freedom per optimization run.

### Core entry timing

* `TOUCH_LOOKBACK_15M`: [6, 8, 10, 12]
* `VWAP_CAP_CORE`: [0.75, 0.85, 0.95]
* `VWAP_CAP_OPEN_EVE`: [0.60, 0.72, 0.85]
* `EXTENSION_SKIP_ATR` (Type B): [0.8, 1.0, 1.2, 1.5]
* `RETEST_TOL_ATR`: [0.15, 0.25, 0.35]

### Momentum / confirmation

* `MOM_N`: [30, 50, 80]
* `FLOOR_PCT`: [0.20, 0.25, 0.30]
* `SLOPE_LB`: [2, 3, 4]

### Stops and guardrails

* `MIN_STOP_POINTS`: [10, 20, 30]
* `MAX_STOP_POINTS`: [80, 120, 160]
* Structure buffer: `0.05–0.20 * ATR1H` (or fixed list)
* ATR stop multiple: [1.2, 1.4, 1.6] × ATR15

### Exits / trailing

* `PARTIAL_PCT`: [0.25, 0.33, 0.50]
* VWAP fail consecutive (15m): [2, 3]
* stale bars: [12, 16, 20]
* stale R threshold: [0.20, 0.30, 0.40]
* trailing window (15m bars): [12, 16, 20]
* trail mult schedule: test 2–3 alternative formulas

### Decision gate

* Weekday hold threshold: [0.8R, 1.0R, 1.2R]
* Borderline threshold: [0.4R, 0.5R, 0.6R]
* Friday hold threshold: [1.2R, 1.5R, 2.0R]
* Weekend lock: [0.25R, 0.5R, 0.75R]

### Risk constraints

* `BASE_RISK_PCT`: [0.20%, 0.25%, 0.30%, 0.35%]
* `HEAT_CAP_MULT`: [1.25, 1.50]
* `CLASS_MULT_NOPRED`: [0.60, 0.70, 0.80]
* Evening session_mult: [0.50, 0.70, 1.00]
* Entry caps: [1, 2, 3] (per direction/day)

### Optional micro-trigger (binary)

* `USE_MICRO_TRIGGER`: [False, True]
* micro window bars: [2, 3, 4]

## 6.2 Optimization methods

Do not brute-force the whole hypercube. Use:

### Stage 1: Coarse random search

* 2,000–10,000 random samples (depending on speed)
* Use broad bounds, focus on biggest levers

### Stage 2: Bayesian optimization (recommended)

* Optimize objective = “robust risk-adjusted return” (below)
* Constrain trade frequency so you don’t “optimize into zero trades”

### Stage 3: Local refinement

* refine around top 20 parameter sets
* narrower grids per parameter

---

# 7) Objective functions and constraints (avoid overfitting)

## 7.1 Metrics to compute

At minimum:

* Net profit, CAGR-ish (for futures, annualized return on margin may be misleading)
* Profit factor
* Sharpe and Sortino (careful: futures returns are not iid)
* Max drawdown, ulcer index
* Tail risk: worst day, worst week
* Win rate + avg win/avg loss
* Expectancy per trade (EV/trade) and per day
* Trade frequency: trades/month, avg holding time
* Exposure: time in market, overnight holds count
* Slippage sensitivity: results across 2–3 slip models

## 7.2 Robust objective (recommended)

Use an objective that rewards return but punishes fragility:

Example:

* **Score =** `0.6 * (annualized_return / max_dd)` + `0.4 * expectancy_per_trade`
* Penalize if:

  * trades/month < threshold (e.g., < 10)
  * maxDD exceeds tolerance
  * profit factor < 1.2
  * results collapse under +1 tick slippage stress

Or use a multi-objective Pareto front:

* maximize return
* minimize drawdown
* maximize EV/trade
* keep frequency above minimum

---

# 8) Filter/condition impact analysis (ablation spec)

This is the most important part for “which filters are gating profitable trades”.

## 8.1 What to ablate (toggle ON/OFF)

Define each “filter module” as a binary flag:

### Regime / volatility

* DailyTrend gate (on/off) — if off, trade both directions always
* Shock block (on/off)
* 1H tactical alignment gate (on/off)

### Entry structure

* Type A only vs Type B only vs both
* VWAP cap gate (on/off) for Type A
* Type B extension sanity (on/off)
* Touch lookback requirement (on/off) — for Type A only
* Use VWAP-A touch alternative (on/off)

### Confirmation

* Decelerating slope gate (on/off)
* Predator overlay (on/off) and compare:

  * overlay sizing vs overlay gating (if you want to test gating too)
* N_mom floor/ceiling condition (on/off)

### Risk & execution constraints

* Min/max stop points (on/off)
* TTL cancel (on/off)
* Teleport skip (on/off)
* Fallback market (on/off)
* Cost/risk viability filter (on/off)
* Sanity spread/slip cap (on/off)
* Directional entry caps (on/off)
* Heat cap strength (1.25 vs 1.50)

### Exits / hold logic

* VWAP failure exit (on/off)
* Stale exit (on/off)
* +1R partial (33% vs 50% vs none)
* Earn-the-hold decision gate (on/off)
* Overnight widening (on/off)
* VWAP-A failure exit (on/off)
* Friday override (on/off)

## 8.2 How to run ablations properly

Ablations are only meaningful if you:

* keep all else constant (same parameters, same data, same execution model)
* run long enough periods (multiple years)
* examine not just returns but also trade distribution and tail events

### Recommended method: “one-at-a-time marginal”

1. Choose a **baseline** configuration (either:

   * spec defaults, or
   * one of the top-robust parameter sets from optimization)
2. For each module:

   * run with module ON
   * run with module OFF
3. Record deltas:

   * Δ net profit
   * Δ max DD
   * Δ profit factor
   * Δ trades/month
   * Δ EV/trade
   * Δ tail losses

This gives a clean marginal contribution.

### Second method: “interaction ablations”

Some filters interact (e.g., decision gate + overnight widening).
Run a small 2×2 grid for key pairs:

* decision gate × overnight widening
* VWAP cap × Type B extension sanity
* TTL × fallback
* slope gate × VWAP cap

## 8.3 Identify “gating profitable trades”

You don’t just want performance deltas; you want to know *which trades were blocked*.

### Blocked-trade analysis spec

Implement a “shadow mode” evaluator:

* When the strategy is flat and a potential entry setup appears:

  1. Evaluate full signal: pass/fail
  2. If fail: log the **first failing gate** (by deterministic gate order)
  3. Also compute a **counterfactual**:

     * “What if we removed only this gate?” would it have entered?
  4. Then simulate the **counterfactual trade path**:

     * entry at the same stop-limit logic (or a simplified entry at next open)
     * same stop/exit rules
  5. Save its realized outcome (PnL, MFE/MAE, time in trade)

This is powerful: you’ll see, for example:

* “VWAP cap blocked 120 trades; 40 would have been strongly profitable”
* “Shock block prevented 20 trades; 19 would have been disasters” (good filter)
* “Slope gate blocked many winners during runaway trends” (bad gate)

You can rank gates by:

* average counterfactual EV of blocked trades
* net EV saved (prevented losers)

**Implementation detail:** to keep compute feasible:

* only shadow-simulate trades for the top K most common gate failures
* or shadow-simulate using simplified fills (market at next bar open) for speed

---

# 9) Walk-forward testing (robustness requirement)

Optimization without walk-forward is overfitting.

## 9.1 Walk-forward procedure

* Split data into chronological folds:

  * Train: 12 months, Test: 3 months (rolling)
  * or Train: 24 months, Test: 6 months
* For each fold:

  * optimize parameters on Train
  * evaluate on Test
* Aggregate performance across all test folds.

## 9.2 Stability criteria

A “good” strategy should show:

* consistent positive expectancy in most test folds
* no single fold responsible for most profits
* resilience to slippage stress

---

# 10) Monte Carlo and stress testing

## 10.1 Trade-order Monte Carlo

Shuffle trades (or daily blocks) to estimate distribution of outcomes:

* max drawdown distribution
* probability of ruin (if using fixed risk%)
* worst-case month

## 10.2 Slippage / spread sensitivity

Run the same configuration under:

* baseline slip (1/2 ticks)
* +1 tick everywhere
* “shock slip” around major event days

A robust strategy should not collapse.

---

# 11) Reporting: what you should produce

## 11.1 Standard backtest report per run

* Equity curve, drawdown curve
* monthly return table
* distribution of R multiples
* MFE/MAE scatter by entry type
* trade duration histogram (RTH vs overnight)
* performance by:

  * DailyTrend regime
  * VolState (Normal vs High)
  * session (RTH vs evening)

## 11.2 Ablation report

For each gate/module:

* # trades blocked / affected
* Δ EV/trade
* Δ total profit
* Δ max DD
* Δ trades/month
* “blocked-trade counterfactual EV” (if shadow mode enabled)

Rank filters by:

* net EV contribution
* drawdown reduction per trade gated
* opportunity cost (blocked winners)

## 11.3 Optimization results

* top 20 parameter sets
* parameter sensitivity plots (how score changes vs each variable)
* Pareto frontier charts (return vs DD vs frequency)

---

# 12) Practical implementation plan (step-by-step)

### Step 1 — build a data pipeline

* pull and store NQ/ES bars (15m/1h/daily) into parquet/csv
* normalize timestamps to ET
* build continuous futures series for NQ and ES
* verify no missing bars around session boundaries

### Step 2 — implement strategy in Backtrader

* multi-timeframe feeds
* deterministic gate order
* explicit position state machine

### Step 3 — implement realistic execution simulation

* stop-limit + TTL + teleport + fallback
* slippage model + spread proxy
* verify against hand-checked examples

### Step 4 — run baseline backtests

* spec defaults first
* validate behavior matches expectations

### Step 5 — run filter ablations

* one-at-a-time toggles
* blocked-trade counterfactual logging

### Step 6 — optimize parameters

* coarse random search → Bayesian → local refine
* with walk-forward validation

### Step 7 — robustness / stress testing

* slippage scenarios
* Monte Carlo
* subperiod + regime breakdown

---