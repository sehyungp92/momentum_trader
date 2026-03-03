# NQ Dominant Trend Capture System — Final Spec v2.0

**“Session-Partitioned Compression → Displacement Breakout → Dual-Order Participation → Quality-Tiered Trend Capture + Continuation”**

**Primary objective:** Maximize expected returns by capturing multi-hour to multi-day **dominant NQ trends in both directions**, while avoiding an overly negative impact on trade frequency.

**Core loop (per session engine):**
**30m frozen compression box → VWAP displacement breakout → 5m execution (A OCO bracket / B trap / C pullback) → tiered exits + 1H chandelier runner → continuation + recompression cycling → structured re-entry**

---

## 0) Validation Requirements (Pre-live)

Required:

* ≥ **5 years** NQ data (include 2020–present style regimes)
* Rolling walk-forward with ≥ **12-month OOS** windows
* Costs: commissions, slippage, spread proxy, tick rounding
* Enforce **past-only** computation for all rolling quantiles/percentiles/slot medians
* Explicit fill model + intrabar priority (see §16)
* Report by:

  * session (ETH/RTH)
  * regime (Aligned/Neutral/Caution/Range/Counter)
  * mode (Normal/Degraded/Halt)
  * entry subtype (A_retest / A_latch / B_sweep / C_standard / C_continuation)
  * direction (long/short)

Guideline targets (not a claim):

* Expectancy > 0R after costs
* PF ≥ 1.3
* No persistent single-year failure
* Participate in ≥ 70% of moves ≥ 2% magnitude (definition in §18.3)

---

## 1) Universe, Timeframes, Sessions, Resets

### 1.1 Instruments

* **NQ** primary
* **MNQ** optional execution/sizing equivalent (same logic)

### 1.2 Timeframes

* **Signal/Structure:** 30m
* **Execution:** 5m
* **Runner trail:** 1H
* **Context:** 4H + Daily

### 1.3 Session Architecture (two engines; separate stats)

NQ microstructure differs materially in ETH vs RTH.

**ETH session**

* Time: **18:00–09:30 New York**
* VWAP anchor reset: **18:00 NY**
* Box engine: ETH engine only
* Entries allowed: **02:00–09:00 NY** (captures Europe + premarket)

**RTH session**

* Time: **09:30–16:15 New York**
* VWAP anchor reset: **09:30 NY**
* Box engine: RTH engine only
* Entries allowed: **09:45–15:30 NY**

**No entries outside windows.**
Open positions managed 24/5 (stops always live).

### 1.4 Resets

* **Daily risk reset:** 00:00 UTC
* **VWAP resets:** ETH 18:00 NY; RTH 09:30 NY
* **Displacement histories:** separate rolling buffers for ETH and RTH, **past-only**
* **Box engines:** ETH engine resets when RTH starts; RTH engine resets when ETH starts (fresh state each session)

---

## 2) Contract Specs + Tick Rounding

```python
NQ_SPECS = {
  "NQ":  {"tick": 0.25, "tick_value": 5.00, "point_value": 20.00},
  "MNQ": {"tick": 0.25, "tick_value": 0.50, "point_value":  2.00},
}

def round_to_tick(price: float, tick: float) -> float:
    return round(price / tick) * tick
```

All order prices (entry, stop, targets, trails) **must be tick-rounded**.

---

## 3) Risk Unit, Costs, and Friction Gate

### 3.1 R definition

**1R = 0.35% of current equity**

* `RISK_PCT = 0.0035`
* `R_dollars = equity * RISK_PCT`

Rationale: suited to NQ volatility while allowing adequate sizing.

### 3.2 Cost assumptions (initial; venue-specific)

```python
COMMISSION_RT   = {"NQ": 4.12, "MNQ": 1.64}   # round trip
SLIPPAGE_TICKS  = {"NQ": 1,    "MNQ": 1}      # per side, conservative
COST_BUFFER_USD = {"NQ": 2.00, "MNQ": 1.00}   # miscellaneous buffer
```

### 3.3 Friction-to-R gate (10%)

Block entry if estimated round-trip friction > **10% of 1R**.

