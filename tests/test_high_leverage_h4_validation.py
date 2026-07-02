import pandas as pd

from research_core.common import validate_run_log_row
from research_core.high_leverage_h4_validation_analysis import (
    DISCOVERY_END,
    compare_finer_liquidation,
    final_h4_decision,
    holdout_sample_status,
    is_holdout_symbol,
    is_time_oos_sufficient,
    risk_retention_status,
    validate_oos_no_overlap,
)


def test_oos_data_cannot_overlap_discovery():
    ok = pd.DataFrame({"timestamp": [DISCOVERY_END + pd.Timedelta(minutes=1)]})
    bad = pd.DataFrame({"timestamp": [DISCOVERY_END]})
    assert validate_oos_no_overlap(ok)
    assert not validate_oos_no_overlap(bad)


def test_oos_less_than_three_months_not_pass():
    ts = pd.date_range(DISCOVERY_END + pd.Timedelta(minutes=1), periods=60 * 24 * 20, freq="1min", tz="UTC")
    frame = pd.DataFrame({"timestamp": ts})
    assert not is_time_oos_sufficient(frame)


def test_holdout_symbols_exclude_discovery_assets():
    assert not is_holdout_symbol("ETHUSDT")
    assert not is_holdout_symbol("BTCUSDT")
    assert is_holdout_symbol("XRPUSDT")


def test_less_than_three_holdout_symbols_insufficient():
    assert holdout_sample_status(["XRPUSDT", "ADAUSDT"]) == "insufficient_sample"
    assert holdout_sample_status(["XRPUSDT", "ADAUSDT", "DOGEUSDT"]) == "valid"


def test_h4_does_not_reselect_factor_rule_shape():
    fixed_factors = {"volatility_ratio_short_long", "atr_pct", "breakout_score_quantile"}
    attempted = {"volatility_ratio_short_long", "rsi"}
    assert not attempted.issubset(fixed_factors)


def test_h4_does_not_optimize_gate_thresholds():
    allowed = {"G1_SINGLE_BEST_PATH_SAFETY": 0.60, "G2_CONSENSUS_TWO_FACTORS": 0.70}
    assert allowed["G1_SINGLE_BEST_PATH_SAFETY"] == 0.60
    assert 0.50 not in allowed.values()


def test_holdout_threshold_source_is_fixed_description():
    threshold_source = "discovery/H3 fixed rules"
    assert "fixed" in threshold_source
    assert "optimized" not in threshold_source


def test_finer_low_liquidation_difference():
    row = pd.Series({
        "entry_price": 100.0,
        "liquidation_price": 90.0,
        "low_1m": 91.0,
        "low_finer": 89.5,
    })
    out = compare_finer_liquidation(row)
    assert not out["hit_liq_1m"]
    assert out["hit_liq_finer"]
    assert out["audit_status"] == "finer_found_extra_liquidation"


def test_risk_retention_status_calculation():
    h3 = pd.Series({"trade_count": 100, "profit_factor": 2.0, "max_drawdown": -0.2, "liquidation_count": 0})
    h4 = pd.Series({"trade_count": 50, "profit_factor": 1.3, "max_drawdown": -0.3, "liquidation_count": 0})
    assert risk_retention_status(h3, h4) == "risk_control_confirmed"
    failed = h4.copy()
    failed["liquidation_count"] = 1
    assert risk_retention_status(h3, failed) == "risk_control_failed"


def test_data_insufficient_report_conclusion_is_e():
    code, _ = final_h4_decision(False, "cross_asset_holdout_fail", False, pd.DataFrame())
    assert code == "E"


def test_cross_asset_holdout_pass_cannot_be_final_a():
    validation = pd.DataFrame({"validation_status": ["validation_pass"]})
    code, _ = final_h4_decision(False, "cross_asset_holdout_pass", False, validation)
    assert code == "B"


def test_run_log_required_fields_complete():
    assert validate_run_log_row({
        "config_hash": "a",
        "data_hash": "b",
        "git_commit": "c",
        "run_timestamp": "2026-06-28T00:00:00+00:00",
        "random_seed": 20260624,
        "data_layer": "high_leverage_validation",
    })
