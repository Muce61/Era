import numpy as np
import pandas as pd

from research_core.high_leverage_gate_analysis import gate_mask_fixed
from research_core.long_history_validation_analysis import year_quarter_trade_summary
from research_core.oos_validation_analysis import discovery_score_thresholds, oos_prototype_masks
from research_core.strict_high_leverage_replay import strict_replay_events


def test_long_history_data_layer_not_oos():
    record = {"data_layer": "expanded_discovery", "oos_eligible": False}
    assert record["data_layer"] != "oos"
    assert record["oos_eligible"] is False


def test_prototype_threshold_uses_discovery_values():
    events = pd.DataFrame({
        "first_breakout_after_flat": [False, False, False],
        "strong_breakout": [False, False, False],
    })
    discovery_scores = pd.DataFrame({
        "momentum_continuation_score": [0, 1, 2, 3, 4],
        "breakout_conviction_score": [10, 20, 30, 40, 50],
    })
    scores = pd.DataFrame({"momentum_score": [4, 1, 0], "breakout_score": [50, 25, 5]})
    thresholds = discovery_score_thresholds(discovery_scores)
    masks = oos_prototype_masks(scores, events, thresholds)
    assert masks["P4_BREAKOUT_TOP20"].tolist() == [True, False, False]
    assert masks["P6_MOMENTUM_OR_BREAKOUT_TOP20"].tolist() == [True, False, False]


def test_gate_threshold_uses_fixed_discovery_threshold():
    events = pd.DataFrame({"prototype": ["P4"] * 3, "risk_factor": [0.1, 0.5, 0.9]})
    factors = pd.DataFrame({"prototype": ["P4"], "factor": ["risk_factor"], "safe20_edge": [1.0]})
    thresholds = pd.DataFrame({
        "prototype": ["P4"],
        "factor": ["risk_factor"],
        "keep_fraction": [0.60],
        "threshold": [0.4],
        "safe_direction": ["high"],
    })
    mask, status = gate_mask_fixed(events, factors, thresholds, "P4", "G1_SINGLE_BEST_PATH_SAFETY")
    assert status == "usable"
    assert mask.tolist() == [False, True, True]


def test_strict_replay_liquidates_fixed_20x():
    idx_1m = pd.date_range("2024-01-01 00:00", periods=45, freq="1min", tz="UTC")
    data_1m = pd.DataFrame({
        "open": [100.0] * 45,
        "high": [101.0] * 45,
        "low": [99.0] * 45,
        "close": [100.0] * 45,
        "volume": [1.0] * 45,
    }, index=idx_1m)
    data_1m.iloc[2, data_1m.columns.get_loc("low")] = 95.0
    idx_15m = pd.date_range("2024-01-01 00:00", periods=3, freq="15min", tz="UTC")
    data_15m = pd.DataFrame({"close": [100.0, 100.0, 100.0], "donchian20_lower": [90.0, 90.0, 90.0]}, index=idx_15m)
    events = pd.DataFrame({
        "event_id": ["ETHUSDT_2024-01-01T00:00:00+00:00"],
        "symbol": ["ETHUSDT"],
        "prototype": ["P4_BREAKOUT_TOP20"],
        "signal_time": [idx_15m[0]],
        "execution_time": [idx_1m[1]],
        "atr14": [10.0],
        "breakout_score_quantile": [1.0],
        "atr_pct_rank": [0.0],
    })
    trades, equity, _ = strict_replay_events(events, data_1m, data_15m, "ETHUSDT", "P4_BREAKOUT_TOP20", "G0_NO_PATH_GATE", "fixed_20x")
    assert len(trades) == 1
    assert bool(trades.iloc[0]["liquidation"])
    assert trades.iloc[0]["exit_reason"] == "liquidation_price"
    assert equity.iloc[-1]["equity"] == 50.0


def test_yearly_summary_marks_2026_partial_and_sparse():
    trades = pd.DataFrame({
        "exit_time": pd.to_datetime(["2025-01-01", "2026-01-01"], utc=True),
        "prototype": ["P4", "P4"],
        "sizing_mode": ["fixed_2x", "fixed_2x"],
        "net_pnl": [10.0, -5.0],
    })
    yearly, _ = year_quarter_trade_summary(trades, 1000.0)
    status_by_year = yearly.set_index("year")["sample_status"].to_dict()
    assert status_by_year[2025] == "insufficient_sample"
    assert status_by_year[2026] == "partial_year"


def test_run_log_required_fields_shape():
    row = {
        "run_id": "LH1_ETH_LONG_HISTORY_VALIDATION",
        "stage": "LH1",
        "script": "research_core.run_long_history_validation",
        "config_hash": "abc",
        "data_hash": "def",
        "git_commit": "ghi",
        "run_timestamp": "2026-06-28T00:00:00+00:00",
        "random_seed": 20260624,
        "data_layer": "expanded_discovery",
        "status": "success",
        "notes": "not OOS",
    }
    assert all(row[k] for k in ["config_hash", "data_hash", "git_commit", "run_timestamp", "data_layer"])