```python
FRICTION_CAP = 0.10

def friction_ok(symbol: str, R_dollars: float) -> bool:
    tv = NQ_SPECS[symbol]["tick_value"]
    slip_cost = 2 * SLIPPAGE_TICKS[symbol] * tv
    total = slip_cost + COMMISSION_RT[symbol] + COST_BUFFER_USD[symbol]
    return total <= FRICTION_CAP * R_dollars
```

### 3.4 Fee-in-R estimate (logged)

```python
fee_R_est = (COMMISSION_RT[symbol] + 2*SLIPPAGE_TICKS[symbol]*tv + COST_BUFFER_USD[symbol]) / R_dollars
```

### 3.5 Sensitivity (required)

Sweep `FRICTION_CAP ∈ {0.08, 0.10, 0.14}` and report:

* trade count, expectancy, PF, max DD, % blocked

---

## 4) News Blackout — Hard Lock

Events: FOMC, CPI, NFP, PCE, GDP, ISM, major Fed speeches, Jackson Hole.

Rules:

* **No new entries ±30 minutes** around high-impact events.
* If **in-trade** and **15 minutes** to event:

  * if **not profit-funded** → flatten
  * if **profit-funded** → tighten stop to **BE ± 1 tick**

```python
if NEWS_BLACKOUT:
    BLOCK_ALL_NEW_ENTRIES()
```

---

## 5) VWAP Computation (Session + Box Anchors)

Typical price:

* `tp = (H + L + C) / 3`

### 5.1 Session VWAP (ETH or RTH)

```python
vwap_session = cumsum(tp * volume) / cumsum(volume)  # from session start anchor
```

### 5.2 Box-anchored VWAP (structural fair value)

Anchored at `box_anchor_time` (when box activates):

```python
vwap_box = cumsum(tp * volume) / cumsum(volume)  # from box_anchor_time
```

### 5.3 Usage

* **Displacement (breakout qualification):** `vwap_box`
* **Entry pullback references (A/B/C):** `vwap_session`
* **Trail:** independent (1H chandelier), not VWAP-based

---

## 6) Hard Safety Gates (binary; must all pass)

If any fail → **no new entry** and **no re-entry**.

1. News blackout (§4)
2. Daily halt / weekly throttle / monthly halt (§15)
3. CHOP hard halt (`chop_score ≥ 3`) (§10)
4. Regime hard block: **4H Counter AND Daily strongly opposed** (§9.4)
5. Breakout hard expiry (unless continuation mode) (§12)
6. Friction gate fail (§3.3)
7. Position overlap rule (§14)

All other logic affects score, permissions, or sizing — not eligibility.

---

## 7) Session-Partitioned Box Engines (ETH + RTH)

Two independent engines per session:

* ETH engine evaluates only ETH bars
* RTH engine evaluates only RTH bars

Entries:

* ETH entry window uses ETH engine only
* RTH entry window uses RTH engine only

---

## 8) Compression Detection: Adaptive 30m Frozen Box

### 8.1 Adaptive box length (3 buckets + hysteresis)

Compute on 30m:

* `ATR_ratio = ATR14_30m / ATR50_30m`

Buckets:

* `ATR_ratio < 0.7` → `L = 20`
* `0.7 ≤ ATR_ratio ≤ 1.2` → `L = 32`
* `ATR_ratio > 1.2` → `L = 48`

Hysteresis:

* change L only if bucket holds **≥4 consecutive 30m closes**

Constants:

* `VIOL_MAX = 2`
* `M_BREAK = 4`  (DIRTY window)

### 8.2 Candidate bounds

```python
range_high_roll = highest(high_30m, L)
range_low_roll  = lowest(low_30m,  L)
box_width_roll  = range_high_roll - range_low_roll
box_mid_roll    = (range_high_roll + range_low_roll) / 2
```

### 8.3 Containment

```python
containment = count(range_low_roll <= close_30m <= range_high_roll over L) / L
```

Require: `containment ≥ 0.85`

### 8.4 Box height minimum

```python
BOX_HEIGHT_MIN_ATR = 0.6 if L == 20 else 0.5
require box_width_roll >= BOX_HEIGHT_MIN_ATR * ATR14_30m
```

### 8.5 ACTIVE qualification + freeze bounds

ACTIVE if:

* age ≥ L
* containment ≥ 0.85
* box width meets min
* closes outside bounds in last L ≤ VIOL_MAX

On activation (false → true):

* freeze:

  * `box_high = range_high_roll`
  * `box_low  = range_low_roll`
  * `box_width = box_high - box_low`
  * `box_mid = (box_high + box_low)/2`
  * `box_anchor_time = bar_time`
  * `L_used = L`
* start `box_bars_active = 0`

While ACTIVE:

* do not update frozen bounds
* increment `box_bars_active`

When box becomes inactive:

* retire box and reset state.

---

## 9) Regime Engine (4H primary + Daily conditioner)

### 9.1 4H regime

Compute on 4H:

* EMA50, ADX14, ATR14

```python
slope_4H = EMA50_4H[t] - EMA50_4H[t-3]
slope_threshold_4H = k_slope * ATR14_4H
k_slope = 0.10  # sweep {0.05,0.10,0.15}
```

Classification:

* TRENDING if `ADX14_4H > 25` and `abs(slope_4H) > slope_threshold_4H`
* RANGE if `ADX14_4H < 20` and `ATR14_4H / SMA(ATR14_4H,50) < 1.0`
* TRANSITIONAL otherwise

Trend direction if TRENDING:

* `trend_dir = long if slope_4H > 0 else short`

### 9.2 Daily support/opposition

Compute daily slope similarly:

```python
slope_D = EMA50_D[t] - EMA50_D[t-3]
slope_threshold_D = k_slope * ATR14_D
```

Flags:

* `daily_supports = slope_D > slope_threshold_D` for long, `< -threshold` for short
* `daily_opposes` inverse

### 9.3 Composite regime (sizing)

Define trade direction from breakout (long/short) and map:

* **Aligned:** 4H TRENDING supports direction and (daily supports or neutral)
* **Neutral:** 4H TRANSITIONAL or daily opposes but 4H supports
* **Caution:** 4H counter but daily supports/neutral (possible reversal start)
* **Range:** 4H RANGE
* **Counter:** 4H counter and daily opposes strongly

### 9.4 Hard block (rare)

Hard block **only if**:

* 4H is **Counter** *and* Daily **strongly opposes** (Counter state)

This preserves frequency in early regime transitions.

---

## 10) CHOP Response (Graduated)

On 30m:

* `ATR14_pctl_60d = percentile_rank(ATR14_30m, lookback≈60d)`
* `vwap_cross_count = count_crosses(close_30m, vwap_session, last_40_bars)`

```python
chop_score = 0
if ATR14_pctl_60d > 75: chop_score += 1
if ATR14_pctl_60d > 90: chop_score += 1
if vwap_cross_count >= 5: chop_score += 1
if vwap_cross_count >= 8: chop_score += 1
```

Modes:

* `chop_score ≥ 3`: **HARD HALT** new entries
* `chop_score == 2`: **DEGRADED**

  * `size_mult = 0.70`
  * cap at TP1 only
  * stale exit timer shorter (§13.7)
  * score threshold +1 (§11.3)
* else NORMAL

---

## 11) Breakout Qualification (30m)

### 11.1 Structural breakout (required)

* Long: `close_30m > box_high`
* Short: `close_30m < box_low`

### 11.2 Displacement (primary confirmation; session-scoped history)

Compute on every 30m bar:

```python
DispMetric = abs(close_30m - vwap_box_30m) / ATR14_30m
```

Maintain separate past-only histories:

* `disp_history_eth`
* `disp_history_rth`

Threshold:

```python
atr_expanding = ATR14_30m > SMA(ATR14_30m, 50)
effective_q_disp = q_disp - 0.05 if atr_expanding else q_disp
disp_th = rolling_quantile_past_only(disp_history_session, effective_q_disp)
displacement_pass = DispMetric >= disp_th
```

Required sweep:

* `q_disp ∈ {0.60,0.65,0.70,0.75,0.80}`
  Choose lowest meeting OOS targets.

### 11.3 Breakout Quality Reject (rare hard block)

On breakout bar:

* `RVOL = volume / median(volume_same_30m_slot_past_sessions)`

Compute:

