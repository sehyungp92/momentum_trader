# VdubusNQ Strategy Optimization: v4.0 → v4.4

## Progression

| Version | Trades | PF | Net Profit | Sharpe | MaxDD | Cumulative Gain |
|---------|--------|------|-----------|--------|-------|-----------------|
| **v4.0** (baseline) | 115 | 0.61 | $5,126 | 1.59 | 4.7% | — |
| **v4.2** (Round 1: +3 changes) | 95 | 1.70 | $20,595 | 3.03 | 2.6% | +$15,469 |
| **v4.3** (Round 2: +1 change) | 93 | 1.79 | $23,498 | 3.20 | 2.9% | +$18,372 |
| **v4.4** (Round 3: +1 change) | 94 | 1.85 | $25,438 | 3.33 | 2.8% | **+$20,312** |

Backtest conditions: MNQ (Micro E-mini Nasdaq-100), 10 contracts fixed, $0.62/side commission, $100K initial equity, ~11 months data (2025-03 to 2026-02).

---

## Changes KEPT (5 of 17 evaluated)

### 1. Midday Dead-Zone Block (11:45–14:00 ET) — Round 1

**Weakness addressed:** Diagnostics showed CORE sub-window trades entered during the midday hours (roughly 11:45–14:00) had severely negative expectancy. This is the lowest-liquidity, choppiest period of RTH — range-bound price action generates false signals that look like valid VWAP touches/breakouts but fail to develop directionally.

**What it does:** Blocks all new entries during 11:45–14:00 ET by classifying that window as `BLOCKED` in `classify_session()`. Trades already open are unaffected.

**Impact:** Removed ~20 losing trades per year. The blocked trades had negative avg R. Removing them directly improved PF and reduced drawdown.

**Files:** `strategy_3/engine.py` (classify_session), `backtest/engine/vdubus_engine.py` (classify_session)

### 2. Wider Trailing Stop with Staged Tightening — Round 1

**Weakness addressed:** The original trail (LOOKBACK=6, MULT=1.4 fixed) was too tight, chopping out winning trades during normal retracements. The winner give-back analysis showed trades were surrendering substantial MFE — the trail was triggering on noise rather than trend reversals. 30%+ of eventual winners absorb >0.5R adverse excursion during development.

**What it does:** Widened the trail parameters (LOOKBACK=12, MULT_BASE=2.5, MULT_MIN=1.8) and introduced staged behaviour: the trail stays wide at 2.5× ATR from +1R to +1.5R, then gradually tightens toward 1.8× ATR above +2.5R (`R_DIV=6.0`). This gives developing winners room to breathe while still protecting large gains.

**Impact:** Largest single-change improvement. Winners that previously got stopped out on noise now reach their full potential. PF and net profit improved substantially.

**Files:** `strategy_3/config.py` (TRAIL_LOOKBACK_15M, TRAIL_MULT_MIN, TRAIL_MULT_BASE, TRAIL_MULT_R_DIV), `strategy_3/exits.py` (compute_intraday_trail staged logic)

### 3. Hourly Alignment Softened to 60% Sizing — Round 1

**Weakness addressed:** The original implementation hard-blocked entries when the hourly EMA trend was neutral (not confirming the daily trend direction). Diagnostics showed many of these neutral-hourly trades were profitable — the hourly trend often lags the daily, and blocking entirely was leaving money on the table.

**What it does:** Replaced the binary block with a sizing multiplier: trades aligned with hourly trend get full size (`HOURLY_ALIGNED_MULT=1.0`), while neutral-hourly trades get 60% size (`HOURLY_NEUTRAL_MULT=0.60`) instead of being rejected. This expresses uncertainty through position size rather than entry denial.

**Impact:** Re-admitted profitable trades that the hard block was killing, while reducing risk on the less-certain ones via smaller size.

**Files:** `strategy_3/config.py` (HOURLY_ALIGNED_MULT, HOURLY_NEUTRAL_MULT), `strategy_3/engine.py` / `backtest/engine/vdubus_engine.py` (sizing logic)

### 4. Midday Block Boundary Adjustment (12:00 → 11:45) — Round 2

