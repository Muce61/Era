import numpy as np
import pandas as pd

from research_core.second_alpha_source_s28.long_history_complement_validation import (
    decision_summary,
    input_validation,
    p4_correlation,
    period_summary,
    random_time_baseline_long_history,
    stress_summary,
    weak_month_overlap,
)


def _events(n=200):
    idx = pd.date_range("2021-01-01 00:15", periods=n, freq="15min", tz="UTC")
    symbols = ["ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT"]
    rows = []
    for i, ts in enumerate(idx):
        rows.append({
            "symbol": symbols[i % 4],
            "side": "long" if i % 3 else "short",
            "signal_time": ts,
            "month": ts.to_period("M").strftime("%Y-%m"),
            "quarter": ts.to_period("Q").strftime("%YQ%q"),
            "year": ts.year,
            "volatility_regime": "mid_vol",
            "trend_strength_bucket": "0.5_1.0",
            "p4_state_bucket": "after_p4_exit_5_16_bars",
            "bars_since_p4_exit_bucket": "after_p4_exit_5_16_bars",
            "fwd_ret_16": 0.002 if i % 7 else -0.001,
            "plus_1atr_first_16": True,
            "minus_1atr_first_16": False,
            "fwd_mae_16": -0.002,
            "fwd_mfe_16": 0.004,
            "data_layer": "expanded_discovery_long_history",
            "oos_status": "not_oos",
        })
    return pd.DataFrame(rows)


def test_input_validation_returns_pass_or_blocked():
    out = input_validation()
    assert out["input_validation_status"].iloc[0] in {"pass", "blocked"}


def test_long_history_data_not_marked_oos():
    events = _events()
    assert set(events["oos_status"]) == {"not_oos"}
    assert set(events["data_layer"]) == {"expanded_discovery_long_history"}


def test_p4_held_phase_not_present_in_exit_events():
    events = _events()
    assert "p4_held" not in set(events["p4_state_bucket"])


def test_monthly_correlation_insufficient_overlap_marked():
    events = _events(20)
    p4 = pd.DataFrame({
        "symbol": ["ETHUSDT"] * 3,
        "month": ["2021-01", "2021-02", "2021-03"],
        "p4_proxy_return": [0.01, -0.01, 0.0],
    })
    out = p4_correlation(events, p4)
    assert "insufficient_overlap" in set(out["corr_status"])


def test_weak_month_overlap_calculation():
    events = _events(80)
    p4 = pd.DataFrame({
        "symbol": ["ETHUSDT"] * 12,
        "month": [f"2021-{m:02d}" for m in range(1, 13)],
        "p4_proxy_return": [-0.01] * 12,
        "p4_negative_month": [True] * 12,
        "p4_weak_month": [True] * 12,
    })
    out = weak_month_overlap(events, p4)
    assert "s28_positive_in_p4_weak_month_rate" in out.columns
    assert "overlap_status" in out.columns


def test_random_time_baseline_accepts_full_market_state_pool(monkeypatch):
    events = _events(40)
    import research_core.second_alpha_source_s28.long_history_complement_validation as mod

    def fake_pool(data, symbol, config, horizon):
        pool = events[events["symbol"] == symbol].copy()
        pool["fwd_ret_16"] = -0.002
        return pool

    monkeypatch.setattr(mod, "build_market_state_pool_s2", fake_pool)
    data_by_symbol = {s: pd.DataFrame() for s in events["symbol"].unique()}
    out = random_time_baseline_long_history(events, data_by_symbol, runs=20, seed=1)
    assert "fallback_match_rate" in out.columns
    assert out["random_runs"].eq(20).all()


def test_remove_best_year_stress_case_exists():
    events = _events(300)
    stress = stress_summary(events)
    assert "remove_best_year" in set(stress["stress_case"])


def test_s28_no_strategy_backtest_and_decision_rule():
    events = _events(400)
    summary = events.groupby("symbol")["fwd_ret_16"].mean().reset_index(name="mean_fwd_ret_16")
    yearly = period_summary(events, "year")
    quarterly = period_summary(events, "quarter")
    random_time = pd.DataFrame({"percentile_vs_random_time": [0.8], "fallback_match_rate": [0.0]})
    stress = stress_summary(events)
    corr = pd.DataFrame({"corr_status": ["low_corr"]})
    overlap = pd.DataFrame({
        "s28_positive_in_p4_negative_month_rate": [0.5],
        "s28_positive_in_p4_weak_month_rate": [0.5],
    })
    input_val = pd.DataFrame({"input_validation_status": ["pass"]})
    decision = decision_summary(input_val, events, summary, yearly, quarterly, random_time, stress, corr, overlap)
    assert decision["strategy_backtest_generated"].iloc[0] == False  # noqa: E712
    assert decision["oos_status"].iloc[0] == "not_oos"
    assert decision["decision_letter"].iloc[0] in {"A", "B", "C", "D", "E"}

