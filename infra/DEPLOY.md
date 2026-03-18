# Deploying momentum_trader (VPS 2)

Deploy the 3 momentum strategy containers (Helix, NQDTC, Vdubus) on a dedicated VPS, connecting to shared infrastructure (PostgreSQL, dashboard, IB Gateway, relay) on VPS 1 via WireGuard tunnel.

## Architecture

```
VPS 1 — Infra (swing_trader)              VPS 2 — Strategies (momentum_trader)
  10.0.0.1                                   10.0.0.2
┌──────────────────────────────┐            ┌──────────────────────────────┐
│  IB Gateway       :4002      │            │  trading_helix               │
│  PostgreSQL       :5432      │◄───────────┤  trading_nqdtc               │
│  Dashboard        :3000      │  WireGuard │  trading_vdubus              │
│  Relay            :8001      │   tunnel   │                              │
└──────────────────────────────┘            └──────────────────────────────┘
```

Containers use `network_mode: host` — they share VPS 2's network stack directly and reach VPS 1 services at `10.0.0.1` via the WireGuard tunnel. No Docker bridge networking, no `trading_net`, no `extra_hosts` needed.

## Prerequisites

- VPS 1 running the swing_trader stack (Postgres, dashboard, IB Gateway, relay)
- WireGuard tunnel established between VPS 1 (`10.0.0.1`) and VPS 2 (`10.0.0.2`)
- VPS 1 services listening on tunnel interface (see `docs/implementation.md` §6)
- `momentum_trader` registered in VPS 1's relay secrets (see Step 2 below)
- Docker and Docker Compose installed on VPS 2

---

## Step 1 — Clone the Repository

```bash
sudo mkdir -p /opt/trading
sudo chown $USER:$USER /opt/trading
cd /opt/trading
git clone <YOUR_REPO_URL> momentum_trader
cd momentum_trader
```

## Step 2 — Register HMAC Secret with Relay (VPS 1)

Generate a shared secret for instrumentation forwarding:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

On **VPS 1**, add `momentum_trader` to the relay's secrets file:

```bash
# Edit /opt/trading-relay/secrets.json on VPS 1
# Add alongside existing entries:
{
    "swing_trader": "<existing>",
    "stock_trader": "<existing>",
    "momentum_trader": "<secret-from-above>"
}
```

Restart the relay on VPS 1:

```bash
sudo systemctl restart trading-relay
```

## Step 3 — Configure Environment (VPS 2)

```bash
cp .env.example .env
chmod 600 .env
nano .env
```

Key values:

| Variable | Value | Notes |
|----------|-------|-------|
| `ALGO_TRADER_ENV` | `paper` | Start with paper, switch to `live` later |
| `DB_HOST` | `10.0.0.1` | VPS 1 via WireGuard |
| `DB_PASSWORD` | (match VPS 1) | Same as swing_trader's `trading_writer` password |
| `IB_HOST` | `10.0.0.1` | VPS 1 via WireGuard |
| `IB_PORT` | `4002` | Paper: 4002, Live: 4001 |
| `IB_ACCOUNT_ID` | `DU1234567` | Your IBKR account |
| `TRADING_SYMBOL` | `MNQ` | Micro E-mini Nasdaq-100 |
| `INSTRUMENTATION_HMAC_SECRET` | (from Step 2) | Must match relay's secrets.json |
| `INSTRUMENTATION_RELAY_URL` | `http://10.0.0.1:8001/events` | Relay on VPS 1 |

## Step 4 — Build and Start

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
docker compose -f infra/docker-compose.yml --profile helix up -d               # Helix only
docker compose -f infra/docker-compose.yml --profile helix --profile nqdtc up -d  # Helix + NQDTC
```

## Step 5 — Verify

Run the verification script:

```bash
bash infra/scripts/verify_deployment.sh
```

Or verify manually:

```bash
# Check containers are running
docker compose -f infra/docker-compose.yml \
  --profile helix --profile nqdtc --profile vdubus ps

# Check strategy logs (look for: DB connected, IB connected, engine started)
docker logs trading_helix --tail 20
docker logs trading_nqdtc --tail 20
docker logs trading_vdubus --tail 20

