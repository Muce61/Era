import numpy as np
import pandas as pd

from research_core.second_alpha_source_s2.candidate_event_study_s2 import IDLE_CANDIDATE
from research_core.second_alpha_source_s26.exit_window_validation import (
    EXIT_BUCKET,
    block_bootstrap,
    canonical_s2_validation,
    decision_summary,
    exit_window_events,
    ordinary_bootstrap,
    random_baseline,
    top_trade_dependency,
)


def _events(n=40):
    idx = pd.date_range("2025-01-01 00:15", periods=n, freq="15min", tz="UTC")
    rows = []
    symbols = ["ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT"]
    for i, ts in enumerate(idx):
        rows.append({
            "event_id": f"e{i}",
            "candidate": IDLE_CANDIDATE,
            "symbol": symbols[i % len(symbols)],
            "side": "long" if i % 2 == 0 else "short",
            "signal_time": ts,
            "execution_time": ts,
            "execution_open": 100.0,
            "p4_state_bucket": EXIT_BUCKET if i < n - 2 else "deep_idle",
            "trend_strength_atr": 0.8,
            "trend_strength_bucket": "0.5_1.0",
            "volatility_regime": "mid_vol",
            "fwd_ret_1": 0.001,
            "fwd_ret_4": 0.002,
            "fwd_ret_8": 0.003,
            "fwd_ret_16": 0.004 if i % 5 else -0.001,
            "fwd_ret_32": 0.005,
            "fwd_mae_16": -0.002,
            "fwd_mfe_16": 0.006,
            "plus_1atr_first_16": True,
            "minus_1atr_first_16": False,
            "ambiguous_touch_16": False,
            "mean_reversion_bars": 4.0,
        })
    return pd.DataFrame(rows)


def test_canonical_s2_missing_blocks():
    validation = canonical_s2_validation(pd.DataFrame())
    assert validation["canonical_validation_status"].iloc[0] == "blocked"


def test_idle_mr1_cannot_contain_p4_held_for_pass():
    events = _events()
    events.loc[0, "p4_state_bucket"] = "p4_held"
    validation = canonical_s2_validation(events)
    assert validation["canonical_validation_status"].iloc[0] == "blocked"
    assert validation["idle_mr1_p4_held_count"].iloc[0] == 1


def test_exit_window_filter_selects_after_exit_5_16_only():
    events = _events()
    selected = exit_window_events(events)
    assert set(selected["p4_state_bucket"]) == {EXIT_BUCKET}
    assert len(selected) == len(events) - 2


def test_random_baseline_uses_full_market_state_pool_not_candidate_only():
    events = exit_window_events(_events())
    pool = events.copy()
    pool["candidate"] = "RANDOM_POOL_MARKER"
    pool["is_candidate_event"] = False
    pool["fwd_ret_16"] = -0.01
    out = random_baseline(events, pool, runs=20, seed=1)
    assert out["pool_source"].iloc[0] == "full_market_state_pool"
    assert out["random_runs"].iloc[0] == 20
    assert out["random_mean"].iloc[0] < events["fwd_ret_16"].mean()


def test_bootstrap_positive_rate_and_block_types():
    events = exit_window_events(_events(80))
    boot = ordinary_bootstrap(events, runs=50, seed=2)
    by_month = block_bootstrap(events.assign(month=events["signal_time"].dt.to_period("M").astype(str)), "month", runs=50, seed=2)
    by_symbol = block_bootstrap(events, "symbol", runs=50, seed=2)
    assert boot["positive_rate"].iloc[0] >= 0
    assert by_month["block_type"].iloc[0] == "month"
    assert by_symbol["block_type"].iloc[0] == "symbol"


def test_top_trade_dependency_calculates_remove_top3():
    dep = top_trade_dependency(exit_window_events(_events(80)))
    assert "top1_positive_contribution" in dep.columns
    assert "remove_top3_mean_fwd_ret" in dep.columns


def test_s26_decision_rule_and_non_oos():
    events = exit_window_events(_events(400))
    validation = canonical_s2_validation(events)
    random = pd.DataFrame([{"percentile_vs_random": 0.75}])
    boot = pd.DataFrame([{"positive_rate": 0.8}])
    block = pd.DataFrame([{"block_type": "month", "positive_rate": 0.7}])
    dep = pd.DataFrame([{"top1_positive_contribution": 0.1, "remove_top3_mean_fwd_ret": 0.001}])
    vol = pd.DataFrame({"volatility_regime": ["low_vol", "mid_vol"], "mean_fwd_ret_16": [0.001, 0.002]})
    decision = decision_summary(validation, events, random, boot, block, dep, vol)
    assert decision["strategy_backtest_generated"].iloc[0] == False  # noqa: E712
    assert decision["oos_status"].iloc[0] == "not_oos"
    assert decision["decision_letter"].iloc[0] in {"A", "B", "C", "D", "E"}

