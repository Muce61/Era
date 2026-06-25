"""Breakout event state machine for post-breakout entry modes (B2/B3)."""

from dataclasses import dataclass

import pandas as pd


MAX_BARS_AFTER_BREAKOUT = 8


@dataclass
class BreakoutState:
    breakout_time: pd.Timestamp
    breakout_level: float
    breakout_close: float
    breakout_atr: float
    bars_after_breakout: int = 0
    has_lower_low: bool = False
    is_valid: bool = True
    entered: bool = False
    prev_low: float | None = None


class BreakoutStateMachine:
    """
    Single active breakout event tracker.

    Rules:
    - Create on trend breakout (close > entry_high, ema_fast > ema_slow).
    - Breakout bar only records; bars_after_breakout starts on next 15m bar.
    - Max 8 bars after breakout.
    - New breakouts do not replace a still-valid active event.
    """

    def __init__(self):
        self.active: BreakoutState | None = None

    @property
    def has_active_valid(self) -> bool:
        return self.active is not None and self.active.is_valid

    def on_bar_close(
        self,
        signal_time: pd.Timestamp,
        row: pd.Series,
        has_position: bool,
    ) -> BreakoutState | None:
        trend_breakout = (
            row["close"] > row["entry_high"] and
            row["ema_fast"] > row["ema_slow"]
        )

        if self.active is not None and self.active.is_valid:
            self._advance_bar(signal_time, row, has_position)

        if trend_breakout and not self.has_active_valid and not has_position:
            self._create_breakout(signal_time, row)

        return self.active

    def _create_breakout(self, signal_time: pd.Timestamp, row: pd.Series) -> None:
        self.active = BreakoutState(
            breakout_time=signal_time,
            breakout_level=float(row["entry_high"]),
            breakout_close=float(row["close"]),
            breakout_atr=float(row["atr"]),
            bars_after_breakout=0,
            has_lower_low=False,
            is_valid=True,
            entered=False,
            prev_low=float(row["low"]),
        )

    def _advance_bar(
        self,
        signal_time: pd.Timestamp,
        row: pd.Series,
        has_position: bool,
    ) -> None:
        state = self.active
        if state is None or not state.is_valid:
            return

        if signal_time <= state.breakout_time:
            return

        state.bars_after_breakout += 1

        if state.prev_low is not None and float(row["low"]) < state.prev_low:
            state.has_lower_low = True
        state.prev_low = float(row["low"])

        if state.bars_after_breakout > MAX_BARS_AFTER_BREAKOUT:
            state.is_valid = False
        if row["ema_fast"] <= row["ema_slow"]:
            state.is_valid = False
        if row["close"] < row["ema_fast"]:
            state.is_valid = False
        if has_position:
            state.is_valid = False

    def mark_entered(self) -> None:
        if self.active is not None:
            self.active.entered = True
            self.active.is_valid = False

    def invalidate(self) -> None:
        if self.active is not None:
            self.active.is_valid = False