# Verify cross-VPS connectivity
ping -c 1 10.0.0.1                                                    # Tunnel
python3 -c "import socket; s=socket.socket(); s.connect(('10.0.0.1',5432)); print('DB OK'); s.close()"
python3 -c "import socket; s=socket.socket(); s.connect(('10.0.0.1',4002)); print('IB OK'); s.close()"
curl -sf http://10.0.0.1:8001/health && echo "Relay OK"
```

Check the dashboard on VPS 1 — all three momentum strategies should appear within 1 minute.

## Step 6 — Set Up Tunnel Monitoring (VPS 2)

```bash
chmod +x infra/scripts/check_tunnel.sh

# Run every 5 minutes
(crontab -l 2>/dev/null; echo "*/5 * * * * /opt/trading/momentum_trader/infra/scripts/check_tunnel.sh") | crontab -
```

---

## Common Operations

| Action | Command |
|--------|---------|
| Restart a strategy | `docker compose -f infra/docker-compose.yml --profile helix restart helix` |
| Stop all | `docker compose -f infra/docker-compose.yml --profile helix --profile nqdtc --profile vdubus down` |
| Start all | `docker compose -f infra/docker-compose.yml --profile helix --profile nqdtc --profile vdubus up -d` |
| View logs | `docker compose -f infra/docker-compose.yml --profile helix --profile nqdtc --profile vdubus logs -f --tail=100` |
| Rebuild | `git pull && docker compose -f infra/docker-compose.yml --profile helix --profile nqdtc --profile vdubus build && docker compose -f infra/docker-compose.yml --profile helix --profile nqdtc --profile vdubus up -d` |
| Check tunnel | `sudo wg show && ping -c 1 10.0.0.1` |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Can't reach VPS 1 (`10.0.0.1`) | Check WireGuard: `sudo wg show`. Restart: `sudo systemctl restart wg-quick@wg0` |
| IB Gateway connection refused | Verify IB Gateway is running on VPS 1: `ssh VPS1 'ss -tlnp \| grep 4002'`. Check VPS 1 firewall allows `10.0.0.0/24` on port 4002. |
| PostgreSQL connection refused | Verify postgres listens on tunnel: `ssh VPS1 'ss -tlnp \| grep 5432'` (must show `10.0.0.1:5432` or `0.0.0.0:5432`). Check `pg_hba.conf` allows `10.0.0.0/24`. |
| IB client ID conflict | Each strategy needs a unique ID. ETF strategies: 1-10, momentum: 11-13. Check for collisions with `ss -tnp \| grep 4002` on VPS 1. |
| Container exits immediately | Check exit code: `docker inspect trading_helix --format='{{.State.ExitCode}}'`. 0=clean shutdown, 1=app error, 137=OOM, 139=segfault. Check logs. |
| Relay forwarding fails | Verify HMAC secret matches VPS 1's `secrets.json`. Test: `curl -sf http://10.0.0.1:8001/health`. |
| Container won't connect after IB Gateway restart | IB Gateway resets ~midnight ET. Containers have `restart: unless-stopped` and will reconnect automatically. If stuck, restart: `docker restart trading_helix`. |

---

## Shared VPS 1 Maintenance (managed by swing_trader)

These cron jobs run on VPS 1 and benefit momentum_trader:

| Job | Schedule | What it does |
|-----|----------|--------------|
| DB backup | 01:00 UTC daily | `pg_dump` → `/opt/trading/backups/`, 30-day retention |
| Data retention | 00:05 UTC daily | Deletes old `order_events`, resets daily counters, `VACUUM ANALYZE` |
| Log rotation | Daily | `/etc/logrotate.d/trading`, 30 days, compressed |
| Relay purge | Daily | Purges acked events from relay SQLite buffer |
| IB Gateway reset | ~00:00 ET | IBC `AutoRestartTime=00:00` handles IBKR's daily disconnect |

---

## Key Files

| File | Purpose |
|------|---------|
| `.env` | All environment variables (secrets, connection strings) |
| `Dockerfile` | Shared image for all 3 strategies |
| `infra/docker-compose.yml` | Strategy container orchestration |
| `infra/scripts/check_tunnel.sh` | WireGuard tunnel health monitor (cron) |
| `infra/scripts/verify_deployment.sh` | Post-deploy smoke test |
| `config/contracts.yaml` | Futures contract specs |
| `config/ibkr_profiles.yaml` | IBKR connection profiles |
| `docs/implementation.md` | Full implementation plan with WireGuard setup |
