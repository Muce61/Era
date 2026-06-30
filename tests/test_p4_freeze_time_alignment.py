import pandas as pd

from research_core.event_table import next_1m_open, strict_resample_15m


def _ohlcv(index):
    return pd.DataFrame({
        "open": range(len(index)),
        "high": range(1, len(index) + 1),
        "low": range(len(index)),
        "close": range(len(index)),
        "volume": 1.0,
    }, index=index)


def test_15m_timestamp_is_completed_candle_time():
    idx = pd.date_range("2024-01-01 00:00", periods=15, freq="1min", tz="UTC")
    bars = strict_resample_15m(_ohlcv(idx))
    assert list(bars.index) == [pd.Timestamp("2024-01-01 00:15", tz="UTC")]


def test_execution_uses_signal_time_1m_open():
    idx = pd.date_range("2024-01-01 00:14", periods=3, freq="1min", tz="UTC")
    data = _ohlcv(idx)
    ts, price = next_1m_open(data, pd.Timestamp("2024-01-01 00:15", tz="UTC"))
    assert ts == pd.Timestamp("2024-01-01 00:15", tz="UTC")
    assert price == 1.0

