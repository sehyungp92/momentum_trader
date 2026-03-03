Here’s a **detailed, implementation-ready backtesting + optimization spec** for this strategy.

---

# 1) Goals of the Research Program

You want to answer three questions with high confidence:

1. **Performance & robustness**

* Is the strategy profitable **after realistic costs**?
* Is it stable across years and regimes?
* Does it capture a high fraction of “dominant trends”?

2. **Which filters/conditions help vs. hurt**

* Which rules reduce drawdown without killing expectancy?
* Which rules mainly **gate profitable trades** (false negatives)?

3. **Parameter sensitivity and optimization**

* What are good defaults for key parameters?
* Are they robust (no single-parameter cliff)?
* Can you optimize without overfitting?

This spec is built to produce:

* **Walk-forward optimized results**
* **Ablation + gating attribution**
* **Trade-level diagnostics** (virtual fills, gate reasons, per-subtype stats)
* **Operational realism** (OCA brackets, stop/target priority, slippage)

---

# 2) Data: What You Need (and what IBKR can/can’t do)

## 2.1 Data requirements (minimum)

For NQ (or MNQ), you need:

* **5m bars** (execution)
* **30m bars** (signal/structure)
* **1H bars** (chandelier trail)
* **4H + Daily bars** (regime)
* Volume at each timeframe (or resampled volume)

To evaluate news blackout properly:

* A high-impact **US macro event calendar** (CPI, FOMC, NFP, etc.) with timestamps.

## 2.2 IBKR reality check

IBKR historical data is:

* limited in lookback for small bar sizes (especially 5m)
* sometimes inconsistent across sessions/rolls
* not ideal for “5+ years deep research”

### Recommendation (best practice)

Use IBKR for:

* **contract metadata / roll rules**
* **live parity validation** (sample periods)
* **paper/live execution testing**

Use a dedicated historical source for backtests:

* CME/paid vendor (best)
* or continuous futures data vendor
* but keep the **same contract/session definitions**.

## 2.3 Continuous futures & roll

Define an explicit roll policy:

* roll on volume lead, or fixed “N business days before expiry”
* document it and apply consistently across all timeframes

**Backtest must be run on the same continuous series across 5m/30m/1H/4H/D.**

---

# 3) Backtrader Architecture

## 3.1 Feeds & resampling plan

You have two viable patterns:

### Pattern A (preferred)

Load **5m** as the master feed, then resample to:

* 30m, 1H, 4H, 1D in Backtrader.

Pros:

* Single timeline source of truth
* Intrabar ordering easier
* Consistent session partitioning

Cons:

* More compute

### Pattern B

Load each timeframe separately and align.
Not recommended unless you already have perfectly aligned bars.

## 3.2 Strategy structure in Backtrader

Implement as a multi-timeframe strategy with:

* `data0 = 5m`
* `data1 = 30m`
* `data2 = 1H`
* `data3 = 4H`
* `data4 = 1D`

Then build “engines” inside the strategy:

* `engine_eth`, `engine_rth` (state machines + rolling histories)
* global `position_state`

---

# 4) Execution Model: Make It Realistic

This strategy’s edge depends on realistic execution:

* OCA bracket behavior (A1 limit + A2 stop)
* stop vs target priority
* slippage differences for stop/market/limit
* tick rounding

## 4.1 Tick rounding

All prices must be rounded to 0.25.

## 4.2 Fill rules (conservative)

Use conservative fill rules similar to your FX spec:

**Limit fill:**

* buy limit at P fills only if low ≤ P − 1 tick
* sell limit at P fills only if high ≥ P + 1 tick

**Stop fill:**

* buy stop triggers if high ≥ P
* fill at P + slippage_ticks*tick (adverse)
* sell stop fill at P − slippage_ticks*tick

**Intrabar priority:**

* If stop and target both touched in same bar: assume **stop first**

  * unless you add higher-resolution simulation

Backtrader note: you’ll likely implement a custom broker or use cheat-on-open/cheat-on-close carefully, but you still need to enforce your own fill logic for OCA brackets and stop-vs-target order.

## 4.3 Slippage and costs model

Create a model that varies by order type:

* limit: 0–1 tick adverse (often 0)
* stop: 1–2 ticks adverse
* market: 1–2 ticks adverse

Add commission per round-turn:

* NQ: ~$4.12 RT (or your broker schedule)
* MNQ: ~$1.64 RT

Make this parameterizable so you can sweep:

* slippage_ticks_stop ∈ {1,2,3}
* slippage_ticks_market ∈ {1,2,3}

---

# 5) Enforcing “Past-only” Correctly (critical)

