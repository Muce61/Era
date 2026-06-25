"""Signal alignment and no-lookahead tests for ETH trend signals."""

import pandas as pd
import pytest

from strategy.eth_trend_signals import (
    EntryMode,
    StrategyConfig,
    build_base_frame,
    build_signal_frame,
    is_signal_bar_close,
    next_1m_open,
    signal_bar_timestamp,
)


def _make_config(**kwargs):
    defaults = {"entry_mode": EntryMode.STRONG_BREAKOUT}
    defaults.update(kwargs)
    return StrategyConfig(**defaults)


def test_donchian_excludes_current_signal_candle():
    idx = pd.date_range("2025-01-01", periods=80, freq="15min", tz="UTC")
    df15 = pd.DataFrame({
        "open": range(80),
        "high": list(range(79)) + [10_000],
        "low": range(80),
        "close": range(80),
        "volume": 1,
    }, index=idx)
    data_1m = df15.resample("1min").ffill()
    config = _make_config(ema_fast=3, ema_slow=5, atr_period=3)
    base = build_base_frame(data_1m, config)
    last = base.iloc[-1]
    assert last["entry_high"] < 10_000


def test_donchian_uses_shift_one_rolling():
    idx = pd.date_range("2025-01-01", periods=60, freq="15min", tz="UTC")
    highs = pd.Series(range(60), index=idx)
    df15 = pd.DataFrame({
        "open": highs,
        "high": highs,
        "low": highs,
        "close": highs,
        "volume": 1,
    })
    data_1m = df15.resample("1min").ffill()
    config = _make_config(donchian_entry=5, ema_fast=3, ema_slow=5, atr_period=3)
    base = build_base_frame(data_1m, config)
    row = base.iloc[-1]
    expected_entry_high = highs.iloc[-6:-1].max()
    assert row["entry_high"] == expected_entry_high


def test_signal_executes_on_next_1m_open():
    idx = pd.date_range("2025-01-01 00:14", periods=3, freq="1min", tz="UTC")
    data_1m = pd.DataFrame({
        "open": [100.0, 101.0, 102.0],
        "high": [100.0, 101.0, 102.0],
        "low": [100.0, 101.0, 102.0],
        "close": [100.0, 101.0, 102.0],
        "volume": [1.0, 1.0, 1.0],
    }, index=idx)

    signal_close = idx[0]
    assert is_signal_bar_close(signal_close)
    exec_ts, exec_price = next_1m_open(data_1m, signal_close)
    assert exec_ts == idx[1]
    assert exec_price == 101.0
    assert exec_ts > signal_close


def test_signal_bar_timestamp_floors_to_15m_boundary():
    ts = pd.Timestamp("2025-01-01 00:14:00", tz="UTC")
    assert signal_bar_timestamp(ts) == pd.Timestamp("2025-01-01 00:00:00", tz="UTC")


def test_signal_frame_does_not_use_future_bar_in_donchian():
    idx = pd.date_range("2025-01-01", periods=100, freq="15min", tz="UTC")
    close = pd.Series(range(100), index=idx)
    spike_idx = idx[-1]
    df15 = pd.DataFrame({
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1,
    })
    df15.loc[spike_idx, "high"] = 50_000
    df15.loc[spike_idx, "close"] = 50_000

    data_1m = df15.resample("1min").ffill()
    config = _make_config(ema_fast=3, ema_slow=5, atr_period=3, donchian_entry=10)
    signals = build_signal_frame(data_1m, config)
    last = signals.iloc[-1]
    assert last["entry_high"] < 50_000


def test_no_candle_uses_trend_breakout_only():
    idx = pd.date_range("2025-01-01", periods=30, freq="15min", tz="UTC")
    close = pd.Series(range(30), index=idx) + 100
    df15 = pd.DataFrame({
        "open": close - 0.5,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 1,
    })
    data_1m = df15.resample("1min").ffill()
    config = _make_config(entry_mode=EntryMode.NO_CANDLE, ema_fast=3, ema_slow=5, atr_period=3, donchian_entry=5)
    signals = build_signal_frame(data_1m, config)
    trend = (signals["close"] > signals["entry_high"]) & (signals["ema_fast"] > signals["ema_slow"])
    assert signals["long_signal"].equals(trend)


def test_pullback_and_hikkake_build_signal_frame():
    idx = pd.date_range("2025-01-01", periods=30, freq="15min", tz="UTC")
    data_1m = pd.DataFrame({
        "open": 1,
        "high": 2,
        "low": 1,
        "close": 1,
        "volume": 1,
    }, index=idx).resample("1min").ffill()

    for mode in (EntryMode.PULLBACK_ENGULFING, EntryMode.BULLISH_HIKKAKE):
        signals = build_signal_frame(data_1m, StrategyConfig(entry_mode=mode))
        assert signals["long_signal"].sum() == 0
        assert "long_exit" in signals.columns
