# Vdubus NQ Dominant-Trend Swing Protocol v4.0 (Final Spec, Clean + Deterministic)

**Instrument:** NQ (E-mini Nasdaq-100 futures)
**Objective:** Maximize expected returns by capturing dominant trends lasting hours → days in **both directions**, while maintaining healthy trade frequency via two entry archetypes (VWAP reclaim + breakout-retest), and using Predator divergence as a **sizing overlay** (not a gate).
**Core Philosophy:** *Intraday precision → Conditional overnight carry → Swing trend capture.*

---

## 0) Sessions, Timeframes, Resets, Rollover

### 0.1 Timeframes (hierarchy)

* **Daily (ES preferred, SPY fallback):** regime (trend + volatility state)
* **1-Hour (NQ):** structure pivots, tactical trend alignment, swing origin for VWAP-A
* **15-Minute (NQ):** primary execution triggers + momentum confirmation + intraday management decisions
* **5-Minute (NQ, optional):** micro-trigger refinement for Type A only (§10.4)

> Default implementation uses **15m only**. The 5m module is optional and does not change signal frequency (only entry quality).

### 0.2 Trading hours

**Entry windows (liquidity-first):**

* **RTH:** 09:40–15:50 ET
* **Evening Globex:** 19:00–22:30 ET (reduced sizing via session_mult, §13.2)

**Hard blocks (no new entries):**

* 09:30–09:40 ET
* 15:50–16:00 ET
* 22:30–09:40 ET (low liquidity / overnight)

**Stops/exits:** managed **24/5** via server-side orders.

### 0.3 Daily reset

At **09:30 ET**:

* Reset: daily realized PnL circuit breaker, directional entry counters
* Reset Session VWAP (RTH)

### 0.4 Futures rollover (mandatory)

**Volume trigger (primary):** front-month RTH volume < back-month RTH volume for **2 consecutive RTH sessions**.
**Calendar backstop (mandatory):** roll **no later than 2 RTH sessions before the front-month Last Trade Date (LTD)**.
If LTD is unavailable, **disable trading for NQ** rather than guessing.

**Roll execution:** flatten by RTH close on the last front-month session traded; resume trading next RTH on back-month.

---

## 1) Contract Specification (Single Source of Truth)

| Parameter     | Value  |
| ------------- | ------ |
| `tick_size`   | 0.25   |
| `tick_value`  | $5.00  |
| `point_value` | $20.00 |

---

## 2) Indicators (Deterministic)

### 2.1 ATR

* `ATR15 = ATR(14) on 15m` (points)
* `ATR15_ticks = ATR15 / tick_size`
* `ATR1H = ATR(14) on 1H` (points)

### 2.2 Trend filters

**Daily dominant trend (ES preferred):**

* `raw_daily = +1 if Close > SMA200 else -1`
* Trend flips only after **2 consecutive daily closes** confirm new state.

**1H tactical trend (NQ):**

* `raw_1h = +1 if Close > EMA50 else -1`
* Tactical trend flips only after **2 consecutive 1H closes** confirm.

### 2.3 Momentum (15m)

* `Mom15 = MACD_hist(8,21,5) on 15m`
* `mom_slope15(t) = Mom15[t] - Mom15[t-3]`

### 2.4 Confirmed pivots (non-repainting)

**1H pivots:**

* `Nconfirm_1H = 4`
  A pivot is valid only after confirmation; no repaint.

**Daily pivots (for VWAP-A anchor only):**

* `Nconfirm_D = 2`

### 2.5 VWAPs

**Session VWAP (15m, reset 09:30 ET):**

* `tp = (H+L+C)/3`
* `SessionVWAP = Σ(tp×vol)/Σ(vol)` from 09:30 onward

**Anchored VWAP-A (swing corridor):**
Anchored to the **swing origin pivot** for the direction:

* **Primary anchor source:** most recent confirmed **Daily** pivot in the direction:

  * Long: confirmed daily swing **low**
  * Short: confirmed daily swing **high**
* **Fallback (if daily pivot not available yet):** most recent confirmed **1H** pivot of the same type.

`VWAP_A = Σ(tp×vol)/Σ(vol)` from the anchor bar onward (use full session data continuity).

**VWAP_used selection rule:**

* For Type A pullback: use the VWAP that was **most recently touched** (SessionVWAP or VWAP_A) within the touch lookback.

---

## 3) Daily Volatility State (Regime)

On ES daily:

