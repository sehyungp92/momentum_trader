# Implementation Plan: NQ/MNQ Momentum Strategies — VPS Deployment

## Overview

Three NQ/MNQ momentum strategies run under a single shared OMS on a dedicated VPS. They connect remotely to PostgreSQL, the Next.js dashboard, and IB Gateway hosted on a separate VPS managed by the swing_trader (ETF) repo. Each strategy runs in its own Docker container, sharing an external Docker network for inter-container communication.

| Strategy | Version | Container | Entry Point | Session (ET) |
|---|---|---|---|---|
| AKC-Helix TrendWrap | v4.1 | `trading_helix` | `python -m strategy` | 03:00-17:00 (multi-window) |
| NQ Dominant Trend Capture | v2.1 (v8 config) | `trading_nqdtc` | `python -m strategy_2` | ETH 04:30-09:15, RTH 09:45-12:00 |
| Vdubus NQ Swing | v4.2 | `trading_vdubus` | `python -m strategy_3` | RTH 09:40-15:50, Evening 19:00-22:30 |

**Account**: $10,000, trading MNQ (Micro E-mini Nasdaq-100)

---

## 1. Architecture

```
┌─────────────────────────────────────┐      ┌─────────────────────────────────────┐
│ VPS 1 — Infra (swing_trader repo)   │      │ VPS 2 — Strategies (this repo)      │
│                                     │      │                                     │
│  IB Gateway (systemd, port 4002)    │◄─────┤  trading_helix  (python -m strategy)│
│                                     │      │  trading_nqdtc   (python -m strategy_2)
│  Docker                             │      │  trading_vdubus (python -m strategy_3)
│    trading_postgres (5432) ◄────────┤◄─────┤                                     │
│    trading_dashboard (3000)         │      │  trading_net (external Docker net)  │
│    trading_net (bridge)             │      │                                     │
└─────────────────────────────────────┘      └─────────────────────────────────────┘
```

**VPS 1 (infra, managed by swing_trader repo)**:
- PostgreSQL 16 — shared `trading` database for all strategies
- Next.js dashboard — real-time monitoring of all strategy heartbeats, positions, risk
- IB Gateway — headless via IBC + Xvfb, ports 4001 (live) / 4002 (paper)
- Docker network `trading_net` — shared by all containers

**VPS 2 (strategies, this repo)**:
- Three strategy containers join the remote `trading_net` network
- Write to the shared PostgreSQL database on VPS 1
- Appear automatically in the dashboard on VPS 1
- Connect to IB Gateway on VPS 1 via network

---

## 2. Portfolio Configuration (v6)

The active portfolio config is `make_10k_v6_config()` in
`shared/oms/config/portfolio_config.py`. Live trading rules are in
`shared/oms/risk/portfolio_rules.py` (`PortfolioRulesConfig`).

### 2.1 Strategy Allocations

| Strategy | Priority | Base Risk | Daily Stop | Max Concurrent | Flags |
|---|---|---|---|---|---|
| Vdubus | 0 (highest) | 0.80% | 2.5R | 1 | — |
| NQDTC | 1 | 0.80% | 2.5R | 1 | continuation_half_size=True (0.70x) |
| Helix | 2 (lowest) | 1.50% | 2.0R | 2 | — |

### 2.2 Portfolio-Level Rules

| Parameter | Value | Rationale |
|---|---|---|
| Heat cap | 3.5R | Headroom for 3 concurrent positions |
| Portfolio daily stop | 1.5R | Blocks 2nd/3rd entries on hostile days (+0.18 Sharpe vs 2.5R) |
| Directional cap | 3.5R | Matches heat cap — allows capacity when strategies agree |
| Max total positions | 3 | One per strategy |
| Proximity cooldown | 120 min (session-only) | Helix-NQDTC bidirectional, only during 09:45-11:30 ET overlap |
| Direction filter | agree=1.50x, oppose=block | NQDTC direction boosts/blocks Vdubus sizing |

### 2.3 Risk Budget at $10K MNQ

| Strategy | Risk % | Risk $ | Typical Stop (pts) | Qty @ 2.5pt stop | Risk R |
|---|---|---|---|---|---|
| Vdubus | 0.80% | $80 | ~2.5 | ~16 MNQ | ~1.0R |
| NQDTC | 0.80% | $80 | ~2.5 | ~16 MNQ | ~1.0R |
| Helix | 1.50% | $150 | ~3.0 | ~30 MNQ | ~1.0R |