```python
bar_range = high - low
body = abs(close - open)
body_ratio = body / bar_range if bar_range > 0 else 1.0

if long:
    adverse_wick = high - max(open, close)
else:
    adverse_wick = min(open, close) - low

wick_ratio = adverse_wick / bar_range if bar_range > 0 else 0.0
```

Reject:

```python
BREAKOUT_REJECTED = (
  bar_range > 1.8 * ATR14_30m and
  (body_ratio < 0.30 or wick_ratio > 0.50) and
  RVOL > 2.0
)
```

Body bonus (score only):

* `body_decisive = body_ratio >= 0.50` (+0.5 score)

---

## 12) Breakout State: Expiry, Decay, Continuation

On qualified breakout (structural + displacement_pass + not rejected):

* `breakout_active = True`
* `bars_since_breakout = 0`
* compute `ATR_pctl_30m` and expiry:

```python
expiry_bars = clamp(round(8 * (ATR_pctl_30m / 50)), 6, 16)

DECAY_STEP = 0.10
DECAY_FLOOR = 0.30
HARD_EXPIRY_EXTENSION = 8
hard_expiry_bars = expiry_bars + HARD_EXPIRY_EXTENSION
```

Expiry multiplier:

```python
if bars_since_breakout <= expiry_bars:
    expiry_mult = 1.0
else:
    extra = bars_since_breakout - expiry_bars
    expiry_mult = max(DECAY_FLOOR, 1.0 - DECAY_STEP*extra)
```

Hard expiry invalidation:

* if `bars_since_breakout > hard_expiry_bars` → invalidate unless continuation mode

### 12.1 Continuation mode (trend keeper)

Activate `CONTINUATION_MODE = True` if either:

* price reaches measured move level (see §13.1), OR
* `R_proxy ≥ 2.0`, where:

  * long: `(mark - box_high) / ATR14_30m`
  * short: `(box_low - mark) / ATR14_30m`

In continuation mode:

* **Entry A/B disabled**
* **Entry C_continuation only** (with tight pause constraint)
* expiry clock pauses while continuation remains active

### 12.2 Breakout invalidation

Invalidate if any:

1. 2 consecutive 30m closes back inside box
2. Hard regime block occurs
3. `bars_since_breakout > hard_expiry_bars` and not in continuation mode

---

## 13) Evidence Scorecard (frequency-safe)

Evaluate score only if:

* structural breakout true
* displacement_pass true
* not rejected

```python
score = 0.0

score += 1.0  # displacement pass baseline
if RVOL > 1.2: score += 1.0

two_outside = (breakout_close[t] outside) and (breakout_close[t-1] outside)
atr_rising = ATR14_30m > ATR14_30m[-8]
if two_outside and atr_rising: score += 1.0

if squeeze_good: score += 1.0
if squeeze_loose: score -= 1.0

# 4H regime support
if regime_4H == "TRENDING" and trend_dir == trade_dir: score += 1.0
elif regime_4H == "TRANSITIONAL": score += 0.5

if daily_supports: score += 1.0
if body_decisive: score += 0.5
```

Thresholds:

* NORMAL: `score ≥ 2.0`
* DEGRADED: `score ≥ 3.0`
* HARD HALT: none

---

## 14) Overlap Rule

One position total per instrument family:

```python
if position_open("NQ") or position_open("MNQ"):
    BLOCK_NEW_ENTRIES()
```

No pyramiding. Continuation re-entry only after flat.

---

## 15) Sizing, Multipliers, Micro-Guard

### 15.1 Base risk

* `base_risk_pct = 0.0035`

### 15.2 Quality multiplier (continuous)

```python
quality_mult = clamp(regime_mult * chop_mult * disp_mult, 0.15, 1.0)
```

**regime_mult** (typical defaults):

* Aligned: 1.00
* Neutral: 0.60
* Caution: 0.35
* Range: 0.40
* Counter: hard block

**chop_mult**

* Normal: 1.00
* Degraded: 0.70

**disp_mult**
Use session-scoped scaling:

```python
T70 = rolling_percentile(DispMetric, 70, session)
T90 = rolling_percentile(DispMetric, 90, session)
disp_norm = clamp((DispMetric - T70) / max(1e-9, T90 - T70), 0, 1)
disp_mult = 0.70 + 0.30*disp_norm
```

