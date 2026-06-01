# Phase 4 Part 2: Schwab streaming ingest

Part 1 on `main` adds canonical `StreamEventType`, `publish_equity_quote` / `publish_option_quote`, optional `ENABLE_QUOTE_STREAM_STUB`, Redis stream bootstrap, and SSE-friendly Redis timeouts.

This branch implements **live Schwab WebSocket** (or schwab-py streaming API) ingest:

1. **Client lifecycle** — connect with existing OAuth/token path, heartbeat/admin handling per Schwab, backoff reconnect. *(Quote loop in `schwab/stream_equity_runner.py`: `LEVELONE_EQUITIES` for plain tickers, `LEVELONE_FUTURES` for symbols with a leading `/` e.g. `/ES`; gated by `ENABLE_SCHWAB_STREAMING` + `SCHWAB_STREAM_EQUITY_SYMBOLS`.)* **schwab-py requires `add_level_one_*_handler` before `level_one_*_subs`** so the first DATA frames after SUBS are not dropped.
2. **Subscriptions** — map gateway symbol lists (equity OSI tickers, option OSI, futures as supported) to Schwab service/field sets.
3. **Normalization** — map stream payloads into `QuoteSnapshot` / `OptionContractQuote` (reuse REST normalizers where possible), then `publish_*` on `EventBus`. Schwab L1 `content` rows carry the symbol in **`key`** (not numeric field `0`); numeric fields are relabeled by schwab-py to enum names where applicable.
4. **Optional LiveCache** — write-through so REST stays aligned with stream (separate follow-up if scope grows).
5. **Tests** — unit tests with recorded frames or mocks; no network in default CI.

**Session resubscribe:** `PUT /events/stream/symbols` (API key) enqueues a new `{equities, futures, options}` triple; the stream task applies `SUBS` / `UNSUBS` on the **existing** WebSocket (no logout). `options` must stay empty until `LEVELONE_OPTIONS` is wired.

See `README.md` (Phase 4 section) and `docs/market_gateway_spec.md` § Phase 4.

**Troubleshooting wire traffic:** set `SCHWAB_STREAMING_DEBUG=true` in `.env` (or export for one run). Restart the gateway; logs show schwab-py `DEBUG:schwab.streaming:Send …` / `Receive …` with JSON payloads. Disable when finished (noisy and may include market data).
