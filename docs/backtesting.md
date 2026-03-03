1) Core objectives
A) What you want to learn

Which filters/gates are net-positive (improve expectancy and/or reduce drawdown) vs over-gating (reducing returns more than risk).

Optimal values for key knobs without overfitting:

Class M depth band

extension gate threshold

spread caps by session

spike filter threshold

trailing parameters (lookback + mult schedule)

partial thresholds (+3/+6/+8) and percentages

add thresholds (+1.2/+1.6/+3.5) and budgets (0.5/0.3)

How robust results are across:

regimes (bull/bear/chop)

volatility regimes (vol_pct quantiles)

sessions (RTH prime vs ETH Europe vs overnight)

calendar events (news windows)

Sensitivity: which parameters matter most and how stable is the optimum.

B) Backtest outputs you must produce

Standard performance: CAGR/annualized return, Sharpe/Sortino, max DD, profit factor, win rate, avg R/trade, median R/trade.

Trade frequency distributions: trades/week, entries/day by session and class.

Filter impact diagnostics:

block rate by filter

“blocked trade counterfactual PnL” (what would have happened if filter were off)

marginal contribution of each filter (ablation)

Risk & tail: worst trade, 95th percentile adverse excursion (MAE), gap/slippage loss tails.

Stability: walk-forward results, parameter stability, out-of-sample performance.

2) Data requirements and how to use IBKR with Backtrader
A) Data you need (minimum)

NQ futures (front month + roll) or continuous synthetic

OHLCV at least:

1H bars (primary)

4H bars (can be derived from 1H)

Daily bars (can be derived from 1H)

Bid/ask/spread proxy for gating:

ideal: historical bid/ask bars or tick snapshots (often hard to get consistently)

practical approach: model spreads/slippage by session and volatility (see below)

News calendar timestamps (CPI/NFP/FOMC/etc.)

must be a deterministic file in backtest (CSV/JSON of event times in ET)

B) Practical realities of IBKR historical data

IBKR historical data can work but:

availability and pacing limits can make large, repeated optimizations slow

bid/ask history is limited; you likely won’t get perfect spread data historically

Recommendation (spec-level):

Use IBKR initially to validate feasibility and collect samples.

For extensive optimization, store a local dataset (Parquet/CSV) and rerun quickly.

C) Contract roll / continuous series

Create a continuous synthetic NQ series for backtesting:

Roll rule (as per spec): next volume ≥ 2× current OR 5 days pre-expiry

Backtest pipeline should produce:

NQ_continuous_1H bars with a contract_id column and roll_flag

Important: backtrader’s built-in “rollover” support is limited; easiest is:

preprocess continuous bars offline, then feed to backtrader as a single data feed.

3) Simulation model: fills, slippage, spreads, and stop-market behavior

Your strategy is sensitive to execution mechanics (stop-market, catch-up, teleport penalty). You need a realistic fill model.

A) Commission + fees

Model per-contract commission + exchange fees (set as parameter).

Apply round-trip cost.

B) Spread model (since historical bid/ask is difficult)

Implement a session-aware spread + slippage model:

Session blocks: RTH prime, ETH quality, ETH Europe, overnight, reopen dead zone

For each block, define baseline spread in points:

RTH: 0.25–1.00 pt

ETH quality: 0.5–1.5 pt

overnight: 1.0–2.0 pt

Spread widens with volatility:

spread = base_spread * (1 + k_vol * max(0, vol_z))

Also widen around news windows.

C) Stop-market fill model (critical)

For a stop-market entry triggered intrabar:

If high/low crosses trigger, treat as “triggered”.

Fill price should be modeled as:

fill = trigger + direction * (slip_component + half_spread_component)

Slip component can be:

slip = max(min_slip_ticks, slip_k * ATR1H), session-scaled

If bar gaps past trigger (open beyond trigger), use open as reference:

fill = open + direction * slip

You must model “teleport fill” probability:

teleport occurs more often in ETH and around news.

If teleport: apply add lockout until +2R.

D) Stops and trailing fills

Stop fills:

if bar crosses stop level, fill at:

stop price ± slip/spread

if large gap through stop (bar opens beyond stop):

fill at open ± slip

E) Catch-up order simulation

When overshoot within cap:

assume marketable limit gets filled at:

fill = last +/- small_offset (or next bar open)

TTL 5 minutes: in 1H-bar backtest, approximate TTL as:

valid only for the current 1H bar (or implement 5-min data for accuracy)

Best practice: if you care about catch-up precision, add a 5-min feed and do order simulation at 5-min resolution. Otherwise, treat catch-up as “same-bar execution” with conservative slippage.

4) Multi-timeframe strategy implementation in Backtrader
A) Data feeds

Base data: 1H

Resample to:

4H

Daily
Backtrader supports resample/replay:

cerebro.resampledata(data1h, timeframe=Minutes, compression=240) etc.