Max simultaneous heat: 3.5R = ~$280 open risk (2.8% of equity).

### 2.4 Drawdown Tiers

| Drawdown | Size Multiplier | Effect |
|---|---|---|
| < 8% | 1.00x | Full size |
| 8-12% | 0.50x | Half size |
| 12-15% | 0.25x | Quarter size |
| > 15% | 0.00x | Halt all entries |

### 2.5 Session Overlap Map (ET)

```
04:30-09:15   NQDTC ETH only
09:35-09:45   Helix RTH_PRIME1 only
09:45-11:30   ALL THREE (Helix RTH_PRIME1 + NQDTC RTH + Vdubus OPEN/CORE)  ← peak overlap, proximity cooldown active
11:30-12:00   NQDTC RTH + Vdubus CORE + Helix RTH_DEAD
12:00-15:50   Helix + Vdubus only (NQDTC RTH closed)
15:50-17:00   Helix only (ETH_QUALITY_PM)
19:00-22:30   Vdubus EVENING + Helix ETH_OVERNIGHT
```

### 2.6 Cross-Strategy Interaction Rules

**Helix-NQDTC Proximity Cooldown (120 min, session-only)**
- Only enforced during 09:45-11:30 ET overlap window
- Outside overlap, strategies trade independently (biggest single lever: +19.3R vs always-on cooldown)
- If Helix enters at 09:45, NQDTC is blocked until 11:45
- If NQDTC enters at 10:00, Helix is blocked until 12:00
- Bidirectional — applies regardless of trade direction

**NQDTC Direction Filter (affects Vdubus only)**
- If NQDTC traded LONG today: Vdubus LONG boosted 1.50x, Vdubus SHORT blocked
- If NQDTC traded SHORT today: Vdubus SHORT boosted 1.50x, Vdubus LONG blocked
- If no NQDTC trade today: no filter applied (Vdubus at 1.0x)

**NQDTC Continuation Half-Sizing**
- C_continuation entries sized at 0.70x base risk
- Reversal entries (slope opposes direction) remain at 1.0x

### 2.7 Portfolio Backtest Results (v6)

| Metric | Value |
|---|---|
| Initial equity | $10,000 |
| Final equity | $45,533 |
| Net P&L | $+35,392 |
| Trades approved | 413 / 517 (104 blocked) |
| Win rate | 51.1% |
| E[R] | +0.508 |
| Profit factor | 2.11 |
| CAGR | 93.2% |
| Sharpe | 1.93 |
| Sortino | 2.26 |
| Calmar | 6.91 |
| Max drawdown | 13.5% ($1,729) |
| Period | 2.3 years (Nov 2023 - Feb 2026) |

Per strategy:
- Helix: 52 trades, 48% WR, +0.552R, $+4,382 (12.4%)
- NQDTC: 256 trades, 52% WR, +0.615R, $+28,522 (80.6%)
- Vdubus: 105 trades, 50% WR, +0.225R, $+2,488 (7.0%)

R-capture: 209.9R of 250.2R isolated = 83.9%

Strategy correlation (daily returns):
```
               Helix     NQDTC    Vdubus
     Helix     1.000     0.103    -0.018
     NQDTC     0.103     1.000     0.008
    Vdubus    -0.018     0.008     1.000
```

Near-zero cross-correlation confirms genuine diversification.

### 2.8 Optimization History

| Config | Trades | Total R | Sharpe | CAGR | MaxDD | PnL |
|---|---|---|---|---|---|---|
| v1 (baseline) | — | +41.4R | — | — | — | $+3,590 |
| v2 (optimized) | — | +55.2R | — | — | — | $+5,055 |
| v3 (sweep-validated) | — | +60.9R | — | — | — | $+5,519 |
| v4 (NQDTC dual-session) | 404 | +169.6R | 1.52 | — | — | $+21,027 |
| v5 (session cooldown + dir cap) | 425 | +204.4R | 1.73 | — | — | $+29,794 |
| **v6 (daily stop 1.5R)** | **413** | **+209.9R** | **1.93** | **93.2%** | **13.5%** | **$+35,392** |

v4→v6 key improvements: session-only cooldown (+19.3R), directional cap raised to 3.5R (+7.1R), portfolio daily stop tightened to 1.5R (+0.18 Sharpe, +$5.5k).

---

