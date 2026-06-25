import numpy as np
import pandas as pd

from research_core.stability_analysis import (
    add_time_groups,
    same_direction_rate,
    stability_status,
    summarize_stability,
)


def test_add_time_groups_marks_current_partial_year():
    events = pd.DataFrame({
        "signal_time": ["2024-01-01 00:00:00+00:00", "2026-06-24 12:00:00+00:00"],
    })
    out = add_time_groups(events)
    assert out["year_group"].tolist() == ["2024", "2026"]
    assert out["quarter_group"].tolist() == ["2024Q1", "2026Q2"]
    assert out["partial_year"].tolist() == [False, True]


def test_same_direction_rate_uses_only_sample_sufficient_rows():
    rows = pd.DataFrame({
        "group_type": ["year_group", "year_group", "year_group"],
        "sample_sufficient": [True, False, True],
        "same_direction_as_full": [True, True, False],
    })
    assert same_direction_rate(rows, "year_group") == 0.5


def test_stability_status_passes_only_after_time_group_confirmation():
    status = stability_status(
        "candidate_for_validation",
        0.01,
        year_same_direction_rate=2 / 3,
        quarter_same_direction_rate=0.75,
        valid_year_count=3,
        valid_quarter_count=6,
    )
    assert status == "candidate_for_random_baseline"
    failed = stability_status(
        "candidate_for_validation",
        0.01,
        year_same_direction_rate=1 / 3,
        quarter_same_direction_rate=0.75,
        valid_year_count=3,
        valid_quarter_count=6,
    )
    assert failed == "unstable_descriptive"


def test_summarize_stability_preserves_unavailable_regime_note():
    rows = []
    for year in [2024, 2025]:
        for quarter_month in [1, 4]:
            for i in range(60):
                signal_time = pd.Timestamp(year=year, month=quarter_month, day=1, tz="UTC") + pd.Timedelta(minutes=i)
                x = i + (quarter_month * 100) + (year - 2024) * 1000
                rows.append({
                    "signal_time": signal_time,
                    "factor_a": x,
                    "fwd_ret_1": x / 10000,
                    "fwd_mfe_1": x / 5000,
                    "fwd_mae_1": -0.01,
                    "plus_1atr_first_1": True,
                    "minus_1atr_first_1": False,
                    "ambiguous_touch_1": False,
                    "trend_regime": "unavailable",
                    "volatility_regime": "unavailable",
                })
    events = pd.DataFrame(rows)
    r2_meta = pd.DataFrame([{
        "factor": "factor_a",
        "common": "Synthetic increasing factor.",
        "horizon": 1,
        "q5_minus_q1": 0.01,
        "direction_consistency": 1.0,
        "candidate_status": "candidate_for_validation",
    }])
    detail, summary = summarize_stability(events, r2_meta)
    assert not detail.empty
    assert summary.loc[0, "state_regime_note"] == "unavailable_in_current_event_table"
    assert summary.loc[0, "valid_year_count"] == 2
    assert summary.loc[0, "valid_quarter_count"] == 4
    assert np.isfinite(summary.loc[0, "quarter_same_direction_rate"])
