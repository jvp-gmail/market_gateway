"""Option symbol normalization for Schwab Trader API (OSI-style contract ids)."""

from __future__ import annotations

import re

# Gateway / DB style: SPY_20260601C00756000 (YYYYMMDD + C/P + strike*1000 as 8 digits)
_GATEWAY_UNDERSCORE = re.compile(r"^([^_]+)_(\d{8})([CPcp])(\d{8})$")


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