## 3. What Exists (Already Built)

### 3.1 Infrastructure Files

| File | Status | Purpose |
|---|---|---|
| `Dockerfile` | Done | Python 3.12-slim, asyncpg, ib_async |
| `infra/docker-compose.yml` | Done | Three strategy containers, external network |
| `infra/DEPLOY.md` | Done | Deployment guide (add-to-existing-VPS) |
| `.env.example` | Done | Environment template |

### 3.2 Shared OMS

| Component | File | Status |
|---|---|---|
| DB config | `shared/oms/persistence/db_config.py` | Done |
| Connection pool | `shared/oms/persistence/pool.py` | Done |
| Schema DDL | `shared/oms/persistence/postgres.py` | Done |
| Risk gateway | `shared/oms/risk/gateway.py` | Done |
| Risk config | `shared/oms/config/risk_config.py` | Done |
| Portfolio config | `shared/oms/config/portfolio_config.py` | Done (v1-v6) |
| Portfolio rules | `shared/oms/risk/portfolio_rules.py` | Done (v6 params) |
| Bootstrap service | `shared/services/bootstrap.py` | Done |
| OMS factory | `shared/oms/services/factory.py` | Done |

### 3.3 Strategy Engines

| Strategy | Config | Engine | Main | Status |
|---|---|---|---|---|
| Helix v4.1 | `strategy/config.py` | `strategy/engine.py` | `strategy/main.py` | Done |
| NQDTC v2.1 (v8 config) | `strategy_2/config.py` | `strategy_2/engine.py` | `strategy_2/main.py` | Done |
| Vdubus v4.2 | `strategy_3/config.py` | `strategy_3/engine.py` | `strategy_3/main.py` | Done |

### 3.4 IBKR Config

| File | Purpose | Status |
|---|---|---|
| `config/ibkr_profiles.yaml` | host, port, client_id, account_id | Done (IB_CLIENT_ID env override) |
| `config/contracts.yaml` | Instrument specifications (MNQ, NQ, etc.) | Done |
| `config/routing.yaml` | Exchange routing (CME, CBOT, etc.) | Done |

### 3.5 Portfolio Risk Infrastructure

| Component | File | Status |
|---|---|---|
| Portfolio rules | `shared/oms/risk/portfolio_rules.py` | Done — proximity, direction filter, directional cap, drawdown tiers, chop throttle |
| Risk gateway integration | `shared/oms/risk/gateway.py` | Done — calls PortfolioRuleChecker before entry |
| Cross-strategy state | `strategy_signals` DB table | Done — strategies publish direction/entry time |
| Portfolio backtester | `backtest/engine/portfolio_engine.py` | Done — post-hoc simulation with all rules |

---

## 4. Implementation Steps (Remaining)

### Step 1 — Resolve IB Client ID Assignment

Each strategy container needs a unique IB client ID. The `IB_CLIENT_ID` environment
variable override is wired up in the IBKR config loader.

Set per-container in `.env` or add `environment` block to `docker-compose.yml`:

```yaml
helix:
  environment:
    - IB_CLIENT_ID=11
nqdtc:
  environment:
    - IB_CLIENT_ID=12
vdubus:
  environment:
    - IB_CLIENT_ID=13
```

ETF strategies on VPS 1 use IDs 1-10. Momentum strategies use 11-20.

### Step 2 — Network Connectivity Between VPS Nodes

Since PostgreSQL, IB Gateway, and dashboard are on a separate VPS, the strategy
containers need network access to VPS 1.

**Option A: WireGuard tunnel (recommended)**

Create a WireGuard VPN between VPS 1 and VPS 2. Strategy containers connect to
Postgres and IB Gateway via the tunnel IP. Low latency, encrypted, persistent.

1. Install WireGuard on both VPS nodes
2. Assign tunnel IPs (e.g., VPS 1 = `10.0.0.1`, VPS 2 = `10.0.0.2`)
3. Update `.env` on VPS 2:
   ```bash
   DB_HOST=10.0.0.1        # VPS 1 tunnel IP (not container name)
   IB_HOST=10.0.0.1        # IB Gateway on VPS 1
   ```
4. Open ports on VPS 1 firewall: 5432 (Postgres) and 4002 (IB Gateway) for `10.0.0.2` only

**Option B: SSH tunnel**

Forward ports via persistent SSH tunnels. Simpler setup but less robust.

