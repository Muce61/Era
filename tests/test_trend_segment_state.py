"""Tests for trend segment state machine."""

import pandas as pd

from strategy.trend_segment_state import TrendSegmentTracker


def _row(close, entry_high, ema_fast, ema_slow, exit_low):
    return pd.Series({
        "close": close,
        "entry_high": entry_high,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "exit_low": exit_low,
    })


def test_segment_entry_only_on_first_breakout_bar():
    tracker = TrendSegmentTracker()
    ts0 = pd.Timestamp("2024-01-01 00:00", tz="UTC")
    ts1 = pd.Timestamp("2024-01-01 00:15", tz="UTC")
    ts2 = pd.Timestamp("2024-01-01 00:30", tz="UTC")

    assert tracker.on_bar_close(ts0, _row(110, 100, 60, 50, 90), False) is True
    assert tracker.on_bar_close(ts1, _row(112, 100, 61, 50, 90), False) is False
    assert tracker.on_bar_close(ts2, _row(113, 100, 62, 50, 90), False) is False


def test_segment_ends_when_trend_invalid():
    tracker = TrendSegmentTracker()
    ts0 = pd.Timestamp("2024-01-01 00:00", tz="UTC")
    ts1 = pd.Timestamp("2024-01-01 00:15", tz="UTC")
    ts2 = pd.Timestamp("2024-01-01 00:30", tz="UTC")

    tracker.on_bar_close(ts0, _row(110, 100, 60, 50, 90), False)
    tracker.on_bar_close(ts1, _row(85, 100, 45, 50, 90), False)
    assert tracker.in_segment is False
    assert tracker.on_bar_close(ts2, _row(110, 100, 60, 50, 90), False) is True


def test_no_entry_when_has_position_on_segment_start():
    tracker = TrendSegmentTracker()
    ts0 = pd.Timestamp("2024-01-01 00:00", tz="UTC")
    assert tracker.on_bar_close(ts0, _row(110, 100, 60, 50, 90), True) is False
    assert tracker.in_segment is True
