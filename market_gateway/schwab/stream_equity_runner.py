"""Background Schwab WebSocket: LEVELONE_EQUITIES / LEVELONE_FUTURES → EventBus (Phase 4 part 2)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from market_gateway.app.config import Settings
from market_gateway.app.core.event_bus import EventBus
from market_gateway.app.core.stream_symbols import StreamSymbolsPayload
from market_gateway.app.services.quote_stream_publisher import publish_equity_quote
from market_gateway.schwab.stream_equity_normalize import level_one_equity_row_to_quote_snapshot

if TYPE_CHECKING:
    from schwab.client.asynchronous import AsyncClient

log = logging.getLogger(__name__)


def _parse_symbols(symbols: list[str]) -> list[str]:
    return sorted({s.strip().upper() for s in symbols if s.strip()})


def partition_equity_and_futures_symbols(symbols: list[str]) -> tuple[list[str], list[str]]:
    """
    Schwab futures L1 streaming expects symbols like ``/ES``, ``/MES`` (leading ``/``).
    Equity tickers are everything else (e.g. ``SPY``).
    """
    equity: list[str] = []
    futures: list[str] = []
    for s in _parse_symbols(symbols):
        if s.startswith("/"):
            futures.append(s)
        else:
            equity.append(s)
    return equity, futures


def _field_sets(StreamClient: type) -> tuple[list[Any], list[Any]]:
    Fe = StreamClient.LevelOneEquityFields
    equity_fields = [
        Fe.SYMBOL,
        Fe.BID_PRICE,
        Fe.ASK_PRICE,
        Fe.LAST_PRICE,
        Fe.MARK,
        Fe.BID_SIZE,
        Fe.ASK_SIZE,
        Fe.TOTAL_VOLUME,
        Fe.QUOTE_TIME_MILLIS,
    ]
    Ff = StreamClient.LevelOneFuturesFields
    fut_fields = [
        Ff.SYMBOL,
        Ff.BID_PRICE,
        Ff.ASK_PRICE,
        Ff.LAST_PRICE,
        Ff.MARK,
        Ff.BID_SIZE,
        Ff.ASK_SIZE,
        Ff.TOTAL_VOLUME,
        Ff.QUOTE_TIME_MILLIS,
    ]
    return equity_fields, fut_fields


async def _apply_subscription_change(
    client: Any,
    old: StreamSymbolsPayload,
    new: StreamSymbolsPayload,
    equity_fields: list[Any],
    fut_fields: list[Any],
) -> None:
    """Same WebSocket session: SUBS replaces keys; UNSUBS when clearing a service."""
    if new.equities != old.equities:
        if old.equities and not new.equities:
            await client.level_one_equity_unsubs(old.equities)
        elif new.equities:
            await client.level_one_equity_subs(new.equities, fields=equity_fields)
    if new.futures != old.futures:
        if old.futures and not new.futures:
            await client.level_one_futures_unsubs(old.futures)
        elif new.futures:
            await client.level_one_futures_subs(new.futures, fields=fut_fields)
    if new.options or old.options:
        log.warning("LEVELONE_OPTIONS resubscribe not implemented; ignoring options change")


async def run_schwab_equity_stream(
    inner: AsyncClient,
    bus: EventBus,
    settings: Settings,
    replace_queue: asyncio.Queue[StreamSymbolsPayload],
    initial: StreamSymbolsPayload,
) -> None:
    from schwab.streaming import StreamClient, UnexpectedResponse

    log.info("Schwab quote stream background task started")

    if not initial.equities and not initial.futures:
        log.warning(
            "Schwab quote stream: no equities or futures in initial payload; exiting "
            "(options-only streaming not implemented)"
        )
        return

    equity_fields, fut_fields = _field_sets(StreamClient)
    backoff = max(3.0, float(settings.schwab_stream_reconnect_seconds))
    current = initial.model_copy()

    while True:
        client = StreamClient(inner, enforce_enums=True)
        publish_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)

        async def _publish_worker() -> None:
            while True:
                msg = await publish_queue.get()
                try:
                    for row in msg.get("content") or []:
                        if not isinstance(row, dict):
                            continue
                        snap = level_one_equity_row_to_quote_snapshot(row)
                        if snap:
                            await publish_equity_quote(bus, snap)
                except Exception:
                    log.exception("Schwab quote stream handler failed")
                finally:
                    publish_queue.task_done()

        worker_task = asyncio.create_task(_publish_worker())

        def _quote_handler(msg: dict[str, Any]) -> None:
            """Sync handler: keep Redis publishes on one bounded worker."""

            if publish_queue.full():
                try:
                    publish_queue.get_nowait()
                    publish_queue.task_done()
                except asyncio.QueueEmpty:
                    pass
            try:
                publish_queue.put_nowait(msg)
            except asyncio.QueueFull:
                log.debug("Schwab quote stream publish queue full; dropping payload")

        async def _reader_loop() -> None:
            while True:
                try:
                    await client.handle_message()
                except UnexpectedResponse as exc:
                    log.warning(
                        "Schwab stream: RESPONSE frame while reading (skipping): %s",
                        getattr(exc, "response", exc),
                    )
                    continue

        async def _control_loop() -> None:
            nonlocal current
            while True:
                new_payload = await replace_queue.get()
                if new_payload == current:
                    log.debug("Schwab stream: resubscribe no-op (unchanged lists)")
                    continue
                log.info(
                    "Schwab stream: applying session resubscribe equities=%s futures=%s",
                    new_payload.equities or "(none)",
                    new_payload.futures or "(none)",
                )
                await _apply_subscription_change(
                    client, current, new_payload, equity_fields, fut_fields
                )
                current = new_payload.model_copy()

        try:
            log.info(
                "Schwab stream: login; equities=%s futures=%s",
                current.equities or "(none)",
                current.futures or "(none)",
            )
            await client.login()
            # Handlers must be registered *before* SUBS (schwab-py drops DATA without handlers).
            client.add_level_one_equity_handler(_quote_handler)
            client.add_level_one_futures_handler(_quote_handler)
            if current.equities:
                await client.level_one_equity_subs(current.equities, fields=equity_fields)
            if current.futures:
                await client.level_one_futures_subs(current.futures, fields=fut_fields)
            log.info(
                "Schwab stream: subscriptions active; reader + resubscribe control running "
                "(equities=%s futures=%s)",
                current.equities or "(none)",
                current.futures or "(none)",
            )
            reader_task = asyncio.create_task(_reader_loop())
            control_task = asyncio.create_task(_control_loop())
            try:
                await asyncio.gather(reader_task, control_task)
            finally:
                for t in (reader_task, control_task):
                    t.cancel()
                await asyncio.gather(reader_task, control_task, return_exceptions=True)
        except asyncio.CancelledError:
            log.info("Schwab quote stream cancelled")
            raise
        except Exception as e:
            log.warning(
                "Schwab quote stream error (%s: %s); reconnecting in %.1fs",
                type(e).__name__,
                e,
                backoff,
            )
        finally:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
            try:
                await client.logout()
            except Exception:
                pass
        await asyncio.sleep(backoff)
