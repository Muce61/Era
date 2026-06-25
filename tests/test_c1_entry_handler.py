"""C1 entry handler vs B0 on same trend segment."""

import pandas as pd

from strategy.breakout_state import BreakoutStateMachine
from strategy.entry_handlers import EntryContext, evaluate_entry
from strategy.eth_trend_signals import EntryMode, StrategyConfig
from strategy.hikkake_tracker import HikkakeSetupTracker
from strategy.trend_segment_state import TrendSegmentTracker


def _make_df(rows: list[dict]) -> pd.DataFrame:
    data = []
    for i, r in enumerate(rows):
        ts = pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(minutes=15 * i)
        data.append({"timestamp": ts, **r})
    df = pd.DataFrame(data).set_index("timestamp")
    return df


def test_c1_enters_once_per_segment_b0_can_reenter_after_flat():
    rows = [
        {"open": 100, "high": 110, "low": 99, "close": 108, "volume": 1000,
         "entry_high": 100, "ema_fast": 60, "ema_slow": 50, "atr": 5, "exit_low": 90},
        {"open": 108, "high": 112, "low": 107, "close": 111, "volume": 1000,
         "entry_high": 100, "ema_fast": 61, "ema_slow": 50, "atr": 5, "exit_low": 90},
        {"open": 111, "high": 113, "low": 110, "close": 112, "volume": 1000,
         "entry_high": 100, "ema_fast": 62, "ema_slow": 50, "atr": 5, "exit_low": 90},
    ]
    df = _make_df(rows)
    sm = BreakoutStateMachine()
    ht = HikkakeSetupTracker()
    ts_tracker = TrendSegmentTracker()
    c1_entries = []
    b0_entries = []

    for i, (ts, row) in enumerate(df.iterrows()):
        sm.on_bar_close(ts, row, has_position=False)
        ts_tracker.on_bar_close(ts, row, has_position=False)
        ctx = EntryContext(ts, row, i, df, False, sm, ht, ts_tracker)
        if evaluate_entry(StrategyConfig(entry_mode=EntryMode.TREND_SEGMENT_ENTRY), ctx):
            c1_entries.append(ts)
        if evaluate_entry(StrategyConfig(entry_mode=EntryMode.NO_CANDLE), ctx):
            b0_entries.append(ts)

    assert len(c1_entries) == 1
    assert len(b0_entries) == 3