```bash
# On VPS 2, forward Postgres and IB Gateway
ssh -L 5432:localhost:5432 -L 4002:localhost:4002 user@vps1 -N
```

**Option C: Direct public access (not recommended)**

Expose Postgres and IB Gateway ports publicly with firewall rules. Higher attack surface.

**Recommendation:** Option A (WireGuard). Production-grade, always-on, minimal latency.

### Step 3 — Configure for MNQ

Verify `TRADING_SYMBOL=MNQ` in `.env`. MNQ is defined in `config/contracts.yaml`:

```yaml
MNQ:
  symbol: MNQ
  sec_type: FUT
  exchange: CME
  multiplier: 2.0
  tick_size: 0.25
  tick_value: 0.50
  trading_class: MNQ
```

The IBKR execution adapter resolves the front-month contract automatically via
`ContractFactory`. No manual contract expiry management needed.

### Step 4 — Paper Trading Validation

Before going live, run all three strategies in paper mode simultaneously to verify:

1. **IB connectivity**: All three containers connect with unique client IDs
2. **Database writes**: All three write to `strategy_state`, `orders`, `fills`
3. **Cross-VPS latency**: Postgres round-trip and IB Gateway order fills work over tunnel
4. **Heat cap**: Portfolio risk state aggregates across all strategies correctly
5. **Cross-strategy signals**: Proximity cooldown and direction filter work via shared DB
6. **No order conflicts**: Verify OCA groups don't interfere across strategies
7. **Dashboard**: All three momentum strategies appear alongside ETF strategies
8. **Session boundaries**: Strategies start/stop entries at correct times

Run for at least 5 trading days in paper mode before going live.

---

## 5. VPS Deployment Steps

### 5.1 Prerequisites (VPS 1 — Infra)

VPS 1 must already be deployed with the swing_trader repo:
- PostgreSQL container (`trading_postgres`) running and healthy
- Next.js dashboard container running
- IB Gateway running as systemd service on port 4002
- Network tunnel (WireGuard) established to VPS 2

Verify from VPS 2:
```bash
# Tunnel is up
ping 10.0.0.1

# Postgres is reachable
nc -zv 10.0.0.1 5432

# IB Gateway is reachable
nc -zv 10.0.0.1 4002
```

### 5.2 Clone Repo (VPS 2)

```bash
sudo mkdir -p /opt/trading
sudo chown $USER:$USER /opt/trading
cd /opt/trading
git clone <YOUR_REPO_URL> momentum_trader
cd momentum_trader
```

### 5.3 Configure Environment

```bash
cp .env.example .env
chmod 600 .env
nano .env
```

Key values:

```bash
# Environment
ALGO_TRADER_ENV=paper              # paper first, then live

# PostgreSQL on VPS 1 (via WireGuard tunnel)
DB_HOST=10.0.0.1                   # VPS 1 tunnel IP
DB_PORT=5432
DB_NAME=trading
DB_USER=trading_writer
DB_PASSWORD=<same_password_as_vps1>

# IB Gateway on VPS 1 (via WireGuard tunnel)
IB_HOST=10.0.0.1
IB_PORT=4002                       # paper=4002, live=4001
IB_ACCOUNT_ID=DU1234567

# IB Client ID (unique per container)
IB_CLIENT_ID=11

# Instrument
TRADING_SYMBOL=MNQ
```

### 5.4 Build and Deploy

```bash
cd /opt/trading/momentum_trader

# Build all strategy images
docker compose -f infra/docker-compose.yml \
  --profile helix --profile nqdtc --profile vdubus build

# Start all strategies
docker compose -f infra/docker-compose.yml \
  --profile helix --profile nqdtc --profile vdubus up -d
```

Start specific strategies only:
```bash
docker compose -f infra/docker-compose.yml --profile nqdtc up -d              # NQDTC only
docker compose -f infra/docker-compose.yml --profile helix --profile nqdtc up -d  # Helix + NQDTC
```

### 5.5 Verify Deployment

**Check containers are running:**
```bash
docker ps | grep trading_
```

Expected: 3 containers with status "Up".

**Check strategy logs:**
```bash
docker logs trading_helix --tail 50
docker logs trading_nqdtc --tail 50
docker logs trading_vdubus --tail 50
```

Look for:
- `Database pool created`
- `Database schema initialized`
- `IB session connected`
- `Engine started`

