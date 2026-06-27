import pandas as pd

from research_core.high_leverage_gate_analysis import build_fixed_gate_thresholds, gate_mask_fixed
from research_core.strict_high_leverage_replay import downside_exit_from_bar, strict_replay_events


def test_fixed_gate_threshold_uses_discovery_value_not_holdout_rank():
    discovery = pd.DataFrame({
        "prototype": ["P4_BREAKOUT_TOP20"] * 5,
        "factor_a": [1, 2, 3, 4, 5],
    })
    factors = pd.DataFrame({
        "prototype": ["P4_BREAKOUT_TOP20"],
        "factor": ["factor_a"],
        "safe20_edge": [1.0],
    })
    thresholds = build_fixed_gate_thresholds(discovery, factors)
    holdout = pd.DataFrame({
        "prototype": ["P4_BREAKOUT_TOP20"] * 5,
        "factor_a": [100, 101, 102, 103, 104],
    })
    mask, status = gate_mask_fixed(holdout, factors, thresholds, "P4_BREAKOUT_TOP20", "G1_SINGLE_BEST_PATH_SAFETY")
    assert status == "usable"
    assert mask.tolist() == [True, True, True, True, True]


def test_downside_exit_prefers_higher_trigger_on_long_path():
    assert downside_exit_from_bar(low=94, stop_loss=90, liquidation_price=95) == ("liquidation_price", 95)
    assert downside_exit_from_bar(low=94, stop_loss=95, liquidation_price=90) == ("atr_stop", 95)
    assert downside_exit_from_bar(low=96, stop_loss=95, liquidation_price=90) is None


def test_strict_replay_liquidates_from_1m_low():
    idx = pd.date_range("2024-01-01 00:00", periods=6, freq="1min", tz="UTC")
    data_1m = pd.DataFrame({
        "open": [100, 100, 100, 100, 100, 100],
        "high": [101, 101, 101, 101, 101, 101],
        "low": [99, 99, 94, 99, 99, 99],
        "close": [100, 100, 100, 100, 100, 100],
        "volume": [1, 1, 1, 1, 1, 1],
    }, index=idx)
    data_15m = pd.DataFrame({
        "close": [100],
        "donchian20_lower": [80],
    }, index=pd.DatetimeIndex([pd.Timestamp("2024-01-01 00:05", tz="UTC")]))
    events = pd.DataFrame({
        "event_id": ["ETHUSDT_2024-01-01T00:00:00+00:00"],
        "symbol": ["ETHUSDT"],
        "prototype": ["P4_BREAKOUT_TOP20"],
        "signal_time": [pd.Timestamp("2024-01-01 00:00", tz="UTC")],
        "execution_time": [pd.Timestamp("2024-01-01 00:01", tz="UTC")],
        "atr14": [10.0],
        "breakout_score_quantile": [1.0],
        "atr_pct_rank": [0.0],
    })
    trades, equity, _ = strict_replay_events(events, data_1m, data_15m, "ETHUSDT", "P4_BREAKOUT_TOP20", "G0_NO_PATH_GATE", "fixed_20x")
    assert len(trades) == 1
    assert trades.iloc[0]["liquidation"] is True or bool(trades.iloc[0]["liquidation"])
    assert trades.iloc[0]["exit_reason"] == "liquidation_price"
    assert equity.iloc[-1]["equity"] == 50.0


def test_strict_replay_donchian_exit_after_minute_scan():
    idx = pd.date_range("2024-01-01 00:00", periods=20, freq="1min", tz="UTC")
    data_1m = pd.DataFrame({
        "open": [100] * 20,
        "high": [101] * 20,
        "low": [99] * 20,
        "close": [100] * 20,
        "volume": [1] * 20,
    }, index=idx)
    data_15m = pd.DataFrame({
        "close": [70],
        "donchian20_lower": [80],
    }, index=pd.DatetimeIndex([pd.Timestamp("2024-01-01 00:15", tz="UTC")]))
    events = pd.DataFrame({
        "event_id": ["ETHUSDT_2024-01-01T00:00:00+00:00"],
        "symbol": ["ETHUSDT"],
        "prototype": ["P4_BREAKOUT_TOP20"],
        "signal_time": [pd.Timestamp("2024-01-01 00:00", tz="UTC")],
        "execution_time": [pd.Timestamp("2024-01-01 00:01", tz="UTC")],
        "atr14": [1.0],
        "breakout_score_quantile": [1.0],
        "atr_pct_rank": [0.0],
    })
    trades, _, _ = strict_replay_events(events, data_1m, data_15m, "ETHUSDT", "P4_BREAKOUT_TOP20", "G0_NO_PATH_GATE", "fixed_10x")
    assert trades.iloc[0]["exit_reason"] == "donchian20_exit"
    assert trades.iloc[0]["exit_time"] == pd.Timestamp("2024-01-01 00:15", tz="UTC")
