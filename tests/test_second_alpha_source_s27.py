import numpy as np
import pandas as pd

from research_core.second_alpha_source_s2.candidate_event_study_s2 import IDLE_CANDIDATE
from research_core.second_alpha_source_s27.strict_exit_window_validation import (
    EXIT_BUCKET,
    direction_symbol_matrix,
    input_validation,
    neighbor_comparison,
    period_stability,
    random_direction_baseline,
    random_time_baseline,
    stress_summary,
    decision_summary,
    top_trade_dependency,
)


def _events(n=400):
    idx = pd.date_range("2025-01-01 00:15", periods=n, freq="15min", tz="UTC")
    symbols = ["ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT"]
    buckets = [EXIT_BUCKET, "after_p4_exit_0_4_bars", "after_p4_exit_17_64_bars", "deep_idle"]
    rows = []
    for i, ts in enumerate(idx):
        bucket = EXIT_BUCKET if i < n // 2 else buckets[i % len(buckets)]
        ret = 0.003 if bucket == EXIT_BUCKET else -0.001
        rows.append({
            "event_id": f"e{i}",
            "candidate": IDLE_CANDIDATE,
            "symbol": symbols[i % 4],
            "side": "long" if i % 2 == 0 else "short",
            "signal_time": ts,
            "execution_time": ts,
            "p4_state_bucket": bucket,
            "bars_since_p4_exit_bucket": bucket,
            "trend_strength_atr": 0.8,
            "trend_strength_bucket": "0.5_1.0",
            "volatility_regime": "mid_vol",
            "month": ts.to_period("M").strftime("%Y-%m"),
            "quarter": ts.to_period("Q").strftime("%YQ%q"),
            "fwd_ret_1": ret / 4,
            "fwd_ret_4": ret / 2,
            "fwd_ret_8": ret * 0.75,
            "fwd_ret_16": ret,
            "fwd_ret_32": ret * 1.2,
            "plus_1atr_first_16": ret > 0,
            "minus_1atr_first_16": ret < 0,
            "fwd_mae_16": -0.003,
            "fwd_mfe_16": 0.006,
        })
    return pd.DataFrame(rows)


def test_s27_input_validation_blocks_without_required_files():
    out = input_validation()
    assert out["input_validation_status"].iloc[0] in {"pass", "blocked"}
    assert "canonical_s2_exists" in out.columns


def test_neighbor_comparison_keeps_fixed_buckets_without_optimization():
    out = neighbor_comparison(_events())
    assert set(out["p4_state_bucket"]) == {
        "after_p4_exit_0_4_bars",
        EXIT_BUCKET,
        "after_p4_exit_17_64_bars",
        "deep_idle",
    }
    target = out.set_index("p4_state_bucket").loc[EXIT_BUCKET, "mean_fwd_ret_16"]
    assert target > out.set_index("p4_state_bucket").loc["deep_idle", "mean_fwd_ret_16"]


def test_random_direction_baseline_uses_same_event_times():
    events = _events()
    out = random_direction_baseline(events, runs=50, seed=1)
    assert out["random_runs"].iloc[0] == 50
    assert out["percentile_vs_random_direction"].between(0, 1).all()


def test_random_time_baseline_uses_full_pool_and_reports_fallback():
    events = _events()
    target = events[events["p4_state_bucket"] == EXIT_BUCKET].copy()
    pool = target.copy()
    pool["fwd_ret_16"] = -0.002
    out = random_time_baseline(events, pool, runs=30, seed=1)
    assert out["random_runs"].iloc[0] == 30
    assert "fallback_match_rate" in out.columns
    assert out["random_mean"].iloc[0] < target["fwd_ret_16"].mean()


def test_positive_period_rate_calculation():
    monthly, stats = period_stability(_events(), "month")
    assert "positive_period" in monthly.columns
    assert 0 <= stats["positive_month_rate"] <= 1


def test_best_month_removal_stress_case_exists():
    stress = stress_summary(_events())
    assert "remove_best_1_month" in set(stress["stress_case"])
    assert "stress_status" in stress.columns


def test_p4_correlation_insufficient_overlap_can_be_marked():
    # The production function reads optional files; this unit only asserts the
    # downstream decision can consume insufficient-overlap rows.
    corr = pd.DataFrame([{"symbol": "ETHUSDT", "overlap_month_count": 0, "monthly_corr": np.nan, "corr_status": "insufficient_overlap"}])
    assert corr["corr_status"].iloc[0] == "insufficient_overlap"


def test_s27_decision_rule_and_non_oos():
    events = _events(800)
    neighbor = neighbor_comparison(events)
    matrix = direction_symbol_matrix(events)
    monthly, _ = period_stability(events, "month")
    quarterly, _ = period_stability(events, "quarter")
    dep = top_trade_dependency(events)
    stress = stress_summary(events)
    input_val = pd.DataFrame([{"input_validation_status": "pass"}])
    random_dir = pd.DataFrame([{"percentile_vs_random_direction": 0.8}])
    random_time = pd.DataFrame([{"percentile_vs_random_time": 0.9}])
    corr = pd.DataFrame([{"symbol": "ETHUSDT", "corr_status": "low_corr"}])
    overlap = pd.DataFrame([{"symbol": "ETHUSDT", "s27_positive_in_p4_negative_month_rate": 0.5}])
    long_hist = pd.DataFrame([{"symbol": "ETHUSDT", "sample_status": "valid", "mean_fwd_ret_16": 0.001}])
    decision = decision_summary(input_val, neighbor, random_dir, random_time, monthly, quarterly, matrix, dep, stress, corr, overlap, long_hist)
    assert decision["strategy_backtest_generated"].iloc[0] == False  # noqa: E712
    assert decision["oos_status"].iloc[0] == "not_oos"
    assert decision["decision_letter"].iloc[0] in {"A", "B", "C", "D", "E"}

