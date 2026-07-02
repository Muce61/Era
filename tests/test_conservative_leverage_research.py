import pandas as pd

from research_core.common import validate_run_log_row
from research_core.leverage_research_analysis import (
    StressConfig,
    adaptive_leverage_by_mode,
    apply_stress_prices,
    liquidation_price,
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


def test_fixed_3x_5x_8x_10x_position_effect():
    trades = make_trades()
    sims = {}
    for mode in ["fixed_3x", "fixed_5x", "fixed_8x", "fixed_10x"]:
        sim, _, _ = simulate_leverage_path(trades, "ETHUSDT", "P4_BREAKOUT_TOP20", mode)
        sims[mode] = sim.iloc[0]
    assert sims["fixed_3x"]["leverage"] == 3
    assert sims["fixed_5x"]["leverage"] == 5
    assert sims["fixed_8x"]["leverage"] == 8
    assert sims["fixed_10x"]["leverage"] == 10
    assert sims["fixed_10x"]["net_pnl"] > sims["fixed_8x"]["net_pnl"] > sims["fixed_5x"]["net_pnl"]


def test_adaptive_3x_8x_raises_to_8x():
    lev, reason, base = adaptive_leverage_by_mode("adaptive_3x_8x_v1", "P4_BREAKOUT_TOP20", 0.9, 0.5, 0.0, 0)
    assert (lev, reason, base) == (8, "all_raise_conditions_met", 3)


def test_adaptive_4x_10x_raises_to_10x():
    lev, reason, base = adaptive_leverage_by_mode("adaptive_4x_10x_v1", "P6_MOMENTUM_OR_BREAKOUT_TOP20", 0.9, 0.5, 0.0, 0)
    assert (lev, reason, base) == (10, "all_raise_conditions_met", 4)


def test_adaptive_5x_12x_raises_to_12x():
    lev, reason, base = adaptive_leverage_by_mode("adaptive_5x_12x_v1", "P4_BREAKOUT_TOP20", 0.9, 0.5, 0.0, 0)
    assert (lev, reason, base) == (12, "all_raise_conditions_met", 5)


def test_l2_high_atr_lowers_leverage():
    assert adaptive_leverage_by_mode("adaptive_3x_8x_v1", "P4_BREAKOUT_TOP20", 0.9, 0.9, 0.0, 0)[0] == 2
    assert adaptive_leverage_by_mode("adaptive_4x_10x_v1", "P4_BREAKOUT_TOP20", 0.9, 0.9, 0.0, 0)[0] == 3
    assert adaptive_leverage_by_mode("adaptive_5x_12x_v1", "P4_BREAKOUT_TOP20", 0.9, 0.9, 0.0, 0)[0] == 3


def test_l2_drawdown_rules():
    assert adaptive_leverage_by_mode("adaptive_3x_8x_v1", "P4_BREAKOUT_TOP20", 0.9, 0.5, 0.11, 0)[0] == 2
    assert adaptive_leverage_by_mode("adaptive_3x_8x_v1", "P4_BREAKOUT_TOP20", 0.9, 0.5, 0.21, 0)[0] == 1
    assert adaptive_leverage_by_mode("adaptive_5x_12x_v1", "P4_BREAKOUT_TOP20", 0.9, 0.5, 0.21, 0)[0] == 1


def test_l2_recent_losses_rule():
    lev, reason, _ = adaptive_leverage_by_mode("adaptive_4x_10x_v1", "P4_BREAKOUT_TOP20", 0.9, 0.5, 0.0, 3)
    assert lev == 2
    assert reason == "recent_3_losses"


def test_liquidation_price_formula_unchanged():
    assert liquidation_price(100, 5, 0.005) == 80.5


def test_account_floor_prevents_negative_equity():
    trades = make_trades()
    trades["exit_price"] = 78.0
    trades["mae_atr"] = -1.0
    sim, equity, _ = simulate_leverage_path(trades, "ETHUSDT", "P4_BREAKOUT_TOP20", "fixed_5x")
    assert bool(sim.iloc[0]["liquidation"])
    assert sim.iloc[0]["risk_event"] == "account_floor_after_costs"
    assert equity.iloc[-1]["equity"] == 50.0
    assert (equity["equity"] >= 0).all()


def test_stress_modifies_cost_or_delay():
    trade = make_trades().iloc[0]
    entry, exit_price = apply_stress_prices(trade, StressConfig("entry_delay_1m", entry_delay_minutes=1))
    assert entry > trade["entry_price"]
    entry2, exit2 = apply_stress_prices(trade, StressConfig("exit_delay_1m", exit_delay_minutes=1))
    assert exit2 < trade["exit_price"]
    assert entry2 == trade["entry_price"]


def test_run_log_required_fields_complete():
    assert validate_run_log_row({
        "config_hash": "a",
        "data_hash": "b",
        "git_commit": "c",
        "run_timestamp": "2026-06-27T00:00:00+00:00",
        "random_seed": 20260624,
        "data_layer": "leverage_research",
    })
