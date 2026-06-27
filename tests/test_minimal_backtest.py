import numpy as np
import pandas as pd

from research_core.common import validate_run_log_row
from research_core.minimal_backtest_analysis import (
    BacktestParams,
    event_to_trade_consistency,
    fixed_2x_quantity,
    fixed_risk_quantity,
    prepare_market_data,
    prototype_event_frames,
    recompute_walk_forward_scores,
    run_prototype_backtest,
    simulate_exit,
    trade_tail_dependence,
    walk_forward_backtest,
)


def make_market():
    idx = pd.date_range("2024-01-01 00:00", periods=180, freq="1min", tz="UTC")
    close = np.linspace(100, 120, len(idx))
    df = pd.DataFrame({
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 1.0,
    }, index=idx)
    data_15m = df.resample("15min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    data_15m["donchian20_lower"] = 80.0
    return df, data_15m


def make_events(n=8):
    ts = pd.date_range("2024-01-01 00:15", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({
        "event_id": [f"e{i}" for i in range(n)],
        "signal_time": ts,
        "execution_time": ts + pd.Timedelta(minutes=1),
        "execution_open": 100 + np.arange(n),
        "atr14": 2.0,
        "first_breakout_after_flat": [i % 2 == 0 for i in range(n)],
        "strong_breakout": [i % 3 == 0 for i in range(n)],
    })


def make_scores(n=8):
    q = pd.Series(np.arange(1, n + 1) / n)
    return pd.DataFrame({"momentum_score_quantile": q, "breakout_score_quantile": q})


def test_prototype_event_frames_do_not_drop_baselines():
    frames = prototype_event_frames(make_events(), make_scores())
    assert "P0_ALL_TREND_CONTEXT" in frames
    assert "P1_C1_FIRST_BREAKOUT" in frames
    assert "P2_STRONG_BREAKOUT" in frames


def test_next_1m_open_and_no_overlapping_positions():
    data_1m, data_15m = make_market()
    events = make_events(5)
    params = BacktestParams(initial_balance=1000, leverage=2, fee_rate=0, slippage_rate=0, atr_stop_mult=3)
    trades, _ = run_prototype_backtest(events, data_1m, data_15m, params, "P0_ALL_TREND_CONTEXT", "fixed_2x")
    assert not trades.empty
    assert trades.iloc[0]["entry_time"] == pd.Timestamp("2024-01-01 00:16", tz="UTC")
    assert (pd.to_datetime(trades["entry_time"], utc=True).diff().dropna() > pd.Timedelta(0)).all()


def test_atr_stop_triggers_correctly():
    data_1m, data_15m = make_market()
    entry_time = pd.Timestamp("2024-01-01 00:16", tz="UTC")
    data_1m.loc[pd.Timestamp("2024-01-01 00:17", tz="UTC"), "low"] = 90
    exit_time, exit_price, reason, _, _ = simulate_exit(
        data_1m, data_15m, entry_time, pd.Timestamp("2024-01-01 00:15", tz="UTC"), 100, 94, 2
    )
    assert exit_time == pd.Timestamp("2024-01-01 00:17", tz="UTC")
    assert exit_price == 94
    assert reason == "atr_stop"


def test_donchian20_exit_triggers_correctly():
    data_1m, data_15m = make_market()
    data_15m.loc[pd.Timestamp("2024-01-01 00:30", tz="UTC"), "close"] = 70
    data_15m.loc[pd.Timestamp("2024-01-01 00:30", tz="UTC"), "donchian20_lower"] = 80
    exit_time, _, reason, _, _ = simulate_exit(
        data_1m, data_15m, pd.Timestamp("2024-01-01 00:16", tz="UTC"), pd.Timestamp("2024-01-01 00:15", tz="UTC"), 100, 50, 2
    )
    assert exit_time == pd.Timestamp("2024-01-01 00:30", tz="UTC")
    assert reason == "donchian20_exit"


def test_sizing_formulas():
    assert fixed_2x_quantity(1000, 100, 2) == 20
    assert fixed_risk_quantity(1000, 100, 90, 2, 0.005) == 0.5


def test_fee_and_slippage_change_entry_price():
    data_1m, data_15m = make_market()
    params = BacktestParams(initial_balance=1000, leverage=2, fee_rate=0.001, slippage_rate=0.01, atr_stop_mult=3)
    trades, _ = run_prototype_backtest(make_events(1), data_1m, data_15m, params, "P0_ALL_TREND_CONTEXT", "fixed_2x")
    assert trades.iloc[0]["entry_price"] > trades.iloc[0]["entry_raw_price"]
    assert trades.iloc[0]["total_fee"] > 0


def test_signal_to_trade_conversion_rate():
    r7 = pd.DataFrame({"prototype": ["P0_ALL_TREND_CONTEXT"], "horizon": [16], "event_count": [10], "mean_fwd_ret": [0.01]})
    summary = pd.DataFrame({"prototype": ["P0_ALL_TREND_CONTEXT"], "sizing_mode": ["fixed_2x"], "trade_count": [5], "total_return": [0.1]})
    monthly = pd.DataFrame({"prototype": ["P0_ALL_TREND_CONTEXT"], "sizing_mode": ["fixed_2x"], "return": [0.1]})
    out = event_to_trade_consistency(r7, summary, monthly)
    assert out.iloc[0]["signal_to_trade_conversion_rate"] == 0.5


def test_tail_dependence_removes_best_trade():
    trades = pd.DataFrame({
        "prototype": ["P"] * 40,
        "sizing_mode": ["fixed_2x"] * 40,
        "exit_time": pd.date_range("2024-01-01", periods=40, freq="D", tz="UTC"),
        "net_pnl": [100] + [1] * 39,
    })
    out = trade_tail_dependence(trades, 1000)
    assert out.iloc[0]["remove_best_1_trade_return"] < out.iloc[0]["original_total_return"]


def test_walk_forward_score_standardization_uses_train_window():
    train = pd.DataFrame({"ret_4h": [1, 2, 3], "ret_12h": [1, 2, 3], "ret_24h": [1, 2, 3], "breakout_distance_atr": [1, 2, 3], "range_atr": [1, 2, 3], "body_ratio": [1, 2, 3], "close_location": [1, 2, 3]})
    test = pd.DataFrame({"ret_4h": [100, 101], "ret_12h": [100, 101], "ret_24h": [100, 101], "breakout_distance_atr": [100, 101], "range_atr": [100, 101], "body_ratio": [100, 101], "close_location": [100, 101]})
    meta = pd.DataFrame({"factor": ["ret_4h", "ret_12h", "ret_24h", "breakout_distance_atr", "range_atr", "body_ratio", "close_location"], "direction": [1, 1, 1, 1, 1, 1, 1]})
    scores = recompute_walk_forward_scores(train, test, meta)
    assert set(scores.columns) == {"momentum_score_quantile", "breakout_score_quantile"}


def test_walk_forward_outputs_independent_windows():
    data_1m, data_15m = make_market()
    events = make_events(20)
    for col in ["ret_4h", "ret_12h", "ret_24h", "breakout_distance_atr", "range_atr", "body_ratio", "close_location"]:
        events[col] = np.arange(len(events))
    meta = pd.DataFrame({"factor": ["ret_4h", "ret_12h", "ret_24h", "breakout_distance_atr", "range_atr", "body_ratio", "close_location"], "direction": [1, 1, 1, 1, 1, 1, 1]})
    windows, summary = walk_forward_backtest(events, meta, data_1m, data_15m, BacktestParams())
    assert set(summary["walk_forward_status"]).issubset({"wf_pass", "wf_weak", "wf_fail", "insufficient_sample"})


def test_run_log_required_fields_complete():
    assert validate_run_log_row({
        "config_hash": "a",
        "data_hash": "b",
        "git_commit": "c",
        "run_timestamp": "2026-06-27T00:00:00+00:00",
        "random_seed": 20260624,
        "data_layer": "discovery",
    })
