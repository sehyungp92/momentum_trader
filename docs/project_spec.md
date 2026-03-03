# AKC-Helix NQ TrendWrap v3.1 — Full Execution Spec (Optimal Unified)

**(Optimized for NQ E-mini futures via IBKR; maximizes expected returns while preserving healthy trade frequency and participating in dominant trends lasting hours → days, both directions.)**

**Execution venue:** Interactive Brokers
**Execution vehicle:** NQ (CME/Globex, front-month continuous with roll logic)
**Timezone:** ET (America/New_York)
**Primary objective:** capture dominant trend legs (hours→days) in both directions with high trend participation, controlled drawdowns, and robust microstructure-aware execution.
**Design:** Helix core (pivots + MACD divergence + R-management) + NQ session participation + frequency engine (1H pullback) + extension/climax protection + disciplined pyramiding.

---

# 0) Instrument, Data, Timeframes

## 0.1 Instrument (NQ)

| Field       | Value                      |
| ----------- | -------------------------- |
| Symbol      | NQ (E-mini Nasdaq-100)     |
| Exchange    | CME / Globex               |
| Tick size   | 0.25 pt                    |
| Tick value  | $5.00                      |
| Point value | $20.00 per pt per contract |
| Sizing unit | Contracts                  |

## 0.2 Contract continuity & roll

Use continuous front-month NQ contract.

**Roll trigger (automated):** roll to next contract when **either**:

* Next contract volume ≥ **2×** current contract volume, OR
* **5 calendar days** before expiry (first trigger wins)

During roll:

* Do not open new positions for 30 minutes around the migration window.
* Migrate stops and logic to new symbol; preserve R accounting via synthetic “position id”.

## 0.3 Timeframes

| TF             | Role                                                                             |
| -------------- | -------------------------------------------------------------------------------- |
| Daily          | regime component 1, ATRd, vol_pct, VolFactor, trend_strength                     |
| 4H             | regime component 2, primary setup generation (Class A, Class R)                  |
| 1H             | setup generation (Class M), triggers, execution, trailing, management            |
| 15m (optional) | not required; only allowed as a momentum assist for re-entry tags if implemented |

## 0.4 Data source

* Bars and quotes from IBKR.
* Use real-time **bid/ask** for spread checks at placement time.
* If bid/ask missing or stale → treat as **spread fail** (eligible for recheck).

---

# 1) Session Rules, Entry Windows, Dead Zones, Queueing

## 1.1 Session blocks (ET)

| Block                | Hours (ET)  | New Entries/Adds | SessionSizeMult | Notes                  |
| -------------------- | ----------- | ---------------: | --------------: | ---------------------- |
| **RTH-Prime 1**      | 09:35–11:30 |              Yes |            1.00 | US open momentum       |
| **RTH-Dead**         | 11:30–13:30 |           **No** |               — | Midday chop filter     |
| **RTH-Prime 2**      | 13:30–15:45 |              Yes |            1.00 | Afternoon continuation |
| **ETH-Quality AM**   | 08:00–09:35 |              Yes |            0.70 | Pre-market             |
| **ETH-Quality PM**   | 15:45–17:00 |              Yes |            0.70 | Post-RTH liquidity     |
| **Daily Halt**       | 17:00–18:00 |           **No** |               — | No activity            |
| **Reopen Dead Zone** | 18:00–20:00 |           **No** |               — | Reopen chop filter     |
| **ETH-Overnight**    | 20:00–03:00 |    Yes (4H only) |            0.50 | Trend-only             |
| **ETH-Europe**       | 03:00–08:00 | Yes (trend-only) |            0.60 | London/Europe seeding  |

**Trend-only** = Class A and Class M only (no reversal class).
**4H only** = Class A only (most conservative) **or** Class A + Class R if you enable it (see §10.4). Default: **Class A only** during 20:00–03:00.

## 1.2 Action matrix

| Action                            | Allowed                                      |
| --------------------------------- | -------------------------------------------- |
| New entries (full size)           | RTH-Prime 1 & 2                              |
| New entries (reduced)             | ETH-Quality AM/PM                            |
| New entries (ETH-Europe)          | 03:00–08:00 at 0.60× (trend-only)            |
| New entries (ETH-Overnight)       | 20:00–03:00 at 0.50× (**Class A only**)      |
| Adds                              | RTH-Prime windows only; must be before 15:00 |
| Management (stops/trailing/exits) | All sessions                                 |