**Weakness addressed:** After implementing the midday block at 12:00–14:00, further analysis of the exit-reason-by-subwindow and per-trade timing data showed that the 11:45–12:00 window still had negative-expectancy entries. The choppy conditions start before noon.

**What it does:** Extended the midday block start from 12:00 to 11:45 ET, capturing the additional 15 minutes of poor-quality entries.

**Impact:** Net profit +$2,903 ($20,595 → $23,498). Sharpe improved from 3.03 to 3.20. A surgical boundary fix that removed a handful of losing trades.

**Files:** `strategy_3/engine.py` (classify_session), `backtest/engine/vdubus_engine.py` (classify_session)

### 5. OPEN → CORE Transition Trail Tightening — Round 3

**Weakness addressed:** The winner give-back analysis (Tier 4 diagnostics) revealed that OPEN sub-window winners surrendered 0.710R per trade — the worst give-back of any sub-window despite having 92% win rate. These trades enter during the day's strongest momentum window (9:40–10:30) and hit +1R quickly, but then bleed as conditions deteriorate during the CORE session (10:30–15:30). The trail was time-agnostic and didn't account for this structural regime shift.

**What it does:** When a trade that entered during OPEN is still alive during CORE and has already partial-closed at +1R, the intraday trail multiplier is reduced by 20% (`TRAIL_CORE_TRANSITION_REDUCTION=0.80`). This means the trail sits 2.0× ATR from the recent high instead of 2.5× ATR, capturing more of the winning move before CORE chop erodes it.

**Impact:** Net profit +$1,940 ($23,498 → $25,438). Every metric improved: PF 1.79→1.85, Sharpe 3.20→3.33, Sortino 1.25→1.33, Calmar 14.79→15.75, MaxDD 2.9%→2.8%.

**Files:** `strategy_3/config.py` (TRAIL_CORE_TRANSITION_REDUCTION), `strategy_3/exits.py` (tighten_factor param on compute_intraday_trail), `strategy_3/engine.py` + `backtest/engine/vdubus_engine.py` (classify_session check + factor application)

---

## Changes REVERTED (12 of 17 evaluated)

