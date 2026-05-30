# market_gateway

FastAPI service that exposes **market data** and **trading-related** APIs to any client on your network (GUIs, services, notebooks, etc.). External market access for those clients is intended to flow through this gateway (see [docs/market_gateway_spec.md](docs/market_gateway_spec.md)).

**Repository layout:** this repo is a **standalone sibling** of other projects (for example Backtester4 under `projects/`). Nothing here needs to be vendored inside another repository.

**Consumers:** the gateway is meant for **several programs**, not a single owner. The **first user** is a **shadow-trading** service: paper execution of Backtester4-derived strategies against **live Schwab quotes** (and related gateway APIs). Backtester4 itself **may or may not** call the gateway later; either way, the API stays the stable boundary for tools that need market data or (eventually) broker actions.

**Historical database:** optional PostgreSQL/Timescale (see **Optional: Timescale / PostgreSQL** below). The reader uses the same canonical 1m table names as Backtester4 (`stocks_1_minute`, `options_1_minute`) when connected.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Redis (local only recommended; default `redis://localhost:6379/0`)

## Setup

```bash
cd market_gateway
cp .env.example .env
# Edit .env — set MARKET_GATEWAY_API_KEY and PostgreSQL (DATABASE_URL or POSTGRES_*)
uv sync --extra dev
```

### Redis on Ubuntu / WSL

```bash
sudo apt update && sudo apt install -y redis-server
sudo service redis-server start
redis-cli ping   # expect PONG
```

### Optional: Timescale / PostgreSQL (Phase 2)

Use **either**:

1. **`DATABASE_URL`** — single URL (wins if non-empty), e.g.  
   `postgresql+asyncpg://market_user:password@localhost:5432/marketdata`  
   Use this for passwordless / trust URLs too (`postgresql+asyncpg://market_user@localhost:5432/marketdata`).

2. **Discrete variables** (same idea as Backtester4’s `dbname` / `user` / `password` / `host` / `port`) — set when `DATABASE_URL` is empty:  
   `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_DBNAME`, and a **non-empty** `POSTGRES_PASSWORD` to opt in.

Canonical intraday tables:

| Asset   | Timeframe | Table / behavior    | Key / notes    |
|---------|-----------|---------------------|----------------|
| Equity  | `1m`      | `stocks_1_minute`   | `symbol`, `time` |
| Equity  | `1d`      | **`stocks_1_day`** (`date` + OHLCV; nightly load) | `symbol`, `date` |
| Option  | `1m`      | `options_1_minute`  | `option_symbol`, `time` |

Other equity timeframes return an empty historical series until added.

**Stale DB + daily charts:** with **`timeframe=1d`**, **`mode=canonical_plus_live`** (or **`best_available`**), and **Postgres** configured, daily bars through the **last `date` in `stocks_1_day`** are canonical. If **Redis** has no newer `1d` live rows, the **rest of the window** is filled with deterministic **`source=sample`** daily bars until your nightly job loads new days. Each row’s `date` is returned as a bar timestamp at **UTC midnight** on that calendar date.

## Run the API

Default HTTP port is **`8020`** (set `MARKET_GATEWAY_PORT` in `.env` to change it).

**Helper script** (loads `MARKET_GATEWAY_PORT` and `MARKET_GATEWAY_API_KEY` from `.env` for curls in `status`):

```bash
bash scripts/gateway.sh restart   # stop listener on that port, then start uvicorn (--reload)
bash scripts/gateway.sh stop
bash scripts/gateway.sh start       # foreground; Ctrl+C to stop
bash scripts/gateway.sh status      # curl /health and /status
bash scripts/gateway.sh redis       # redis-cli ping
```

Manual:

```bash
uv run uvicorn market_gateway.app.main:create_app --factory --host 0.0.0.0 --port "${MARKET_GATEWAY_PORT:-8020}" --reload
```

### Run as a systemd service (Linux)

See [`deploy/systemd/market_gateway.service.example`](deploy/systemd/market_gateway.service.example): set `User`, paths, and match **`ExecStart --port`** to `MARKET_GATEWAY_PORT` in your `.env`. Use **`--reload` only in development**; production unit should omit it.

## Tests

```bash
uv run pytest
```

## Example curl

```bash
export MARKET_GATEWAY_API_KEY="$(grep '^MARKET_GATEWAY_API_KEY=' .env | cut -d= -f2-)"
export MARKET_GATEWAY_PORT="${MARKET_GATEWAY_PORT:-8020}"

curl -s "http://localhost:${MARKET_GATEWAY_PORT}/health"

curl -s -H "X-API-Key: $MARKET_GATEWAY_API_KEY" \
  "http://localhost:${MARKET_GATEWAY_PORT}/quotes?symbols=SPY,AAPL,NVDA"

# SPY daily bars: `stocks_1_day` through last loaded `date`, then sample tail if Redis has no newer 1d rows
curl -s -H "X-API-Key: $MARKET_GATEWAY_API_KEY" \
  "http://localhost:${MARKET_GATEWAY_PORT}/history/SPY?timeframe=1d&lookback_days=14&mode=canonical_plus_live"
```

## Tailscale

You may expose only the FastAPI port on the tailnet. **Do not rely on Tailscale alone for authorization** — every protected route also requires `X-API-Key` (see spec).

## Security (summary)

- Redis should bind to localhost; do not expose it on the tailnet.
- Do not commit `.env`, Schwab tokens, or credentials.
- Real broker order submission is **not** implemented; order routes are paper/stub through Phase 5+.

## Phase roadmap

| Phase | Scope |
|-------|--------|
| 1 | FastAPI skeleton, Redis, stubs, SSE, tests (current baseline) |
| 2 | Timescale historical reads + resolver modes (partially implemented via `DATABASE_URL`) |
| 3 | Schwab read-only live data |
| 4 | Streaming + shadow testing |
| 5 | Paper trading lifecycle |
| 6 | Real trading (explicit gates) |