### 15.3 Final risk

```python
final_risk_pct = base_risk_pct * quality_mult * expiry_mult
RISK_FLOOR_PCT = 0.15 * base_risk_pct
final_risk_pct = clamp(final_risk_pct, RISK_FLOOR_PCT, base_risk_pct)
floored_to_risk_floor = (base_risk_pct*quality_mult*expiry_mult < RISK_FLOOR_PCT)
```

### 15.4 Micro-trade guard (fee-drag prevention)

Skip if:

* `floored_to_risk_floor == True`
* `expiry_mult < 0.60`
* `exit_tier == "Caution"`
* AND `disp_mult < 0.85`

Log skip reason.

### 15.5 Position sizing

```python
def compute_contracts(symbol, entry, stop, equity):
    tick = NQ_SPECS[symbol]["tick"]
    tv = NQ_SPECS[symbol]["tick_value"]
    R_dollars = equity * RISK_PCT

    stop_ticks = abs(entry - stop) / tick
    risk_per_contract = stop_ticks * tv + (COMMISSION_RT[symbol] / 2) + (COST_BUFFER_USD[symbol] / 2)
    qty = int((equity * final_risk_pct) // risk_per_contract)
    return max(0, qty)
```

Skip if:

* `qty < 1`
* friction gate fails

---

## 16) Entries (5m) — Dual-Order Participation + A/B/C

All entries require:

* breakout_active true
* hard gates pass
* score threshold met
* `final_risk_pct ≥ RISK_FLOOR_PCT`
* micro-guard passes
* within entry window

### 16.1 Entry permissions

* **A:** allowed only if `CONTINUATION_MODE == False`
* **B:** allowed only if `composite_regime == Aligned` AND `DispMetric ≥ session p90` AND not continuation
* **C:** allowed if `composite_regime in {Aligned, Neutral}` OR continuation mode true

### 16.2 Entry A (primary): OCO dual-order bracket

On breakout qualification, place two OCO orders:

**A1 — Retest Discount (limit)**

* long: limit at `vwap_session + offsetA`
* short: limit at `vwap_session - offsetA`
  where:
* `offsetA = 0 to +2 ticks` (default +2 ticks long / -2 ticks short)

**A2 — Latch Participation (stop)**

* long: stop at `breakout_30m_high + 2 ticks`
* short: stop at `breakout_30m_low  - 2 ticks`

TTL:

* 3 bars of 5m (15 minutes)

Cancellation / invalidation:

* long: cancel both if `close_5m < box_high - 0.15*ATR14_30m`
* short: cancel both if `close_5m > box_low + 0.15*ATR14_30m`

On fill:

* cancel the sibling order
* log subtype:

  * A1 fill → `entry_subtype="A_retest"`
  * A2 fill → `entry_subtype="A_latch"`

### 16.3 Entry B (trap specialist): sweep + reclaim

sweep depth:

* `sweep_depth = 0.20 * ATR14_30m`

On 5m:

* long: `low_5m < vwap_session - sweep_depth` AND `close_5m > vwap_session`
* short: mirror

Entry:

* stop-market/market on close (see fill model)

Subtype: `B_sweep`

### 16.4 Entry C (pullback/hold)

Base hold signal (2 consecutive 5m bars):

* long: `close > vwap_session AND low >= vwap_session` (both bars)
* short: mirror

`hold_ref`:

* long: min(low of the two bars)
* short: max(high of the two bars)

**C_standard**

* allowed only if not continuation mode
* entry: `hold_ref + 0.05*ATR14_30m` (long) / minus for short
* subtype: `C_standard`

**C_continuation** (continuation mode only, strict selectivity)
Additional tight pause constraint:

* compute `rng1, rng2` of the two 5m bars
* require `max(rng1,rng2) ≤ 0.4*ATR14_5m`

Entry:

* stop at pause high/low OR shallow limit:

  * long: `pause_high + 1 tick`
  * short: `pause_low  - 1 tick`
    Subtype: `C_continuation`

### 16.5 Stops (by entry subtype; key expectancy improvement)

All stops tick-rounded.

**A_latch (wick-resistant)**

* long: `stop = box_mid - 0.10*ATR14_30m`
* short: `stop = box_mid + 0.10*ATR14_30m`

