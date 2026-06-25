"""Tests for pullback engulfing entry mode."""

import pandas as pd

from strategy.breakout_state import BreakoutStateMachine
from strategy.candlestick_patterns import is_bullish_engulfing
from strategy.entry_handlers import EntryContext, evaluate_entry
from strategy.eth_trend_signals import EntryMode, StrategyConfig, build_base_frame, next_1m_open
from strategy.hikkake_tracker import HikkakeSetupTracker


def _make_df(rows):
    idx = pd.date_range("2025-01-01", periods=len(rows), freq="15min", tz="UTC")
    return pd.DataFrame(rows, index=idx)


def test_is_bullish_engulfing_standard():
    df = _make_df([
        {"open": 110, "high": 111, "low": 105, "close": 106, "volume": 100},
        {"open": 105, "high": 112, "low": 104, "close": 111, "volume": 100},
    ])
    assert is_bullish_engulfing(df, 1)


def test_non_engulfing_bullish_fails():
    df = _make_df([
        {"open": 110, "high": 111, "low": 105, "close": 106, "volume": 100},
        {"open": 107, "high": 109, "low": 106, "close": 108, "volume": 100},
    ])
    assert not is_bullish_engulfing(df, 1)


def test_prev_not_bearish_fails():
    df = _make_df([
        {"open": 105, "high": 111, "low": 105, "close": 110, "volume": 100},
        {"open": 109, "high": 112, "low": 108, "close": 111, "volume": 100},
    ])
    assert not is_bullish_engulfing(df, 1)


def test_shadow_engulf_without_body_fails():
    df = _make_df([
        {"open": 110, "high": 115, "low": 105, "close": 106, "volume": 100},
        {"open": 107, "high": 116, "low": 104, "close": 108, "volume": 100},
    ])
    assert not is_bullish_engulfing(df, 1)


def test_next_1m_open_after_signal():
    idx = pd.date_range("2025-01-01 00:14", periods=3, freq="1min", tz="UTC")
    data_1m = pd.DataFrame({
        "open": [100, 101, 102],
        "high": [100, 101, 102],
        "low": [100, 101, 102],
        "close": [100, 101, 102],
        "volume": [1, 1, 1],
    }, index=idx)
    ts, price = next_1m_open(data_1m, idx[0])
    assert ts == idx[1]
    assert price == 101


def test_one_entry_per_breakout_event():
    config = StrategyConfig(entry_mode=EntryMode.PULLBACK_ENGULFING)
    rows = []
    for i in range(12):
        rows.append({
            "open": 100 + i, "high": 102 + i, "low": 99 + i,
            "close": 101 + i, "volume": 100,
            "entry_high": 100, "ema_fast": 105, "ema_slow": 100, "atr": 10,
            "entry_low": 90, "exit_low": 90,
        })
    rows[0]["close"] = 110
    rows[0]["high"] = 112
    rows[0]["low"] = 108
    rows[1]["low"] = 105
    rows[2]["open"] = 110
    rows[2]["high"] = 111
    rows[2]["low"] = 105
    rows[2]["close"] = 106
    rows[3]["open"] = 105
    rows[3]["high"] = 112
    rows[3]["low"] = 104
    rows[3]["close"] = 111

    df = _make_df([{k: v for k, v in r.items() if k in ("open", "high", "low", "close", "volume")} for r in rows])
    for col in ("entry_high", "ema_fast", "ema_slow", "atr", "entry_low", "exit_low"):
        df[col] = [r[col] for r in rows]

    sm = BreakoutStateMachine()
    ht = HikkakeSetupTracker()
    ts_tracker = TrendSegmentTracker()
    entries = []
    for i, (ts, row) in enumerate(df.iterrows()):
        sm.on_bar_close(ts, row, has_position=False)
        ts_tracker.on_bar_close(ts, row, has_position=False)
        ctx = EntryContext(ts, row, i, df, False, sm, ht, ts_tracker)
        sig = evaluate_entry(config, ctx)
        if sig:
            entries.append(ts)
            sm.mark_entered()

    assert len(entries) == 1
