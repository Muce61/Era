import numpy as np
import pandas as pd

from research_core.second_alpha_source_s3.minimal_strategy_prototype import (
    CANDIDATE,
    EXIT_BUCKET,
    S3Params,
    decision_summary,
    quantity_for_sizing,
    replay_exit,
    run_backtest_for_symbol,
)


def _data_1m(periods=300, start="2021-01-01 00:00"):
    idx = pd.date_range(start, periods=periods, freq="1min", tz="UTC")
    price = 100 + np.linspace(0, 1, periods)
    return pd.DataFrame({
        "open": price,
        "high": price + 0.2,
        "low": price - 0.2,
        "close": price,
        "volume": 1.0,
    }, index=idx)


def _data_15m(data):
    idx = pd.date_range(data.index[15], periods=20, freq="15min", tz="UTC")
    return pd.DataFrame({
        "open": 100,
        "high": 101,
        "low": 99,
        "close": 100,
        "donchian55_upper": 110,
        "ema50": 101,
        "ema200": 100,
        "atr14": 1,
    }, index=idx)


def _event(ts, side="long"):
    return pd.Series({
        "event_id": f"e_{side}_{ts.isoformat()}",
        "candidate": CANDIDATE,
        "symbol": "ETHUSDT",
        "signal_time": ts,
        "execution_time": ts,
        "execution_open": 100.0,
        "side": side,
        "atr14": 1.0,
        "ema20": 100.5 if side == "long" else 99.5,
        "range_mid": 100.7 if side == "long" else 99.3,
        "p4_state_bucket": EXIT_BUCKET,
    })


def test_s3_fixed_definition_constants():
    assert CANDIDATE == "IDLE_MR1_P4_IDLE_REVERSION"
    assert EXIT_BUCKET == "after_p4_exit_5_16_bars"


def test_quantity_fixed_1x_and_fixed_risk_caps_at_1x():
    params = S3Params(initial_balance=1000, max_leverage=1.0)
    assert quantity_for_sizing(1000, 100, 1, "fixed_1x", params) == 10
    assert quantity_for_sizing(1000, 100, 0.1, "fixed_risk_0_5pct", params) == 10
    assert quantity_for_sizing(1000, 100, 10, "fixed_risk_0_5pct", params) == 0.5


def test_long_atr_stop_and_mean_exit():
    data = _data_1m(20)
    ts = data.index[1]
    event = _event(ts, "long")
    event["ema20"] = 100.1
    out = replay_exit(event, data, set(), "long", ts, 100.0, 1.0)
    assert out[2] == "mean_exit"
    data2 = data.copy()
    data2.loc[ts, "low"] = 98.5
    event["ema20"] = 105
    out2 = replay_exit(event, data2, set(), "long", ts, 100.0, 1.0)
    assert out2[2] == "atr_stop"


def test_short_atr_stop_and_mean_exit():
    data = _data_1m(20)
    ts = data.index[1]
    event = _event(ts, "short")
    event["ema20"] = 99.9
    out = replay_exit(event, data, set(), "short", ts, 100.0, 1.0)
    assert out[2] == "mean_exit"
    data2 = data.copy()
    data2.loc[ts, "high"] = 101.5
    event["ema20"] = 95
    out2 = replay_exit(event, data2, set(), "short", ts, 100.0, 1.0)
    assert out2[2] == "atr_stop"


def test_same_bar_stop_and_mean_uses_conservative_price():
    data = _data_1m(20)
    ts = data.index[1]
    data.loc[ts, "low"] = 98.5
    data.loc[ts, "high"] = 101.0
    event = _event(ts, "long")
    event["ema20"] = 100.5
    out = replay_exit(event, data, set(), "long", ts, 100.0, 1.0)
    assert out[2] == "stop_and_mean_conservative"
    assert out[1] == 99.0


def test_time_stop_and_trend_restart_exit():
    data = _data_1m(300)
    ts = data.index[1]
    event = _event(ts, "long")
    event["ema20"] = 500
    event["range_mid"] = 500
    out = replay_exit(event, data, set(), "long", ts, 100.0, 1.0)
    assert out[2] in {"time_stop", "atr_stop"}
    short_event = _event(ts, "short")
    short_event["ema20"] = 50
    short_event["range_mid"] = 50
    out2 = replay_exit(short_event, data, {ts + pd.Timedelta(minutes=3)}, "short", ts, 100.0, 10.0)
    assert out2[2] == "trend_restart_exit"


def test_run_backtest_no_overlapping_positions_and_fee_accounting():
    data = _data_1m(300)
    data15 = _data_15m(data)
    ts = data.index[15]
    events = pd.DataFrame([_event(ts, "long"), _event(ts + pd.Timedelta(minutes=1), "long")])
    trades, equity, conv = run_backtest_for_symbol(events, data, data15, "ETHUSDT", "fixed_1x", "both")
    assert len(trades) == 1
    assert (conv["status"] == "ignored_due_to_position").sum() == 1
    assert trades["total_fee"].iloc[0] > 0
    assert equity["equity"].iloc[-1] != 1000


def test_decision_rule_non_oos():
    summary = pd.DataFrame([{
        "symbol": "ALL",
        "side_scope": "both",
        "sizing_mode": "fixed_1x",
        "trade_count": 250,
        "profit_factor": 1.2,
        "max_drawdown": -0.1,
        "top1_profit_contribution": 0.1,
    }, {
        "symbol": "ETHUSDT",
        "side_scope": "both",
        "sizing_mode": "fixed_1x",
        "trade_count": 50,
        "profit_factor": 1.1,
        "max_drawdown": -0.1,
        "top1_profit_contribution": 0.1,
    }, {
        "symbol": "SOLUSDT",
        "side_scope": "both",
        "sizing_mode": "fixed_1x",
        "trade_count": 50,
        "profit_factor": 1.2,
        "max_drawdown": -0.1,
        "top1_profit_contribution": 0.1,
    }])
    tail = pd.DataFrame({"symbol": ["ALL"], "sizing_mode": ["fixed_1x"], "remove_best_3_trades_return": [0.01]})
    comp = pd.DataFrame({"symbol": ["ALL"], "s3_positive_in_p4_weak_month_rate": [0.5], "monthly_corr_with_p4": [0.1]})
    out = decision_summary(summary, tail, comp)
    assert out["oos_status"].iloc[0] == "not_oos"
    assert out["decision_letter"].iloc[0] == "A"