| Round | Change | Why Reverted |
|-------|--------|-------------|
| 1 | Tighter VWAP cap for CORE | Near-identical results, no meaningful filtering |
| 1 | ATR stop multiplier change | Degraded risk-adjusted metrics |
| 1 | Stale exit timing (16→24 bars) | Worse outcomes — stale trades that survive longer still fail |
| 1 | VWAP fail timing (MIN_BARS/CONSEC) | VWAP_FAIL protects fast deaths — weakening it increases losses |
| 1 | Partial percentage change | Marginal or negative impact |
| 2 | Entry confirmation via prior-bar VWAP (CONFIRM_TOL_ATR=0.15) | Zero impact — tolerance too generous to filter anything |
| 2 | Sub-window sizing multiplier | PF improved but net profit dropped $584 |
| 2 | Early profit protection at +0.5R MFE | Net profit dropped $5,333 — stops too tight, killed developing winners |
| 2 | CORE VWAP cap tightening (0.85→0.65) | Near-identical — no trades filtered at tighter threshold |
| 3 | VWAP_FAIL → aggressive trail tightening | Net -$4,514, MaxDD 2.9%→6.8%. Letting losers survive via trail creates deeper drawdowns |
| 3 | STALE → breakeven stop lock | Net -$3,594. Stale trades surviving via BE lock don't reach profitable exits |
| 3 | Pre-+1R micro-trail | At wide params (2.0–3.0× ATR): zero effect (mathematically can't tighten before +1R). At tight params (1.5× ATR): catastrophic -$30K. No viable parameter exists |

---

## Key Lessons

1. **The pre-+1R phase is sacred.** Three separate attempts to add stop protection before +1R (early profit protection, VWAP_FAIL trail, micro-trail) all failed. Winners genuinely need their full initial stop width to absorb normal retracements during development.

2. **Exit mechanism changes are dangerous.** VWAP_FAIL and STALE exits look expensive in aggregate, but they're protecting against worse outcomes. Converting forced exits into softer alternatives (trails, BE locks) consistently increased drawdowns.

3. **Post-+1R is where optimization pays off.** The two most impactful changes (wider staged trail, OPEN→CORE tightening) both operate after the +1R partial — once the trade has proven itself. This is where the strategy has real edge to extract.

4. **Time-of-day awareness matters.** Three of the five kept changes are fundamentally about time (midday block, boundary refinement, OPEN→CORE tightening). NQ has distinct intraday personality shifts that a time-agnostic system leaves on the table.

---
---

# NQDTC Strategy Optimization: v1.0 → v2.0

## Progression

| Version | Trades | WR | PF | CAGR | Sharpe | MaxDD | Calmar | Equity Δ |
|---------|--------|------|------|------|--------|-------|--------|----------|
| **v1.0** (baseline) | 213 | 45.5% | 1.37 | 47.3% | 2.40 | 10.6% | 4.47 | — |
| **v1.1** (+Change 2) | 166 | 48.2% | 1.55 | 56.1% | 2.69 | 10.8% | 5.19 | +$8,745 |
| **v2.0** (+Changes 13,14) | 166 | 51.2% | 1.64 | 57.0% | 2.81 | 8.8% | 6.46 | +$51,183 |

Backtest conditions: MNQ (Micro E-mini Nasdaq-100), 10 contracts fixed, $0.62/side commission, $100K initial equity, ~11 months data (2025-03 to 2026-02).

---

## Changes KEPT (3 of 15 evaluated)

### 1. Kill RTH Entries — Round 1 (Change 2)

**Weakness addressed:** Diagnostics showed that entries during RTH (Regular Trading Hours, 9:30–16:00 ET) had severely negative expectancy. NQDTC is a swing strategy designed to capture multi-day trends using 30m/1H/4H timeframes — entering during RTH exposes trades to intraday noise and mean-reversion dynamics that work against the strategy's thesis. RTH entries had 33% win rate vs 52% for ETH, and contributed -$17K in losses.

**What it does:** Blocks all new entries during RTH by adding a time-of-day gate in the engine. Only entries during ETH (Extended Trading Hours: 18:00–09:30 ET) are permitted. Existing positions are unaffected.

**Impact:** Removed 47 losing RTH trades. CAGR improved from 47.3% to 56.1%, Sharpe from 2.40 to 2.69. Net profit increased by $8,745. The remaining 166 ETH-only trades have substantially better expectancy.

**Files:** `backtest/engine/nqdtc_engine.py` (RTH gate in entry logic)

### 2. Widen C_continuation Initial Stop (0.50 → 0.80 ATR) — Round 3 (Change 13)

**Weakness addressed:** Stop distance band analysis revealed that tight stops (0–15 points) had only 29% win rate and contributed -$3,600 in losses, while medium stops (22.5–33.5 points) had 41% win rate and contributed +$32,000. C_continuation entries used `hold_ref ± 0.50 × ATR14_30m`, placing many stops in the lethal tight band where normal NQ noise triggers them before the trade can develop.

**What it does:** Changed the C_continuation initial stop multiplier from 0.50 to 0.80 in `compute_initial_stop()`, widening the stop from `hold_ref ± 0.50 × ATR14_30m` to `hold_ref ± 0.80 × ATR14_30m`. This shifts C_continuation stops from the tight band into the profitable medium band.

**Impact:** Same total returns with substantially better risk metrics. Win rate improved from 48.2% to 51.2% (+3%). MaxDD fell from 10.8% to 8.8% (−2.0%). Calmar improved from 5.19 to 6.28 (+1.09). Sharpe from 2.69 to 2.77 (+0.08). Fewer whipsaw stops means more winners reach their targets.

**Files:** `strategy_2/stops.py` (compute_initial_stop, C_CONTINUATION case)

### 3. Fix R-Calculation to Use Initial Stop — Round 3 (Change 14)

**Weakness addressed:** A recording bug in `_close_position` calculated R-multiples using `pos.stop_price` (the current, migrated stop) rather than the initial stop set at entry. After TP1, the stop migrates to breakeven (~2 points from entry), shrinking the R denominator from ~40 points to ~2 points. This inflated reported R-multiples by ~12× on average (e.g., a 1.5R winner appeared as 18R). All diagnostic sections relying on R-multiples were unreliable.

**What it does:** Added `initial_stop_price` field to `PositionState`, frozen at entry and never migrated by breakeven or chandelier logic. Changed `_close_position` to use `initial_stop_price` for the R denominator, with a fallback to `stop_price` if initial is zero (backward compatibility).

**Impact:** Zero equity impact — this is a recording-only fix. The equity curve is bit-for-bit identical ($51,182.68 delta). R-multiples are now accurate: median winner R dropped from inflated ~12R to realistic ~1.5R. All R-based diagnostics (R-distribution, expectancy, give-back analysis) now report truthful numbers.

**Files:** `strategy_2/models.py` (PositionState.initial_stop_price), `backtest/engine/nqdtc_engine.py` (_close_position R-calc, position constructor)

---

## Changes REVERTED (12 of 15 evaluated)

| Round | Change | Why Reverted |
|-------|--------|-------------|
| 1 | Widen initial stop (all subtypes, 0.50→0.80 ATR) | Positive impact but superseded by targeted C_continuation-only change |
| 1 | Tighten chandelier for short trades | Degraded returns — asymmetry is intentional (shorts run differently) |
| 1 | Add volatility gate (block entries when ATR > threshold) | Removed too many trades including winners; volatility ≠ bad signal quality |
| 1 | Scale position size by inverse ATR | Marginal improvement, added complexity with no clear edge |
| 1 | Add 4H trend alignment gate | Blocked profitable trades — 4H trend lags, same problem as VdubusNQ hourly gate |
| 1 | Reduce TP1 target from +1R to +0.75R | Hit rate improved but net profit dropped — smaller wins don't compensate |
| 1 | Move breakeven stop to +0.25R instead of entry | Net negative — too tight, whipsawed out of winners post-TP1 |
| 2 | Entry confirmation via prior-bar close | Zero impact — filter too loose to reject any trades |
| 2 | STALE timer reduction (24→16 bars) | Worse outcomes — force-exiting earlier kills trades about to turn profitable |
| 2 | Session-based sizing multiplier | PF improved but net profit dropped — smaller size on best trades hurt |
| 3 | Add 30m trailing stop (replace 1H chandelier) | Net -$9,225. Trail at 1.5× ATR_30m (~75pt offset) is too tight after TP1 at +40pts — cuts winners short before they develop. The existing chandelier (wide, ~200pts) lets winners run |
| 3 | Pre-TP1 micro-trail | Same lesson as VdubusNQ: no viable parameter exists before +1R |

---

## Key Lessons

1. **Stop distance is a first-order driver.** The single largest determinant of trade outcome is initial stop width. Tight stops (< 15 pts) have 29% WR; medium stops (22–34 pts) have 41% WR; wide stops have 63% WR. Moving stops from the tight band to the medium band via the 0.50→0.80 ATR change improved WR by 3% with zero cost to returns.

2. **RTH is toxic for swing strategies.** NQDTC's edge comes from capturing multi-day trends on higher timeframes. RTH entries inject intraday noise — 33% WR vs 52% for ETH. Killing RTH entries was the largest single improvement (+$8,745, +8.8% CAGR).

3. **Trail tightness is the hardest parameter.** The 30m trailing stop at 1.5× ATR_30m (~75 pts) was too tight — it cuts winners that need 100–200 points of room post-TP1. The existing 1H chandelier at ~200 pts lets winners develop. There's no middle ground: tight trails kill winners, wide trails don't protect. This mirrors VdubusNQ's finding that post-+1R trail calibration is the highest-leverage optimization.

4. **Recording accuracy enables optimization.** The R-calculation bug (Change 14) didn't affect the equity curve, but it made every R-based diagnostic section unreliable — R-distributions, expectancy, give-back analysis, and stop-distance band analysis were all inflated by ~12×. Fixing this was prerequisite to trusting the diagnostics that justified Changes 13 and future work.

5. **Pre-+1R phase is sacred (confirmed across strategies).** Same lesson as VdubusNQ: three attempts to add stop protection before +1R all failed. Winners need their full initial stop width to absorb development-phase retracements.
