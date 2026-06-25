import pandas as pd

from research.trend_research_pipeline import first_touch, next_1m_open
from strategy.trend_following import build_signal_frame


def test_donchian_excludes_current_signal_candle():
    idx = pd.date_range("2025-01-01", periods=80, freq="15min", tz="UTC")
    df15 = pd.DataFrame({
        "open": range(80),
        "high": list(range(79)) + [10_000],
        "low": range(80),
        "close": range(80),
        "volume": 1,
    }, index=idx)
    data_1m = df15.resample("1min").ffill()
    config = {
        "signal_timeframe": "15min",
        "ema_fast": 3,
        "ema_slow": 5,
        "atr_period": 3,
        "donchian_entry": 55,
        "donchian_exit": 20,
    }
    signal = build_signal_frame(data_1m, config)
    last = signal.iloc[-1]
    assert last["donchian_high_55"] < 10_000


def test_signal_executes_next_available_1m_open():
    idx = pd.date_range("2025-01-01 00:14", periods=3, freq="1min", tz="UTC")
    data_1m = pd.DataFrame({"open": [100, 101, 102]}, index=idx)
    ts, price = next_1m_open(data_1m, idx[0])
    assert ts == idx[1]
    assert price == 101


def test_first_touch_ambiguous_same_bar():
    idx = pd.date_range("2025-01-01", periods=1, freq="1min", tz="UTC")
    path = pd.DataFrame({"high": [111], "low": [89]}, index=idx)
    outcome, ts, ambiguous = first_touch(path, 100, 10, "LONG", 1, 1)
    assert outcome == "ambiguous"
    assert ambiguous is True
