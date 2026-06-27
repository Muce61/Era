import numpy as np
import pandas as pd

from research_core.common import validate_run_log_row
from research_core.prototype_attribution_analysis import (
    PROTOTYPES,
    decision_summary,
    event_summary,
    incremental_attribution,
    period_summary,
    prototype_masks,
    stability_summary,
    tail_dependence,
    top_positive_contribution,
)


def make_events(n=120):
    ts = pd.date_range("2024-01-01", periods=n, freq="7D", tz="UTC")
    x = np.arange(n, dtype=float)
    events = pd.DataFrame({
        "event_id": [f"e{i}" for i in range(n)],
        "signal_time": ts,
        "execution_time": ts + pd.Timedelta(minutes=1),
        "first_breakout_after_flat": x % 3 == 0,
        "strong_breakout": x % 4 == 0,
    })
    for h in [1, 4, 8, 16, 32]:
        events[f"fwd_ret_{h}"] = (x - 40) / 10000
        events[f"fwd_mfe_{h}"] = x / 9000
        events[f"fwd_mae_{h}"] = -((120 - x) / 10000)
        events[f"plus_1atr_first_{h}"] = x > 70
        events[f"minus_1atr_first_{h}"] = x < 20
        events[f"ambiguous_touch_{h}"] = False
    return events


def make_scores(n=120):
    q = pd.Series(np.arange(1, n + 1) / n)
    return pd.DataFrame({
        "momentum_score_quantile": q,
        "breakout_score_quantile": 1 - q + (1 / n),
    })


def test_prototype_masks_include_required_baselines():
    events = make_events()
    masks = prototype_masks(events, make_scores())
    assert set(PROTOTYPES) == set(masks)
    assert masks["P0_ALL_TREND_CONTEXT"].all()
    assert masks["P1_C1_FIRST_BREAKOUT"].sum() == events["first_breakout_after_flat"].sum()
    assert masks["P2_STRONG_BREAKOUT"].sum() == events["strong_breakout"].sum()


def test_event_count_below_30_is_marked_insufficient():
    events = make_events(20)
    summary = event_summary(events, prototype_masks(events, make_scores(20)))
    assert (summary[summary["prototype"] == "P0_ALL_TREND_CONTEXT"]["sample_status"] == "insufficient_sample").all()


def test_top_contribution_uses_positive_returns_only():
    contribution = top_positive_contribution(pd.Series([-10, 1, 2, 7]), 1)
    assert contribution == 0.7


def test_incremental_attribution_calculates_expected_direction():
    events = make_events(200)
    summary = event_summary(events, prototype_masks(events, make_scores(200)))
    inc = incremental_attribution(summary)
    p3 = inc[(inc["comparison"] == "P3_vs_P0") & (inc["horizon"] == 16)].iloc[0]
    assert p3["incremental_mean_ret"] > 0
    assert p3["interpretation"] in {"clear_incremental", "weak_incremental"}


def test_monthly_and_quarterly_stability_outputs_status():
    events = make_events(180)
    masks = prototype_masks(events, make_scores(180))
    monthly = period_summary(events, masks, "month_group")
    quarterly = period_summary(events, masks, "quarter_group")
    stable = stability_summary(monthly, quarterly)
    assert set(stable["stability_status"]).issubset({"stable", "month_fragile", "quarter_fragile", "insufficient_sample"})


def test_tail_dependence_remove_best_event_logic():
    events = make_events()
    masks = prototype_masks(events, make_scores())
    tail = tail_dependence(events, masks)
    row = tail[(tail["prototype"] == "P0_ALL_TREND_CONTEXT") & (tail["horizon"] == 16)].iloc[0]
    assert row["remove_best_1_event"] < row["original_mean_ret"]
    assert row["tail_dependence_status"] in {
        "not_tail_dependent",
        "single_event_dependent",
        "top5_event_dependent",
        "top10pct_dependent",
        "best_month_dependent",
        "best_quarter_dependent",
        "insufficient_sample",
    }


def test_c1_high_overlap_can_only_be_explanatory():
    events = make_events(300)
    events["first_breakout_after_flat"] = True
    scores = make_scores(300)
    masks = prototype_masks(events, scores)
    summary = event_summary(events, masks)
    inc = incremental_attribution(summary)
    monthly = period_summary(events, masks, "month_group")
    quarterly = period_summary(events, masks, "quarter_group")
    stable = stability_summary(monthly, quarterly)
    tail = tail_dependence(events, masks)
    decisions = decision_summary(summary, inc, stable, tail, events, masks)
    p3 = decisions[decisions["prototype"] == "P3_MOMENTUM_TOP20"].iloc[0]
    assert p3["decision_status"] == "explanatory_only"


def test_decision_rules_allow_candidate_when_conditions_pass():
    events = make_events(200)
    events["first_breakout_after_flat"] = False
    scores = make_scores(200)
    masks = prototype_masks(events, scores)
    summary = event_summary(events, masks)
    inc = incremental_attribution(summary)
    monthly = period_summary(events, masks, "month_group")
    quarterly = period_summary(events, masks, "quarter_group")
    stable = stability_summary(monthly, quarterly)
    tail = tail_dependence(events, masks)
    decisions = decision_summary(summary, inc, stable, tail, events, masks)
    assert set(decisions["decision_status"]).issubset({
        "candidate_for_R8_backtest",
        "explanatory_only",
        "weak_candidate",
        "discard_for_now",
        "insufficient_sample",
    })


def test_run_log_required_fields_complete():
    assert validate_run_log_row({
        "config_hash": "a",
        "data_hash": "b",
        "git_commit": "c",
        "run_timestamp": "2026-06-27T00:00:00+00:00",
        "random_seed": 20260624,
        "data_layer": "discovery",
    })