**A_retest and C_standard (R-efficient structural stop)**

* long: `stop = box_high - 0.60*ATR14_30m`
* short: `stop = box_low  + 0.60*ATR14_30m`

**C_continuation (hold-based structural stop)**

* long: `stop = hold_ref - 0.50*ATR14_30m`
* short: `stop = hold_ref + 0.50*ATR14_30m`

Rationale:

* chase entries need wick survival (midpoint-ish)
* pullback entries need R-efficiency (structure invalidation)

### 16.6 Maker-first offset + rescue (single attempt)

For limit orders (A1, C entries), use:

* `OFFSET_BASE = 0.015` (ATR fraction)
* `offset_mult = 1.25 if ATR_pctl_30m>80 else 0.85 if <20 else 1.0`
* clamp offset to `[0.010, 0.030]` in ATR terms

**Rescue** (single attempt):
Eligible if:

* limit not filled by TTL
* signal still valid
* composite_regime == Aligned
* DispMetric ≥ session p90
* quality_mult ≥ 0.50

Execution: marketable limit with max slippage cap:

* `RESCUE_MAX_SLIPPAGE = 0.03 * ATR14_30m`
  Cancel if not immediate.

---

## 17) Trade Management — Tiered Exits + 1H Chandelier Runner

### 17.1 Measured move (duration-adjusted)

```python
duration_factor = clamp(sqrt(box_bars_active / 20), 0.8, 1.4)
MM_long  = box_high + 1.5*box_width*duration_factor
MM_short = box_low  - 1.5*box_width*duration_factor
```

### 17.2 Exit tier (freeze at entry)

* Base tier by composite regime, then downgrade by quality:

  * quality ≥ 0.50: keep tier
  * 0.25–0.50: downgrade one
  * <0.25: Caution
    Freeze: `exit_tier_at_entry`

### 17.3 Exit schedules

**Aligned**

* TP1 +1.5R (25%)
* TP2 +3.0R (20%)
* TP3 +5.0R (10%)
* Runner 45%

**Neutral**

* TP1 +1.0R (35%)
* TP2 +2.0R (30%)
* Runner 35%

**Caution**

* TP1 +1.0R (50%)
* TP2 +1.8R (30%)
* Runner 20%

### 17.4 Profit-funded rule

After TP1:

* `profit_funded = True`
* move stop to **BE + 0.05*ATR14_5m** (or BE + 1–2 ticks min)

### 17.5 Runner trail (1H chandelier; ratchet-only)

Compute each 1H close:

```python
if long:
    chandelier = highest(high_1H, lookback) - mult*ATR14_1H
else:
    chandelier = lowest(low_1H, lookback) + mult*ATR14_1H
trail = max(prev_trail, chandelier) for long (min for short)
```

Tier by open trade R:

* R < 2: lookback=12, mult=3.0
* 2 ≤ R < 4: lookback=10, mult=2.2
* R ≥ 4 and MM not reached: lookback=8, mult=1.8
* R ≥ 4 and MM reached: lookback=6, mult=1.2

### 17.6 Stale exit

Timer measured in 30m bars:

* NORMAL: exit if `< +0.5R` after **12 bars** (6h)
* DEGRADED or RANGE: exit if `< +0.5R` after **8 bars** (4h)

Overnight bridge:

* if at RTH close, price holds breakout side and 4H TRENDING supports direction:

  * extend stale timer to next RTH open + 4 bars
* else stale timer continues normally

### 17.7 Mode/regime overrides

* RANGE: cap at TP1 only + stale=8 bars
* DEGRADED: cap at TP1 only + stale=8 bars
* ALIGNED+NORMAL: full schedule including TP3 + runner

---

## 18) Re-entry, Continuation Cycling, Pending

### 18.1 Re-entry (one per box)

After stop-out, allow one re-entry per box if:

* stop-out ≥ −0.5R
* cooldown ≥ 30 minutes
* breakout still valid
* all hard gates pass + micro-guard pass

### 18.2 Trend cycling

After TP2 or profitable full exit:

* if a new compression box forms in trend direction → new trade id (fresh state)
* else if continuation mode active → allow C_continuation only

### 18.3 Trend capture metric (for reporting)

