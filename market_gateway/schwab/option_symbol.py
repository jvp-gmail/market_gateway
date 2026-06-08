"""Option symbol normalization: **compact OSI** (canonical), Schwab padded OSI at the API edge."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

# Legacy gateway: SPY_20260601C00756000
_GATEWAY_UNDERSCORE = re.compile(r"^([^_]+)_(\d{8})([CPcp])(\d{8})$")
# Padded OCC: 6-char root (spaces ok) + YYMMDD + C/P + 8-digit strike
_OSI_PADDED = re.compile(r"^([A-Za-z0-9 ]{6})(\d{6})([CPcp])(\d{8})$")
# Compact / Polygon wire root (after ``O:``): letters, digits, class ``.``, hyphen; no spaces.
_OPTION_ROOT_COMPACT = re.compile(r"^[A-Z0-9](?:[A-Z0-9.\-]*[A-Z0-9])?$")
_MAX_COMPACT_OPTION_ROOT_LEN = 32


def _yymmdd_to_date(yymmdd: str, *, today: date | None = None) -> date | None:
    if len(yymmdd) != 6 or not yymmdd.isdigit():
        return None
    yy = int(yymmdd[0:2])
    mm = int(yymmdd[2:4])
    dd = int(yymmdd[4:6])
    today = today or date.today()
    best: date | None = None
    best_abs: int | None = None
    for century in (1900, 2000, 2100):
        y = century + yy
        try:
            d = date(y, mm, dd)
        except ValueError:
            continue
        dist = abs((d - today).days)
        if best is None or best_abs is None or dist < best_abs:
            best = d
            best_abs = dist
        elif dist == best_abs and best is not None and d > best:
            best = d
    return best


def _parse_parts(symbol: str) -> tuple[str, str, Literal["C", "P"], str] | None:
    s0 = symbol.strip()
    if not s0:
        return None
    s = s0.upper()
    if s.startswith("O:"):
        s = s[2:]

    m_u = _GATEWAY_UNDERSCORE.match(s)
    if m_u:
        root, ymd8, cp, strike8 = m_u.group(1), m_u.group(2), m_u.group(3).upper(), m_u.group(4)
        if len(ymd8) != 8 or not ymd8.isdigit():
            return None
        yymmdd = ymd8[2:4] + ymd8[4:6] + ymd8[6:8]
        rt = root.strip().upper()
        if not rt or len(rt) > 6 or cp not in ("C", "P"):
            return None
        if not strike8.isdigit() or len(strike8) != 8:
            return None
        return (rt, yymmdd, cp, strike8)  # type: ignore[return-value]

    m_o = _OSI_PADDED.match(s)
    if m_o:
        root6, yymmdd, cp, strike8 = (
            m_o.group(1).strip().upper(),
            m_o.group(2),
            m_o.group(3).upper(),
            m_o.group(4),
        )
        if not root6 or len(root6) > 6 or cp not in ("C", "P"):
            return None
        return (root6, yymmdd, cp, strike8)  # type: ignore[return-value]

    if len(s) < 16:
        return None
    tail15 = s[-15:]
    yymmdd, cp, strike8 = tail15[:6], tail15[6], tail15[7:]
    if cp not in ("C", "P") or not yymmdd.isdigit() or not strike8.isdigit():
        return None
    root = s[:-15].strip().upper()
    if (
        not root
        or " " in root
        or len(root) > _MAX_COMPACT_OPTION_ROOT_LEN
        or len(s) != len(root) + 15
        or _OPTION_ROOT_COMPACT.fullmatch(root) is None
    ):
        return None
    return (root, yymmdd, cp, strike8)  # type: ignore[return-value]


def normalize_option_to_compact(symbol: str) -> str | None:
    """Canonical compact OSI (DB + HTTP client id)."""
    parts = _parse_parts(symbol)
    if not parts:
        return None
    root, yymmdd, cp, strike8 = parts
    return f"{root}{yymmdd}{cp}{strike8}"


def is_option_contract_symbol(symbol: str) -> bool:
    """True if *symbol* is a supported option contract id (compact, ``O:``, padded OSI, legacy underscore)."""
    return normalize_option_to_compact(symbol) is not None


def gateway_option_symbol(option_symbol: str) -> str:
    """Historical name: canonical **compact** id for Postgres / cache keys.

    Returns stripped input if the string does not parse as an option contract.
    """
    c = normalize_option_to_compact(option_symbol)
    return c if c is not None else option_symbol.strip()


def parse_osi_option_contract(
    symbol: str,
) -> tuple[str, date, Literal["CALL", "PUT"], float] | None:
    """Parse compact, ``O:``, padded OSI, or legacy underscore into contract fields."""
    parts = _parse_parts(symbol)
    if not parts:
        return None
    root, yymmdd, cp, strike8 = parts
    exp_d = _yymmdd_to_date(yymmdd)
    if exp_d is None:
        return None
    opt_type: Literal["CALL", "PUT"] = "CALL" if cp == "C" else "PUT"
    strike = int(strike8) / 1000.0
    return (root, exp_d, opt_type, strike)


def schwab_option_symbol(option_symbol: str) -> str:
    """Schwab REST/stream: six-space-padded root + YYMMDD + C/P + strike8.

    Accepts compact, ``O:``, padded OSI, or legacy underscore input.
    """
    parts = _parse_parts(option_symbol)
    if not parts:
        return option_symbol.strip()
    root, yymmdd, cp, strike8 = parts
    root6 = (root + "      ")[:6]
    return f"{root6}{yymmdd}{cp}{strike8}"
