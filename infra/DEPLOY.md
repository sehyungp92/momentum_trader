# Deploying momentum_trader on an Existing VPS

Deploy the 3 momentum strategy containers (Helix, NQDTC, Vdubus) alongside the existing shared infrastructure (PostgreSQL, dashboard, IB Gateway) managed by the swing_trader repo.

## Architecture

```
Ubuntu VPS (existing)
├── IB Gateway (systemd, port 4002)       ← managed by swing_trader
├── Docker
│   ├── trading_postgres (5432)           ← managed by swing_trader
│   ├── trading_dashboard (3000)          ← managed by swing_trader
│   └── trading_net network               ← shared
│
└── momentum_trader containers (this repo)
    ├── trading_helix  ──► IB Gateway:4002, Postgres
    ├── trading_nqdtc  ──► IB Gateway:4002, Postgres
    └── trading_vdubus ──► IB Gateway:4002, Postgres
```

## Prerequisites

- VPS already running the swing_trader stack (Postgres, dashboard, IB Gateway)
- `trading_net` Docker network exists (`docker network ls | grep trading_net`)
- Docker and Docker Compose installed

---

## Step 1 — Clone the Repository

```bash
cd /opt/trading
git clone <YOUR_REPO_URL> momentum_trader
cd momentum_trader
```

## Step 2 — Configure Environment

```bash
cp .env.example .env
nano .env
```

Key values:

| Variable | Value | Notes |
|----------|-------|-------|
| `SWING_TRADER_ENV` | `paper` or `live` | Trading mode |
| `IB_ACCOUNT_ID` | `DU1234567` | Your IBKR account |
| `IB_HOST` | `host.docker.internal` | Reaches host IB Gateway from container |
| `IB_PORT` | `4002` | Paper: 4002, Live: 4001 |
| `IB_CLIENT_ID_HELIX` | `11` | Unique per strategy |
| `IB_CLIENT_ID_NQDTC` | `12` | Unique per strategy |
| `IB_CLIENT_ID_VDUBUS` | `13` | Unique per strategy |
| `POSTGRES_HOST` | `trading_postgres` | Container name on trading_net |
| `POSTGRES_PORT` | `5432` | |
| `POSTGRES_PASSWORD` | (match swing_trader) | Same DB cluster |

```bash
chmod 600 .env
```

## Step 3 — Build and Start

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
docker compose -f infra/docker-compose.yml --profile helix up -d          # Helix only
docker compose -f infra/docker-compose.yml --profile helix --profile nqdtc up -d  # Helix + NQDTC
```

## Step 4 — Verify

### Check containers are running
```bash
docker compose -f infra/docker-compose.yml --profile helix --profile nqdtc --profile vdubus ps
```

### Check strategy logs
```bash
docker compose -f infra/docker-compose.yml --profile helix logs -f helix
docker compose -f infra/docker-compose.yml --profile nqdtc logs -f nqdtc
docker compose -f infra/docker-compose.yml --profile vdubus logs -f vdubus
```

You should see: database connection, IB Gateway connection, strategy engine start, heartbeat messages.

### Check IB Gateway connectivity from container
```bash
docker exec -it trading_helix python -c \
  "import socket; s = socket.socket(); s.connect(('host.docker.internal', 4002)); print('Connected!'); s.close()"
```

### Check heartbeats in shared dashboard
Open the dashboard — strategy heartbeats should appear within 1 minute.

---

## Common Operations

| Action | Command |
|--------|---------|
| Restart a strategy | `docker compose -f infra/docker-compose.yml --profile helix restart helix` |
| Stop all strategies | `docker compose -f infra/docker-compose.yml --profile helix --profile nqdtc --profile vdubus down` |
| Start all strategies | `docker compose -f infra/docker-compose.yml --profile helix --profile nqdtc --profile vdubus up -d` |
| View all logs | `docker compose -f infra/docker-compose.yml --profile helix --profile nqdtc --profile vdubus logs -f --tail=100` |
| Rebuild after code changes | `git pull && docker compose -f infra/docker-compose.yml --profile helix --profile nqdtc --profile vdubus build && docker compose -f infra/docker-compose.yml --profile helix --profile nqdtc --profile vdubus up -d` |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Strategy can't connect to IB Gateway | Check `ss -tlnp \| grep 4002` on host. Verify IB Gateway systemd service is running. |
| Strategy can't connect to Postgres | Verify `trading_net` network exists and swing_trader postgres is running. Check DB credentials in `.env`. |
| Container exits immediately | Check logs: `docker logs trading_helix`. Common cause: missing `.env` or wrong IB client ID (conflict). |
| IB client ID conflict | Each strategy needs a unique client ID. Ensure IDs don't overlap with swing_trader strategies. |

---

## Key Files

| File | Purpose |
|------|---------|
| `.env` | All environment variables |
| `Dockerfile` | Shared image for all 3 strategies |
| `infra/docker-compose.yml` | Strategy container orchestration |
| `config/contracts.yaml` | Futures contract specs |
| `config/ibkr_profiles.yaml` | IBKR connection profiles |
