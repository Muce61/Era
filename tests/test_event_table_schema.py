import pandas as pd

from research_core.event_table import next_1m_open, strict_resample_15m


def test_strict_resample_15m_requires_complete_minutes():
    idx = pd.date_range("2025-01-01 00:00", periods=29, freq="1min", tz="UTC")
    df = pd.DataFrame({"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1}, index=idx)
    out = strict_resample_15m(df)
    assert len(out) == 1
    assert out.index[0] == pd.Timestamp("2025-01-01 00:00", tz="UTC")


def test_next_1m_open_is_strictly_after_signal_time():
    idx = pd.date_range("2025-01-01 00:00", periods=3, freq="1min", tz="UTC")
    df = pd.DataFrame({"open": [10, 11, 12], "high": 12, "low": 9, "close": 10, "volume": 1}, index=idx)
    ts, price = next_1m_open(df, pd.Timestamp("2025-01-01 00:00", tz="UTC"))
    assert ts == pd.Timestamp("2025-01-01 00:01", tz="UTC")
    assert price == 11

