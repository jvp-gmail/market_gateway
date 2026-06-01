"""Option symbol normalization for Schwab Trader API (OSI-style contract ids)."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

# Gateway / DB style: SPY_20260601C00756000 (YYYYMMDD + C/P + strike*1000 as 8 digits)
_GATEWAY_UNDERSCORE = re.compile(r"^([^_]+)_(\d{8})([CPcp])(\d{8})$")
# Schwab / OCC OSI: 6-char padded root + YYMMDD + C/P + 8-digit strike (21 chars)
_OSI_CONTRACT = re.compile(r"^([A-Za-z0-9 ]{6})(\d{6})([CPcp])(\d{8})$")


def is_option_contract_symbol(symbol: str) -> bool:
    """True for gateway underscore ids or Schwab OSI (padded root, no underscore)."""
    s = symbol.strip()
    if _GATEWAY_UNDERSCORE.match(s):
        return True
    return bool(_OSI_CONTRACT.match(s))


def gateway_option_symbol(option_symbol: str) -> str:
    """Canonical gateway/DB key: underscore form. OSI inputs map to that form; others unchanged."""
    s = option_symbol.strip()
    if _GATEWAY_UNDERSCORE.match(s):
        return s
    m = _OSI_CONTRACT.match(s)
    if not m:
        return s
    root6, yymmdd, cp, strike8 = m.group(1), m.group(2), m.group(3).upper(), m.group(4)
    root = root6.strip().upper()
    ymd = f"20{yymmdd[0:2]}{yymmdd[2:4]}{yymmdd[4:6]}"
    return f"{root}_{ymd}{cp}{strike8}"


def parse_osi_option_contract(
    symbol: str,
) -> tuple[str, date, Literal["CALL", "PUT"], float] | None:
    """Parse Schwab OCC-style option id (6-char root + YYMMDD + C/P + strike×1000, 8 digits).

    Returns ``(underlying, expiration, call_put, strike)`` or ``None`` if the string
    does not match the OSI pattern.
    """
    s = symbol.strip().upper()
    m = _OSI_CONTRACT.match(s)
    if not m:
        return None
    root6, yymmdd, cp, strike8 = m.group(1), m.group(2), m.group(3).upper(), m.group(4)
    root = root6.strip().upper()
    ymd = f"20{yymmdd[0:2]}{yymmdd[2:4]}{yymmdd[4:6]}"
    exp = date(int(ymd[0:4]), int(ymd[4:6]), int(ymd[6:8]))
    opt_type: Literal["CALL", "PUT"] = "CALL" if cp == "C" else "PUT"
    strike = int(strike8) / 1000.0
    return (root, exp, opt_type, strike)


def schwab_option_symbol(option_symbol: str) -> str:
    """Map gateway underscore ids to Schwab's 6-char padded root + YYMMDD + C/P + strike8.

    Schwab chains use OSI-style symbols, e.g. ``SPY   260601C00756000`` (``SPY`` plus
    spaces to width 6, then ``YYMMDD``, ``C`` or ``P``, then 8-digit strike × 1000).

    If ``option_symbol`` does not match the underscore pattern, it is returned
    stripped (already in broker form).
    """
    s = option_symbol.strip()
    m = _GATEWAY_UNDERSCORE.match(s)
    if not m:
        return s
    root, ymd, cp, strike8 = m.group(1), m.group(2), m.group(3).upper(), m.group(4)
    yymmdd = ymd[2:4] + ymd[4:6] + ymd[6:8]
    root6 = (root.upper() + "      ")[:6]
    return f"{root6}{yymmdd}{cp}{strike8}"
