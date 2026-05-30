# Market Gateway Specification

## Purpose

Build a FastAPI-based service named `market_gateway` for Backtester4 and other programs. The service is the single external access point for market-related activity:

- live equity quotes
- live option quotes
- option chains
- current-day partial intraday bars
- canonical historical equity bars from TimescaleDB
- canonical historical option bars from TimescaleDB
- Schwab API access
- future trading/order submission
- strategy/shadow-test control
- live event streaming to GUIs and remote tools

The guiding rule is:

> All market data and trading requests from outside the Backtester4 process boundary should flow through `market_gateway`.

The gateway should not replace the existing Backtester4 database or historical loaders. It should sit above them and provide a clean resolver layer that can combine canonical historical data with live/session data when requested.  This service will be used simultaneously by other programs to access historical and live market data and to place orders and manage positions at Shwab and eventually other brokerages such as Tradier.

---

## System Context

Backtester4 already has a historical stock and option system. It stores and caches historical data in a TimescaleDB/PostgreSQL database.

Existing historical data characteristics:

- Equity historical data is updated nightly.
- Equity bars in the canonical historical database are full-day, finalized bars.
- Option historical data is currently sourced from Polygon or similar providers.
- Historical option data contains OHLC data for the whole day for every downloaded option contract.
- Existing historical tables should remain canonical for backtesting and research.

New Schwab-sourced data characteristics:

- Live equity quotes include bid/ask/last/mark data.
- Live option quotes include bid/ask/last/mark and, where available, greeks and implied volatility.
- Current-day historical bars from Schwab may be partial and evolving.
- Schwab data should not be written directly into canonical historical tables.
- Schwab data should be cached separately and optionally persisted into separate live/session tables.

Important architectural distinction:

```text
Canonical historical data:
    Source: existing Backtester4 loaders / Polygon / nightly process
    Shape: OHLCV bars
    Completeness: finalized, full-day
    Storage: existing TimescaleDB historical tables
    Use: formal backtesting, research, repeatable results

Live/session data:
    Source: Schwab
    Shape: quotes, option chains, current-day partial bars
    Completeness: partial, evolving, session-specific
    Storage: Redis initially; optional separate live_* TimescaleDB tables later
    Use: GUI display, shadow testing, live monitoring, future trading
```

---

## Project Name

Use the project/package/service name:

```text
market_gateway
```

Suggested repository placement:

```text
Backtester4/
    market_gateway/
        app/
        tests/
        README.md
        pyproject.toml
```

or, if the existing Backtester4 repo prefers top-level app modules:

```text
Backtester4/
    gateway/
        market_gateway/
```

The coding agent should inspect the existing repository layout and place the package where it best fits the current Backtester4 architecture.

---

## High-Level Architecture

```text
Remote clients / GUI / notebooks / scripts / remote servers
        |
        | HTTPS or HTTP over LAN/Tailscale
        v
+------------------------------+
|        market_gateway        |
|          FastAPI app         |
+------------------------------+
        |
        +-- API key auth
        +-- REST endpoints
        +-- SSE event stream
        +-- optional future WebSocket endpoint
        |
        +-- Schwab adapter
        |       - OAuth/token ownership
        |       - REST market data
        |       - streaming market data later
        |       - future order submission
        |
        +-- Redis live cache
        |       - latest quotes
        |       - latest option quotes
        |       - option chain snapshots
        |       - current-day partial bars
        |       - event streams
        |
        +-- TimescaleDB historical store
        |       - existing canonical stock bars
        |       - existing canonical option bars
        |
        +-- DataResolver
                - source selection
                - historical/live stitching
                - source precedence
                - normalized responses
```

External clients should talk only to FastAPI. Redis, TimescaleDB, Schwab token storage, and internal strategy processes should not be directly exposed to remote machines.

---

## Core Design Rules

