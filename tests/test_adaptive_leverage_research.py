import pandas as pd

from research_core.common import validate_run_log_row
from research_core.leverage_research_analysis import (
    StressConfig,
    adaptive_leverage,
    apply_stress_prices,
    liquidation_price,
    shifted_liquidation_price,
    simulate_leverage_path,
)


def make_trades():
    return pd.DataFrame({
        "event_id": ["e1"],
        "entry_time": ["2024-01-01 00:01:00+00:00"],
        "exit_time": ["2024-01-01 01:00:00+00:00"],
        "entry_price": [100.0],
        "exit_price": [110.0],
        "atr": [1.0],
        "mae_atr": [-1.0],
        "mfe_atr": [20.0],
        "atr_pct": [0.01],
        "atr_pct_rank": [0.5],
        "breakout_score_quantile": [0.9],
    })


def test_fixed_10x_20x_position_effect():
    trades = make_trades()
    sim10, _, _ = simulate_leverage_path(trades, "ETHUSDT", "P4_BREAKOUT_TOP20", "fixed_10x")
    sim20, _, _ = simulate_leverage_path(trades, "ETHUSDT", "P4_BREAKOUT_TOP20", "fixed_20x")
    assert sim10.iloc[0]["leverage"] == 10
    assert sim20.iloc[0]["leverage"] == 20
    assert sim20.iloc[0]["net_pnl"] > sim10.iloc[0]["net_pnl"]


def test_liquidation_price_formula():
    assert liquidation_price(100, 10, 0.005) == 90.5
    assert shifted_liquidation_price(100, 10, 0.10) > liquidation_price(100, 10)


def test_liquidation_sets_equity_to_five_percent():
    trades = make_trades()
    trades["mae_atr"] = -20.0
    sim, equity, _ = simulate_leverage_path(trades, "ETHUSDT", "P4_BREAKOUT_TOP20", "fixed_20x")
    assert bool(sim.iloc[0]["liquidation"])
    assert equity.iloc[-1]["equity"] == 50.0


def test_account_floor_after_costs_is_marked_as_liquidation():
    trades = make_trades()
    trades["exit_price"] = 94.0
    trades["mae_atr"] = -1.0
    sim, equity, _ = simulate_leverage_path(trades, "ETHUSDT", "P4_BREAKOUT_TOP20", "fixed_20x")
    assert bool(sim.iloc[0]["liquidation"])
    assert sim.iloc[0]["risk_event"] == "account_floor_after_costs"
    assert equity.iloc[-1]["equity"] == 50.0


def test_adaptive_high_atr_lowers_to_8x():
    lev, reason = adaptive_leverage("P4_BREAKOUT_TOP20", 0.9, 0.9, 0.0, 0)
    assert lev == 8
    assert reason == "atr_pct_rank_gt_80pct"


def test_adaptive_drawdown_rules():
    assert adaptive_leverage("P4_BREAKOUT_TOP20", 0.9, 0.5, 0.11, 0)[0] == 6
    assert adaptive_leverage("P4_BREAKOUT_TOP20", 0.9, 0.5, 0.21, 0)[0] == 3


def test_adaptive_recent_losses_rule():
    lev, reason = adaptive_leverage("P4_BREAKOUT_TOP20", 0.9, 0.5, 0.0, 3)
    assert lev == 5
    assert reason == "recent_3_losses"


def test_adaptive_raise_to_20x():
    lev, reason = adaptive_leverage("P6_MOMENTUM_OR_BREAKOUT_TOP20", 0.9, 0.5, 0.0, 0)
    assert lev == 20
    assert reason == "all_raise_conditions_met"


def test_stress_modifies_cost_or_delay():
    trade = make_trades().iloc[0]
    entry, exit_price = apply_stress_prices(trade, StressConfig("entry_delay_3m", entry_delay_minutes=3))
    assert entry > trade["entry_price"]
    entry2, exit2 = apply_stress_prices(trade, StressConfig("exit_delay_3m", exit_delay_minutes=3))
    assert exit2 < trade["exit_price"]


def test_run_log_required_fields_complete():
    assert validate_run_log_row({
        "config_hash": "a",
        "data_hash": "b",
        "git_commit": "c",
        "run_timestamp": "2026-06-27T00:00:00+00:00",
        "random_seed": 20260624,
        "data_layer": "leverage_research",
    })
