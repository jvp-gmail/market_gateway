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

### Phase 3: Schwab live read-only (quotes, chains, price history)

1. Create a Schwab developer app and note **app key**, **secret**, and **callback URL** (must match the app; `https://127.0.0.1:8182` is typical).
2. Generate a **token JSON** on a trusted machine (do not commit it), e.g.  
   `schwab-generate-token.py --token_file /path/schwab_tokens.json --api_key ... --app_secret ... --callback_url https://127.0.0.1:8182`
3. In `.env`: `ENABLE_SCHWAB_LIVE_DATA=true`, `SCHWAB_CLIENT_ID`, `SCHWAB_CLIENT_SECRET`, `SCHWAB_TOKEN_FILE=/path/schwab_tokens.json`.  
   Optional: `SCHWAB_MIN_REQUEST_INTERVAL_SECONDS` (default `0.12`) to space HTTP calls.

If live mode is on but credentials or the token file are missing, the gateway **falls back to the stub client** and logs a warning. **`GET /status`** includes `schwab_backend`: `live` or `stub`.

With live Schwab, **`/quotes`**, **`/options/*`**, and the **live segment** of **`/history`** (when Redis has no bars yet) use the Trader API; bars are cached in Redis with the same TTLs as before. **Orders and positions** remain paper/stub for Phase 3 (no real broker orders).

**Stale DB + daily charts:** with **`timeframe=1d`**, **`mode=canonical_plus_live`** (or **`best_available`**), and **Postgres** configured, daily bars through the **last `date` in `stocks_1_day`** are canonical. If **Redis** has no newer `1d` rows, the gateway tries **Schwab price history** for the gap. With **live Schwab** (`GET /status` → `schwab_backend: live`), if Schwab still returns no candles, the tail is **not** filled with deterministic **`source=sample`** bars (you see a real gap and a log warning). With the **stub** client or live data disabled, the tail still uses **`source=sample`** until your nightly job loads new days. Each row’s `date` is returned as a bar timestamp at **UTC midnight** on that calendar date.

**Price history empty but quotes work:** Schwab can return `{"empty": true, "candles": []}` when the developer app lacks **Market Data** access for historical bars, or when requested dates are invalid for the account. Confirm entitlements in the Schwab developer portal and that canonical dates are not ahead of available market history. For **daily** bars the gateway uses **`get_price_history_every_day`** with **America/New_York** calendar bounds (same pattern as a working batch job: `datetime.combine(date, min/max, TZ_ET)`), not only unbounded period queries.

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

# Option quote: gateway id `ROOT_YYYYMMDD{C|P}strike8` is normalized to Schwab OSI (6-char root + spaces)
curl -s -H "X-API-Key: $MARKET_GATEWAY_API_KEY" \
  "http://localhost:${MARKET_GATEWAY_PORT}/options/quotes?symbols=SPY_20260601C00756000"
# SPY daily bars: canonical through last `stocks_1_day` date, then Schwab (live) or sample tail (stub / live off)
curl -s -H "X-API-Key: $MARKET_GATEWAY_API_KEY" \
  "http://localhost:${MARKET_GATEWAY_PORT}/history/SPY?timeframe=1d&lookback_days=14&mode=canonical_plus_live"
```

## Tailscale

You may expose only the FastAPI port on the tailnet. **Do not rely on Tailscale alone for authorization** — every protected route also requires `X-API-Key` (see spec).

## Security (summary)

- Redis should bind to localhost; do not expose it on the tailnet.
- Do not commit `.env`, Schwab tokens, or credentials.
- Real broker order submission is **not** implemented; order routes are paper/stub through Phase 5+.

## Phase 4 (streaming): part 1

Canonical stream event types (`StreamEventType` in `app/core/models.py`), publishers in `app/services/quote_stream_publisher.py`, and an optional **stub loop** for SSE testing without a Schwab WebSocket.

In `.env`, set:

```bash
ENABLE_QUOTE_STREAM_STUB=true
QUOTE_STREAM_STUB_SYMBOLS=/MES,/ES
QUOTE_STREAM_STUB_INTERVAL_SECONDS=5
```

Then stream events (symbols are synthetic quotes only—use whatever tickers you want to see in the payload):

```bash
curl -N -H "X-API-Key: $MARKET_GATEWAY_API_KEY" \
  "http://localhost:${MARKET_GATEWAY_PORT:-8020}/events/stream"