1. `market_gateway` is the external boundary for market activity.
2. Existing historical database tables remain canonical.
3. Schwab live/session data must be cached separately.
4. Schwab partial/current-day data must not contaminate canonical historical tables.
5. Only the resolver layer is allowed to combine historical and live data.
6. Strategy code, GUI code, notebooks, and scripts should not manually stitch TimescaleDB + Redis + Schwab data.
7. Future real trading must be disabled by default and protected by multiple safety gates.
8. API key authentication should be required for all endpoints except `/health`.
9. Redis should initially bind locally only.
10. The gateway should be usable over Tailscale by exposing only the FastAPI port.

---

## Implementation Phases

The implementation should be staged. Do not try to build the full live-trading system at once.

## Phase 1: Skeleton, Read-Only Data, Redis Cache, Stubs

Goal: create a working FastAPI service with clean interfaces, Redis integration, deterministic sample Schwab responses, and tests.

Phase 1 should include:

- FastAPI app
- API key authentication
- configuration via environment variables
- Redis async client
- basic event bus using Redis Streams
- read-only market data routers
- Schwab client stubs returning deterministic sample data
- DataResolver interface
- historical store interface that can later connect to existing TimescaleDB code
- SSE endpoint for live events
- paper/stub-only order endpoints
- pytest tests
- README setup instructions

Phase 1 must not:

- submit real Schwab orders
- require real Schwab OAuth
- store secrets in the repo
- expose Redis over the network
- alter existing historical database schema unless explicitly approved
- write Schwab data into canonical historical tables

## Phase 2: Connect to Existing Backtester4 Historical Data

Goal: make the gateway resolve historical bars from the existing Backtester4 TimescaleDB database.

Phase 2 should include:

- inspect existing Backtester4 data access modules and schemas
- implement `HistoricalStore.get_equity_bars()`
- implement `HistoricalStore.get_option_bars()` if needed
- normalize timestamps and columns
- add data mode handling: `historical_only`, `live_only`, `canonical_plus_live`, `best_available`
- implement current-day stitching from Redis live bars + TimescaleDB canonical history
- add source labels to returned bars
- tests for source selection and stitching logic

## Phase 3: Schwab Read-Only Live Market Data

Goal: integrate real Schwab read-only market data.

Phase 3 should include:

- Schwab OAuth/token handling
- token storage outside the repo
- Schwab quote retrieval
- Schwab option chain retrieval
- Schwab option quote retrieval
- Schwab historical/current-day price history retrieval
- Redis caching with TTLs
- optional writing of live quote snapshots to separate live tables
- robust error handling and rate-limit protection

Phase 3 still must not submit real orders.

## Phase 4: Live Data Streaming and Shadow Testing Support

Goal: support forward shadow testing and GUI monitoring.

Phase 4 should include:

- Schwab streaming connection if available and suitable
- live equity quote updates
- live option quote updates
- current-day bar construction from quote/trade events or Schwab data
- strategy/shadow-test status endpoints
- Redis Streams for signals, fills/paper fills, risk events, and system events
- SSE stream to GUI clients
- reconnect/recovery logic

## Phase 5: Paper Trading Order Path

Goal: implement a complete paper order lifecycle before any live orders are enabled.

Phase 5 should include:

- order preview
- order submit in paper mode
- order lifecycle events
- paper fills
- active order tracking
- position simulation if not already present in Backtester4
- risk checks
- audit log

## Phase 6: Real Trading, Disabled by Default

Goal: enable real Schwab order submission only after the rest of the system is stable.

Real trading must require all of the following:

- `ENABLE_REAL_TRADING=true`
- Schwab OAuth configured
- explicit endpoint-level authorization
- order preview before submit
- risk checks pass
- complete audit logging
- clear response indicating live mode

Real order submission should not be implemented until specifically requested.

---

## Suggested Directory Structure

The coding agent may adapt this to the existing Backtester4 layout.