**Verify database connectivity:**
```bash
docker exec trading_nqdtc python -c \
  "import socket; s=socket.socket(); s.connect(('10.0.0.1',5432)); print('DB OK'); s.close()"
```

**Verify IB Gateway connectivity:**
```bash
docker exec trading_nqdtc python -c \
  "import socket; s=socket.socket(); s.connect(('10.0.0.1',4002)); print('IB OK'); s.close()"
```

**Check heartbeats in dashboard:**

Open the dashboard on VPS 1. All three momentum strategies should appear alongside
ETF strategies in:
- Strategy health view — heartbeats
- Live positions — open positions across all strategies
- Today's risk — daily risk by strategy

---

## 6. Operational Procedures

### 6.1 Daily Checklist

1. Verify all containers are running: `docker ps | grep trading_`
2. Check strategy health in dashboard (heartbeats)
3. Verify IB Gateway is connected
4. Review overnight positions
5. Check daily risk state

### 6.2 Common Operations

| Action | Command |
|---|---|
| View all logs | `docker compose -f infra/docker-compose.yml --profile helix --profile nqdtc --profile vdubus logs -f --tail=100` |
| Restart one strategy | `docker compose -f infra/docker-compose.yml --profile nqdtc restart nqdtc` |
| Stop all | `docker compose -f infra/docker-compose.yml --profile helix --profile nqdtc --profile vdubus down` |
| Rebuild after update | `git pull && docker compose -f infra/docker-compose.yml --profile helix --profile nqdtc --profile vdubus build && docker compose -f infra/docker-compose.yml --profile helix --profile nqdtc --profile vdubus up -d` |

### 6.3 Switching Paper to Live

1. Stop all momentum containers
2. Update `.env`:
   ```bash
   ALGO_TRADER_ENV=live
   IB_PORT=4001              # live port (vs 4002 paper)
   IB_ACCOUNT_ID=U1234567    # live account ID
   ```
3. Verify IB Gateway on VPS 1 is configured for live trading on port 4001
4. Rebuild and restart
5. Monitor closely for the first trading session

### 6.4 Handling IB Gateway Restarts

IB Gateway restarts daily (default: 11:45 PM ET for paper, Sunday for live).
Each strategy has reconnection logic:
- `reconnect_max_retries: 10`
- `reconnect_base_delay_s: 1.0`
- `reconnect_max_delay_s: 60.0`

Strategies automatically reconnect. No manual intervention needed unless
IB Gateway is down for an extended period.

### 6.5 Contract Rollovers

MNQ futures expire quarterly (March, June, September, December). The
`ContractFactory` resolves the front-month contract automatically via
IB's contract database. No manual config changes needed at rollover.

---

## 7. Troubleshooting

| Problem | Diagnosis | Solution |
|---|---|---|
| Can't reach DB from VPS 2 | WireGuard tunnel down | `wg show`, check `ping 10.0.0.1`, restart WireGuard |
| Can't reach IB Gateway | Tunnel down or IB Gateway stopped | Check tunnel + `ss -tlnp \| grep 4002` on VPS 1 |
| IB disconnects other strategy | Client ID collision | Each container needs unique `IB_CLIENT_ID` |
| Container exits immediately | Crash on startup | Check `docker logs <container>` for traceback |
| Database tables missing | First run hasn't initialized | Bootstrap creates tables on startup (`CREATE TABLE IF NOT EXISTS`) |
| Dashboard missing momentum data | Strategy not writing to DB | Check logs for `Database bootstrap complete` message |
| Heat cap blocking all entries | Stale positions from prior run | Check positions table, manually close orphaned positions |
| Strategy not entering trades | Outside entry window or daily stop hit | Check risk state and verify current time vs session windows |
| Portfolio daily stop triggered | -1.5R cumulative loss today | Expected — blocks further entries until next trading day |

---

## 8. File Reference

### Configuration
| File | Purpose |
|---|---|
| `.env` | Environment variables (DB, IB, mode, instrumentation) |
| `config/ibkr_profiles.yaml` | IB Gateway connection (host, port, client_id, account) |
| `config/contracts.yaml` | Instrument specifications (MNQ, NQ, etc.) |
| `config/routing.yaml` | Exchange routing rules |