Define a “dominant trend” as:

* peak-to-trough move ≥ **2%** from a local swing pivot over ≤ 3 trading days
  Report whether strategy held any position in the trend direction for ≥ 25% of that move.

### 18.4 Pending (optional; only for transient blocks)

Only allowed if entry trigger is true but blocked by:

* Max positions (mostly irrelevant for single-instrument)
* Ops circuit breaker (if implemented)
* Heat cap (if you add portfolio later)

Given single-instrument focus, **pending is disabled by default**.

---

## 19) Backtest Execution Model (Required)

### 19.1 Tick rounding

All levels tick-rounded.

### 19.2 Limit fills (conservative trade-through)

* buy limit P: fill only if low ≤ P − 1 tick
* sell limit P: fill only if high ≥ P + 1 tick
  Fill at P.

### 19.3 Stop fills

* buy stop P: fill at P + slippage_ticks*tick (adverse)
* sell stop P: fill at P − slippage_ticks*tick

### 19.4 Market fills

* fill at close ± slippage_ticks*tick adverse

### 19.5 Intrabar priority

* stop executes before target if both touched in same bar unless higher-resolution data used
* in A OCO: if both could fill in same 5m bar, assume **A1 limit fills first** (conservative)

---

## 20) State Persistence (Required)

Persist per session engine:

* box state: bounds, timers, L_used, box_bars_active
* DIRTY state: dirty_high/low, start bar, reset deltas
* VWAP accumulators: ETH, RTH, box-anchored
* disp histories: ETH + RTH rolling buffers
* chop stats, regime state
* breakout state: active, bars_since_breakout, expiry_mult, continuation flag
* daily/weekly/monthly pnl + throttle state
* open position state: entry subtype, size, stop, targets, profit_funded, trail, MM reached flag
* outstanding orders: A OCO, C orders, TTL counters, rescue attempt flag

Save on every 5m close and on any fill/order update.

---

## 21) Telemetry (Required)

Log for every signal attempt (even blocked):

* session, mode, regime, direction
* box params: L_used, height, squeeze metric + flags
* DispMetric, threshold, q_disp, atr_expanding flag
* score total and components
* entry requested/placed subtype, permission reasons
* risk: base_risk_pct, quality_mult components, expiry_mult, final_risk_pct
* floored_to_risk_floor, micro-guard flag + reason
* friction_to_R estimate, `fee_R_est`
* execution: fill price, slippage ticks, rescue attempted/filled
* exits: realized R, MFE/MAE in R, time-in-trade, runner exit reason
* DIRTY audit: reset method + delta shifts

Aggregate reporting by entry subtype:

* count, expectancy after costs, PF, max DD
* win rate, avg win/loss in R
* runner contribution to total R
* trend capture metric (§18.3)

Review cadence:

* every 20 closed trades or monthly, whichever first

---

## 22) Parameter Sweep Protocol

Primary (tune first):

* `q_disp ∈ {0.60,0.65,0.70,0.75,0.80}`
* `q_sq ∈ {0.15,0.20,0.25,0.30}`
* `k_slope ∈ {0.05,0.10,0.15}`
* `base_risk_pct ∈ {0.0025,0.0035,0.0050}`

Secondary:

* continuation threshold R_proxy ∈ {1.5, 2.0, 2.5}
* chandelier mult tiers ±20%
* micro-guard disp floor ∈ {0.80, 0.85, 0.90}

Robustness:

* ±20% perturbation on ≥10 parameters must keep:

  * expectancy > 0
  * max DD ≤ 2× baseline
  * trade count ≥ 50% baseline

---

## 23) Enforcement Precedence (Final)

1. News blackout
2. Daily/weekly/monthly risk controls
3. Overlap rule
4. Chop mode (halt/degraded/normal)
5. Select session engine (ETH/RTH)
6. Update box state + DIRTY lifecycle
7. Structural breakout + breakout reject
8. Displacement pass (session history; ATR expansion discount)
9. Score threshold
10. Sizing + friction gate + micro-guard
11. Entries: A OCO → B → C (with permissions)
12. Execution: tick rounding + fill model + rescue
13. Management: tiered exits + chandelier runner + stale/bridge + continuation cycling

---