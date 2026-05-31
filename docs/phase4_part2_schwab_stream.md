# Phase 4 Part 2: Schwab streaming ingest

Part 1 on `main` adds canonical `StreamEventType`, `publish_equity_quote` / `publish_option_quote`, optional `ENABLE_QUOTE_STREAM_STUB`, Redis stream bootstrap, and SSE-friendly Redis timeouts.

This branch implements **live Schwab WebSocket** (or schwab-py streaming API) ingest:

1. **Client lifecycle** — connect with existing OAuth/token path, heartbeat/admin handling per Schwab, backoff reconnect.
2. **Subscriptions** — map gateway symbol lists (equity OSI tickers, option OSI, futures as supported) to Schwab service/field sets.
3. **Normalization** — map stream payloads into `QuoteSnapshot` / `OptionContractQuote` (reuse REST normalizers where possible), then `publish_*` on `EventBus`.
4. **Optional LiveCache** — write-through so REST stays aligned with stream (separate follow-up if scope grows).
5. **Tests** — unit tests with recorded frames or mocks; no network in default CI.

See `README.md` (Phase 4 section) and `docs/market_gateway_spec.md` § Phase 4.
