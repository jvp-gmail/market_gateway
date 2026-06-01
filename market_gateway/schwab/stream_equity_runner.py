"""Background Schwab WebSocket: LEVELONE_EQUITIES / LEVELONE_FUTURES / LEVELONE_OPTIONS → EventBus."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from market_gateway.app.config import Settings
from market_gateway.app.core.event_bus import EventBus
from market_gateway.app.core.stream_symbols import StreamSymbolsPayload
from market_gateway.app.services.quote_stream_publisher import publish_equity_quote, publish_option_quote
from market_gateway.schwab.option_symbol import schwab_option_symbol
from market_gateway.schwab.stream_equity_normalize import (
    level_one_equity_row_to_quote_snapshot,
    level_one_option_row_to_option_contract_quote,
)

if TYPE_CHECKING:
    from schwab.client.asynchronous import AsyncClient

log = logging.getLogger(__name__)

# One queue entry = one Schwab ``data`` frame (often one service, multiple ``content`` rows).
# A depth of 1 drops whole frames when another service (e.g. futures) outpaces Redis publish,
# which starves equities L1 next to chatty ``/ES``.
_SCHWAB_STREAM_PUBLISH_QUEUE_MAX = 512


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


def _stream_option_keys(symbols: list[str]) -> list[str]:
    """Schwab ``LEVELONE_OPTIONS`` keys use OSI; map gateway underscore ids the same as REST."""
    return [schwab_option_symbol(s) for s in symbols]


def _field_sets(StreamClient: type) -> tuple[list[Any], list[Any], list[Any]]:
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
    Fo = StreamClient.LevelOneOptionFields
    opt_fields = [
        Fo.SYMBOL,
        Fo.BID_PRICE,
        Fo.ASK_PRICE,
        Fo.LAST_PRICE,
        Fo.MARK,
        Fo.BID_SIZE,
        Fo.ASK_SIZE,
        Fo.TOTAL_VOLUME,
        Fo.QUOTE_TIME_MILLIS,
        Fo.UNDERLYING,
        Fo.EXPIRATION_YEAR,
        Fo.EXPIRATION_MONTH,
        Fo.EXPIRATION_DAY,
        Fo.CONTRACT_TYPE,
        Fo.DELTA,
        Fo.GAMMA,
        Fo.THETA,
        Fo.VEGA,
        Fo.RHO,
        Fo.VOLATILITY,
        Fo.OPEN_INTEREST,
    ]
    return equity_fields, fut_fields, opt_fields


async def _apply_subscription_change(
    client: Any,
    old: StreamSymbolsPayload,
    new: StreamSymbolsPayload,
    equity_fields: list[Any],
    fut_fields: list[Any],
    opt_fields: list[Any],
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
    if new.options != old.options:
        old_k = _stream_option_keys(old.options)
        new_k = _stream_option_keys(new.options)
        if old_k and not new_k:
            await client.level_one_option_unsubs(old_k)
        elif new_k:
            await client.level_one_option_subs(new_k, fields=opt_fields)


async def run_schwab_equity_stream(
    inner: AsyncClient,
    bus: EventBus,
    settings: Settings,
    replace_queue: asyncio.Queue[StreamSymbolsPayload],
    initial: StreamSymbolsPayload,
) -> None:
    from schwab.streaming import StreamClient, UnexpectedResponse

    log.info("Schwab quote stream background task started")

    if not initial.equities and not initial.futures and not initial.options:
        log.warning(
            "Schwab quote stream: initial payload has no equities, futures, or options; exiting"
        )
        return

    equity_fields, fut_fields, opt_fields = _field_sets(StreamClient)
    backoff = max(3.0, float(settings.schwab_stream_reconnect_seconds))
    current = initial.model_copy()

    while True:
        client = StreamClient(inner, enforce_enums=True)
        publish_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=_SCHWAB_STREAM_PUBLISH_QUEUE_MAX
        )

        async def _publish_worker() -> None:
            while True:
                msg = await publish_queue.get()
                try:
                    for row in msg.get("content") or []:
                        if not isinstance(row, dict):
                            continue
                        if msg.get("service") == "LEVELONE_OPTIONS":
                            oc = level_one_option_row_to_option_contract_quote(row)
                            if oc:
                                await publish_option_quote(bus, oc)
                        else:
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

        async def _multiplex_loop() -> None:
            """Never run ``handle_message`` concurrently with SUBS/UNSUBS (same WebSocket ``recv``)."""
            nonlocal current
            while True:
                read_task = asyncio.create_task(client.handle_message())
                ctrl_task = asyncio.create_task(replace_queue.get())
                try:
                    done, _ = await asyncio.wait(
                        {read_task, ctrl_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                except asyncio.CancelledError:
                    read_task.cancel()
                    ctrl_task.cancel()
                    await asyncio.gather(read_task, ctrl_task, return_exceptions=True)
                    raise

                if ctrl_task in done:
                    # Always consume the queue payload first so a failing handle_message cannot drop it.
                    new_payload = ctrl_task.result()
                    if read_task not in done:
                        read_task.cancel()
                        await asyncio.gather(read_task, return_exceptions=True)
                    else:
                        try:
                            read_task.result()
                        except UnexpectedResponse as exc:
                            log.warning(
                                "Schwab stream: RESPONSE frame while reading (skipping): %s",
                                getattr(exc, "response", exc),
                            )
                    if new_payload == current:
                        log.debug("Schwab stream: resubscribe no-op (unchanged lists)")
                        continue
                    log.info(
                        "Schwab stream: applying session resubscribe equities=%s futures=%s options=%s",
                        new_payload.equities or "(none)",
                        new_payload.futures or "(none)",
                        new_payload.options or "(none)",
                    )
                    old = current.model_copy()
                    current = new_payload.model_copy()
                    try:
                        await _apply_subscription_change(
                            client, old, new_payload, equity_fields, fut_fields, opt_fields
                        )
                    except Exception:
                        log.exception(
                            "Schwab stream: subscription apply failed (local intent already updated; "
                            "will retry on reconnect)"
                        )
                        raise
                    continue

                ctrl_task.cancel()
                await asyncio.gather(ctrl_task, return_exceptions=True)
                try:
                    read_task.result()
                except UnexpectedResponse as exc:
                    log.warning(
                        "Schwab stream: RESPONSE frame while reading (skipping): %s",
                        getattr(exc, "response", exc),
                    )

        try:
            log.info(
                "Schwab stream: login; equities=%s futures=%s options=%s",
                current.equities or "(none)",
                current.futures or "(none)",
                current.options or "(none)",
            )
            await client.login()
            # Handlers must be registered *before* SUBS (schwab-py drops DATA without handlers).
            client.add_level_one_equity_handler(_quote_handler)
            client.add_level_one_futures_handler(_quote_handler)
            client.add_level_one_option_handler(_quote_handler)
            if current.equities:
                await client.level_one_equity_subs(current.equities, fields=equity_fields)
            if current.futures:
                await client.level_one_futures_subs(current.futures, fields=fut_fields)
            if current.options:
                await client.level_one_option_subs(
                    _stream_option_keys(current.options), fields=opt_fields
                )
            log.info(
                "Schwab stream: subscriptions active; multiplexed read + resubscribe loop "
                "(equities=%s futures=%s options=%s)",
                current.equities or "(none)",
                current.futures or "(none)",
                current.options or "(none)",
            )
            await _multiplex_loop()
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
