import pandas as pd

from research_core.event_table import strict_resample_15m
from research_core.p4_short_research.p4_short_event_study import build_short_events_for_symbol
from research_core.p4_short_research.p4_short_replay import replay_short_events
from research_core.p4_short_research.p4_short_accounting import BASE_COST


def test_15m_close_time_and_short_entry_open_alignment():
    idx = pd.date_range("2024-01-01 00:00", periods=15, freq="1min", tz="UTC")
    data = pd.DataFrame({"open": 1, "high": 2, "low": 0, "close": 1, "volume": 1}, index=idx)
    out = strict_resample_15m(data)
    assert out.index[0] == pd.Timestamp("2024-01-01 00:15", tz="UTC")


def test_short_event_execution_time_equals_signal_completion_open():
    idx = pd.date_range("2024-01-01", periods=5000, freq="1min", tz="UTC")
    close = pd.Series(range(5000, 0, -1), index=idx, dtype=float) + 1000
    data = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close - 0.5, "volume": 1}, index=idx)
    events, _ = build_short_events_for_symbol("ETHUSDT", data)
    first = events.iloc[0]
    assert first["execution_time"] == first["signal_time"]
    assert first["execution_time"].minute % 15 == 0


def test_short_donchian_exit_uses_confirmed_1m_open_not_15m_close():
    idx = pd.date_range("2024-01-01 00:00", periods=40, freq="1min", tz="UTC")
    data_1m = pd.DataFrame({"open": [100] * 15 + [110] + [111] * 24, "high": [101] * 40, "low": [99] * 40, "close": [100] * 40, "volume": 1}, index=idx)
    data_15m = pd.DataFrame({"close": [120.0], "donchian20_upper": [105.0]}, index=pd.DatetimeIndex([pd.Timestamp("2024-01-01 00:15", tz="UTC")]))
    events = pd.DataFrame({"event_id": ["e"], "signal_time": [pd.Timestamp("2024-01-01 00:00", tz="UTC")], "execution_time": [pd.Timestamp("2024-01-01 00:00", tz="UTC")], "atr14": [20.0]})
    trades, _ = replay_short_events(events, data_1m, data_15m, "ETHUSDT", BASE_COST)
    assert trades.iloc[0]["exit_reason"] == "donchian20_exit"
    assert trades.iloc[0]["exit_time"] == pd.Timestamp("2024-01-01 00:15", tz="UTC")