### Strategy
| File | Purpose |
|---|---|
| `strategy/config.py` | Helix v4.1 constants |
| `strategy/engine.py` | Helix live engine |
| `strategy/main.py` | Helix entry point |
| `strategy_2/config.py` | NQDTC v2.1 (v8 config) constants |
| `strategy_2/engine.py` | NQDTC live engine |
| `strategy_2/main.py` | NQDTC entry point |
| `strategy_3/config.py` | Vdubus v4.2 constants |
| `strategy_3/engine.py` | Vdubus live engine |
| `strategy_3/main.py` | Vdubus entry point |

### Shared OMS
| File | Purpose |
|---|---|
| `shared/oms/config/portfolio_config.py` | Portfolio allocations (v1-v6 configs) |
| `shared/oms/config/risk_config.py` | Per-strategy risk parameters |
| `shared/oms/risk/gateway.py` | Pre-trade risk checks (heat cap, daily stop, portfolio rules) |
| `shared/oms/risk/portfolio_rules.py` | Cross-strategy rules (proximity, direction, drawdown) |
| `shared/oms/persistence/db_config.py` | Database config from environment |
| `shared/oms/persistence/pool.py` | asyncpg connection pool with retry |
| `shared/oms/persistence/postgres.py` | Schema DDL + PgStore queries |
| `shared/services/bootstrap.py` | Database initialization + graceful degradation |
| `shared/oms/services/factory.py` | OMS service builder (PG or in-memory) |

### Infrastructure
| File | Purpose |
|---|---|
| `Dockerfile` | Python 3.12-slim image (shared by all 3 strategies) |
| `requirements.txt` | asyncpg, ib_async, numpy, pytz, requests |
| `infra/docker-compose.yml` | Three strategy containers (external network, instrumentation volumes) |
| `infra/DEPLOY.md` | Deployment guide |

### Instrumentation
| File | Purpose |
|---|---|
| `instrumentation/src/event_metadata.py` | Deterministic event IDs, timestamps, clock skew |
| `instrumentation/src/market_snapshot.py` | Point-in-time market state capture (IBKR NQ/MNQ) |
| `instrumentation/src/trade_logger.py` | Entry/exit event logging with full context |
| `instrumentation/src/missed_opportunity.py` | Blocked signal logging + hypothetical backfill |
| `instrumentation/src/process_scorer.py` | Deterministic process quality scoring |
| `instrumentation/src/daily_snapshot.py` | End-of-day aggregate builder |
| `instrumentation/src/regime_classifier.py` | ADX/ATR/MA regime classification |
| `instrumentation/src/sidecar.py` | HMAC-signed event forwarding to relay |
| `instrumentation/config/instrumentation_config.yaml` | Bot ID, symbols, sidecar settings |
| `instrumentation/config/simulation_policies.yaml` | Per-strategy simulation assumptions |
| `instrumentation/config/process_scoring_rules.yaml` | Per-strategy scoring rules |
| `instrumentation/config/regime_classifier_config.yaml` | Regime classifier thresholds |

### Backtesting
| File | Purpose |
|---|---|
| `backtest/engine/helix_engine.py` | Helix v4.1 backtest engine |
| `backtest/engine/nqdtc_engine.py` | NQDTC v2.1 backtest engine |
| `backtest/engine/vdubus_engine.py` | Vdubus v4.2 backtest engine |
| `backtest/engine/portfolio_engine.py` | Portfolio backtest (post-hoc rule simulation) |
| `backtest/output/portfolio_10k_v6.txt` | Latest portfolio backtest results |

---

## 9. Instrumentation Layer

A structured event-logging layer that captures trade events, missed opportunities, process
quality scores, market snapshots, and daily aggregates. All data is written to local JSONL
files first, then forwarded to a central relay by a background sidecar thread.

### 9.1 Architecture

```
Strategy Engine
  │
  ├─ MarketSnapshotService.capture_now()   → instrumentation/data/snapshots/
  ├─ TradeLogger.log_entry() / log_exit()  → instrumentation/data/trades/
  ├─ MissedOpportunityLogger.log_missed()  → instrumentation/data/missed/
  ├─ ProcessScorer.score_trade()           → instrumentation/data/scores/
  └─ DailySnapshotBuilder.build()          → instrumentation/data/daily/
                                                    │
                                              Sidecar (background thread)
                                                    │
                                              ▼ HMAC-signed HTTP POST
                                           Central Relay
```

Each strategy container has its own instrumentation data volume. The sidecar reads
local JSONL files, wraps events in an envelope, signs with HMAC-SHA256, and forwards
to the relay with retry/backoff.

### 9.2 Components

