import numpy as np
import pandas as pd

from research_core.random_baseline_analysis import (
    benjamini_hochberg_q_values,
    classify_random_baseline,
    observed_quintile_edge,
    percentile_rank_in_direction,
    random_q5_minus_q1_distribution,
    summarize_random_baseline,
)


def test_percentile_rank_uses_plus_one_formula_positive_direction():
    observed = 3.0
    random_values = np.array([0.0, 1.0, 2.0, 4.0])
    percentile, p_value = percentile_rank_in_direction(observed, random_values, direction=1)
    assert percentile == 4 / 5
    assert p_value == 2 / 5


def test_percentile_rank_handles_negative_direction():
    observed = -3.0
    random_values = np.array([-4.0, -2.0, -1.0, 0.0])
    percentile, p_value = percentile_rank_in_direction(observed, random_values, direction=-1)
    assert percentile == 4 / 5
    assert p_value == 2 / 5


def test_classify_random_baseline_thresholds():
    assert classify_random_baseline(0.96, 0.04) == "passes_random_baseline"
    assert classify_random_baseline(0.85, 0.15) == "weak_random_evidence"
    assert classify_random_baseline(0.70, 0.30) == "not_significant_vs_random"


def test_benjamini_hochberg_q_values_are_monotone_by_rank():
    p = pd.Series([0.01, 0.04, 0.03, np.nan])
    q = benjamini_hochberg_q_values(p)
    assert pd.isna(q.iloc[3])
    assert q.iloc[0] <= q.iloc[2] <= q.iloc[1]


def test_observed_quintile_edge_and_random_distribution_are_reproducible():
    events = pd.DataFrame({
        "factor_a": range(100),
        "fwd_ret_1": np.linspace(-0.05, 0.05, 100),
    })
    observed, counts = observed_quintile_edge(events, "factor_a", 1)
    assert observed > 0
    assert counts["q1_count"] == 20
    assert counts["q5_count"] == 20
    rng1 = np.random.default_rng(7)
    rng2 = np.random.default_rng(7)
    dist1 = random_q5_minus_q1_distribution(events, 1, 20, 20, 10, rng1)
    dist2 = random_q5_minus_q1_distribution(events, 1, 20, 20, 10, rng2)
    np.testing.assert_allclose(dist1, dist2)


def test_summarize_random_baseline_outputs_runs_and_summary():
    events = pd.DataFrame({
        "factor_a": range(100),
        "fwd_ret_1": np.linspace(-0.05, 0.05, 100),
    })
    candidates = pd.DataFrame([{
        "factor": "factor_a",
        "common": "Synthetic factor.",
        "horizon": 1,
        "full_q5_minus_q1": 0.01,
    }])
    summary, runs = summarize_random_baseline(events, candidates, n_runs=25, random_seed=11)
    assert len(summary) == 1
    assert len(runs) == 25
    assert summary.loc[0, "direction"] == 1
    assert summary.loc[0, "n_runs"] == 25
    assert summary.loc[0, "directional_percentile"] > 0
    assert "bh_fdr_q_value" in summary.columns