## 1.3 Pre-halt protocol

At **16:55 ET**:

* Cancel all unfilled entry and add orders.
* Keep protective stops active through the halt.

## 1.4 Halt queue rule

If a setup confirms during **17:00–18:00**:

* Mark as **QUEUED**.
* At **18:00**, do **not** arm (reopen dead zone).
* At **20:00**, revalidate structure + gates + extension, then arm if still valid at overnight sizing rules.

## 1.5 Sunday open gap rule (only)

At Sunday 18:00 reopen:

* If price beyond trigger by more than `0.30 × ATR1H` → skip the queued setup instance.

Mon–Fri: no gap rule (continuous trading); catch-up logic handles overshoot.

---

# 2) Deterministic Pivots (Non-Repainting)

For TF ∈ {1H, 4H}, define 5-bar confirmed pivots:

* Pivot High at (t−2) if `High[t−2] == max(High[t−4..t])`
* Pivot Low at (t−2) if `Low[t−2]  == min(Low[t−4..t])`

Pivot is confirmed at time t (2 bars after pivot bar). Store at pivot bar:

* timestamp, type, price
* MACD line at pivot bar
* ATR_TF at pivot bar

**Buffer**

* `buffer = max(0.25, 0.05 × ATR_TF)`  (points)

---

# 3) Momentum Engine

Compute **MACD(8, 21, 5)** on 1H and 4H:

* MACD **line**: divergence logic, momentum confirmations.
* MACD **histogram**: momentum hold for trailing; optional assist.

(Optional) MACD(8,21,5) on 15m only for re-entry assist; not required.

---

# 4) News Guard (NQ-Scoped)

Block **new entries and adds** (management allowed) within:

| Event                            | Block Window |
| -------------------------------- | ------------ |
| CPI, NFP                         | −60m to +30m |
| FOMC decision + press conference | −60m to +60m |
| Fed Chair scheduled speeches     | −30m to +30m |
| GDP (advance), PCE               | −30m to +15m |
| ISM Mfg/Services                 | −15m to +10m |

Applies during all sessions (NQ trades through them).

Optional conservative mode: on CPI/NFP days, no new entries until 10:00 ET.

---

# 5) Daily + 4H Regime, Alignment Score, Trend Strength

## 5.1 Daily

* `EMA_fast_d = EMA(20, close)`
* `EMA_slow_d = EMA(50, close)`
* `ATRd = ATR(14)`

## 5.2 4H

* `EMA_fast_4h = EMA(20, close)`
* `EMA_slow_4h = EMA(50, close)`

## 5.3 Alignment score (0–2)

For **long**:

* +1 if `EMA_fast_d > EMA_slow_d` AND `close_d > EMA_fast_d`
* +1 if `EMA_fast_4h > EMA_slow_4h` AND `close_4h > EMA_fast_4h`

For **short**: mirrored.

## 5.4 Trend strength and strong trend

* `trend_strength = abs(EMA_fast_d - EMA_slow_d) / ATRd`
* `strong_trend = (trend_strength > 0.80) AND (alignment_score == 2)`

---

# 6) Volatility Engine (VolFactor) + Extreme-Vol Quality Mode

Daily:

* `ATR_base = median(ATRd, 60)`
* `vol_pct = percentile_rank(ATRd_today, 60)`

VolFactor:

```python
VolFactor_raw = ATR_base / ATRd_today
VolFactor = clamp(VolFactor_raw, 0.40, 1.50)
if vol_pct < 20:
    VolFactor = min(VolFactor, 1.0)
```

**Extreme-vol mode** if `vol_pct > 95`:

* Disable **Class R** (reversal)
* Keep **Class A and Class M**
* Reduce Unit1Risk by **20%** (multiplicative)
* Increase MinStop gate (see §7.2)
* Tighten portfolio heat cap to **1.25R**

---

# 7) Quote Quality + Stop-Distance Gates

## 7.1 Spread gate (session-aware)

At placement:

* `spread_pts = ask - bid`

Max spread:

| Session                  | Max spread |
| ------------------------ | ---------- |
| RTH-Prime                | 1.00 pt    |
| ETH-Quality + ETH-Europe | 1.50 pt    |
| ETH-Overnight            | 2.00 pt    |

**Re-check grace:** if spread fails, recheck up to **2 consecutive 1H bars** while setup remains valid.

Fail-closed on missing/stale quotes.

## 7.2 Minimum stop distance gate

* `stop_dist = abs(EntryPrice_ref - Stop0)`
* `MinStop = max(5.0, 0.35 × ATR1H)`

Extreme-vol:

* `MinStop = max(7.5, 0.50 × ATR1H)`

Allow only if `stop_dist ≥ MinStop`.

## 7.3 Breakout sanity (spike filter)

If the 1H bar that triggers the entry has:

* `range_1h > 1.8 × ATR1H`
  Then **skip** the setup instance (avoids news-spike fills), especially for Class M.

---

# 8) Extension Gate (Avoid Buying Tops / Selling Bottoms)

Daily extension flag:

* `extension_long  = close_d > EMA_fast_d + 1.5 × ATRd`
* `extension_short = close_d < EMA_fast_d - 1.5 × ATRd`

Effects:

* If `extension_long`: block new **long** entries for **Class A and Class M**.
* If `extension_short`: block new **short** entries for **Class A and Class M**.
* **Class R** reversal into the extension remains allowed (unless extreme-vol).

---

# 9) Divergence Magnitude Filter (Hybrid)

For divergence candidate (P1, P2) on TF:

* `div_mag_norm = abs(macd(P1) - macd(P2)) / ATR_TF_at_P2`

Maintain history per TF. Threshold:

```python
if len(history) < 20:
    threshold = 0.05
else:
    threshold = max(0.04, percentile(history, 25))
```

Accept only if `div_mag_norm ≥ threshold`.

---

# 10) Setup Classes (Unified)

## 10.1 SetupSizeMult table

### Class A — 4H Hidden Divergence Continuation

| Alignment score | SetupSizeMult |
| --------------- | ------------- |
| 2               | 1.00          |
| 1               | 0.75          |
| 0               | 0.50          |

### Class M — 1H Pullback Continuation

| Alignment score | SetupSizeMult                |
| --------------- | ---------------------------- |
| 2               | 0.85 (×1.10 if strong_trend) |
| 1               | 0.65                         |
| 0               | Disabled                     |

### Class R — 4H Classic Divergence Reversal (Selective)

| Context                        | SetupSizeMult |
| ------------------------------ | ------------- |
| Weakening trend / regime shift | 0.65          |
| Chop                           | 0.60          |
| Fading strong trend            | 0.40          |
| vol_pct > 95                   | Disabled      |

## 10.2 Class A — 4H Hidden Divergence Continuation (Anchor)

**Pre-entry gates:**

* Not news-blocked
* Spread + MinStop gates pass
* **Extension in trade direction must be false**
* Corridor cap must pass

**Long**
On confirmation of 4H pivot low L2:

* `L2 > L1`
* hidden divergence: `macd_4h(L2) < macd_4h(L1)`
* magnitude passes §9

Let `H_last_4h` = pivot high between L1 and L2.

Trigger (on 1H):

* `EntryStop = H_last_4h + buffer`

Stop0:

* `Stop0 = L2 − 0.75 × ATR4H`

**Corridor cap (score-based)**
Let `stop_dist = EntryStop - Stop0`:

* score 2: cap = `1.8 × ATRd`
* score 1: cap = `1.6 × ATRd`
* score 0: cap = `1.4 × ATRd`

Skip if `stop_dist > cap`.

Short: mirrored.

## 10.3 Class M — 1H Pullback Continuation (Frequency Engine)

**Pre-entry gates:**

* alignment_score ≥ 1
* Not news-blocked
* Spread + MinStop gates pass
* Extension in trade direction is false
* 4H structure not broken against direction (no fresh 4H pivot invalidation)
* Trigger-bar spike filter passes (§7.3)

**Long**

