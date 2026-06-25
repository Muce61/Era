import pandas as pd
import pytest

from research_core.factor_analysis import assign_quintile, summarize_factor


def test_assign_quintile_marks_sparse_sample():
    q = assign_quintile(pd.Series([1, 1, 1]), min_count=5, min_unique=2)
    assert set(q.dropna()) == {"insufficient_sample"}


def test_assign_quintile_is_reproducible():
    series = pd.Series(range(100))
    q1 = assign_quintile(series)
    q2 = assign_quintile(series)
    pd.testing.assert_series_equal(q1, q2)


def test_summarize_factor_computes_q5_minus_q1_by_horizon():
    events = pd.DataFrame({
        "factor_a": range(100),
        "fwd_ret_1": [x / 100 for x in range(100)],
        "fwd_mfe_1": [x / 50 for x in range(100)],
        "fwd_mae_1": [-0.01 for _ in range(100)],
        "plus_1atr_first_1": [True for _ in range(100)],
        "minus_1atr_first_1": [False for _ in range(100)],
        "ambiguous_touch_1": [False for _ in range(100)],
    })
    _, meta = summarize_factor(events, "factor_a", 1)
    assert meta["sample_sufficient"] is True
    assert meta["q5_minus_q1"] > 0
    assert meta["candidate_status"] in {"weak_candidate", "candidate_for_validation"}