```text
market_gateway/
    pyproject.toml
    README.md
    .env.example

    app/
        __init__.py
        main.py
        config.py
        auth.py

        api/
            __init__.py
            health.py
            status.py
            quotes.py
            options.py
            history.py
            positions.py
            orders.py
            strategies.py
            events.py

        core/
            __init__.py
            redis_client.py
            event_bus.py
            models.py
            time_utils.py
            cache_keys.py

        services/
            __init__.py
            data_resolver.py
            historical_store.py
            live_cache.py
            quote_service.py
            option_chain_service.py
            option_quote_service.py
            history_service.py
            position_service.py
            order_service.py
            strategy_service.py

        schwab/
            __init__.py
            client.py
            auth.py
            models.py
            symbol_utils.py

    tests/
        test_health.py
        test_auth.py
        test_quotes.py
        test_options.py
        test_history.py
        test_data_resolver.py
        test_orders_safety.py
        test_cache_keys.py
```

---

## Configuration

Use environment variables. Include `.env.example` but do not commit real secrets.

Required/initial variables:

```bash
MARKET_GATEWAY_API_KEY=change-me
REDIS_URL=redis://localhost:6379/0
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/marketdata
ENABLE_SCHWAB_LIVE_DATA=false
ENABLE_REAL_TRADING=false
QUOTE_TTL_SECONDS=3
OPTION_QUOTE_TTL_SECONDS=3
OPTION_CHAIN_TTL_SECONDS=120
HISTORY_TTL_SECONDS=3600
EVENT_STREAM_NAME=stream:events
```

Future Schwab variables:

```bash
SCHWAB_CLIENT_ID=
SCHWAB_CLIENT_SECRET=
SCHWAB_REDIRECT_URI=
SCHWAB_TOKEN_FILE=/secure/path/outside/repo/schwab_tokens.json
```

Recommended config object:

```python
class Settings(BaseSettings):
    market_gateway_api_key: str
    redis_url: str = "redis://localhost:6379/0"
    database_url: str | None = None
    enable_schwab_live_data: bool = False
    enable_real_trading: bool = False
    quote_ttl_seconds: int = 3
    option_quote_ttl_seconds: int = 3
    option_chain_ttl_seconds: int = 120
    history_ttl_seconds: int = 3600
    event_stream_name: str = "stream:events"
```

---

## API Authentication

All endpoints except `/health` should require an API key.

Use header:

```text
X-API-Key: <key>
```

or:

```text
Authorization: Bearer <key>
```

Either is acceptable, but choose one and document it. The simplest first version is `X-API-Key`.

Do not rely solely on Tailscale for safety. Tailscale is the network boundary; the API key is the application boundary.

---

## API Endpoints

## Health and Status

```text
GET /health
GET /status
```

`/health` should not require auth and should return minimal liveness information.

Example:

```json
{
  "ok": true,
  "service": "market_gateway"
}
```

`/status` should require auth and return useful internal status:

```json
{
  "ok": true,
  "service": "market_gateway",
  "redis": "ok",
  "database": "ok_or_not_configured",
  "schwab_live_data_enabled": false,
  "real_trading_enabled": false
}
```

## Quotes

```text
GET /quotes?symbols=AAPL,NVDA,SPY
```

Returns latest equity quote snapshots.

Behavior:

1. Check Redis cache.
2. If live Schwab data enabled and cache miss/stale, fetch from Schwab.
3. If Schwab live data disabled, return deterministic sample data in Phase 1.
4. Store refreshed quote snapshots in Redis.

## Option Chains

```text
GET /options/chains?symbol=AAPL
GET /options/chains?symbol=AAPL&expiration=2026-06-19
GET /options/chains?symbol=AAPL&from_date=2026-06-01&to_date=2026-07-31
GET /options/chains?symbol=AAPL&strike_count=10
GET /options/chains?symbol=AAPL&contract_type=CALL
GET /options/chains?symbol=AAPL&contract_type=PUT
```

Parameters:

