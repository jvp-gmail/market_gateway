"""Build StubSchwabClient or live SchwabPyMarketClient from Settings."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from market_gateway.app.config import Settings
from market_gateway.schwab.client import StubSchwabClient
from market_gateway.schwab.schwab_py_client import SchwabPyMarketClient

log = logging.getLogger(__name__)


async def create_schwab_market_client(settings: Settings) -> StubSchwabClient | SchwabPyMarketClient:
    if not settings.enable_schwab_live_data:
        return StubSchwabClient()

    cid = (settings.schwab_client_id or "").strip()
    secret = (settings.schwab_client_secret or "").strip()
    token_file = (settings.schwab_token_file or "").strip()
    if not cid or not secret or not token_file:
        log.warning(
            "ENABLE_SCHWAB_LIVE_DATA is true but SCHWAB_CLIENT_ID, SCHWAB_CLIENT_SECRET, "
            "or SCHWAB_TOKEN_FILE is missing; using stub Schwab client"
        )
        return StubSchwabClient()

    path = Path(token_file).expanduser()
    if not path.is_file():
        log.warning("Schwab token file not found at %s; using stub client", path)
        return StubSchwabClient()

    from schwab.auth import client_from_token_file

    try:
        inner = client_from_token_file(
            str(path),
            cid,
            secret,
            asyncio=True,
            enforce_enums=True,
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        log.warning(
            "Schwab token file at %s is unreadable or invalid (%s: %s); using stub client",
            path,
            type(e).__name__,
            e,
        )
        return StubSchwabClient()

    log.info("Schwab live market client initialized (token file %s)", path)
    return SchwabPyMarketClient(inner, settings)
