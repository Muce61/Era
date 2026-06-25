import numpy as np
import pandas as pd
import pytest

from backtest.run_stage2_existing_data_pipeline import (
    compact_missing_ranges,
    filter_overlapping_events,
    percentile_rank,
    sequence_metrics,
)


def test_compact_missing_ranges_groups_consecutive_minutes():
    missing = pd.DatetimeIndex([
        pd.Timestamp("2025-01-01 00:01", tz="UTC"),
        pd.Timestamp("2025-01-01 00:02", tz="UTC"),
        pd.Timestamp("2025-01-01 00:05", tz="UTC"),
    ])
    ranges = compact_missing_ranges(missing)
    assert len(ranges) == 2
    assert ranges.iloc[0]["missing_minutes"] == 2
    assert ranges.iloc[1]["missing_minutes"] == 1


def test_filter_overlapping_events_keeps_only_non_overlapping_positions():
    events = pd.DataFrame([
        {
            "entry_time": pd.Timestamp("2025-01-01 00:00", tz="UTC"),
            "exit_time": pd.Timestamp("2025-01-01 01:00", tz="UTC"),
        },
        {
            "entry_time": pd.Timestamp("2025-01-01 00:30", tz="UTC"),
            "exit_time": pd.Timestamp("2025-01-01 02:00", tz="UTC"),
        },
        {
            "entry_time": pd.Timestamp("2025-01-01 01:01", tz="UTC"),
            "exit_time": pd.Timestamp("2025-01-01 03:00", tz="UTC"),
        },
    ])
    filtered = filter_overlapping_events(events)
    assert len(filtered) == 2
    assert list(filtered["entry_time"]) == [events.iloc[0]["entry_time"], events.iloc[2]["entry_time"]]


def test_sequence_metrics_uses_initial_balance_equity_path():
    metrics = sequence_metrics([100.0, -50.0, 25.0])
    assert metrics["final_return"] == pytest.approx(7.5)
    assert metrics["profit_factor"] == 2.5
    assert metrics["min_equity"] == 1000.0


def test_percentile_rank_ignores_non_finite_values():
    values = pd.Series([1.0, 2.0, np.inf, np.nan, 3.0])
    assert percentile_rank(values, 2.0) == 2 / 3 * 100