Many filters use rolling quantiles:

* displacement thresholds (q_disp)
* squeeze thresholds (q_sq and loose=0.60)
* ATR percentiles for expiry, chop, offset mults

**Spec requirement:** value at time t must be compared against thresholds computed from history up to t-1.

Implementation spec:

* Maintain rolling buffers as deques
* compute threshold using buffer contents (already past-only)
* append current observation only after the decision

You should add a unit test:

* confirm that at bar t, threshold does not change if you temporarily modify the current bar value

---

# 6) Parameterization: What You Optimize

## 6.1 Primary optimization set (high value / low fragility)

* `q_disp` ∈ {0.60, 0.65, 0.70, 0.75, 0.80}
* `q_sq` ∈ {0.15, 0.20, 0.25, 0.30}
* `k_slope` ∈ {0.05, 0.10, 0.15}
* `base_risk_pct` ∈ {0.0025, 0.0035, 0.0050}
* `chop thresholds` (cross counts and ATR pctl cutoffs) small sweeps

## 6.2 Secondary optimization set (only after primary fixed)

* Entry A TTL (5m bars): {2,3,4}
* A latch buffer (ticks): {1,2,3}
* Sweep depth factor: {0.15, 0.20, 0.25} * ATR30
* Continuation activation: `R_proxy` threshold {1.5, 2.0, 2.5}
* Chandelier parameters by profit tier:

  * ATR mults: ±20%
  * lookbacks: {6,8,10,12} range
* DIRTY reset thresholds:

  * box_shift ATR factor {0.4,0.5,0.6}
  * depth definition {0.35,0.40,0.45} of box width

## 6.3 Switch parameters for ablation (on/off)

You want to evaluate whether these gate good trades:

Hard/soft gates:

* News blackout (on/off)
* Chop hard halt (on/off)
* Chop degraded behavior (on/off)
* DIRTY mechanism (on/off)
* Displacement thresholding (on/off)
* Score thresholding (on/off)
* Breakout reject (on/off)
* Micro-trade guard (on/off)
* Friction-to-R gate (on/off)
* Daily support score bonus (on/off)
* Continuation mode (on/off)

For each: you need **gating attribution** (Section 9).

---

# 7) Experimental Design: Avoid Overfitting

## 7.1 Walk-forward optimization (WFO)

Use a rolling scheme such as:

* Train (optimize): 24 months
* Test (OOS): 6 months
* Step forward by 6 months

For each window:

* find best parameters on train using objective function (below)
* run OOS using those parameters
* stitch all OOS segments into a single equity curve

## 7.2 Objective function (not just net profit)

Optimize for something like:

**Primary objective**

* maximize `Expectancy_R_after_costs`

**Constraints**

* PF ≥ 1.2
* max DD ≤ threshold (or minimize DD secondarily)
* trade count ≥ 50% baseline (frequency constraint)
* “trend participation” ≥ target (Section 8.4)

You can encode as a scalar:

* `score = expectancy_R - 0.1*maxDD_R + 0.05*log(trades)`
* and reject parameter sets that fail constraints

## 7.3 Robustness stress tests

For the chosen final parameters:

* ±20% perturbation on 10 parameters (random sampling)
* ensure:

  * expectancy remains > 0
  * DD ≤ 2× baseline
  * trades ≥ 50% baseline

---

# 8) What You Must Measure (Outputs)

## 8.1 Standard performance

* expectancy (R) after costs
* PF, win rate, avg win/avg loss
* max DD (R and %)
* Sharpe/Sortino (optional)
* average hold time
* long vs short splits
* ETH vs RTH splits
* entry subtype splits:

  * A_retest, A_latch, B_sweep, C_standard, C_continuation

## 8.2 Regime and mode reporting

Report by:

* composite regime (Aligned/Neutral/Caution/Range)
* chop mode (Normal/Degraded/Halt)

## 8.3 Execution diagnostics

* fill probability for A1 vs A2
* price improvement (A_retest vs latch)
* stop distance distribution
* realized slippage proxy (if modeled probabilistically)

## 8.4 Trend participation metric (key to your goal)

Define a “dominant trend event” and measure capture rate.

Example definition:

* a move of ≥ X% or ≥ Y ATR over a horizon of 6–48 hours
* direction determined by net move
* trend start time defined by first breakout above rolling high etc.

Measure:

* % of dominant trend events where strategy:

  * entered within Z bars of start, OR
  * captured ≥ K% of the move, OR
  * achieved ≥ 1R in direction during the event

This is crucial to validate “participates in all dominant trends”.

---

# 9) Filter Effectiveness & “Gating Profitable Trades” Analysis