* 1H pivots produce `L2 > L1` (higher low)
* define `pullback_depth = recent_1H_swing_high - L2`
* require: `0.4×ATR1H ≤ pullback_depth ≤ 1.4×ATR1H`
* momentum reclaim:

  * `macd_1h[t] > macd_1h[t−3]`
  * `macd_1h[t] > macd_1h(L2)`

Let `H_last_1h` = pivot high between L1 and L2.

Trigger:

* `EntryStop = H_last_1h + buffer`

Stop0:

* `Stop0 = L2 − 0.60 × ATR1H`

Short: mirrored.

## 10.4 Class R — 4H Classic Divergence Reversal (Selective Pivot)

Disabled if `vol_pct > 95`.

**Gate: at least 2 of 3**

1. `trend_strength_today < trend_strength_3days_ago`
2. `abs(close_d - EMA_fast_d) > 1.8 × ATRd`
3. Vol signature: `ATR_4h(10)` rising AND prior `ATR_4h(20)` falling (“coil then break”)

**Short**

* 4H pivot highs H1, H2 where `H2 > H1`
* classic divergence: `macd_4h(H2) < macd_4h(H1)` + magnitude passes §9
* `L_last_4h` = pivot low between H1 and H2
* Trigger (1H): `EntryStop = L_last_4h − buffer`
* Stop0: `Stop0 = H2 + 0.75×ATR4H`
* Corridor cap applies (same as Class A)

Long: mirrored.

## 10.5 Re-entry modifier (RE-ENTRY tag on Class M)

If a same-direction Class A or Class M trade exited within last `20×1H` bars and alignment_score still ≥ 1:

* Next valid Class M is tagged **RE-ENTRY**
* Apply sizing penalty: `SetupSizeMult *= 0.85`
* Cooldown: only one RE-ENTRY attempt per trend leg; if it fails, wait for a fresh Class A.

## 10.6 Priority

If multiple candidates compete and heat allows only one:

1. Class A
2. Class R
3. Class M (normal)
4. Class M (RE-ENTRY)

---

# 11) Execution (Stop-Market Primary, Catch-up, Slippage Guard)

## 11.1 Primary entry order type

* Stop-Market for all entries:

  * Long: Buy Stop at `EntryStop`
  * Short: Sell Stop at `EntryStop`

## 11.2 Slippage guard (“Teleport”)

Record:

* `trigger_price = EntryStop`
* `fill_price`

Compute:

* `slip_pts = abs(fill_price - trigger_price)`
* `slip_ticks = slip_pts / 0.25`

Threshold:

* RTH: `max(4 ticks, 0.08×ATR1H)`
* ETH: `max(6 ticks, 0.12×ATR1H)`

If exceeded:

* Mark as TELEPORT_FILL
* Keep position
* **Block adds until +2R**
* If `slip > 3× threshold` → immediately flatten (catastrophic fill)

## 11.3 Catch-up entry (overshoot)

If price already beyond trigger:

* `overshoot_cap = 0.20×ATR1H`

If within cap:

* Place marketable limit:

  * long: buy at `last + 0.50`
  * short: sell at `last - 0.50`
* TTL: 5 minutes
* Must be in same **OCA** group as primary stop

## 11.4 End-of-bar backstop

If trigger occurred but not filled by close of next 1H bar:

* cancel setup instance.

## 11.5 OCA duplication prevention

Primary stop and catch-up must share the same OCA group per setup instance.

---

# 12) Pending Order Management (TTL + Structure Invalidation)

## 12.1 TTL (from placement)

* 4H entries (A, R): 12 hours
* 1H entries (M): 6 hours
* Adds: 6 hours
* Catch-up: 5 minutes

## 12.2 Structure invalidation (cancel pending)

Cancel if:

* Long: new confirmed pivot low ≤ L2 on setup TF
* Short: new confirmed pivot high ≥ H2 on setup TF
* BoS superseded (new pivot materially redefines H_last/L_last)

## 12.3 Session cancellations

* 16:55 ET: cancel all unfilled entry/add orders
* 17:00–18:00: no activity
* 18:00–20:00: no new entries/adds (management only)

---

# 13) Risk, Sizing, Heat Caps

## 13.1 Base risk

* `Unit1Risk_$ = 0.50% equity × VolFactor`