B) Indicators to implement

EMA20/EMA50 daily

EMA20/EMA50 4H

ATR14 daily, ATR1H, ATR4H

MACD(8,21,5) on 1H and 4H

Deterministic 5-bar pivot detector on 1H & 4H (custom indicator)

C) Event timing

Run logic on 1H bar close:

detect pivots (using 5-bar confirmed rule)

generate setups

update trailing/partials/adds/stale logic

manage TTL

This matches your production “bar-close engine” design.

5) “Filter impact” backtesting design (ablation + counterfactual)

This is the heart of your question: “which ones are gating profitable trades?”

You need two complementary methods:

Method 1: Ablation testing (turn filters off)

Run a “base” version and variants that remove one filter at a time.

Example toggles:

use_extension_gate

use_spike_filter

use_spread_gate

use_dead_zone_midday

use_reopen_dead_zone

use_extreme_vol_mode

use_corridor_cap

use_min_stop_gate

use_news_guard

use_teleport_penalty

use_class_R

enable_ETH_Europe

Outputs:

delta in total return, max DD, profit factor

delta in trades/week

delta in avg R/trade

how the distribution changes (tail risk, worst trade)

This tells you the net value of each filter.

Method 2: Counterfactual “blocked trade shadow ledger”

Even more powerful: when a trade is blocked by a filter, you simulate a shadow trade (paper) that does not affect equity/position limits, to estimate “opportunity cost”.

Implementation:

When setup passes signal rules but fails gates, record:

setup id, class, direction, time, entry_stop, stop0

which gate blocked it (single “primary gate” plus list)

Then in the background, simulate what would have happened if it were taken:

apply same stop, trailing, partial logic (or simpler: stop + 1H chandelier)

track R outcome

Aggregate results by gate reason:

mean/median R of blocked trades

% winners among blocked trades

“blocked alpha” vs “blocked junk”

This directly answers: is this gate blocking good trades?

Important detail: gates interact. Use:

Primary block reason = the first gate in an ordered evaluation chain.

Also record all failing gates for multi-tag analysis.

6) Parameter optimization plan (without overfitting)
A) Parameter groups (optimize in stages)

Don’t brute force everything at once. Use staged optimization:

Stage 1: Frequency engine (Class M knobs)

M_depth_low: 0.3–0.6 × ATR1H

M_depth_high: 1.1–1.6 × ATR1H

M_stop_atr_mult: 0.50–0.80

M_spike_max: 1.6–2.2 × ATR1H

Goal: maximize R/week with acceptable DD; ensure trade frequency doesn’t collapse.

Stage 2: Overextension controls

extension_threshold: 1.2–2.0 × ATRd

climax_threshold: 2.0–3.0 × ATR1H

climax_fraction: 0.2–0.4

Goal: reduce give-back without removing too many winners.

Stage 3: Trailing & partial schedule

trailing lookback: 18–30 bars

mult schedule: base 3.5–4.5, decay rate 4–6

partial at first threshold: +2.5–+3.5

first fraction: 0.25–0.40

second threshold: +5–+7, fraction 0.20–0.30

daily trail trigger: +7–+10

Goal: best tail capture vs DD.

Stage 4: Adds

Add1 threshold: 1.0–1.6 (A origin) / 1.3–2.0 (M origin)

Add2 threshold: 3.0–4.5

Add1 budget: 0.3–0.7 of Unit1Risk

Add2 budget: 0.2–0.4 of Unit1Risk

Goal: maximize upside while preserving DD profile.

Stage 5: Session gates / participation

include/exclude ETH Europe (03:00–08:00)

overnight allowed classes (A only vs A+R)

spread caps per session

Goal: ensure you don’t “buy noise” overnight but keep trend seeding.

B) Optimization methodology

Use Walk-Forward Optimization (WFO):

Example:

Train: 6 months

Test: 3 months

Slide forward by 3 months

Or:

Train 1 year, test 6 months for longer robustness

For each window:

run optimization on train

select top N parameter sets by a robust objective

evaluate those on test

aggregate OOS metrics

C) Objective functions (use 2–3, not 1)

You want returns without crushing frequency, so pick objectives like:

Return / Drawdown: NetProfit / MaxDD

Expectancy stability: median_R_trade * sqrt(trades) (rewards returns but penalizes low frequency)

Tail-aware: CVaR(5%) constraint or penalty

Example composite score:

Score = 0.5*(NetProfit/MaxDD) + 0.3*(AvgR * sqrt(trades)) + 0.2*(Sharpe)
with constraints:

trades/week >= 2 (or your target)

maxDD <= threshold

D) Avoiding overfitting

Require parameter stability: top parameter sets should cluster, not be isolated spikes.

Use White Reality Check / SPA test style thinking: compare many strategies properly (optional).

Use robustness plots:

heatmaps for key pairs (depth band, extension threshold)

performance vs parameter curves to detect “knife-edge” optima

7) Testing the impact of individual conditions inside each class

Beyond global filter toggles, test “internal conditions”:

Class M internal knobs

momentum reclaim form:

MACD[t] > MACD[t-3] vs MACD slope or histogram confirmation

pullback depth band: width sensitivity

stop ATR multiplier

Class A internal knobs

corridor cap multipliers (1.4/1.6/1.8)

hidden divergence magnitude threshold percentile (25th vs 30th)

Class R internal knobs

2-of-3 gate variants:

(trend_strength drop) threshold

extension multiple 1.6–2.2

coil-break volatility signature definition

You’ll discover which specific subcondition is doing the heavy lifting.

8) Required instrumentation (“why did we trade / not trade?”)

You need structured logging from the backtest engine, not just final PnL.

A) For every detected setup

Record:

timestamp, class, direction, alignment score, strong_trend, vol_pct

entry_stop, stop0, stop_dist, corridor cap

which gates passed/failed

session block

whether it became:

ARMED

FILLED

EXPIRED

INVALIDATED

B) For every block event

Record:

primary block reason

full list of failing gates

C) For every trade

Record a trade trace:

entry time/price, stop0, Unit1Risk_$, SetupSizeMult, SessionMult

teleport? (yes/no)

add orders (placed/filled), add prices

partials (time/price/qty)

stop updates (time/new stop)

exit reason (stop, stale, catastrophic, etc.)

MFE/MAE, bars held, session contributions

This data powers filter impact and condition effectiveness.

9) Backtrader implementation outline
A) Strategy class design

next() runs on 1H close

Maintains:

pivot history for 1H/4H

setup book (pending/armed)

position state

shadow ledger for blocked trades

B) Broker model customization

Implement a custom CommissionInfo and a slippage model:

session-aware slippage/spread adjustments

stop-market handling approximations

Backtrader has:

broker.set_slippage_fixed() but it’s crude.
For your needs, implement custom broker fill logic or emulate in strategy by placing limit/stop prices adjusted by your model.

C) Optimizations in Backtrader

Backtrader supports cerebro.optstrategy() but it can become slow.
Recommendation:

wrap Backtrader runs in multiprocessing

store results and diagnostics to Parquet

use a driver script that manages WFO splits and parameter sets.

10) Concrete experiment matrix (what to run)
Phase 1: Baseline verification

Run v3.1 with “reasonable defaults” across 3–5 years.

Verify trade traces match expected logic.

Phase 2: Gate ablation suite (single changes)

Run baseline and these toggles (one at a time):

remove extension gate

remove climax exit

remove spike filter

remove spread gate

remove midday dead zone

remove reopen dead zone

remove extreme-vol mode

remove corridor cap

remove min-stop gate

remove news guard

disable adds

disable Class R

disable ETH Europe participation

Deliverable: table of deltas + distributions.

Phase 3: Shadow “blocked trade” ledger (always-on)

For baseline run, collect blocked setups and compute:

mean/median R by block reason

winners % by block reason

“blocked alpha index” = meanR_blocked - meanR_taken (per class/session/regime)

Phase 4: Optimization with WFO

Stage 1 optimize Class M knobs (train windows)

Lock them, then stage 2 optimize extension/climax

Lock those, then stage 3 optimize trailing/partials

Finally stage 4 optimize adds

Phase 5: Robustness + regime slicing

Slice results by:

session block

alignment score bucket

vol_pct bucket (0–20, 20–50, 50–80, 80–95, 95+)

bull/bear macro regime (daily EMA alignment)

11) What “effective” looks like (decision rules)

A filter is net-positive if:

It improves NetProfit/MaxDD and/or reduces tail losses

It doesn’t reduce trades/week below your minimum

Shadow blocked trades by that filter have:

mean R ≤ 0 and/or

significantly worse MAE profiles than taken trades

A filter is likely “over-gating” if:

Removing it improves both returns and DD (rare but possible)

Or it reduces returns significantly more than DD improvements

Shadow blocked trades show positive mean R and similar MAE

12) Extra high-value suggestions for this backtest project

Add a 5-minute data mode for execution realism
Run signals on 1H close, but simulate order triggering/fills on 5m bars. This dramatically improves realism for stop-market, catch-up TTL, and slippage.

Benchmark against simpler baselines
Compare to:

plain 1H EMA trend + chandelier

breakout-only (20-bar high/low)

pure mean reversion
Ensures you’re actually adding edge.

Use a “parameter importance” analysis
After collecting many runs, fit a model (e.g., random forest regression) mapping parameters → OOS performance.
This reveals which knobs matter and which don’t.

Stress tests

widen slippage x2

widen spreads x2 in ETH

increase teleport frequency

remove best 10 trades
A good strategy survives these.