This is the most important part of your request.

## 9.1 You need two kinds of experiments

### A) Ablation runs (macro impact)

Run the full system, then rerun with one rule removed:

* compare OOS expectancy, DD, trade count, trend capture

This tells you net effect but not *why*.

### B) Candidate-level gating attribution (micro impact)

For every potential trade candidate, log:

* would-be entry time/price
* all gate decisions in order
* first gate that blocked it
* **virtual outcome** if it had been taken (using same stop/targets/trailing logic)

This gives you:

* “Gate X blocked 120 trades; 40 would have been winners; net virtual EV was +0.12R”
* which is exactly what you want.

## 9.2 Candidate definition (consistent and fair)

Define a “candidate” at the moment the strategy would otherwise place orders:

* after structural breakout + displacement + score pass
* before entry permissions and micro-guard and friction
* candidate stores:

  * intended entry subtype(s)
  * planned stop model
  * planned risk sizing
  * planned exit tier

Then apply gates in spec order and record:

* allowed or blocked
* block reason

## 9.3 Virtual trade simulation

When blocked, simulate “as if taken” using:

* same entry trigger type (A/B/C)
* same fill model
* same stop/targets/trailing
* record virtual R, MFE/MAE, time-to-TP1, whether MM reached

You’ll need this especially for:

* news blackout
* chop halt
* micro-guard
* friction gate
* score thresholds

## 9.4 Outputs from gating attribution

For each gate:

* number of candidates blocked
* % that would have reached TP1 / TP2
* average virtual R
* median virtual R
* virtual max DD contribution
* impact on trend participation

This is how you determine whether a filter is “effective” or “over-gating.”

---

# 10) Optimization Workflow (Step-by-step)

## Phase 0 — Baseline correctness

* Validate strategy replicates expected behavior on a small period (1–2 months).
* Verify:

  * session switching works
  * past-only quantiles correct
  * OCA A bracket behaves correctly
  * stop/target priority correct
  * telemetry matches expectations

## Phase 1 — Primary parameter sweep + WFO

* Optimize: q_disp, q_sq, k_slope, base_risk_pct
* Run WFO stitched OOS curve
* Produce regime/mode/subtype breakdowns

## Phase 2 — Filter effectiveness

* Run gating attribution logging on the stitched OOS curve
* Run ablation toggles (one-at-a-time and small combinations)
* Identify:

  * rules that reduce DD materially
  * rules that mostly kill frequency
  * rules that block net-profitable candidates

## Phase 3 — Secondary parameter sweeps

* Only on the “winning” filter set from Phase 2
* Optimize continuation thresholds, chandelier tiers, entry offsets/TTL, DIRTY thresholds

## Phase 4 — Robustness + stress

* ±20% perturbation
* slippage stress
* volatility regime slices (VIX proxy if available)
* crash windows (2020, 2022, etc.)

---

# 11) Backtrader Implementation Notes (practical)

## 11.1 Use analyzers

Implement custom analyzers for:

* trade stats by subtype/regime/session/mode
* gating attribution
* trend participation
* walk-forward segment reporting

## 11.2 Use `optstrategy` carefully

Backtrader `optstrategy` does brute-force grids well, but:

* huge grids explode combinatorially
* use staged optimization and keep grids small
* consider random search / Bayesian optimization externally:

  * run backtrader as a function called by an optimizer (Optuna is common)

## 11.3 Determinism

* fix random seeds if you randomize slippage
* ensure reproducibility across runs

---

# 12) Deliverables: What Your Backtest Harness Should Produce

Every run produces:

1. **Stitched OOS equity curve** (walk-forward)
2. Performance tables:

   * by year, by session, by regime, by mode, by entry subtype
3. **Gating attribution report**

   * net virtual EV blocked by each gate
4. Ablation report

   * Δ expectancy, Δ DD, Δ trade count, Δ trend participation
5. Parameter sensitivity plots/tables

   * expectancy vs q_disp, q_sq, k_slope, etc.
6. Full JSONL logs for:

   * candidates
   * gate decisions
   * order fills
   * trade lifecycle events

---

# 13) Suggested “Minimum Viable Research Harness” build order

If you want the fastest path to high-quality results:

1. Build the **core backtrader strategy** with:

   * session engines
   * box → breakout → A bracket
   * stop/TP1/runner
2. Add **past-only quantiles** + displacement threshold
3. Add **scorecard**
4. Add **chop mode**
5. Add **DIRTY**
6. Add **continuation**
7. Add **gating attribution + virtual trades**
8. Add **walk-forward optimization**
9. Add **ablation toggles**
10. Add robustness sweeps

---