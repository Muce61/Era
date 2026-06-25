"""Tests for bullish Hikkake entry mode."""

import pandas as pd

from strategy.hikkake_patterns import is_bullish_hikkake_confirm, is_bullish_hikkake_setup, is_inside_bar
from strategy.hikkake_tracker import HikkakeSetupTracker


def _make_df(rows):
    idx = pd.date_range("2025-01-01", periods=len(rows), freq="15min", tz="UTC")
    return pd.DataFrame(rows, index=idx)


def test_inside_bar_strict():
    df = _make_df([
        {"open": 100, "high": 110, "low": 95, "close": 105},
        {"open": 104, "high": 108, "low": 98, "close": 102},
    ])
    assert is_inside_bar(df, 1)


def test_equal_high_not_inside_bar():
    df = _make_df([
        {"open": 100, "high": 110, "low": 95, "close": 105},
        {"open": 104, "high": 110, "low": 98, "close": 102},
    ])
    assert not is_inside_bar(df, 1)


def test_bullish_hikkake_setup():
    df = _make_df([
        {"open": 100, "high": 110, "low": 95, "close": 105},
        {"open": 104, "high": 108, "low": 98, "close": 102},
        {"open": 101, "high": 107, "low": 94, "close": 100},
    ])
    assert is_inside_bar(df, 1)
    assert is_bullish_hikkake_setup(df, 1)


def test_no_downside_break_no_setup():
    df = _make_df([
        {"open": 100, "high": 110, "low": 95, "close": 105},
        {"open": 104, "high": 108, "low": 98, "close": 102},
        {"open": 101, "high": 107, "low": 99, "close": 100},
    ])
    assert not is_bullish_hikkake_setup(df, 1)


def test_confirm_within_three_bars():
    tracker = HikkakeSetupTracker()
    df = _make_df([
        {"open": 100, "high": 110, "low": 95, "close": 105},
        {"open": 104, "high": 108, "low": 98, "close": 102},
        {"open": 101, "high": 107, "low": 94, "close": 100},
        {"open": 100, "high": 111, "low": 99, "close": 109},
    ])
    breakout_valid = True
    confirmed = None
    for i, (ts, row) in enumerate(df.iterrows()):
        result = tracker.on_bar(ts, row, df, i, breakout_valid)
        if result and result.confirmed:
            confirmed = ts
    assert confirmed == df.index[3]


def test_expires_after_three_bars_without_confirm():
    tracker = HikkakeSetupTracker()
    df = _make_df([
        {"open": 100, "high": 110, "low": 95, "close": 105},
        {"open": 104, "high": 108, "low": 98, "close": 102},
        {"open": 101, "high": 107, "low": 94, "close": 100},
        {"open": 100, "high": 106, "low": 99, "close": 101},
        {"open": 100, "high": 106, "low": 99, "close": 101},
        {"open": 100, "high": 106, "low": 99, "close": 101},
        {"open": 100, "high": 106, "low": 99, "close": 101},
    ])
    for i, (ts, row) in enumerate(df.iterrows()):
        tracker.on_bar(ts, row, df, i, True)
    assert tracker.active is None


def test_duplicate_confirm_blocked():
    tracker = HikkakeSetupTracker()
    df = _make_df([
        {"open": 100, "high": 110, "low": 95, "close": 105},
        {"open": 104, "high": 108, "low": 98, "close": 102},
        {"open": 101, "high": 107, "low": 94, "close": 100},
        {"open": 100, "high": 111, "low": 99, "close": 109},
        {"open": 100, "high": 112, "low": 99, "close": 110},
    ])
    confirms = []
    for i, (ts, row) in enumerate(df.iterrows()):
        result = tracker.on_bar(ts, row, df, i, True)
        if result and result.confirmed:
            confirms.append(ts)
            tracker.mark_entered()
    assert len(confirms) == 1
