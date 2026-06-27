import pandas as pd

from research_core.common import validate_run_log_row
from research_core.high_leverage_gate_analysis import (
    build_incremental,
    coverage_status,
    downshift_leverage,
    factor_ranks,
    gate_mask,
    h3_decision_status,
    high_risk_mask,
    risk_reduction_status,
    simulate_gate_leverage_path,
)
from research_core.leverage_research_analysis import StressConfig, liquidation_price


def make_events():
    rows = []
    for i in range(10):
        rows.append({
            "symbol": "ETHUSDT",
            "prototype": "P4_BREAKOUT_TOP20",
            "event_id": f"e{i}",
            "atr_pct": i / 1000,
            "volatility_ratio_short_long": i,
            "atr_pct_rank": i / 10,
            "breakout_score_quantile": i / 10,
            "momentum_score_quantile": i / 10,
        })
    return pd.DataFrame(rows)


def make_factors(n=1):
    factors = [
        {"factor": "volatility_ratio_short_long", "prototype": "P4_BREAKOUT_TOP20", "safe20_edge": 0.2, "rank_score": 0.3},
        {"factor": "atr_pct", "prototype": "P4_BREAKOUT_TOP20", "safe20_edge": -0.1, "rank_score": 0.2},
        {"factor": "breakout_score_quantile", "prototype": "P4_BREAKOUT_TOP20", "safe20_edge": 0.1, "rank_score": 0.1},
    ]
    return pd.DataFrame(factors[:n])


def make_trades():
    return pd.DataFrame({
        "symbol": ["ETHUSDT", "ETHUSDT"],
        "prototype": ["P4_BREAKOUT_TOP20", "P4_BREAKOUT_TOP20"],
        "event_id": ["e8", "e1"],
        "entry_time": ["2024-01-01 00:01:00+00:00", "2024-01-02 00:01:00+00:00"],
        "exit_time": ["2024-01-01 01:00:00+00:00", "2024-01-02 01:00:00+00:00"],
        "entry_price": [100.0, 100.0],
        "exit_price": [105.0, 105.0],
        "atr": [1.0, 1.0],
        "mae_atr": [-1.0, -20.0],
        "mfe_atr": [10.0, 10.0],
        "atr_pct": [0.01, 0.01],
        "atr_pct_rank": [0.5, 0.5],
        "breakout_score_quantile": [0.9, 0.9],
        "gate_high_risk": [False, True],
    })


def test_gate_mask_single_best_keeps_lowest_risk_60pct():
    events = factor_ranks(make_events(), ["volatility_ratio_short_long"])
    mask, status = gate_mask(events, make_factors(1), "P4_BREAKOUT_TOP20", "G1_SINGLE_BEST_PATH_SAFETY")
    assert status == "usable"
    assert mask.sum() == 6
    assert set(events.loc[mask, "event_id"]) == {"e4", "e5", "e6", "e7", "e8", "e9"}


def test_gate_unavailable_for_missing_consensus_factors():
    events = factor_ranks(make_events(), ["volatility_ratio_short_long"])
    mask, status = gate_mask(events, make_factors(1), "P4_BREAKOUT_TOP20", "G2_CONSENSUS_TWO_FACTORS")
    assert status == "gate_unavailable"
    assert mask.sum() == 0


def test_acceptance_rate_statuses():
    assert coverage_status("G2_CONSENSUS_TWO_FACTORS", "gate_unavailable", 0.0) == "gate_unavailable"
    assert coverage_status("G1_SINGLE_BEST_PATH_SAFETY", "usable", 0.1) == "too_restrictive"
    assert coverage_status("G1_SINGLE_BEST_PATH_SAFETY", "usable", 0.6) == "usable"


def test_failure_case_rejection_rate_formula():
    accepted = {"e1", "e2"}
    failures = {"e2", "e3", "e4"}
    rate = len(failures - accepted) / len(failures)
    assert rate == 2 / 3