| Component | File | Purpose |
|---|---|---|
| Event Metadata | `instrumentation/src/event_metadata.py` | Deterministic event IDs (SHA256), timestamps, clock skew |
| Market Snapshots | `instrumentation/src/market_snapshot.py` | Point-in-time bid/ask/ATR capture for NQ/MNQ via IBKR |
| Trade Logger | `instrumentation/src/trade_logger.py` | Entry/exit events with full context (signal, regime, slippage) |
| Missed Opportunities | `instrumentation/src/missed_opportunity.py` | Blocked signals + hypothetical outcome backfill |
| Process Scorer | `instrumentation/src/process_scorer.py` | Deterministic rules engine (regime fit, signal strength, latency, slippage) |
| Daily Snapshots | `instrumentation/src/daily_snapshot.py` | End-of-day aggregates (PnL, win rate, regime breakdown) |
| Regime Classifier | `instrumentation/src/regime_classifier.py` | ADX/ATR/MA-based regime tagging (trending_up/down, ranging, volatile) |
| Sidecar Forwarder | `instrumentation/src/sidecar.py` | Watermark-based event forwarding with HMAC signing and retry |

### 9.3 Configuration

| File | Purpose |
|---|---|
| `instrumentation/config/instrumentation_config.yaml` | Bot ID, symbols, sidecar settings, rotation policy |
| `instrumentation/config/simulation_policies.yaml` | Per-strategy hypothetical outcome assumptions (slippage, TP/SL) |
| `instrumentation/config/process_scoring_rules.yaml` | Per-strategy scoring rules (preferred/adverse regimes, thresholds) |
| `instrumentation/config/regime_classifier_config.yaml` | ADX/ATR thresholds for regime classification |

### 9.4 Data Storage

Event data is written to `instrumentation/data/` with daily file rotation:

```
instrumentation/data/
  snapshots/snapshots_YYYY-MM-DD.jsonl
  trades/trades_YYYY-MM-DD.jsonl
  missed/missed_YYYY-MM-DD.jsonl
  scores/scores_YYYY-MM-DD.jsonl
  daily/daily_YYYY-MM-DD.json
  errors/instrumentation_errors_YYYY-MM-DD.jsonl
  .sidecar_buffer/watermark.json
```

Each container has a named Docker volume for persistence:

| Container | Volume |
|---|---|
| `trading_helix` | `helix_instrumentation` |
| `trading_nqdtc` | `nqdtc_instrumentation` |
| `trading_vdubus` | `vdubus_instrumentation` |

### 9.5 Environment Variables

| Variable | Purpose | Required |
|---|---|---|
| `INSTRUMENTATION_HMAC_SECRET` | HMAC-SHA256 signing key for relay authentication | Yes (for relay forwarding) |
| `INSTRUMENTATION_RELAY_URL` | Relay endpoint URL (overrides config YAML) | Yes (for relay forwarding) |

Both are set in `.env` and passed to all containers via `env_file`. The sidecar reads
`INSTRUMENTATION_RELAY_URL` as an env var override for the config file's `relay_url`.
If neither is set, the sidecar logs locally but does not forward.

### 9.6 Deployment Checklist

1. Set `INSTRUMENTATION_HMAC_SECRET` in `.env` (generate: `openssl rand -hex 32`)
2. Set `INSTRUMENTATION_RELAY_URL` in `.env` (e.g., `https://relay.example.com/events`)
3. Rebuild containers: `docker compose -f infra/docker-compose.yml --profile helix --profile nqdtc --profile vdubus build`
4. Restart: `docker compose -f infra/docker-compose.yml --profile helix --profile nqdtc --profile vdubus up -d`
5. Monitor `instrumentation/data/errors/` for the first 24 hours
6. Verify events arrive at the relay

### 9.7 Fault Tolerance

All instrumentation is wrapped in try/except. If any component fails:
- Trades still execute normally (instrumentation never blocks trading logic)
- Degraded data is logged (e.g., zero-value snapshot on capture failure)
- Errors are written to `instrumentation/data/errors/`
- The sidecar buffers events when the relay is unreachable and retries with exponential backoff

### 9.8 Integration Hooks

Each strategy's `main.py` bootstraps instrumentation via `InstrumentationManager` after OMS
starts and shuts it down before engine stops. The bootstrap is wrapped in try/except so
instrumentation failure never prevents the strategy from running.

