"""Tests for breakout event state machine."""

import pandas as pd

from strategy.breakout_state import BreakoutStateMachine, MAX_BARS_AFTER_BREAKOUT


def _row(close, high, low, entry_high, ema_fast, ema_slow, atr=10.0):
    return pd.Series({
        "close": close,
        "high": high,
        "low": low,
        "entry_high": entry_high,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "atr": atr,
    })


def test_breakout_event_created():
    sm = BreakoutStateMachine()
    ts = pd.Timestamp("2025-01-01 00:00:00", tz="UTC")
    sm.on_bar_close(ts, _row(110, 112, 108, 100, 105, 100), has_position=False)

    assert sm.active is not None
    assert sm.active.breakout_time == ts
    assert sm.active.breakout_level == 100
    assert sm.active.breakout_close == 110
    assert sm.active.bars_after_breakout == 0
    assert sm.active.is_valid is True


def test_breakout_bar_does_not_increment_bars_after():
    sm = BreakoutStateMachine()
    ts = pd.Timestamp("2025-01-01 00:00:00", tz="UTC")
    sm.on_bar_close(ts, _row(110, 112, 108, 100, 105, 100), has_position=False)
    sm.on_bar_close(ts, _row(111, 113, 109, 100, 105, 100), has_position=False)
    assert sm.active.bars_after_breakout == 0


def test_bars_after_breakout_increments_from_next_bar():
    sm = BreakoutStateMachine()
    t0 = pd.Timestamp("2025-01-01 00:00:00", tz="UTC")
    t1 = pd.Timestamp("2025-01-01 00:15:00", tz="UTC")
    t2 = pd.Timestamp("2025-01-01 00:30:00", tz="UTC")

    sm.on_bar_close(t0, _row(110, 112, 108, 100, 105, 100), has_position=False)
    sm.on_bar_close(t1, _row(109, 111, 107, 100, 105, 100), has_position=False)
    assert sm.active.bars_after_breakout == 1
    sm.on_bar_close(t2, _row(108, 110, 106, 100, 105, 100), has_position=False)
    assert sm.active.bars_after_breakout == 2


def test_lower_low_detected():
    sm = BreakoutStateMachine()
    t0 = pd.Timestamp("2025-01-01 00:00:00", tz="UTC")
    t1 = pd.Timestamp("2025-01-01 00:15:00", tz="UTC")

    sm.on_bar_close(t0, _row(110, 112, 108, 100, 105, 100), has_position=False)
    sm.on_bar_close(t1, _row(109, 111, 105, 100, 105, 100), has_position=False)
    assert sm.active.has_lower_low is True


def test_expires_after_eight_bars():
    sm = BreakoutStateMachine()
    t0 = pd.Timestamp("2025-01-01 00:00:00", tz="UTC")
    sm.on_bar_close(t0, _row(110, 112, 108, 100, 105, 100), has_position=False)

    for i in range(1, MAX_BARS_AFTER_BREAKOUT + 1):
        ts = t0 + pd.Timedelta(minutes=15 * i)
        sm.on_bar_close(ts, _row(109, 111, 107, 100, 105, 100), has_position=False)

    assert sm.active.bars_after_breakout == MAX_BARS_AFTER_BREAKOUT
    assert sm.active.is_valid is True

    ts_expire = t0 + pd.Timedelta(minutes=15 * (MAX_BARS_AFTER_BREAKOUT + 1))
    sm.on_bar_close(ts_expire, _row(95, 96, 94, 100, 105, 100), has_position=False)
    assert sm.active.is_valid is False


def test_invalid_when_ema_trend_breaks():
    sm = BreakoutStateMachine()
    t0 = pd.Timestamp("2025-01-01 00:00:00", tz="UTC")
    t1 = pd.Timestamp("2025-01-01 00:15:00", tz="UTC")

    sm.on_bar_close(t0, _row(110, 112, 108, 100, 105, 100), has_position=False)
    sm.on_bar_close(t1, _row(109, 111, 107, 100, 99, 100), has_position=False)
    assert sm.active.is_valid is False


def test_invalid_when_close_below_ema50():
    sm = BreakoutStateMachine()
    t0 = pd.Timestamp("2025-01-01 00:00:00", tz="UTC")
    t1 = pd.Timestamp("2025-01-01 00:15:00", tz="UTC")

    sm.on_bar_close(t0, _row(110, 112, 108, 100, 105, 100), has_position=False)
    sm.on_bar_close(t1, _row(98, 100, 96, 100, 105, 100), has_position=False)
    assert sm.active.is_valid is False


def test_invalid_when_has_position():
    sm = BreakoutStateMachine()
    t0 = pd.Timestamp("2025-01-01 00:00:00", tz="UTC")
    t1 = pd.Timestamp("2025-01-01 00:15:00", tz="UTC")

    sm.on_bar_close(t0, _row(110, 112, 108, 100, 105, 100), has_position=False)
    sm.on_bar_close(t1, _row(109, 111, 107, 100, 105, 100), has_position=True)
    assert sm.active.is_valid is False
    assert sm.active.breakout_time == t0


def test_new_breakout_does_not_replace_valid_event():
    sm = BreakoutStateMachine()
    t0 = pd.Timestamp("2025-01-01 00:00:00", tz="UTC")
    t1 = pd.Timestamp("2025-01-01 00:15:00", tz="UTC")
    t2 = pd.Timestamp("2025-01-01 00:30:00", tz="UTC")

    sm.on_bar_close(t0, _row(110, 112, 108, 100, 105, 100), has_position=False)
    sm.on_bar_close(t1, _row(109, 111, 107, 100, 105, 100), has_position=False)
    sm.on_bar_close(t2, _row(120, 122, 118, 115, 108, 100), has_position=False)

    assert sm.active.breakout_time == t0
    assert sm.active.breakout_close == 110


def test_new_breakout_after_expiry():
    sm = BreakoutStateMachine()
    t0 = pd.Timestamp("2025-01-01 00:00:00", tz="UTC")
    sm.on_bar_close(t0, _row(110, 112, 108, 100, 105, 100), has_position=False)

    for i in range(1, MAX_BARS_AFTER_BREAKOUT + 2):
        ts = t0 + pd.Timedelta(minutes=15 * i)
        row = _row(109, 111, 107, 100, 105, 100)
        if i == MAX_BARS_AFTER_BREAKOUT + 1:
            row = _row(120, 122, 118, 115, 108, 100)
        sm.on_bar_close(ts, row, has_position=False)

    assert sm.active.breakout_time == t0 + pd.Timedelta(minutes=15 * (MAX_BARS_AFTER_BREAKOUT + 1))
    assert sm.active.breakout_close == 120