def test_g4_downshifts_without_filtering():
    assert downshift_leverage("fixed_10x", 10.0, True) == (5.0, "g4_fixed_10x_to_5x")
    assert downshift_leverage("fixed_20x", 20.0, True) == (8.0, "g4_fixed_20x_to_8x")
    assert downshift_leverage("adaptive_4x_10x_v1", 10.0, True) == (5.0, "g4_adaptive_cap_50pct")
    events = factor_ranks(make_events(), ["volatility_ratio_short_long"])
    high_risk = high_risk_mask(events, make_factors(1), "P4_BREAKOUT_TOP20")
    assert high_risk.sum() == 4


def test_liquidation_model_reused_in_gate_simulation():
    assert liquidation_price(100, 10, 0.005) == 90.5
    trades = make_trades().iloc[[1]].copy()
    sim, _, _ = simulate_gate_leverage_path(trades, "ETHUSDT", "P4_BREAKOUT_TOP20", "G0_NO_PATH_GATE", "fixed_10x")
    assert bool(sim.iloc[0]["liquidation"])
    assert sim.iloc[0]["risk_event"] == "liquidation_price"


def test_incremental_risk_reduction_calculation():
    base = pd.Series({"trade_count": 100, "liquidation_count": 2, "max_drawdown": -0.6, "profit_factor": 1.2, "total_return": 10.0})
    gated = pd.Series({"trade_count": 80, "liquidation_count": 0, "max_drawdown": -0.3, "profit_factor": 1.1, "total_return": 5.0})
    assert risk_reduction_status(base, gated) == "clear_risk_reduction"
    summary = pd.DataFrame([
        {"symbol": "ETHUSDT", "prototype": "P4_BREAKOUT_TOP20", "leverage_mode": "fixed_10x", "gate": "G0_NO_PATH_GATE", "trade_count": 100, "liquidation_count": 2, "max_drawdown": -0.6, "profit_factor": 1.2, "total_return": 10.0},
        {"symbol": "ETHUSDT", "prototype": "P4_BREAKOUT_TOP20", "leverage_mode": "fixed_10x", "gate": "G1_SINGLE_BEST_PATH_SAFETY", "trade_count": 80, "liquidation_count": 0, "max_drawdown": -0.3, "profit_factor": 1.1, "total_return": 5.0},
    ])
    out = build_incremental(summary)
    assert out.iloc[0]["liquidation_reduction"] == 2


def test_pressure_stress_can_shift_liquidation_price():
    trades = make_trades().iloc[[0]].copy()
    base, _, _ = simulate_gate_leverage_path(trades, "ETHUSDT", "P4_BREAKOUT_TOP20", "G0_NO_PATH_GATE", "fixed_10x")
    stressed, _, _ = simulate_gate_leverage_path(
        trades,
        "ETHUSDT",
        "P4_BREAKOUT_TOP20",
        "G0_NO_PATH_GATE",
        "fixed_10x",
        stress=StressConfig("liquidation_price_up_20pct", liquidation_up_shift=0.20),
    )
    assert stressed.iloc[0]["liquidation_price"] > base.iloc[0]["liquidation_price"]


def test_h3_decision_rule_candidate():
    row = pd.Series({
        "symbol": "ETHUSDT",
        "gate": "G1_SINGLE_BEST_PATH_SAFETY",
        "trade_count": 60,
        "profit_factor": 1.5,
        "max_drawdown": -0.2,
        "liquidation_count": 0,
    })
    status, next_step = h3_decision_status(row, stress_liq=0, acceptance_rate=0.5, cross_ok=True)
    assert status == "candidate_for_H4_oos_or_finer_data_validation"
    assert next_step == "H4_new_data_or_1s_validation"


def test_run_log_required_fields_complete():
    assert validate_run_log_row({
        "config_hash": "a",
        "data_hash": "b",
        "git_commit": "c",
        "run_timestamp": "2026-06-28T00:00:00+00:00",
        "random_seed": 20260624,
        "data_layer": "high_leverage_research",
    })
