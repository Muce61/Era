import pandas as pd

from research_core.p4_short_research.p4_short_event_study import build_short_events_for_symbol


def test_tail_extension_does_not_change_historical_short_events():
    idx = pd.date_range("2024-01-01", periods=5200, freq="1min", tz="UTC")
    close = pd.Series(range(5200, 0, -1), index=idx, dtype=float) + 1000
    base = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close - 0.5, "volume": 1}, index=idx)
    extra_idx = pd.date_range(idx[-1] + pd.Timedelta(minutes=1), periods=200, freq="1min", tz="UTC")
    extra = pd.DataFrame({"open": 999, "high": 1000, "low": 998, "close": 999, "volume": 1}, index=extra_idx)
    events_a, _ = build_short_events_for_symbol("ETHUSDT", base)
    events_b, _ = build_short_events_for_symbol("ETHUSDT", pd.concat([base, extra]))
    cutoff = events_a.iloc[-5]["signal_time"]
    assert events_a[events_a["signal_time"] <= cutoff]["event_id"].tolist() == events_b[events_b["signal_time"] <= cutoff]["event_id"].tolist()