* `ATRv = ATR(14)`
* `ATRpct = percentile_rank(ATRv, 252)`
* `ATR_med = median(ATRv, 252)`

States:

* **Shock:** `(ATRpct > 90) AND (ATRv > 1.2×ATR_med)`
* **High:** `(ATRpct > 85) AND NOT Shock`
* **Normal:** otherwise

---

## 4) Direction Permission + Flip Exception

### 4.1 Base permission (hard gate)

* **Long entries allowed only if:** `DailyTrend = +1` AND `Shock = false`
* **Short entries allowed only if:** `DailyTrend = -1` AND `Shock = false`

### 4.2 Flip Entry exception (reversal participation)

When DailyTrend **has flipped (persisted)** to a new direction at a daily close:

* Allow **one** entry in the new direction next session even if `1H_Trend` not yet aligned.
* This entry uses `class_mult = 0.50`.
* Counts toward daily directional caps.

### 4.3 Regime flip mid-position

Regime changes do **not** force liquidation.

* If DailyTrend flips against the position: no new adds next session in that direction; manage normally.
* If Shock becomes true: no new entries next session; at next liquid session open:

  * Long: `Stop := max(Stop, EntryPrice)`
  * Short: `Stop := min(Stop, EntryPrice)`

---

## 5) Session Windows

**Hard blocks:** 09:30–09:40, 15:50–16:00
**Two-tier windows (affect caps/slippage):**

* **Open:** 09:40–10:30 and 15:30–15:50
* **Core:** 10:30–15:30
* **Evening:** 19:00–22:30

---

## 6) Event Safety + Re-Arm

### 6.1 Tier-1 event block

No new entries in `[-60m, +15m]` around:

* CPI, NFP, FOMC decision/statement, FOMC presser

### 6.2 Re-arm

After the post-event window ends, require **BOTH**:

**(1) Cooldown (15m closes):**

* CPI/NFP: ≥ **3** full 15m closes
* FOMC: ≥ **6** full 15m closes

**(2) Stability (union):** on each check, re-arm if **either**

* ATR normalization: `ATR15_current < 1.3 × ATR15_pre`
  where `ATR15_pre` = mean ATR15 over the 12 bars preceding the pre-event window start
* Bar calm: last closed 15m bar satisfies `SpreadTicks ≤ 2` **OR** `Range(bar) ≤ 1.8×ATR15`

If neither stability condition holds, extend stand-down by 1 bar, re-evaluate each bar, up to max **60 minutes** post-event.

---

## 7) Momentum Confirmation (Decelerating Slope, Same-Bar Only)

Compute bounds over last `N_mom = 50` closed 15m bars:

* `Mom_min50 = min(Mom15[t-50..t-1])`
* `Mom_max50 = max(Mom15[t-50..t-1])`
* `Mom_floor = Mom_min50 + 0.25×(Mom_max50 - Mom_min50)`
* `Mom_ceiling = Mom_max50 - 0.25×(Mom_max50 - Mom_min50)`

**Long SlopeOK(t)** is true if either:

1. `mom_slope15(t) > 0`
2. `(mom_slope15(t) > mom_slope15(t-1)) AND (Mom15[t] > Mom_floor)`

**Short SlopeOK(t)** is true if either:

1. `mom_slope15(t) < 0`
2. `(mom_slope15(t) < mom_slope15(t-1)) AND (Mom15[t] < Mom_ceiling)`

**No recheck. One bar, one decision.**

---

## 8) Predator Module (Sizing Overlay, Not a Gate)

### 8.1 Predator detection (1H pivots)

Use the most recent two confirmed 1H pivots of the required type:

**Predator Long:**

* Structure: `Low2 > Low1`
* Divergence: `Mom15_at_pivot2 < Mom15_at_pivot1`

**Predator Short:**

* Structure: `High2 < High1`
* Divergence: `Mom15_at_pivot2 > Mom15_at_pivot1`

`Mom15_at_pivot` is Mom15 sampled at the 15m bar closest to the 1H pivot bar close timestamp.

### 8.2 Effect on sizing

* Predator present in trade direction: `class_mult = 1.00`
* No Predator: `class_mult = 0.70`
* Flip Entry forces `class_mult = 0.50`

---

## 9) Entry Archetypes (Two Types)

### 9.1 Type A — Trend Pullback Reclaim (workhorse)

Evaluated on each **15m close** during entry windows.

**Long: all must be true**