- `symbol`: required underlying symbol
- `contract_type`: `CALL`, `PUT`, or `ALL`, default `ALL`
- `expiration`: optional ISO date
- `from_date`: optional ISO date
- `to_date`: optional ISO date
- `strike_count`: optional integer
- `include_quotes`: optional boolean, default true

Behavior:

1. Build a stable cache key from all request parameters.
2. Check Redis cache.
3. If enabled and needed, fetch from Schwab.
4. Store the full chain response as a coherent snapshot.
5. Return normalized contract data.

## Option Quotes

```text
GET /options/quotes?symbols=AAPL_20260619C00200000,AAPL_20260619P00195000
```

The coding agent should inspect Schwab's actual option symbol format and Backtester4's existing option symbol conventions. Add conversion utilities if needed.

Behavior:

1. Check Redis cache per option symbol.
2. If enabled and needed, fetch missing/stale symbols from Schwab.
3. Return normalized bid/ask/mark/last and greeks where available.

## Historical / Bar Data

```text
GET /history/{symbol}?timeframe=1m&start=2026-05-01T13:30:00Z&end=2026-05-29T20:00:00Z&mode=historical_only
GET /history/{symbol}?timeframe=1m&lookback_days=30&mode=canonical_plus_live
GET /history/{symbol}?timeframe=1d&lookback_days=365&mode=historical_only
```

Preferred normalized parameters:

- `symbol`: path parameter
- `timeframe`: `1m`, `5m`, `15m`, `1h`, `1d`, etc.
- `start`: optional ISO datetime
- `end`: optional ISO datetime, default now
- `lookback_days`: optional integer if start omitted
- `mode`: data source mode, default `canonical_plus_live` for GUI-style requests

Supported data modes:

```text
historical_only:
    Use only finalized canonical TimescaleDB historical data.
    Suitable for formal backtesting and repeatable research.

live_only:
    Use only Schwab/Redis/live cache data.
    Suitable for current session monitoring and shadow testing.

canonical_plus_live:
    Use canonical history through the last finalized timestamp, then live cache for current session.
    Suitable for charts and indicators requiring lookback plus today's action.

best_available:
    Convenience mode. May use any available source.
    Good for display, but not recommended for formal backtests.
```

Example SPY request:

```text
GET /history/SPY?timeframe=1m&lookback_days=30&mode=canonical_plus_live
```

Expected resolver behavior:

```text
1. Determine requested time range.
2. Determine last finalized historical timestamp for SPY/timeframe.
3. Query TimescaleDB for canonical bars from start through finalized history.
4. Query Redis/live cache for current-day/session bars after the finalized point.
5. Normalize columns.
6. Concatenate.
7. Sort by timestamp.
8. Remove duplicates.
9. Add source labels.
```

Returned bars should optionally include `source`:

```json
{
  "symbol": "SPY",
  "timeframe": "1m",
  "mode": "canonical_plus_live",
  "bars": [
    {
      "timestamp": "2026-05-29T19:59:00Z",
      "open": 520.1,
      "high": 520.4,
      "low": 519.9,
      "close": 520.2,
      "volume": 123456,
      "source": "historical"
    },
    {
      "timestamp": "2026-05-30T13:30:00Z",
      "open": 521.0,
      "high": 521.5,
      "low": 520.8,
      "close": 521.2,
      "volume": 34567,
      "source": "live_schwab"
    }
  ]
}
```

## Positions

```text
GET /positions
```

Phase 1: return deterministic sample positions or empty list.

Future: fetch from Schwab account endpoint and/or internal paper account state.

## Orders

```text
GET /orders/open
POST /orders/preview
POST /orders/submit
POST /orders/cancel
```

Phase 1 and Phase 5 only: paper/stub behavior.

Safety requirements:

- `/orders/submit` must not submit real orders unless `ENABLE_REAL_TRADING=true`.
- `/orders/submit` should require a `preview_id` from `/orders/preview`.
- Every order preview and submit attempt should be logged to Redis Stream `stream:orders` or general `stream:events`.
- Live order support should not be implemented until explicitly requested.

