"""Schwab L1 stream symbol lists (equities / futures / options) for session resubscribe."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


def _norm_equity_list(v: list[str]) -> list[str]:
    return sorted({s.strip().upper() for s in v if s.strip()})


def _norm_futures_list(v: list[str]) -> list[str]:
    out: list[str] = []
    for s in v:
        t = s.strip().upper()
        if not t:
            continue
        if not t.startswith("/"):
            raise ValueError(f"futures symbol must start with '/': {s!r}")
        out.append(t)
    return sorted(set(out))


def _norm_options_list(v: list[str]) -> list[str]:
    """Preserve OSI padding/case; trim outer whitespace and drop empties."""
    return [s.strip() for s in v if s.strip()]


class StreamSymbolsPayload(BaseModel):
    """Normalized subscription triple for Schwab LEVELONE services."""

    equities: list[str] = Field(default_factory=list)
    futures: list[str] = Field(default_factory=list)
    options: list[str] = Field(default_factory=list)

    @field_validator("equities", mode="before")
    @classmethod
    def _v_eq(cls, v: object) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise TypeError("equities must be a list")
        return _norm_equity_list([str(x) for x in v])

    @field_validator("futures", mode="before")
    @classmethod
    def _v_fu(cls, v: object) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise TypeError("futures must be a list")
        return _norm_futures_list([str(x) for x in v])

    @field_validator("options", mode="before")
    @classmethod
    def _v_op(cls, v: object) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise TypeError("options must be a list")
        return _norm_options_list([str(x) for x in v])
