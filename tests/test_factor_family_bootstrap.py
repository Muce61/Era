import numpy as np
import pandas as pd

from research_core.common import validate_run_log_row
from research_core.family_bootstrap_analysis import (
    attach_family,
    block_bootstrap_sample,
    distribution_stats,
    edge_distribution,
    family_bootstrap_summary,
    horizon_decay_summary,
    month_stress_summary,
    role_classification,
)


def make_events() -> pd.DataFrame:
    rows = []
    for month in range(1, 5):
        for i in range(80):
            x = i + month * 100
            rows.append({
                "signal_time": pd.Timestamp(2024, month, 1, tz="UTC") + pd.Timedelta(minutes=i),
                "factor_a": x,
                "factor_b": -x,
                "fwd_ret_1": x / 10000,
                "fwd_ret_4": -x / 10000,
            })
    return pd.DataFrame(rows)


def make_queue() -> pd.DataFrame:
    return pd.DataFrame([
        {"family": "fam_alpha", "role": "alpha", "related_existing_factors": "factor_a;factor_b", "status": "candidate"},
        {"family": "fam_blocked", "role": "execution", "related_existing_factors": "future liquidity proxies", "status": "blocked_missing_liquidity_data"},
    ])


def test_ordinary_bootstrap_distribution_is_reproducible():
    events = make_events()
    d1 = edge_distribution(events, "factor_a", 1, 1, "ordinary", 20, 7)
    d2 = edge_distribution(events, "factor_a", 1, 1, "ordinary", 20, 7)
    np.testing.assert_allclose(d1, d2)


def test_directional_distribution_same_direction_uses_positive_edge():
    stats = distribution_stats(np.array([0.1, 0.2, -0.1]), direction=-1)
    assert stats["same_direction_rate"] == stats["positive_rate"]
    assert stats["same_direction_rate"] == 2 / 3


def test_monthly_and_quarterly_block_bootstrap_use_block_columns():
    events = make_events()
    events["month_group"] = pd.to_datetime(events["signal_time"], utc=True).dt.strftime("%Y-%m")
    events["quarter_group"] = pd.to_datetime(events["signal_time"], utc=True).dt.year.astype(str) + "Q" + pd.to_datetime(events["signal_time"], utc=True).dt.quarter.astype(str)
    rng = np.random.default_rng(1)
    monthly = block_bootstrap_sample(events, "month_group", rng)
    assert len(monthly) % 80 == 0
    rng = np.random.default_rng(1)
    quarterly = block_bootstrap_sample(events, "quarter_group", rng)
    assert len(quarterly) == len(events)


def test_attach_family_maps_factor_to_literature_family():
    candidates = pd.DataFrame([{"factor": "factor_a", "horizon": 1}])
    out = attach_family(candidates, make_queue())
    assert out.loc[0, "family"] == "fam_alpha"
    assert out.loc[0, "role"] == "alpha"


def test_family_aggregation_marks_concentration():
    factor_summary = pd.DataFrame([
        {"family": "fam_alpha", "role": "alpha", "factor": "factor_a", "horizon": 1, "original_q5_minus_q1": 1.0, "direction": 1, "ordinary_same_direction_rate": 1.0, "monthly_same_direction_rate": 1.0, "quarterly_same_direction_rate": 1.0},
        {"family": "fam_alpha", "role": "alpha", "factor": "factor_b", "horizon": 1, "original_q5_minus_q1": 0.1, "direction": 1, "ordinary_same_direction_rate": 1.0, "monthly_same_direction_rate": 1.0, "quarterly_same_direction_rate": 1.0},
    ])
    out = family_bootstrap_summary(factor_summary, make_queue())
    fam = out[out["family"] == "fam_alpha"].iloc[0]
    assert fam["top_factor_contribution"] > 0.6
    assert fam["family_bootstrap_status"] == "family_concentrated"


def test_month_stress_removes_best_and_repeats_worst_month():
    events = make_events()
    candidates = pd.DataFrame([{"factor": "factor_a", "family": "fam_alpha", "horizon": 1, "direction": 1}])
    out = month_stress_summary(events, candidates)
    row = out.iloc[0]
    assert np.isfinite(row["original_edge"])
    assert np.isfinite(row["remove_best_1_month_edge"])
    assert np.isfinite(row["repeat_worst_1_month_edge"])
    assert row["stress_status"] in {"stress_survives", "best_month_dependent", "best_quarter_dependent", "worst_month_fragile", "invalid_or_sparse"}


def test_horizon_decay_identifies_reversal():
    factor_summary = pd.DataFrame([
        {"family": "fam_alpha", "role": "alpha", "factor": "factor_a", "horizon": 1, "original_q5_minus_q1": 1.0, "direction": 1},
        {"family": "fam_alpha", "role": "alpha", "factor": "factor_a", "horizon": 4, "original_q5_minus_q1": -1.0, "direction": 1},
    ])
    out = horizon_decay_summary(factor_summary, make_queue())
    row = out[out["family"] == "fam_alpha"].iloc[0]
    assert row["decay_pattern"] == "horizon_reversal"


def test_role_classification_never_promotes_blocked_family_to_alpha():
    family_summary = pd.DataFrame([
        {"family": "fam_blocked", "family_bootstrap_status": "family_invalid_or_sparse"},
    ])
    decay = pd.DataFrame([
        {"family": "fam_blocked", "decay_pattern": "invalid_or_sparse"},
    ])
    out = role_classification(family_summary, decay, make_queue())
    row = out[out["family"] == "fam_blocked"].iloc[0]
    assert row["final_research_role"] == "blocked"
    assert row["allowed_next_step"] == "blocked_missing_data"


def test_run_log_required_fields_complete():
    row = {
        "config_hash": "a",
        "data_hash": "b",
        "git_commit": "c",
        "run_timestamp": "2026-06-27T00:00:00+00:00",
        "random_seed": 1,
        "data_layer": "discovery",
    }
    assert validate_run_log_row(row)
