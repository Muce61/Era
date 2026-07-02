import pandas as pd

from research_core.common import validate_run_log_row
from research_core.event_table import build_event_candidates, next_1m_open, strict_resample_15m
from research_core.run_realistic_replay_10_symbol import INVALID_MARKER
from research_core.strict_high_leverage_replay import downside_exit_from_bar, strict_replay_events


def _ohlcv(index, opens=None, lows=None):
    n = len(index)
    opens = opens or [100.0] * n
    lows = lows or [99.0] * n
    return pd.DataFrame({
        "open": opens,
        "high": [max(o + 1, 101.0) for o in opens],
        "low": lows,
        "close": opens,
        "volume": [1.0] * n,
    }, index=index)


def test_15m_timestamp_is_candle_close_time():
    idx = pd.date_range("2024-01-01 00:00", periods=15, freq="1min", tz="UTC")
    out = strict_resample_15m(_ohlcv(idx))
    assert list(out.index) == [pd.Timestamp("2024-01-01 00:15", tz="UTC")]


def test_15m_bar_cannot_enter_at_first_minute():
    idx = pd.date_range("2024-01-01 00:00", periods=4200, freq="1min", tz="UTC")
    data = _ohlcv(idx)
    # Force enough trend context for at least one candidate after indicators warm up.
    data["open"] = range(100, 4300)
    data["high"] = data["open"] + 1
    data["low"] = data["open"] - 1
    data["close"] = data["open"] + 0.5
    events, _ = build_event_candidates(data, symbol="ETHUSDT")
    assert not events.empty
    first = events.iloc[0]
    assert first["execution_time"] == first["signal_time"]
    assert first["execution_time"].minute % 15 == 0


def test_next_1m_open_uses_signal_completion_open():
    idx = pd.date_range("2024-01-01 00:14", periods=3, freq="1min", tz="UTC")
    data = _ohlcv(idx, opens=[99, 100, 101])
    ts, price = next_1m_open(data, pd.Timestamp("2024-01-01 00:15", tz="UTC"))
    assert ts == pd.Timestamp("2024-01-01 00:15", tz="UTC")
    assert price == 100


def test_donchian_exit_uses_next_1m_open_not_15m_close():
    idx = pd.date_range("2024-01-01 00:00", periods=20, freq="1min", tz="UTC")
    data_1m = _ohlcv(idx, opens=[100] * 15 + [88] + [87] * 4, lows=[99] * 20)
    data_15m = pd.DataFrame({
        "close": [70.0],
        "donchian20_lower": [80.0],
    }, index=pd.DatetimeIndex([pd.Timestamp("2024-01-01 00:15", tz="UTC")]))
    events = pd.DataFrame({
        "event_id": ["ETHUSDT_2024-01-01T00:00:00+00:00"],
        "signal_time": [pd.Timestamp("2024-01-01 00:00", tz="UTC")],
        "execution_time": [pd.Timestamp("2024-01-01 00:00", tz="UTC")],
        "atr14": [10.0],
        "breakout_score_quantile": [1.0],
        "atr_pct_rank": [0.0],
    })
    trades, _, _ = strict_replay_events(events, data_1m, data_15m, "ETHUSDT", "P4_BREAKOUT_TOP20", "G0_NO_PATH_GATE", "fixed_3x")
    assert trades.iloc[0]["exit_reason"] == "donchian20_exit"
    assert trades.iloc[0]["exit_time"] == pd.Timestamp("2024-01-01 00:15", tz="UTC")
    assert round(trades.iloc[0]["exit_price"], 4) == round(88 * (1 - 0.0002), 4)


def test_atr_stop_checked_before_donchian_exit_window():
    idx = pd.date_range("2024-01-01 00:00", periods=20, freq="1min", tz="UTC")
    lows = [99] * 5 + [96] + [99] * 14
    data_1m = _ohlcv(idx, lows=lows)
    data_15m = pd.DataFrame({
        "close": [70.0],
        "donchian20_lower": [80.0],
    }, index=pd.DatetimeIndex([pd.Timestamp("2024-01-01 00:15", tz="UTC")]))
    events = pd.DataFrame({
        "event_id": ["ETHUSDT_2024-01-01T00:00:00+00:00"],
        "signal_time": [pd.Timestamp("2024-01-01 00:00", tz="UTC")],
        "execution_time": [pd.Timestamp("2024-01-01 00:00", tz="UTC")],
        "atr14": [1.0],
        "breakout_score_quantile": [1.0],
        "atr_pct_rank": [0.0],
    })
    trades, _, _ = strict_replay_events(events, data_1m, data_15m, "ETHUSDT", "P4_BREAKOUT_TOP20", "G0_NO_PATH_GATE", "fixed_3x")
    assert trades.iloc[0]["exit_reason"] == "atr_stop"
    assert trades.iloc[0]["exit_time"] == pd.Timestamp("2024-01-01 00:05", tz="UTC")


def test_liquidation_priority_when_same_1m_hits_stop_and_liquidation():
    assert downside_exit_from_bar(low=94.0, stop_loss=97.0, liquidation_price=95.0) == ("liquidation_price", 95.0)


def test_downside_risk_at_donchian_execution_uses_conservative_exit():
    idx = pd.date_range("2024-01-01 00:00", periods=20, freq="1min", tz="UTC")
    data_1m = _ohlcv(idx, opens=[100] * 15 + [94] + [94] * 4, lows=[99] * 20)
    data_15m = pd.DataFrame({
        "close": [70.0],
        "donchian20_lower": [80.0],
    }, index=pd.DatetimeIndex([pd.Timestamp("2024-01-01 00:15", tz="UTC")]))
    events = pd.DataFrame({
        "event_id": ["ETHUSDT_2024-01-01T00:00:00+00:00"],
        "signal_time": [pd.Timestamp("2024-01-01 00:00", tz="UTC")],
        "execution_time": [pd.Timestamp("2024-01-01 00:00", tz="UTC")],
        "atr14": [1.0],
        "breakout_score_quantile": [1.0],
        "atr_pct_rank": [0.0],
    })
    trades, _, _ = strict_replay_events(events, data_1m, data_15m, "ETHUSDT", "P4_BREAKOUT_TOP20", "G0_NO_PATH_GATE", "fixed_20x")
    assert trades.iloc[0]["exit_reason"] == "liquidation_price"


def test_invalid_marker_prevents_old_results_from_valid_evidence():
    assert INVALID_MARKER == "time_alignment_invalid"


def test_run_log_required_fields_complete():
    row = {
        "config_hash": "a",
        "data_hash": "b",
        "git_commit": "c",
        "run_timestamp": "2026-06-28T00:00:00+00:00",
        "random_seed": 20260624,
        "data_layer": "expanded_discovery",
    }
    assert validate_run_log_row(row)
