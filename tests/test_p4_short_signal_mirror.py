import pandas as pd

from research_core.p4_short_research.p4_short_event_study import add_short_indicators, build_short_events_for_symbol


def _downtrend_1m(periods=5000):
    idx = pd.date_range("2024-01-01", periods=periods, freq="1min", tz="UTC")
    close = pd.Series(range(periods, 0, -1), index=idx, dtype=float) + 1000
    return pd.DataFrame({
        "open": close + 0.2,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 1.0,
    }, index=idx)


def test_short_mirror_uses_lower_breakout_and_bear_ema():
    data = _downtrend_1m()
    events, _ = build_short_events_for_symbol("ETHUSDT", data)
    assert not events.empty
    row = events.iloc[0]
    assert row["close_15m"] < row["donchian55_lower"]
    assert row["ema50"] < row["ema200"]


def test_donchian_lower_uses_shift_one_not_signal_bar():
    idx = pd.date_range("2024-01-01", periods=80, freq="15min", tz="UTC")
    data = pd.DataFrame({
        "open": [100.0] * 80,
        "high": [101.0] * 80,
        "low": [99.0] * 79 + [1.0],
        "close": [100.0] * 80,
        "volume": [1.0] * 80,
    }, index=idx)
    out = add_short_indicators(data)
    assert out["donchian55_lower"].iloc[-1] == 99.0

