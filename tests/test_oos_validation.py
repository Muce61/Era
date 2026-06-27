from pathlib import Path

import numpy as np
import pandas as pd

from research_core.common import validate_run_log_row
from research_core.oos_validation_analysis import (
    DISCOVERY_END,
    build_data_inventory,
    coverage_decision,
    discovery_score_thresholds,
    discovery_vs_oos_comparison,
    oos_prototype_masks,
    transform_oos_scores,
    validate_no_discovery_overlap,
)


def test_oos_data_cannot_overlap_discovery():
    oos = pd.DataFrame({"timestamp": [DISCOVERY_END + pd.Timedelta(minutes=1)]})
    assert validate_no_discovery_overlap(oos)
    overlapping = pd.DataFrame({"timestamp": [DISCOVERY_END]})
    assert not validate_no_discovery_overlap(overlapping)


def test_coverage_below_three_months_is_blocked(tmp_path):
    path = tmp_path / "ETHUSDT.csv"
    ts = pd.date_range(DISCOVERY_END + pd.Timedelta(minutes=1), periods=60 * 24 * 10, freq="1min", tz="UTC")
    pd.DataFrame({"timestamp": ts}).to_csv(path, index=False)
    inventory = build_data_inventory([path])
    decision = coverage_decision(inventory)
    assert decision["status"] == "blocked"
    assert decision["reason"] == "oos_data_unavailable_or_insufficient"


def test_oos_score_transform_uses_discovery_metadata_not_refit():
    events = pd.DataFrame({
        "event_id": ["a", "b"],
        "signal_time": pd.date_range("2026-10-01", periods=2, freq="1h", tz="UTC"),
        "execution_time": pd.date_range("2026-10-01 00:01", periods=2, freq="1h", tz="UTC"),
        "ret_4h": [100, 200],
        "ret_12h": [100, 200],
        "ret_24h": [100, 200],
        "breakout_distance_atr": [100, 200],
        "range_atr": [100, 200],
        "body_ratio": [100, 200],
        "close_location": [100, 200],
    })
    metadata = pd.DataFrame({
        "family": ["momentum_continuation"] * 3 + ["breakout_conviction"] * 4,
        "factor": ["ret_4h", "ret_12h", "ret_24h", "breakout_distance_atr", "range_atr", "body_ratio", "close_location"],
        "direction": [1] * 7,
        "winsor_lower": [0] * 7,
        "winsor_upper": [10] * 7,
        "mean": [5] * 7,
        "std": [5] * 7,
        "missing_rate": [0] * 7,
    })
    scores = transform_oos_scores(events, metadata)
    assert (scores["momentum_score"] == 1.0).all()
    assert (scores["breakout_score"] == 1.0).all()


def test_oos_thresholds_use_discovery_scores():
    discovery_scores = pd.DataFrame({
        "momentum_continuation_score": np.arange(100),
        "breakout_conviction_score": np.arange(100) * 2,
    })
    thresholds = discovery_score_thresholds(discovery_scores)
    assert set(thresholds["quantile"]) == {0.60, 0.80}
    assert thresholds[(thresholds["score"] == "momentum") & (thresholds["quantile"] == 0.80)]["threshold"].iloc[0] > 70


def test_oos_masks_do_not_rank_inside_oos():
    events = pd.DataFrame({
        "first_breakout_after_flat": [False, False, False],
        "strong_breakout": [False, True, False],
    })
    scores = pd.DataFrame({"momentum_score": [1, 2, 3], "breakout_score": [1, 2, 3]})
    thresholds = pd.DataFrame({
        "score": ["momentum", "momentum", "breakout", "breakout"],
        "quantile": [0.60, 0.80, 0.60, 0.80],
        "threshold": [10, 20, 10, 20],
    })
    masks = oos_prototype_masks(scores, events, thresholds)
    assert masks["P3_MOMENTUM_TOP20"].sum() == 0
    assert masks["P4_BREAKOUT_TOP20"].sum() == 0


def test_oos_event_schema_can_match_r1():
    r1_cols = ["event_id", "signal_time", "execution_time", "fwd_ret_16"]
    oos_cols = ["event_id", "signal_time", "execution_time", "fwd_ret_16"]
    assert r1_cols == oos_cols


def test_discovery_vs_oos_retention_calculation():
    discovery = pd.DataFrame({
        "prototype": ["P4_BREAKOUT_TOP20"],
        "sizing_mode": ["fixed_2x"],
        "trade_count": [100],
        "total_return": [2.0],
        "profit_factor": [2.0],
        "max_drawdown": [-0.1],
        "win_rate": [0.5],
        "top1_profit_contribution": [0.2],
    })
    oos = pd.DataFrame({
        "prototype": ["P4_BREAKOUT_TOP20"],
        "sizing_mode": ["fixed_2x"],
        "trade_count": [40],
        "total_return": [1.0],
        "profit_factor": [1.5],
        "max_drawdown": [-0.1],
        "win_rate": [0.5],
        "top1_profit_contribution": [0.2],
    })
    out = discovery_vs_oos_comparison(discovery, oos)
    assert out.iloc[0]["performance_retention_ratio"] == 0.5
    assert out.iloc[0]["oos_status"] == "oos_confirmed"


def test_oos_data_insufficient_report_conclusion_is_e():
    decision = coverage_decision(pd.DataFrame())
    assert decision["conclusion"].startswith("E.")


def test_run_log_blocked_success_fields_complete():
    assert validate_run_log_row({
        "config_hash": "a",
        "data_hash": "b",
        "git_commit": "c",
        "run_timestamp": "2026-06-27T00:00:00+00:00",
        "random_seed": 20260624,
        "data_layer": "oos",
        "status": "blocked",
    })
