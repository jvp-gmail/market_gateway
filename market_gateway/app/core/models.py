from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class DataMode(StrEnum):
    HISTORICAL_ONLY = "historical_only"
    LIVE_ONLY = "live_only"
    CANONICAL_PLUS_LIVE = "canonical_plus_live"
    BEST_AVAILABLE = "best_available"


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


class OptionChainResponse(BaseModel):
    symbol: str
    underlying_price: float | None = None
    requested_at: datetime
    received_ts: datetime
    source: str = "schwab_or_sample"
    contracts: list[OptionContractQuote]


class OptionChainRequest(BaseModel):
    symbol: str
    contract_type: Literal["CALL", "PUT", "ALL"] = "ALL"
    expiration: date | None = None
    from_date: date | None = None
    to_date: date | None = None
    strike_count: int | None = None
    include_quotes: bool = True


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


class HistoricalDataResponse(BaseModel):
    symbol: str
    timeframe: str
    mode: str
    start: datetime | None = None
    end: datetime | None = None
    bars: list[Bar]


class StreamEventType(StrEnum):
    """Canonical `GatewayEvent.event_type` values for SSE / Redis stream consumers."""

    HEARTBEAT = "heartbeat"
    EQUITY_QUOTE = "equity_quote"
    OPTION_QUOTE = "option_quote"
    STREAM_ERROR = "stream_error"


class GatewayEvent(BaseModel):
    event_type: str
    event_ts: datetime | None = None
    received_ts: datetime
    source: str
    payload: dict[str, Any] = Field(default_factory=dict)


class OrderPreviewRequest(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"] = "BUY"
    quantity: int = 1
    order_type: str = "MARKET"


class OrderPreviewResponse(BaseModel):
    preview_id: str
    symbol: str
    side: str
    quantity: int
    mode: str = "paper"
    estimated_notional: float | None = None


class OrderSubmitRequest(BaseModel):
    preview_id: str
    symbol: str
    side: Literal["BUY", "SELL"] = "BUY"
    quantity: int = 1


class OrderSubmitResponse(BaseModel):
    order_id: str
    status: str
    mode: str
    message: str


class PositionRow(BaseModel):
    symbol: str
    quantity: float
    avg_price: float | None = None


class StrategyStatusResponse(BaseModel):
    strategies: list[dict[str, Any]] = Field(default_factory=list)