**Bootstrap module**: `instrumentation/src/bootstrap.py`

**Lifecycle per container**:

```
OMS.start()
  → InstrumentationManager(oms, STRATEGY_ID, strategy_type)
  → instr.start()
      ├─ Subscribe to OMS EventBus (stream_all_events)
      ├─ Start periodic market snapshot loop (60s)
      └─ Start sidecar background thread
  ... strategy runs ...
  → instr.stop()
      ├─ Build and save daily snapshot
      ├─ Final sidecar flush (run_once)
      └─ Stop background tasks
  → engine.stop()
  → OMS.stop()
```

**What runs automatically**:

| Feature | Trigger | Data |
|---|---|---|
| Market snapshots | Every 60s (configurable) | `snapshots/snapshots_YYYY-MM-DD.jsonl` |
| Risk denial → missed opportunity | OMS EventBus `RISK_DENIAL` event | `missed/missed_YYYY-MM-DD.jsonl` |
| Sidecar forwarding | Background thread (60s poll) | Sends to relay when configured |
| Daily snapshot | On graceful shutdown | `daily/daily_YYYY-MM-DD.json` |

**What is wired into engine fill handlers**:

| Feature | Helix | NQDTC | Vdubus |
|---|---|---|---|
| `log_entry()` on fill | `_handle_entry_fill` | `_on_fill` (working order branch) | `_on_fill` (working entry branch) |
| `log_exit()` on stop | `_handle_stop_fill` | `_on_fill` (stop branch) | `_on_stop_fill` |
| `log_exit()` on flatten | `_reconcile_exit_fill` | `_flatten` | `_flatten_position` |

Each engine receives the `InstrumentationManager` via `instrumentation=` constructor param,
passed from `main.py`. All calls are wrapped in try/except — never block trading logic.

**Strategy main.py changes** (identical pattern in all three):

```python
# After OMS start
instr = None
try:
    from instrumentation.src.bootstrap import InstrumentationManager
    instr = InstrumentationManager(oms, STRATEGY_ID, strategy_type="<type>")
    await instr.start()
except Exception as e:
    logger.warning("Instrumentation init failed (non-fatal): %s", e)

# Before engine stop (shutdown section)
if instr:
    try:
        await instr.stop()
    except Exception as e:
        logger.warning("Instrumentation shutdown error: %s", e)
```

| Strategy | `strategy_type` | Modified file |
|---|---|---|
| Helix | `"helix"` | `strategy/main.py` |
| NQDTC | `"nqdtc"` | `strategy_2/main.py` |
| Vdubus | `"vdubus"` | `strategy_3/main.py` |

**Engine-level missed opportunity hooks**:

Each engine has a `_log_missed()` helper that calls `MissedOpportunityLogger.log_missed()` with
a guard (`if not self._instr`) and try/except. Calls are inserted at block points where a
concrete signal exists but is suppressed by engine logic.

| Strategy | `blocked_by` values | Method |
|---|---|---|
| Helix | `max_concurrent`, `short_min_score`, `ETH_QUALITY_AM_short`, `duplicate_position`, `gate_<reason>`, `drawdown_throttle`, `sizing_zero` | `_detect_and_arm` |
| NQDTC | `regime_hard_block`, `C_CONT_DISABLED`, `C_CONT_MAX_FILLS`, `C_CONT_MFE_GATE`, `C_CONT_ALIGNED_BLOCK`, `C_STD_NEUTRAL_LOW_DISP`, `MIN_STOP_DISTANCE`, `BLOCK_06_ET`, `BLOCK_12_ET` | `_evaluate_entries`, `_on_fill` |
| Vdubus | `OPPOSITE_POSITION`, `PYRAMID_NOT_ELIGIBLE`, `viability_<reason>`, `risk_gate_<reason>`, `WORKING_ORDER_EXISTS` | `_evaluate_direction`, `_submit_entry` |

All missed opportunity events write to `missed/missed_YYYY-MM-DD.jsonl` via the same
`MissedOpportunityLogger` that handles OMS-level risk denials.

### 9.9 Tests

94 tests across 9 test files in `instrumentation/tests/`:

```bash
PYTHONPATH="$(pwd):$PYTHONPATH" pytest instrumentation/tests/ -v
```

Covers: event ID determinism, fault tolerance, PnL computation, process scoring taxonomy,
regime classification, sidecar watermarks/signing, and a full lifecycle integration test.
