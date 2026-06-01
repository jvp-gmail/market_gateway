"""Background Schwab WebSocket: LEVELONE_EQUITIES / LEVELONE_FUTURES → EventBus (Phase 4 part 2)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from market_gateway.app.config import Settings
from market_gateway.app.core.event_bus import EventBus
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


async def run_schwab_equity_stream(
    inner: AsyncClient,
    bus: EventBus,
    symbols: list[str],
    settings: Settings,
) -> None:
    from schwab.streaming import StreamClient, UnexpectedResponse

    log.info("Schwab quote stream background task started")

    equity_syms, fut_syms = partition_equity_and_futures_symbols(symbols)
    if not equity_syms and not fut_syms:
        log.warning("Schwab quote stream: empty symbol list after parse; exiting")
        return

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
    backoff = max(3.0, float(settings.schwab_stream_reconnect_seconds))

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

        try:
            log.info(
                "Schwab stream: login; equities=%s futures=%s",
                equity_syms or "(none)",
                fut_syms or "(none)",
            )
            await client.login()
            # Handlers must be registered *before* SUBS: schwab-py drops DATA frames
            # that arrive before a handler exists (see streaming docs).
            if equity_syms:
                client.add_level_one_equity_handler(_quote_handler)
                await client.level_one_equity_subs(equity_syms, fields=equity_fields)
            if fut_syms:
                client.add_level_one_futures_handler(_quote_handler)
                await client.level_one_futures_subs(fut_syms, fields=fut_fields)
            log.info(
                "Schwab stream: subscriptions active; entering read loop "
                "(equities=%s futures=%s)",
                equity_syms or "(none)",
                fut_syms or "(none)",
            )
            while True:
                try:
                    await client.handle_message()
                except UnexpectedResponse as exc:
                    # Some servers occasionally send RESPONSE envelopes on the read path;
                    # treat as non-fatal so quote DATA frames can still be processed.
                    log.warning(
                        "Schwab stream: RESPONSE frame while reading (skipping): %s",
                        getattr(exc, "response", exc),
                    )
                    continue
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
