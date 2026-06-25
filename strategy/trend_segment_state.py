"""Trend segment tracker for C1 (one entry per trend regime leg)."""

import pandas as pd


class TrendSegmentTracker:
    """
    Tracks Donchian+EMA trend segments.

    Segment starts: close > entry_high and ema_fast > ema_slow (was not in segment).
    Segment ends: ema_fast <= ema_slow or close < exit_low.
    C1 enters only on the first bar of a new segment when flat.
    """

    def __init__(self):
        self.in_segment = False
        self.segment_entry_bar = False

    def on_bar_close(
        self,
        signal_time: pd.Timestamp,
        row: pd.Series,
        has_position: bool,
    ) -> bool:
        self.segment_entry_bar = False
        trend_breakout = (
            row["close"] > row["entry_high"] and
            row["ema_fast"] > row["ema_slow"]
        )
        still_valid = (
            row["ema_fast"] > row["ema_slow"] and
            row["close"] >= row["exit_low"]
        )

        if not self.in_segment and trend_breakout:
            self.in_segment = True
            if not has_position:
                self.segment_entry_bar = True

        if self.in_segment and not still_valid:
            self.in_segment = False

        return self.segment_entry_bar
