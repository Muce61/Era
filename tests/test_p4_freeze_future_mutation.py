import pandas as pd

from research_core.event_table import strict_resample_15m


def test_future_mutation_does_not_change_past_resampled_bar():
    idx = pd.date_range("2024-01-01 00:00", periods=30, freq="1min", tz="UTC")
    data = pd.DataFrame({
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "volume": 1.0,
    }, index=idx)
    base = strict_resample_15m(data).iloc[0].copy()
    mutated = data.copy()
    mutated.loc[idx[20:], "close"] = 999.0
    after = strict_resample_15m(mutated).iloc[0]
    assert base.equals(after)