1. Long permission (DailyTrend=+1, Shock=false) OR Flip Entry exception
2. 1H trend aligned: `1H_Trend=+1` (unless Flip Entry)
3. Touch within last `L_touch = 8` bars (15m):

   * `Low ≤ SessionVWAP` OR `Low ≤ VWAP_A`
4. Reclaim: trigger bar `Close > VWAP_used` (most recently touched)
5. VWAP cap gate (avoid chasing):

   * `UpperCap = VWAP_used + b_cap×ATR15`
   * Require `Close ≤ UpperCap`
6. Momentum: `SlopeOK_long(t)` true

**Short is mirror**

* Touch: `High ≥ SessionVWAP` OR `High ≥ VWAP_A`
* Reclaim down: `Close < VWAP_used`
* Cap: `LowerCap = VWAP_used - b_cap×ATR15`, require `Close ≥ LowerCap`
* Momentum: `SlopeOK_short(t)` true

### 9.2 Type B — Breakout → Retest (runaway trend catcher)

**Long: all must be true**

1. Long permission (DailyTrend=+1, Shock=false)
2. 1H trend aligned: `1H_Trend=+1`
3. Break level:

   * `BreakLevel_long = highest confirmed 1H pivot high over last 20×1H bars`
4. Breakout: a 15m close above BreakLevel_long occurred within last `L_break = 12` bars
5. Retest: within `L_retest = 8` bars after breakout, a 15m bar:

   * `Low ≤ BreakLevel_long + 0.25×ATR15` AND `Close > BreakLevel_long`
6. Momentum: `SlopeOK_long(t)` true
7. Extension sanity: skip if `Close > BreakLevel_long + 1.2×ATR15`

**Short is mirror**

* `BreakLevel_short = lowest confirmed 1H pivot low over last 20×1H bars`
* Breakout: close below
* Retest: `High ≥ BreakLevel_short - 0.25×ATR15` and `Close < BreakLevel_short`
* Extension sanity: skip if `Close < BreakLevel_short - 1.2×ATR15`

### 9.3 Priority

If Type A and Type B qualify same direction on the same 15m bar: **Type A takes priority**.

---

## 10) Optional 5M Micro-Trigger (Type A Only)

If a Type A signal is valid on the 15m close at time `T`:

**Micro-trigger window:** next `W_micro = 3` closed 5m bars.

Enter on the first 5m bar that satisfies:

* VWAP touch+reclaim around **SessionVWAP** within last 8×5m bars
* 5m decelerating slope confirmation using `Mom5 = MACD_hist(8,21,5) on 5m` and same logic as §7

If no micro-trigger within `W_micro`, then:

* **Default:** enter using the 15m trigger bar logic.
* (Config option: skip instead. Default is **do not skip**.)

---

## 11) VWAP Cap Calibration

Define `b_cap` by window:

* **Core:** 0.85
* **Open & Evening:** 0.72

Type A uses cap gate; Type B does not use cap but uses extension sanity (§9.2).

---

## 12) Risk Architecture

### 12.1 Unit risk

* `BaseRiskPct = 0.30% of NAV`
* `VolFactor`: Normal=1.0, High=0.65, Shock=0.0

`UnitRisk$ = NAV × BaseRiskPct × VolFactor`

### 12.2 Session multiplier

* `session_mult = 1.00` for RTH entries
* `session_mult = 0.70` for Evening entries

### 12.3 Effective risk

`EffectiveRisk$ = UnitRisk$ × class_mult × session_mult`

### 12.4 Position sizing

`qty = floor(EffectiveRisk$ / (R_points × point_value))`
If `qty < 1`: **skip trade**.

### 12.5 Heat cap

`MaxOpenRisk$ = 1.50 × UnitRisk$` (base, before class_mult)
Allow entry only if:
`OpenRisk$ + NewPositionRisk$ ≤ MaxOpenRisk$`

Where:
`PositionRisk$ = R_points × point_value × qty`

### 12.6 Daily circuit breaker

No new entries for rest of day if:
`DailyRealizedPnL ≤ -2 × UnitRisk$` (reset 09:30).

### 12.7 Directional entry caps

Per calendar day (reset 09:30):

* Long fills ≤ 2
* Short fills ≤ 2

Counts include Flip Entry and add-ons.

### 12.8 Pyramiding (one add-on, high-EV only)

Allow **one** add-on per direction if:

1. Existing position is ≥ +1R (based on its original R)
2. A new **Type A** signal fires in same direction
3. Add-on entry price is **more favorable than the current trailing stop** of the existing position (no chasing)
4. Combined risk ≤ heat cap
5. Directional caps not exceeded

