"""Entry mode handlers delegating signal evaluation from the shared engine."""

from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from strategy.breakout_state import BreakoutStateMachine
from strategy.candlestick_patterns import is_bullish_engulfing
from strategy.eth_trend_signals import EntryMode, StrategyConfig, entry_reason_for_mode
from strategy.hikkake_tracker import HikkakeSetupTracker
from strategy.trend_segment_state import TrendSegmentTracker


@dataclass
class EntrySignal:
    atr: float
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EntryContext:
    signal_time: pd.Timestamp
    row: pd.Series
    bar_idx: int
    signals_15m: pd.DataFrame
    has_position: bool
    breakout_sm: BreakoutStateMachine
    hikkake_tracker: HikkakeSetupTracker
    trend_segment_tracker: TrendSegmentTracker


def evaluate_entry(config: StrategyConfig, ctx: EntryContext) -> Optional[EntrySignal]:
    handlers = {
        EntryMode.NO_CANDLE: _evaluate_no_candle,
        EntryMode.STRONG_BREAKOUT: _evaluate_strong_breakout,
        EntryMode.PULLBACK_ENGULFING: _evaluate_pullback_engulfing,
        EntryMode.BULLISH_HIKKAKE: _evaluate_bullish_hikkake,
        EntryMode.TREND_SEGMENT_ENTRY: _evaluate_trend_segment_entry,
    }
    return handlers[config.entry_mode](config, ctx)


def _trend_breakout(row: pd.Series) -> bool:
    return bool(row["close"] > row["entry_high"] and row["ema_fast"] > row["ema_slow"])


def _evaluate_no_candle(config: StrategyConfig, ctx: EntryContext) -> Optional[EntrySignal]:
    if _trend_breakout(ctx.row):
        return EntrySignal(
            atr=float(ctx.row["atr"]),
            reason=entry_reason_for_mode(EntryMode.NO_CANDLE),
            metadata={"entry_mode": EntryMode.NO_CANDLE.value},
        )
    return None


def _evaluate_strong_breakout(config: StrategyConfig, ctx: EntryContext) -> Optional[EntrySignal]:
    candle_range = ctx.row["high"] - ctx.row["low"]
    if candle_range <= 0:
        return None
    body_ratio = abs(ctx.row["close"] - ctx.row["open"]) / candle_range
    upper_shadow = ctx.row["high"] - max(ctx.row["open"], ctx.row["close"])
    upper_shadow_ratio = upper_shadow / candle_range
    close_location = (ctx.row["close"] - ctx.row["low"]) / candle_range
    volume_ma20 = ctx.signals_15m["volume"].shift(1).rolling(20).mean().iloc[ctx.bar_idx]
    confirm = (
        ctx.row["close"] > ctx.row["open"] and
        body_ratio >= 0.35 and
        upper_shadow_ratio <= 0.30 and
        close_location >= 0.70 and
        ctx.row["volume"] >= volume_ma20
    )
    if _trend_breakout(ctx.row) and bool(confirm):
        return EntrySignal(
            atr=float(ctx.row["atr"]),
            reason=entry_reason_for_mode(EntryMode.STRONG_BREAKOUT),
            metadata={"entry_mode": EntryMode.STRONG_BREAKOUT.value},
        )
    return None


def _evaluate_pullback_engulfing(config: StrategyConfig, ctx: EntryContext) -> Optional[EntrySignal]:
    state = ctx.breakout_sm.active
    if state is None or not state.is_valid or state.entered:
        return None

    bars = state.bars_after_breakout
    if bars < 2 or bars > 8:
        return None
    if not state.has_lower_low:
        return None
    if ctx.row["ema_fast"] <= ctx.row["ema_slow"] or ctx.row["close"] < ctx.row["ema_fast"]:
        return None
    if not is_bullish_engulfing(ctx.signals_15m, ctx.bar_idx):
        return None

    return EntrySignal(
        atr=float(ctx.row["atr"]),
        reason=entry_reason_for_mode(EntryMode.PULLBACK_ENGULFING),
        metadata={
            "entry_mode": EntryMode.PULLBACK_ENGULFING.value,
            "pattern_name": "bullish_engulfing",
            "breakout_time": state.breakout_time,
            "breakout_level": state.breakout_level,
            "signal_time": ctx.signal_time,
            "bars_after_breakout": bars,
        },
    )


def _evaluate_trend_segment_entry(config: StrategyConfig, ctx: EntryContext) -> Optional[EntrySignal]:
    if ctx.has_position or not ctx.trend_segment_tracker.segment_entry_bar:
        return None
    if not _trend_breakout(ctx.row):
        return None
    return EntrySignal(
        atr=float(ctx.row["atr"]),
        reason=entry_reason_for_mode(EntryMode.TREND_SEGMENT_ENTRY),
        metadata={
            "entry_mode": EntryMode.TREND_SEGMENT_ENTRY.value,
            "segment_start_time": ctx.signal_time,
        },
    )


def _evaluate_bullish_hikkake(config: StrategyConfig, ctx: EntryContext) -> Optional[EntrySignal]:
    state = ctx.breakout_sm.active
    breakout_valid = state is not None and state.is_valid and not state.entered

    setup = ctx.hikkake_tracker.on_bar(
        ctx.signal_time,
        ctx.row,
        ctx.signals_15m,
        ctx.bar_idx,
        breakout_valid,
    )
    if setup is None or setup.entered or not setup.confirmed:
        return None
    if state is None or state.entered:
        return None
    if ctx.row["ema_fast"] <= ctx.row["ema_slow"] or ctx.row["close"] < ctx.row["ema_fast"]:
        return None

    return EntrySignal(
        atr=float(ctx.row["atr"]),
        reason=entry_reason_for_mode(EntryMode.BULLISH_HIKKAKE),
        metadata={
            "entry_mode": EntryMode.BULLISH_HIKKAKE.value,
            "pattern_name": "bullish_hikkake",
            "execution_style": "close_confirmed_next_1m_open",
            "inside_bar_time": setup.inside_bar_time,
            "inside_bar_high": setup.inside_bar_high,
            "setup_time": setup.setup_time,
            "confirm_time": ctx.signal_time,
            "bars_after_breakout": state.bars_after_breakout if state else 0,
            "breakout_time": state.breakout_time if state else None,
        },
    )
