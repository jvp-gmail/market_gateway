from datetime import UTC, datetime, timedelta

from market_gateway.app.services.historical_store import _deterministic_sample_bars


def test_sample_daily_one_bar_per_utc_day() -> None:
    start = datetime(2026, 5, 1, tzinfo=UTC)
    end = datetime(2026, 5, 3, 23, 0, tzinfo=UTC)
    bars = _deterministic_sample_bars("SPY", "1d", start, end, source="sample")
    assert len(bars) == 3
    assert all(b.timeframe == "1d" for b in bars)
    assert bars[0].timestamp.day == 1
    assert bars[-1].timestamp.day == 3