```

Look for `event_type` `equity_quote` and `payload.quote`.

**Part 2 (live Schwab WebSocket):** with `ENABLE_SCHWAB_LIVE_DATA` and a valid token, set `ENABLE_SCHWAB_STREAMING=true` and `SCHWAB_STREAM_EQUITY_SYMBOLS=SPY,QQQ,/ES` (comma-separated). **Futures** must use Schwab’s slash symbols (e.g. **`/ES`**, **`/MES`**) so they go to `LEVELONE_FUTURES`; plain tickers use `LEVELONE_EQUITIES`. **Indexes and NYSE internals** use Schwab’s **`$`-prefixed** keys on that same equities service—for example **`$SPX`** and **`$TICK`** in `SCHWAB_STREAM_EQUITY_SYMBOLS` or in `PUT /events/stream/symbols` → `equities` (not bare `SPX` / `TICK`). **Options:** set `SCHWAB_STREAM_OPTIONS_SYMBOLS` to a comma list of Schwab OSI strings or gateway underscore ids (same as `/options/quotes`); those contracts stream on `LEVELONE_OPTIONS` and emit **`option_quote`** + `OptionContractQuote` (`source` `live_schwab_stream`). Equities and futures still emit **`equity_quote`** + `QuoteSnapshot`. Set **`SCHWAB_STREAMING_DEBUG=true`** temporarily to log raw WebSocket JSON from schwab-py (`Send` / `Receive` lines); turn it off afterward. See `docs/phase4_part2_schwab_stream.md`.

**Session resubscribe (same WebSocket):** `PUT /events/stream/symbols` with JSON `{"equities":["SPY"],"futures":["/ES"],"options":["SPY   260601C00756000"]}` (any subset; **at least one** of the three lists non-empty) and `X-API-Key` replaces Schwab `LEVELONE_*` keys without reconnecting. Returns **503** if streaming is not active.

If you only see SSE **idle** heartbeats while the Schwab stream is connected: the gateway registers **schwab-py handlers before SUBS** (per library docs, early DATA frames are dropped if no handler exists). If it still idles, enable `logging.getLogger("schwab.streaming").setLevel(logging.DEBUG)` temporarily to inspect raw traffic. Also check gateway logs at **INFO** — you should see `Starting Schwab quote WebSocket` and `Schwab quote stream background task started`. If you see **`ENABLE_SCHWAB_STREAMING is true but Schwab client has no http_client`**, the app fell back to the **stub** Schwab client (fix `ENABLE_SCHWAB_LIVE_DATA`, `SCHWAB_*`, and `SCHWAB_TOKEN_FILE`). If logs show **`RESPONSE frame while reading (skipping)`** in a tight loop, say so (we can tune that path).

Application log lines are prefixed like `INFO:market_gateway.app.main:...` (the `market_gateway` logger is configured so **INFO** is visible even when uvicorn’s `--log-level info` only affects its own loggers).

If `curl` exits with **(18) transfer closed with outstanding read data**, the SSE generator likely hit a Redis error (common: **`EVENT_STREAM_NAME` points at a key that is not a stream** — e.g. a string key from another app). Pick a dedicated name (default `stream:events`) or `DEL` the conflicting key, then restart the gateway. With the current code you should instead receive a **`stream_error`** SSE event describing the failure.

If you see repeating **`stream_error`** / **`TimeoutError`** / “Timeout reading from localhost:6379” every ~5–6s while idle on **`/events/stream`**, that is usually **redis-py’s default 5s `socket_timeout`** racing with **`XREAD BLOCK`** (`EVENT_BUS_XREAD_BLOCK_MS`, default 5000 ms). The gateway now applies **`socket_timeout=None`** to the Redis pool by default (leave **`REDIS_SOCKET_TIMEOUT_SECONDS`** unset), **after** parsing `REDIS_URL`, so it overrides **`?socket_timeout=`** in the URL too. If you set a read timeout, make it **larger than the block window** (e.g. 65 when block is 5000 ms).

## Phase roadmap

| Phase | Scope |
|-------|--------|
| 1 | FastAPI skeleton, Redis, stubs, SSE, tests (current baseline) |
| 2 | Timescale historical reads + resolver modes (`DATABASE_URL` / `POSTGRES_*`) |
| 3 | Schwab read-only live data ([schwab-py](https://github.com/alexgolec/schwab-py); token file + `ENABLE_SCHWAB_LIVE_DATA`) |
| 4 | Streaming + shadow testing |
| 5 | Paper trading lifecycle |
| 6 | Real trading (explicit gates) |
