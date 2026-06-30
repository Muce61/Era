import pandas as pd

from research_core.p4_short_research.p4_short_event_study import build_short_events_for_symbol


def _data():
    idx = pd.date_range("2024-01-01", periods=5200, freq="1min", tz="UTC")
    close = pd.Series(range(5200, 0, -1), index=idx, dtype=float) + 1000
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close - 0.5, "volume": 1}, index=idx)


def test_future_mutation_does_not_change_past_short_signals():
    base = _data()
    events, _ = build_short_events_for_symbol("ETHUSDT", base)
    cutoff = events.iloc[3]["signal_time"]
    mutated = base.copy()
    mutated.loc[mutated.index > cutoff + pd.Timedelta(hours=12), "low"] = 0.01
    mutated_events, _ = build_short_events_for_symbol("ETHUSDT", mutated)
    left = events[events["signal_time"] <= cutoff]["event_id"].tolist()
    right = mutated_events[mutated_events["signal_time"] <= cutoff]["event_id"].tolist()
    assert left == right

