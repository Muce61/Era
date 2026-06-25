"""ETH trend-following signal generation on 15m bars derived from 1m OHLCV."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal

import pandas as pd

from strategy.candlestick_patterns import (
    add_candle_metrics,
    bullish_hikkake_confirm,
    no_candle_confirm,
    pullback_engulfing_confirm,
    strong_breakout_confirm,
    trend_segment_entry_confirm,
)


class EntryMode(str, Enum):
    NO_CANDLE = "no_candle"
    STRONG_BREAKOUT = "strong_breakout"
    PULLBACK_ENGULFING = "pullback_engulfing"
    BULLISH_HIKKAKE = "bullish_hikkake"
    TREND_SEGMENT_ENTRY = "trend_segment_entry"


@dataclass
class StrategyConfig:
    entry_mode: EntryMode
    leverage: float = 2.0
    ema_fast: int = 50
    ema_slow: int = 200
    donchian_entry: int = 55
    donchian_exit: int = 20
    atr_period: int = 14
    atr_stop_mult: float = 3.0
    fee_rate: float = 0.0005
    slippage_rate: float = 0.0002
    signal_timeframe: str = "15min"
    position_sizing_mode: Literal["fixed_leverage", "fixed_risk"] = "fixed_leverage"
    risk_fraction: float = 0.005


ENTRY_CONFIRM_FNS = {
    EntryMode.NO_CANDLE: no_candle_confirm,
    EntryMode.STRONG_BREAKOUT: strong_breakout_confirm,
    EntryMode.PULLBACK_ENGULFING: pullback_engulfing_confirm,
    EntryMode.BULLISH_HIKKAKE: bullish_hikkake_confirm,
    EntryMode.TREND_SEGMENT_ENTRY: trend_segment_entry_confirm,
}

ENTRY_REASONS = {
    EntryMode.NO_CANDLE: "Donchian Long Breakout",
    EntryMode.STRONG_BREAKOUT: "Donchian Long Breakout + Candlestick Confirmation",
    EntryMode.PULLBACK_ENGULFING: "Donchian Long Breakout + Pullback Engulfing",
    EntryMode.BULLISH_HIKKAKE: "Donchian Long Breakout + Bullish Hikkake",
    EntryMode.TREND_SEGMENT_ENTRY: "Donchian Trend Segment Entry",
}


def load_ohlcv_1m(path: Path | str, start_date: str, end_date: str) -> pd.DataFrame:
    df = pd.read_csv(Path(path), parse_dates=["timestamp"])
    df = df.dropna(subset=["timestamp"]).set_index("timestamp").sort_index()
    df = df[~df.index.duplicated(keep="last")]

    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    df.columns = [c.lower() for c in df.columns]
    required_cols = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    start = pd.Timestamp(start_date, tz="UTC")
    end = pd.Timestamp(end_date, tz="UTC")
    sliced = df.loc[start:end, required_cols].copy()
    if sliced.empty:
        raise ValueError("No 1m data in requested date range.")
    return sliced


def build_base_frame(data_1m: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    df = data_1m.resample(config.signal_timeframe).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()

    df["ema_fast"] = df["close"].ewm(span=config.ema_fast, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=config.ema_slow, adjust=False).mean()

    prev_close = df["close"].shift(1)
    true_range = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = true_range.rolling(config.atr_period).mean()

    df["entry_high"] = df["high"].shift(1).rolling(config.donchian_entry).max()
    df["entry_low"] = df["low"].shift(1).rolling(config.donchian_entry).min()
    df["exit_low"] = df["low"].shift(1).rolling(config.donchian_exit).min()
    df["exit_high"] = df["high"].shift(1).rolling(config.donchian_exit).max()

    return df


def build_entry_confirmation(df: pd.DataFrame, config: StrategyConfig) -> pd.Series:
    confirm_fn = ENTRY_CONFIRM_FNS[config.entry_mode]
    if config.entry_mode == EntryMode.STRONG_BREAKOUT:
        enriched = add_candle_metrics(df)
        return confirm_fn(enriched)
    return confirm_fn(df)


def build_signal_frame(data_1m: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    df = build_base_frame(data_1m, config)
    trend_breakout = (df["close"] > df["entry_high"]) & (df["ema_fast"] > df["ema_slow"])

    if config.entry_mode in (EntryMode.NO_CANDLE, EntryMode.STRONG_BREAKOUT):
        if config.entry_mode == EntryMode.NO_CANDLE:
            df["bullish_candle_confirm"] = True
            df["long_signal"] = trend_breakout
        else:
            enriched = add_candle_metrics(df)
            candle_confirm = strong_breakout_confirm(enriched)
            df["bullish_candle_confirm"] = candle_confirm
            df["long_signal"] = trend_breakout & candle_confirm
    else:
        df["bullish_candle_confirm"] = False
        df["long_signal"] = False

    df["long_exit"] = df["close"] < df["exit_low"]
    return df.dropna()


def is_signal_bar_close(current_time: pd.Timestamp) -> bool:
    return (current_time.minute + 1) % 15 == 0


def signal_bar_timestamp(current_time: pd.Timestamp, timeframe: str = "15min") -> pd.Timestamp:
    return current_time.floor(timeframe)


def next_1m_open(data_1m: pd.DataFrame, signal_close_time: pd.Timestamp) -> tuple[pd.Timestamp, float]:
    """Return the first 1m open strictly after signal_close_time."""
    future = data_1m.loc[data_1m.index > signal_close_time]
    if future.empty:
        raise ValueError(f"No 1m bar after {signal_close_time}")
    ts = future.index[0]
    return ts, float(future.iloc[0]["open"])


def entry_reason_for_mode(entry_mode: EntryMode) -> str:
    return ENTRY_REASONS[entry_mode]