Extreme-vol adjustment:

* `Unit1Risk_$ *= 0.80`

Strong-trend bonus (return maximization, controlled):
If `strong_trend` AND entry is Class A or Class M AND not extended:

* `Unit1Risk_$ *= 1.10`

## 13.2 Contract sizing

For each entry fill:

* `risk_per_contract_$ = abs(fill_price - Stop0) × 20`
* `contracts = floor((Unit1Risk_$ × SetupSizeMult × SessionSizeMult) / risk_per_contract_$)`

If `contracts < 1` → skip.

## 13.3 Heat caps

Default:

* Portfolio total: `OpenRisk_R + PendingWorstCase_R ≤ 1.50R`
* Per-direction cap: `≤ 1.20R`

Extreme-vol:

* total cap: `≤ 1.25R`
* per-direction cap: `≤ 1.00R`

---

# 14) Position Management & Profit Capture

## 14.1 R accounting

At Unit1 fill:

* `Unit1Risk_$` fixed (placement-time VolFactor & bonuses locked)

Definitions:

* `unrealized_R = unrealized_PnL / Unit1Risk_$`
* `R_state = (realized + unrealized) / Unit1Risk_$`

## 14.2 Catastrophic loss cap (−2R hard floor)

On every bar, before any other logic:

* If `R_state < −2.0` → flatten entire position immediately.

## 14.3 +1R transition (buffered BE)

When `unrealized_R ≥ +1.0`:

* Long: `Stop = max(Stop, AvgEntry − 0.20×ATR1H)`
* Short: mirrored
  Enable:
* trailing (§15)
* add eligibility (§16), subject to gates

## 14.4 +2R ratchet (profit floor)

When `unrealized_R ≥ +2.0`:

* `R_price = Unit1Risk_$ / (contracts_open × 20)`
* Long: `Stop = max(Stop, AvgEntry + 0.50×R_price)`
* Short: mirrored

(No contracts sold here.)

## 14.5 Scheduled partials (runner-preserving)

* At `unrealized_R ≥ +3.0`: close **33%** of total contracts.
* At `unrealized_R ≥ +6.0`: close **25%** of remaining; apply trailing bonus (§15.2).
* At `unrealized_R ≥ +8.0`: close **25%** of remaining; switch remaining runner to daily chandelier (§15.5).

## 14.6 Climax exit (anti V-top/V-bottom)

On every 1H close:

* `climax_long  = close_1h > EMA20_1h + 2.5×ATR1H`
* `climax_short = close_1h < EMA20_1h − 2.5×ATR1H`

If climax in trade direction AND `R_state > +2.0`:

* Exit **30%** of current position immediately (market).
* This is additive to scheduled partials (apply both if same bar).
* Log reason: CLIMAX_EXIT.

## 14.7 Stale exits (drift control without starving winners)

**Early stale (never reached +1R):** exit next 1H close if ALL:

* `bars_held_1h ≥ 18`
* trailing never activated
* `R_state < 0`
* not in Class R minimum hold (first 12 bars)

**Standard stale:**

* Class M (incl RE-ENTRY): after **28×1H bars**, if `R_state < +0.3`
* Class A / Class R: after **12×4H bars**, if `R_state < +0.3`

---

# 15) Trailing Engine (R-Adaptive Chandelier + Momentum Hold)

Active only after +1R.

## 15.1 Base multiplier

```python
mult_base = max(2.0, 4.0 - (R_state / 5.0))
```

If `strong_trend`: `mult_base = max(2.5, mult_base)`.

## 15.2 Momentum hold

If `R_state > 2.0`:

* `momentum_strong = (macd_1h[t] > macd_1h[t-5]) AND (hist_1h[t] > 0)`
  If strong:
* `mult = clamp(mult_base + 0.5, 2.0, 4.5)`
  Else:
* `mult = mult_base`

At +6R partial: `mult += 0.5` (cap 4.5).

## 15.3 1H chandelier (primary)

Lookback: **24×1H bars**.

* Long:

  * `Chand = HighestHigh(24) − mult×ATR1H`
  * `Stop = max(Stop, Chand)`
* Short mirrored.

Stop never loosens.

## 15.4 Regime tightening

