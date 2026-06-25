"""Hikkake setup tracker within an active breakout event."""

from dataclasses import dataclass

import pandas as pd

from strategy.hikkake_patterns import is_bullish_hikkake_confirm, is_bullish_hikkake_setup, is_inside_bar

MAX_BARS_AFTER_SETUP = 3


@dataclass
class HikkakeSetup:
    inside_bar_time: pd.Timestamp
    inside_bar_high: float
    inside_bar_low: float
    setup_time: pd.Timestamp
    bars_after_setup: int = 0
    confirmed: bool = False
    entered: bool = False


class HikkakeSetupTracker:
    def __init__(self):
        self.active: HikkakeSetup | None = None
        self._pending_inside_idx: int | None = None
        self._pending_inside_time: pd.Timestamp | None = None
        self._pending_inside_high: float | None = None
        self._pending_inside_low: float | None = None

    def reset(self) -> None:
        self.active = None
        self._pending_inside_idx = None
        self._pending_inside_time = None
        self._pending_inside_high = None
        self._pending_inside_low = None

    def on_bar(
        self,
        signal_time: pd.Timestamp,
        row: pd.Series,
        df: pd.DataFrame,
        bar_idx: int,
        breakout_valid: bool,
    ) -> HikkakeSetup | None:
        if not breakout_valid:
            self.reset()
            return None

        if self.active is not None and not self.active.entered:
            self.active.bars_after_setup += 1
            if self.active.bars_after_setup > MAX_BARS_AFTER_SETUP:
                self.active = None
            elif is_bullish_hikkake_confirm(row, self.active.inside_bar_high):
                self.active.confirmed = True
                return self.active

        if self._pending_inside_idx is not None and bar_idx == self._pending_inside_idx + 1:
            if is_bullish_hikkake_setup(df, self._pending_inside_idx):
                self.active = HikkakeSetup(
                    inside_bar_time=self._pending_inside_time,
                    inside_bar_high=self._pending_inside_high,
                    inside_bar_low=self._pending_inside_low,
                    setup_time=signal_time,
                    bars_after_setup=0,
                )
            self._pending_inside_idx = None

        if self.active is None and is_inside_bar(df, bar_idx):
            inside = df.iloc[bar_idx]
            self._pending_inside_idx = bar_idx
            self._pending_inside_time = signal_time
            self._pending_inside_high = float(inside["high"])
            self._pending_inside_low = float(inside["low"])

        return self.active if self.active and self.active.confirmed else None

    def mark_entered(self) -> None:
        if self.active is not None:
            self.active.entered = True
            self.active = None
        self._pending_inside_idx = None