## Strategies / Shadow Testing

```text
GET /strategies/status
POST /strategies/start
POST /strategies/stop
```

Phase 1: stub endpoints.

Future: integrate with existing Backtester4 strategy/shadow-test process management.

## Events

```text
GET /events/stream
GET /events/recent
```

`/events/stream` should use Server-Sent Events initially.

Event types may include:

```text
heartbeat
quote
option_quote
option_chain_snapshot
bar
signal
order_preview
order_submit
paper_fill
position_update
strategy_event
risk_event
error
```

---

## Data Models

Use Pydantic models for API boundaries.

## QuoteSnapshot

```python
class QuoteSnapshot(BaseModel):
    symbol: str
    event_ts: datetime | None = None
    received_ts: datetime
    bid: float | None = None
    ask: float | None = None
    bid_size: int | None = None
    ask_size: int | None = None
    last: float | None = None
    mark: float | None = None
    volume: int | None = None
    source: str = "schwab_or_sample"
    raw: dict[str, Any] | None = None
```

## OptionContractQuote

```python
class OptionContractQuote(BaseModel):
    option_symbol: str
    underlying_symbol: str | None = None
    expiration: date | None = None
    strike: float | None = None
    option_type: Literal["CALL", "PUT"] | None = None
    event_ts: datetime | None = None
    received_ts: datetime
    bid: float | None = None
    ask: float | None = None
    bid_size: int | None = None
    ask_size: int | None = None
    last: float | None = None
    mark: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    rho: float | None = None
    implied_volatility: float | None = None
    open_interest: int | None = None
    volume: int | None = None
    source: str = "schwab_or_sample"
    raw: dict[str, Any] | None = None
```

## OptionChainResponse

```python
class OptionChainResponse(BaseModel):
    symbol: str
    underlying_price: float | None = None
    requested_at: datetime
    received_ts: datetime
    source: str = "schwab_or_sample"
    contracts: list[OptionContractQuote]
```

## Bar

```python
class Bar(BaseModel):
    symbol: str
    timestamp: datetime
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None
    source: Literal["historical", "live_schwab", "sample", "derived"]
```

## HistoricalDataResponse

```python
class HistoricalDataResponse(BaseModel):
    symbol: str
    timeframe: str
    mode: str
    start: datetime | None = None
    end: datetime | None = None
    bars: list[Bar]
```

## GatewayEvent

```python
class GatewayEvent(BaseModel):
    event_type: str
    event_ts: datetime | None = None
    received_ts: datetime
    source: str
    payload: dict[str, Any]
```

---

## DataResolver

The `DataResolver` is a central piece. It prevents source-stitching logic from spreading across the app.

Suggested interface:

```python
class DataResolver:
    async def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
        lookback_days: int | None = None,
        mode: DataMode = DataMode.CANONICAL_PLUS_LIVE,
    ) -> HistoricalDataResponse:
        ...

    async def get_quote(self, symbol: str) -> QuoteSnapshot:
        ...

    async def get_option_quote(self, option_symbol: str) -> OptionContractQuote:
        ...

    async def get_option_chain(self, request: OptionChainRequest) -> OptionChainResponse:
        ...
```

Source precedence rules:

```text
1. In historical_only mode, use only canonical TimescaleDB data.
2. In live_only mode, use only Redis/live Schwab data.
3. In canonical_plus_live mode, use canonical history through the last finalized historical timestamp and live cache after that.
4. In best_available mode, use whatever source can satisfy the request, but include source labels.
5. Canonical historical data wins over live cache for completed periods.
6. Live cache only fills the gap after the last finalized historical timestamp unless explicitly requested.
```

The resolver should be heavily tested.

---

## Redis Key Design

Use stable cache key helper functions. Do not build keys ad hoc throughout the code.

Suggested keys:

```text
quote:{symbol}
option_quote:{option_symbol}
option_chain:{symbol}:{params_hash}
history_live:{symbol}:{timeframe}:{date}
positions
orders:open
strategy:{name}:state
stream:events
stream:orders
stream:signals
stream:system
```

Cache key examples:

```text
quote:SPY
option_quote:SPY_20260619C00520000
option_chain:SPY:7f38a9b1
history_live:SPY:1m:2026-05-30
```

Use a stable hash of normalized option-chain parameters:

```python
{
    "symbol": "SPY",
    "contract_type": "ALL",
    "expiration": "2026-06-19",
    "from_date": None,
    "to_date": None,
    "strike_count": 10,
    "include_quotes": True,
}
```

Recommended TTLs:

```text
Equity quotes:       1-5 seconds during market hours
Option quotes:       1-5 seconds during market hours
Option chains:       30-300 seconds
Current-day bars:    session/day TTL, or explicit expiry after reconciliation
Historical bars:     long TTL if cached, but prefer TimescaleDB source
```

---

## Optional Live Tables

Phase 1 can use Redis only. Later phases may persist Schwab live/session observations into separate TimescaleDB tables. Do not insert Schwab data into canonical historical tables.

Possible tables:

```sql
CREATE TABLE live_equity_quotes (
    ts timestamptz NOT NULL,
    received_ts timestamptz NOT NULL,
    symbol text NOT NULL,
    bid double precision,
    ask double precision,
    bid_size integer,
    ask_size integer,
    last double precision,
    mark double precision,
    volume bigint,
    source text NOT NULL DEFAULT 'schwab',
    raw jsonb,
    PRIMARY KEY (symbol, ts, received_ts)
);
```

```sql
CREATE TABLE live_option_quotes (
    ts timestamptz NOT NULL,
    received_ts timestamptz NOT NULL,
    option_symbol text NOT NULL,
    underlying_symbol text,
    expiration date,
    strike double precision,
    option_type text,
    bid double precision,
    ask double precision,
    bid_size integer,
    ask_size integer,
    last double precision,
    mark double precision,
    delta double precision,
    gamma double precision,
    theta double precision,
    vega double precision,
    rho double precision,
    implied_volatility double precision,
    open_interest integer,
    volume integer,
    source text NOT NULL DEFAULT 'schwab',
    raw jsonb,
    PRIMARY KEY (option_symbol, ts, received_ts)
);
```

For option chains, consider storing coherent snapshots:

```sql
CREATE TABLE live_option_chain_snapshots (
    snapshot_id uuid PRIMARY KEY,
    underlying_symbol text NOT NULL,
    requested_at timestamptz NOT NULL,
    received_ts timestamptz NOT NULL,
    underlying_price double precision,
    source text NOT NULL DEFAULT 'schwab',
    request_params jsonb,
    raw jsonb
);
```

```sql
CREATE TABLE live_option_chain_snapshot_contracts (
    snapshot_id uuid NOT NULL,
    option_symbol text NOT NULL,
    expiration date,
    strike double precision,
    option_type text,
    bid double precision,
    ask double precision,
    mark double precision,
    last double precision,
    delta double precision,
    gamma double precision,
    theta double precision,
    vega double precision,
    implied_volatility double precision,
    open_interest integer,
    volume integer,
    raw jsonb,
    PRIMARY KEY (snapshot_id, option_symbol)
);
```

These tables are optional later-phase additions. The coding agent should not create or migrate database tables without checking existing Backtester4 migration practices.

---

## Schwab Adapter

Phase 1 should stub this adapter. Phase 3 can implement real Schwab read-only calls.

Suggested interface:

```python
class SchwabClient:
    async def get_quotes(self, symbols: list[str]) -> dict:
        ...

    async def get_option_chain(
        self,
        symbol: str,
        contract_type: str = "ALL",
        expiration: date | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        strike_count: int | None = None,
        include_quotes: bool = True,
    ) -> dict:
        ...

    async def get_option_quotes(self, option_symbols: list[str]) -> dict:
        ...

    async def get_price_history(
        self,
        symbol: str,
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
        lookback_days: int | None = None,
    ) -> dict:
        ...

    async def get_positions(self) -> dict:
        ...

    async def preview_order(self, order: dict) -> dict:
        ...

    async def submit_order(self, order: dict) -> dict:
        ...
```

Phase 1 behavior:

- Return deterministic sample data.
- Do not require credentials.
- Do not attempt network calls.
- Allow tests to run offline.

Phase 3 behavior:

- Add OAuth.
- Add token refresh.
- Add read-only endpoint calls.
- Add rate limiting.
- Add retries/backoff.
- Preserve raw Schwab responses in `raw` fields where useful.

---

## HistoricalStore Adapter

The coding agent should inspect existing Backtester4 data access code and database schemas.

Suggested interface:

```python
class HistoricalStore:
    async def get_equity_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        ...

    async def get_option_bars(
        self,
        option_symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        ...

    async def get_last_finalized_timestamp(
        self,
        symbol: str,
        timeframe: str,
    ) -> datetime | None:
        ...
```

The coding agent should reuse existing Backtester4 database access modules if they exist, rather than duplicating SQL unnecessarily.

---

## LiveCache Adapter

Suggested interface:

```python
class LiveCache:
    async def get_quote(self, symbol: str) -> QuoteSnapshot | None:
        ...

    async def set_quote(self, quote: QuoteSnapshot, ttl_seconds: int) -> None:
        ...

    async def get_option_quote(self, option_symbol: str) -> OptionContractQuote | None:
        ...

    async def set_option_quote(self, quote: OptionContractQuote, ttl_seconds: int) -> None:
        ...

    async def get_option_chain(self, cache_key: str) -> OptionChainResponse | None:
        ...

    async def set_option_chain(self, cache_key: str, chain: OptionChainResponse, ttl_seconds: int) -> None:
        ...

    async def get_live_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        ...

    async def set_live_bar(self, bar: Bar) -> None:
        ...
```

---

## Event Bus

Use Redis Streams initially.

Suggested helper:

```python
class EventBus:
    async def publish(self, event: GatewayEvent) -> str:
        ...

    async def recent(self, count: int = 100) -> list[GatewayEvent]:
        ...

    async def stream_from(self, last_id: str = "$") -> AsyncIterator[GatewayEvent]:
        ...
```

SSE endpoint should read from EventBus.

Example SSE event:

```json
{
  "event_type": "quote",
  "event_ts": "2026-05-30T16:00:01.000Z",
  "received_ts": "2026-05-30T16:00:01.120Z",
  "source": "schwab",
  "payload": {
    "symbol": "SPY",
    "bid": 520.10,
    "ask": 520.12
  }
}
```

---

## Time and Time Zones

Use UTC internally.

Requirements:

- API responses should use ISO 8601 timestamps with timezone.
- Store timestamps as timezone-aware datetimes.
- Market session logic should respect US equity market hours.
- Existing Backtester4 conventions should be followed if already defined.
- Keep both event timestamp and received timestamp where available.

Quote timestamps:

```text
event_ts:
    when the exchange/source says the quote occurred

received_ts:
    when market_gateway received or processed the quote
```

These are both important for diagnosing stale quotes and live-data latency.

---

## Testing Requirements

Phase 1 tests:

- `/health` returns OK without auth.
- `/status` requires API key.
- `/quotes` requires API key.
- `/quotes?symbols=AAPL,NVDA` returns deterministic sample data.
- `/options/chains` requires API key.
- `/options/chains?symbol=AAPL` returns deterministic sample chain.
- `/options/quotes` returns deterministic sample quotes.
- `/history/{symbol}` returns deterministic sample bars when historical store is stubbed.
- cache key generation is stable.
- order submit returns paper/stub mode when `ENABLE_REAL_TRADING=false`.
- order submit never calls Schwab real order methods in Phase 1.

