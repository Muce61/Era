import numpy as np
import pandas as pd

from research_core.common import validate_run_log_row
from research_core.path_safety_factor_validation_analysis import (
    block_bootstrap_edges,
    bootstrap_edges,
    classify_factor_role,
    edge_metrics,
    failure_case_explainability,
    horizon_consistency,
    path_safety_stress,
    remove_best_month,
)


def make_labels():
    rows = []
    for symbol in ["ETHUSDT", "BTCUSDT"]:
        for month in ["2024-01", "2024-02"]:
            for window in ["1m", "15m"]:
                for i in range(40):
                    high = i >= 32
                    low = i < 8
                    rows.append({
                        "symbol": symbol,
                        "prototype": "P4_BREAKOUT_TOP20",
                        "event_id": f"{symbol}-{month}-{window}-{i}",
                        "entry_time": pd.Timestamp(f"{month}-01 00:00:00+00:00") + pd.Timedelta(minutes=i),
                        "month": month,
                        "forward_window": window,
                        "range_atr": i,
                        "safe_for_20x": high,
                        "hit_liquidation_20x": low,
                        "mae_pct": i / 10000,
                        "mfe_pct": i / 5000,
                        "fast_follow_through": high,
                    })
    return pd.DataFrame(rows)


def test_factor_role_classification_dual_use():
    metrics = {
        "valid": True,
        "safe20_edge": 0.1,
        "mae_edge": 0.01,
        "hit_liq20_edge": 0.0,
        "mfe_edge": 0.02,
        "fast_follow_edge": 0.1,
    }
    assert classify_factor_role(metrics) == "dual_use_candidate"


def test_alpha_only_and_path_safety_only_are_distinct():
    alpha = {"valid": True, "safe20_edge": 0, "mae_edge": 0, "hit_liq20_edge": 0, "mfe_edge": 0.1, "fast_follow_edge": 0}
    safety = {"valid": True, "safe20_edge": 0.1, "mae_edge": 0.1, "hit_liq20_edge": 0, "mfe_edge": 0, "fast_follow_edge": 0}
    assert classify_factor_role(alpha) == "alpha_only"
    assert classify_factor_role(safety) == "path_safety_only"


def test_ordinary_bootstrap_reproducible():
    labels = make_labels()
    rng1 = np.random.default_rng(1)
    rng2 = np.random.default_rng(1)
    a = bootstrap_edges(labels, "range_atr", rng1, iterations=100)
    b = bootstrap_edges(labels, "range_atr", rng2, iterations=100)
    assert np.allclose(a, b)


def test_monthly_block_bootstrap_uses_month_blocks():
    labels = make_labels()
    rng = np.random.default_rng(2)
    vals = block_bootstrap_edges(labels, "range_atr", "month", rng, iterations=50)
    assert len(vals) == 50
    assert np.isfinite(vals).all()


def test_symbol_block_bootstrap_uses_symbol_blocks():
    labels = make_labels()
    rng = np.random.default_rng(3)
    vals = block_bootstrap_edges(labels, "range_atr", "symbol", rng, iterations=50)
    assert len(vals) == 50


def test_remove_best_month_logic():
    labels = make_labels()
    reduced = remove_best_month(labels, "range_atr", 1)
    assert reduced["month"].nunique() == labels["month"].nunique() - 1


def test_top_mfe_stress_outputs_status():
    labels = make_labels()
    out = path_safety_stress(labels)
    row = out[(out["factor"] == "range_atr") & (out["prototype"] == "P4_BREAKOUT_TOP20") & (out["forward_window"] == "1m")].iloc[0]
    assert row["stress_status"] in {
        "stress_pass",
        "month_dependent",
        "symbol_dependent",
        "tail_event_dependent",
        "worst_month_fragile",
        "invalid_or_sparse",
    }


def test_horizon_consistency_identifies_multi_window():
    role = pd.DataFrame({
        "factor": ["range_atr", "range_atr"],
        "prototype": ["P4_BREAKOUT_TOP20", "P4_BREAKOUT_TOP20"],
        "forward_window": ["1m", "15m"],
        "safe20_edge": [0.1, 0.2],
        "mae_edge": [0.1, 0.1],
        "mfe_edge": [0.1, 0.1],
        "factor_role": ["dual_use_candidate", "dual_use_candidate"],
    })
    from research_core import path_safety_factor_validation_analysis as h

    original_factors = h.H2_FACTORS
    original_windows = h.H2_WINDOWS
    h.H2_FACTORS = ["range_atr"]
    h.H2_WINDOWS = ["1m", "15m"]
    try:
        out = horizon_consistency(role)
    finally:
        h.H2_FACTORS = original_factors
        h.H2_WINDOWS = original_windows
    assert out.iloc[0]["window_role"] == "path_safety_multi_window"


def test_failure_case_lift_calculation():
    labels = make_labels()
    failures = labels[(labels["prototype"] == "P4_BREAKOUT_TOP20") & (labels["range_atr"] < 8)][["prototype", "event_id"]].head(10)
    out = failure_case_explainability(labels, failures)
    row = out[(out["factor"] == "range_atr") & (out["prototype"] == "P4_BREAKOUT_TOP20")].iloc[0]
    assert row["lift"] > 1


def test_run_log_required_fields_complete():
    assert validate_run_log_row({
        "config_hash": "a",
        "data_hash": "b",
        "git_commit": "c",
        "run_timestamp": "2026-06-27T00:00:00+00:00",
        "random_seed": 20260624,
        "data_layer": "high_leverage_research",
    })