If alignment score drops:

* by 1: `mult = max(2.0, mult − 0.25)`
* to 0: `mult = max(2.0, mult − 0.50)`

## 15.5 Daily chandelier (extended runner only, after +8R)

For remaining runner:

* lookback_daily = 10
* Long: `Chand_D = HighestHigh_D(10) − 2.0×ATRd`
* Short: mirrored
* Stop = max/min accordingly; never loosen.

---

# 16) Adds (Unit1 + 2 Adds Max, Declining Size)

Max units: Unit1 + Add1 + Add2 (3 units total).

## 16.1 Add prerequisites (ALL must pass)

* In RTH-Prime 1 or 2 (not dead zone)
* Time < 15:00 ET
* Not news-blocked
* Spread gate passes
* Heat caps pass
* Extension in trade direction is false
* Trigger-bar spike filter passes (range ≤ 1.8×ATR1H)
* If TELEPORT_FILL occurred: adds blocked until +2R

## 16.2 Add thresholds and risk budgets

| Add                   | Threshold                             | Risk budget        |
| --------------------- | ------------------------------------- | ------------------ |
| Add1 (Class A origin) | `unrealized_R ≥ +1.2`                 | `0.50×Unit1Risk_$` |
| Add1 (Class M origin) | `unrealized_R ≥ +1.6`                 | `0.50×Unit1Risk_$` |
| Add2 (any origin)     | `unrealized_R ≥ +3.5` AND Add1 filled | `0.30×Unit1Risk_$` |

## 16.3 Add setup (structure + momentum)

* New pivot in direction confirms (L3 > L2 for longs).
* Price remains beyond last BoS level.
* Momentum: `macd_1h[t] > macd_1h[t−3]` AND `macd_1h[t] > macd_1h(L2)`
* Trigger: break `H3_last + buffer` (short mirrored)

## 16.4 Sizing adds

* `add_risk_$ = risk_budget`
* `contracts_add = floor((add_risk_$ × SessionSizeMult) / (risk_per_contract_$))`

## 16.5 Single global stop + tighten on add fill

One stop for all units; never loosen.

On Add1 fill:

* `be_level = AvgEntry ± 0.20×ATR1H`
* tighten stop to at least be_level.

On Add2 fill:

* `profit_lock = AvgEntry ± 0.50×(Unit1Risk_$ / (total_contracts×20))`
* tighten stop to at least profit_lock.

## 16.6 Pre-halt add control

At **16:50 ET**:

* If Add2 active and `unrealized_R < 2.0` → flatten Add2 only.
* If Add1 active and `unrealized_R < 1.0` → flatten Add1 only.
* Else keep all units through the halt.

---

# 17) Implementation Requirements (IBKR via ib_async)

Must be event-driven:

* market data events (bar closes, tick updates for spread)
* order status events (fill/cancel/reject)
* scheduled timers (TTL, session transitions, pre-halt actions)

Required:

* OCA groups for primary stop vs catch-up
* Protective stop must never loosen
* State machine per setup instance: DETECTED → ARMED → PENDING → FILLED → MANAGED → EXITED
* Automated roll handling and position migration

Logging must capture:

* gate decisions (session, news, spread, MinStop, extension, spike filter, corridor, heat)
* slippage + TELEPORT classification (session context)
* add lockout events and release
* partials (+3R/+6R/+8R), climax exits
* trailing continuity and stop evolution
* stale exit reasons
* alignment score, vol_pct, VolFactor at entry and exit

---

# 18) Validation & Reporting (Minimum)

Per class (A/M/R) and per alignment score:

* trades, win rate, avg R/trade, R/week, max DD (R), avg hold time
* fill rate by session (RTH vs ETH-Europe vs ETH-Quality vs Overnight)
* Class M depth band distribution vs outcomes
* extension gate block rate + subsequent price path (“did it save us?”)
* climax exit frequency and captured R vs trailing-only counterfactual
* re-entry tagged trades: conversion rate and delta R vs non-re-entry
* slippage distribution by session; teleport rate
* add contribution: incremental R from Add1/Add2
* drawdown clustering: max consecutive losers, DD duration

---

## Symmetry

All rules mirrored for shorts.

---