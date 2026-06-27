import numpy as np
import pandas as pd

from research_core.common import validate_run_log_row
from research_core.family_validation_analysis import (
    build_family_scores,
    c1_overlap,
    compute_family_score,
    decision_summary,
    fit_factor_params,
    score_quantile_groups,
    standardize_with_params,
    stress_summary,
    walk_forward_windows,
    winsor_bounds,
)


def make_events(n=200):
    ts = pd.date_range("2024-01-01", periods=n, freq="7D", tz="UTC")
    x = np.arange(n, dtype=float)
    df = pd.DataFrame({
        "event_id": [f"e{i}" for i in range(n)],
        "signal_time": ts,
        "execution_time": ts + pd.Timedelta(minutes=1),
        "ret_4h": x,
        "ret_12h": x + 1,
        "ret_24h": x + 2,
        "breakout_distance_atr": x,
        "range_atr": x,
        "body_ratio": x,
        "close_location": x,
        "bars_after_breakout": x % 10,
        "ema_gap_atr": x / 10,
        "atr_pct": x / 1000,
        "first_breakout_after_flat": x % 2 == 0,
        "strong_breakout": x % 3 == 0,
    })
    for h in [1, 4, 8, 16, 32]:
        df[f"fwd_ret_{h}"] = x / 10000
        df[f"fwd_mfe_{h}"] = x / 9000
        df[f"fwd_mae_{h}"] = -x / 10000
        df[f"plus_1atr_first_{h}"] = x > n / 2
        df[f"minus_1atr_first_{h}"] = x < n / 4
        df[f"ambiguous_touch_{h}"] = False
    return df


def make_r4(direction=1):
    rows = []
    for factor in ["ret_4h", "ret_12h", "ret_24h", "breakout_distance_atr", "range_atr", "body_ratio", "close_location"]:
        rows.append({"factor": factor, "direction": direction})
    return pd.DataFrame(rows)


def test_winsorize_and_zscore_are_reproducible():
    s = pd.Series([1, 2, 3, 100])
    lo, hi = winsor_bounds(s, 0.25, 0.75)
    z1 = standardize_with_params(s, lo, hi, 2.5, 1.0)
    z2 = standardize_with_params(s, lo, hi, 2.5, 1.0)
    pd.testing.assert_series_equal(z1, z2)


def test_family_score_equal_weight_and_negative_direction():
    events = make_events(20)
    params = fit_factor_params(events, ["ret_4h", "ret_12h"], {"ret_4h": -1, "ret_12h": -1})
    score = compute_family_score(events, ["ret_4h", "ret_12h"], params)
    assert score.iloc[-1] < score.iloc[0]


def test_build_family_scores_outputs_expected_columns():
    scores, metadata = build_family_scores(make_events(80), make_r4())
    assert "momentum_continuation_score" in scores.columns
    assert "breakout_conviction_score" in scores.columns
    assert set(metadata["family"]) == {"momentum_continuation", "breakout_conviction"}


def test_top20_bottom20_grouping():
    groups = score_quantile_groups(pd.Series(range(100)))
    assert (groups == "top20").sum() == 20
    assert (groups == "bottom20").sum() == 20


def test_walk_forward_uses_train_params_without_future_failure():
    events = make_events(160)
    windows, summary = walk_forward_windows(events, make_r4())
    assert not windows.empty
    assert set(summary["walk_forward_status"]).issubset({"wf_pass", "wf_weak", "wf_fail", "insufficient_sample"})


def test_c1_overlap_calculates_rates():
    events = make_events(100)
    scores, _ = build_family_scores(events, make_r4())
    out = c1_overlap(events, scores)
    assert {"first_breakout_rate", "strong_breakout_rate"}.issubset(out.columns)


def test_stress_remove_best_month_logic_outputs_status():
    events = make_events(140)
    scores, _ = build_family_scores(events, make_r4())
    out = stress_summary(events, scores)
    assert set(out["stress_status"]).issubset({"stress_pass", "month_dependent", "quarter_dependent", "tail_event_dependent", "stress_fail", "invalid_or_sparse"})


def test_high_correlation_family_not_two_independent_alpha():
    wf = pd.DataFrame([
        {"family": "momentum_continuation", "horizon": 1, "walk_forward_status": "wf_pass"},
        {"family": "breakout_conviction", "horizon": 1, "walk_forward_status": "wf_pass"},
    ])
    corr = pd.DataFrame([{"score_a": "momentum_continuation_score", "score_b": "breakout_conviction_score", "spearman_corr": 0.9}])
    c1 = pd.DataFrame([
        {"family": "momentum_continuation", "score_group": "top20", "first_breakout_rate": 0.1},
        {"family": "breakout_conviction", "score_group": "top20", "first_breakout_rate": 0.1},
    ])
    stress = pd.DataFrame([
        {"family": "momentum_continuation", "stress_status": "stress_pass"},
        {"family": "breakout_conviction", "stress_status": "stress_pass"},
    ])
    out = decision_summary(wf, corr, c1, stress)
    assert out[out["family"] == "breakout_conviction"]["r6_status"].iloc[0] == "explanatory_only"


def test_run_log_required_fields_complete():
    assert validate_run_log_row({
        "config_hash": "a",
        "data_hash": "b",
        "git_commit": "c",
        "run_timestamp": "2026-06-27T00:00:00+00:00",
        "random_seed": 1,
        "data_layer": "discovery",
    })
