import numpy as np
import pandas as pd

from research_core.second_alpha_source_s25.idle_mr1_state_breakdown import (
    add_trend_strength_bucket,
    blocked_strategy_summary,
    breakdown,
    failure_case_sample,
    random_baseline_diagnostics,
    simulate_p4_phase,
)


def _minute_data(minutes=90, start_price=100.0):
    idx = pd.date_range("2025-01-01 00:00", periods=minutes, freq="1min", tz="UTC")
    base = np.full(minutes, start_price)
    return pd.DataFrame({
        "open": base,
        "high": base + 1,
        "low": base - 1,
        "close": base,
        "volume": np.ones(minutes),
    }, index=idx)


def test_p4_held_state_persists_until_donchian_exit_without_future():
    data = _minute_data(4500)
    # Flat warmup, then a clean breakout above prior Donchian, then a sharp drop exits.
    data["close"] = 100.0
    data.iloc[3300:3900, data.columns.get_loc("close")] = 140.0
    data["open"] = data["close"]
    data["high"] = data["close"] + 1
    data["low"] = data["close"] - 1
    data.iloc[-600:, data.columns.get_loc("close")] = 80
    data.iloc[-600:, data.columns.get_loc("open")] = 80
    data.iloc[-600:, data.columns.get_loc("high")] = 81
    data.iloc[-600:, data.columns.get_loc("low")] = 79
    phase = simulate_p4_phase(data)
    assert phase["p4_held"].any()
    held_idx = phase.index[phase["p4_held"]]
    assert held_idx.min() < held_idx.max()
    assert (phase.loc[held_idx, "p4_phase"] == "p4_held").any()


def test_after_exit_and_deep_idle_labels_are_defined_from_past_only():
    data = _minute_data(6000)
    data["close"] = 100.0
    data.iloc[3300:3900, data.columns.get_loc("close")] = 140.0
    data.iloc[3900:4500, data.columns.get_loc("close")] = 80.0
    data.iloc[4500:, data.columns.get_loc("close")] = 95.0
    data["open"] = data["close"]
    data["high"] = data["close"] + 1
    data["low"] = data["close"] - 1
    phase = simulate_p4_phase(data)
    assert "after_p4_exit_0_4_bars" in set(phase["p4_phase"])
    assert "deep_idle" in set(phase["p4_phase"])


def _sample_events():
    idx = pd.date_range("2025-01-01", periods=8, freq="15min", tz="UTC")
    return pd.DataFrame({
        "event_id": [f"e{i}" for i in range(8)],
        "symbol": ["ETHUSDT", "ETHUSDT", "BTCUSDT", "BTCUSDT", "SOLUSDT", "SOLUSDT", "BNBUSDT", "BNBUSDT"],
        "side": ["long", "short"] * 4,
        "signal_time": idx,
        "execution_time": idx,
        "execution_open": np.arange(8) + 100,
        "p4_phase": ["deep_idle", "deep_idle", "after_p4_exit_0_4_bars", "after_p4_exit_0_4_bars", "deep_idle", "unknown", "deep_idle", "unknown"],
        "trend_strength_atr": [0.1, 0.6, 1.2, 2.0, 3.0, 0.4, 0.8, 1.4],
        "volatility_regime": ["low_vol", "mid_vol", "high_vol", "low_vol", "mid_vol", "high_vol", "low_vol", "mid_vol"],
        "deviation_ema20_atr": np.linspace(-2, 2, 8),
        "fwd_ret_1": np.linspace(-0.01, 0.01, 8),
        "fwd_ret_4": np.linspace(-0.02, 0.02, 8),
        "fwd_ret_8": np.linspace(-0.03, 0.03, 8),
        "fwd_ret_16": [-0.05, 0.02, -0.03, 0.01, -0.02, 0.03, -0.01, 0.04],
        "fwd_ret_32": np.linspace(-0.04, 0.04, 8),
        "fwd_mae_16": [-0.10, -0.02, -0.08, -0.03, -0.07, -0.01, -0.06, -0.02],
        "fwd_mfe_16": [0.01, 0.05, 0.02, 0.04, 0.03, 0.06, 0.02, 0.07],
        "plus_1atr_first_16": [False, True, False, True, False, True, False, True],
        "minus_1atr_first_16": [True, False, True, False, True, False, True, False],
        "subsequent_trend_breakout": [True, False, True, False, True, False, True, False],
    })


def test_side_and_symbol_breakdown_statistics():
    events = _sample_events()
    side = breakdown(events, ["side"])
    symbol = breakdown(events, ["symbol"])
    assert set(side["side"]) == {"long", "short"}
    assert set(symbol["symbol"]) == {"ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT"}
    assert "remove_top3_mean_fwd_ret" in side.columns


def test_failure_sample_contains_worst_return_worst_mae_and_minus_samples():
    sample = failure_case_sample(_sample_events(), seed=1)
    reasons = set(sample["sample_reason"])
    assert "worst_return" in reasons
    assert "worst_mae" in reasons
    assert "minus_1atr_random" in reasons


def test_random_baseline_diagnostics_reports_fallback_rate():
    events = add_trend_strength_bucket(_sample_events())
    diag = random_baseline_diagnostics(events)
    assert "fallback_match_rate" in diag.columns
    assert "unmatched_event_count" in diag.columns
    assert (diag["group"] == "overall").any()


def test_s25_blocks_strategy_backtest_and_is_not_oos():
    blocked = blocked_strategy_summary()
    row = blocked.iloc[0]
    assert row["status"] == "blocked_event_research_only"
    assert row["oos_status"] == "not_oos"
    assert row["deployable_strategy_generated"] == False  # noqa: E712