Phase 2 tests:

- `historical_only` uses only HistoricalStore.
- `live_only` uses only LiveCache.
- `canonical_plus_live` stitches historical + live data correctly.
- canonical bars win over live bars on overlap.
- duplicate timestamps are removed or resolved consistently.
- returned bars are sorted.
- returned bars include source labels.

Phase 3 tests:

- Schwab adapter can be mocked.
- cache is used when fresh.
- stale cache triggers Schwab fetch.
- failures return useful errors and publish error events.
- rate limit behavior can be tested without hitting Schwab.

---

## README Requirements

The coding agent should create a README covering:

- purpose of `market_gateway`
- how it fits into Backtester4
- setup using `uv`
- environment variables
- Redis installation/start on Ubuntu/WSL
- running the FastAPI service
- running tests
- example curl commands
- Tailscale usage note
- security notes
- phase roadmap

Example run command:

```bash
uv run uvicorn market_gateway.app.main:app --host 0.0.0.0 --port 8000 --reload
```

Example curl:

```bash
curl http://localhost:8000/health

curl -H "X-API-Key: $MARKET_GATEWAY_API_KEY" \
  "http://localhost:8000/quotes?symbols=SPY,AAPL,NVDA"
```

---

## Security Notes

- Expose only FastAPI to remote machines.
- Keep Redis local-only.
- Keep PostgreSQL access internal unless there is a separate reason to expose it.
- Never commit Schwab tokens or secrets.
- Token files must live outside the repo.
- Real trading disabled by default.
- Order submission must require preview and risk checks.
- Log all trading-related requests.
- Consider separate API keys or permissions for read-only vs trading endpoints later.

---

## Coding Agent Instructions

When building this:

1. Inspect the existing Backtester4 repository layout before creating files.
2. Reuse existing database access utilities where appropriate.
3. Do not break existing Backtester4 functionality.
4. Keep the first implementation simple and testable.
5. Use deterministic sample data for Schwab in Phase 1.
6. Do not implement real trading.
7. Do not store credentials in code.
8. Do not expose Redis directly.
9. Add tests as functionality is added.
10. Keep source-selection logic inside `DataResolver`.
11. Make all API responses typed with Pydantic models.
12. Prefer clean interfaces over clever shortcuts.
13. Add source labels when returning stitched data.
14. Document assumptions and TODOs clearly.

---

## Initial Milestone Definition of Done

The first milestone is complete when:

- FastAPI app starts.
- `/health` works without auth.
- all other endpoints require API key.
- Redis client initializes.
- `/quotes`, `/options/chains`, `/options/quotes`, and `/history/{symbol}` return deterministic sample data.
- `/events/stream` emits heartbeat or sample events via SSE.
- order endpoints exist but are paper/stub only.
- tests pass.
- README explains setup and usage.
- no real Schwab credentials are required.
- no real trades can be placed.

---

## Later Milestone Definition of Done: Data Resolver

The data resolver milestone is complete when:

- existing Backtester4 TimescaleDB historical bars can be queried.
- Redis live/current-day bars can be queried.
- `historical_only`, `live_only`, and `canonical_plus_live` modes work.
- a 30-day SPY 1-minute request can return finalized historical bars plus today's live/session bars.
- returned data is sorted, de-duplicated, and source-labeled.
- canonical historical bars win over live/session bars on overlap.
- tests cover the stitching logic.

---

## Later Milestone Definition of Done: Schwab Read-Only

The Schwab read-only milestone is complete when:

- OAuth/token handling works.
- tokens are stored outside the repo.
- live equity quotes can be fetched and cached.
- option chains can be fetched and cached.
- option quotes can be fetched and cached.
- current-day price history can be fetched and cached.
- raw Schwab responses are preserved where useful.
- rate limiting and error handling are implemented.
- no real order submission is enabled.