Add-on risk: `0.50 × EffectiveRisk$` for the new signal.

Add-on is managed as a separate position with its own stop/exit logic.

---

## 13) Stops (Initial) and R Definition

### 13.1 Base stop calculation (structure-first with ATR guardrail)

**Long:**

* `StructureStop = last_confirmed_1H_pivot_low - 0.10×ATR1H`
* `ATRStop = Entry - 1.4×ATR15`
* Candidate stop is the **wider** invalidation (further away):

  * `Stop = min(StructureStop, ATRStop)`  (more negative = farther for longs)

**Short:**

* `StructureStop = last_confirmed_1H_pivot_high + 0.10×ATR1H`
* `ATRStop = Entry + 1.4×ATR15`
* `Stop = max(StructureStop, ATRStop)` (more positive = farther for shorts)

### 13.2 Guardrails

* `MinStopPoints = 20`
* `MaxStopPoints = 120`

If `|Entry - Stop| < 20`: force distance to 20 points.
If `|Entry - Stop| > 120`: cap distance to 120 points.

`R_points = |Entry - Stop|`

---

## 14) Costs & Viability

Config:

* `rt_comm_fees_per_contract_usd`
* `slip_ticks_by_window`: Open/Evening=2, Core=1

Compute:

* `slip_cost = slip_ticks × tick_value × qty`
* `fees_cost = rt_comm_fees_per_contract_usd × qty`
* `total_cost = slip_cost + fees_cost`
* `risk_usd = R_points × point_value × qty`

Skip if:

* `total_cost / risk_usd > 0.12`

Extreme sanity cap (skip):

* `SpreadTicks > 8` OR `ExpectedSlipTicks > 6`

---

## 15) Execution (Stop-Limit + TTL + One Fallback)

### 15.1 Primary entry order

Using the trigger bar (15m bar for default; 5m bar if micro-trigger used):

**Long:**

* `StopEntry = High(trigger_bar) + BufferTicks×tick_size`
* `LimitEntry = StopEntry + OffsetTicks×tick_size`

**Short:**

* `StopEntry = Low(trigger_bar) - BufferTicks×tick_size`
* `LimitEntry = StopEntry - OffsetTicks×tick_size`

Defaults:

* `BufferTicks = 1`
* `OffsetTicks = clamp(1, 8, round(0.10 × ATR15_ticks))`
  (If micro-trigger used, you may substitute ATR5_ticks analogously; default is still ATR15-based offset to avoid under-offsetting in high vol.)

### 15.2 TTL cancel-only

* `TTL_primary = 3 bars` (of the order’s timeframe)
* If not filled → cancel (no reprice)
* Partial fill → cancel remainder; manage filled qty normally

### 15.3 Teleport skip

If price trades > **8 ticks** beyond limit without fill → cancel/skip.

### 15.4 Dual-path fallback (single shot)

Fallback eligible only if:

1. StopEntry was traded through (triggered)
2. After **1 full bar** since trigger, order still not fully filled
3. Tight conditions: `SpreadTicks ≤ 2`, `ExpectedSlipTicks ≤ 2`, and `ATR15_ticks ≤ 120`

Action:

* Cancel remainder
* Submit one immediate execution replacement (market) for remaining qty

Only one fallback attempt per signal.

---

## 16) Trade Management: Intraday Phase (09:40–15:50 ET)

### 16.1 +1R Free-Ride

At +1R unrealized:

* Multi-lot: take **33%** (rounded down)
* Move stop to **Entry** on remaining qty
* 1-lot: move stop to Entry (no partial)

### 16.2 Intraday trailing (post-+1R)

After +1R:

* `R_now = UnrealizedPnL_usd / (R_points × point_value × qty_runner)`
* `trail_mult = max(1.5, 3.0 - (R_now/4.0))`

**Long:**

* `TrailStop = HighestHigh_15m(16) - trail_mult×ATR15`
  **Short:**
* `TrailStop = LowestLow_15m(16) + trail_mult×ATR15`

Stop only tightens.

### 16.3 VWAP failure exit (pre-+1R only)

Using `VWAP_used` from Type A logic (SessionVWAP or VWAP-A):

* Long: exit if **2 consecutive 15m closes** are `Close < VWAP_used`
* Short: exit if **2 consecutive 15m closes** are `Close > VWAP_used`

Disabled after +1R.

### 16.4 Stale exit (pre-+1R only)

Exit at market if:

* `bars_since_entry ≥ 16` (15m bars ≈ 4 hours)
* AND `unrealized_R < 0.30`

---

## 17) 15:50 ET Decision Gate — “Earn the Hold”

At **15:50 ET** Monday–Thursday, evaluate each open position:

**HOLD overnight** if **either**:

1. `Unrealized_R ≥ +1.0R`
2. `Unrealized_R ≥ +0.5R` AND (SlopeOK in trade direction on the 15m close) AND (1H trend aligned)

Otherwise: **FLATTEN** (market or immediate-execution equivalent).

### 17.1 Friday override (weekend risk)

At **15:50 ET Friday**:

* HOLD only if `Unrealized_R ≥ +1.5R`
* If held, tighten to lock at least +0.5R:

  * Long: `Stop := max(Stop, Entry + 0.5×R_points)`
  * Short: `Stop := min(Stop, Entry - 0.5×R_points)`

**Exception:** if the current trailing stop is already tighter than the above, leave it unchanged.

---

## 18) Overnight Phase (16:00–09:40 ET)

Only applies if the position passed the decision gate.

### 18.1 Overnight trail widening (wick-tolerant)

Compute:

* Long: `OvernightTrail = LowestLow_1H(4) - 0.5×ATR1H`
* Short: `OvernightTrail = HighestHigh_1H(4) + 0.5×ATR1H`

Adoption rules (never increase risk improperly):

* If position is at/above breakeven, do **not** set stop below Entry (long) / above Entry (short).
* Stop only tightens relative to the current stop in a way consistent with risk policy:

  * If OvernightTrail would **loosen** risk below allowed guardrails, keep current stop.
  * If OvernightTrail is tighter (more protective), adopt it.

### 18.2 Next RTH reassessment

At **09:40 ET**:

* Resume intraday trailing rules (§16.2), with the constraint: stop only tightens.

### 18.3 VWAP-A failure exit (multi-session profit protection)

For positions held into a second (or later) RTH session:

* Long: exit if a **1H close** is below `VWAP_A` AND `R_now > 0`
* Short: exit if a **1H close** is above `VWAP_A` AND `R_now > 0`

---

## 19) Deterministic Gate Order (15m evaluation loop)

On each **15m close** during entry windows, evaluate **per direction**:

1. Event gate (not blocked; if post-event, re-armed)
2. Regime gate (DailyTrend permits; Shock=false)
3. 1H alignment (or Flip Entry exception)
4. Window gate (within allowed entry times; not hard block)
5. Signal: Type A OR Type B conditions met
6. Type A cap gate OR Type B extension sanity gate
7. Momentum: SlopeOK same-bar
8. Predator overlay → set `class_mult`
9. Risk gates: heat cap, breaker, direction caps, pyramid conditions
10. Viability: cost/risk + sanity cap
11. Submit stop-limit + TTL
12. Fallback once if eligible
13. Manage intraday exits/trailing
14. 15:50 decision gate (if time)
15. Overnight management (if held)

**Priority:** Type A over Type B when both qualify same direction on same bar.

---

## 20) Defaults Summary (v4.0)

* Timeframes: Daily regime, 1H structure, 15m execution, optional 5m micro-trigger (Type A only)
* DailyTrend: ES SMA200, 2-close persistence
* 1H trend: EMA50, 2-close persistence
* Shock: ATRpct>90 and ATRv>1.2×median
* VWAP: SessionVWAP + VWAP-A anchored to swing-origin pivot (daily preferred, 1H fallback)
* Type A touch lookback: 8×15m bars
* Type B: breakout within 12 bars, retest within 8 bars, extension cap 1.2×ATR15
* Momentum: MACD_hist(8,21,5), slope lookback 3, N_mom=50, floor/ceiling 25%
* VWAP caps: Core 0.85, Open/Evening 0.72
* Risk: BaseRiskPct 0.30%; VolFactor High 0.65; heat cap 1.50×
* Stops: structure vs ATR guardrail; min 20 pts, max 120 pts
* Entries/day: 2 longs + 2 shorts
* Partial: 33% at +1R; move stop to BE
* Intraday trail: 15m HH/LL(16) with adaptive mult
* Stale: 16×15m bars and <0.30R (pre-+1R)
* Earn-the-hold: 15:50 gate; Fri stricter + weekend stop lock
* Overnight: 1H LL/HH(4) ± 0.5×ATR1H; VWAP-A failure exit if profitable
* Execution: stop-limit TTL=3; teleport 8 ticks; one fallback if tight; cost/risk ≤0.12

---