from __future__ import annotations

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from market_gateway.app.deps import get_settings_from_app

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    request: Request,
    x_api_key: str | None = Security(api_key_header),
) -> None:
    settings = get_settings_from_app(request)
    if not x_api_key or x_api_key != settings.market_gateway_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
