"""Candlestick entry confirmation patterns for ETH trend signals."""

import pandas as pd


def add_candle_metrics(df: pd.DataFrame) -> pd.DataFrame:
    candle_range = (df["high"] - df["low"]).replace(0, pd.NA)
    body = (df["close"] - df["open"]).abs()
    upper_shadow = df["high"] - df[["open", "close"]].max(axis=1)

    out = df.copy()
    out["body_ratio"] = body / candle_range
    out["upper_shadow_ratio"] = upper_shadow / candle_range
    out["close_location"] = (df["close"] - df["low"]) / candle_range
    out["volume_ma20"] = df["volume"].shift(1).rolling(20).mean()
    return out


def strong_breakout_confirm(df: pd.DataFrame) -> pd.Series:
    return (
        (df["close"] > df["open"]) &
        (df["body_ratio"] >= 0.35) &
        (df["upper_shadow_ratio"] <= 0.30) &
        (df["close_location"] >= 0.70) &
        (df["volume"] >= df["volume_ma20"])
    )


def is_bullish_engulfing(df: pd.DataFrame, idx: int) -> bool:
    if idx < 1:
        return False
    prev = df.iloc[idx - 1]
    curr = df.iloc[idx]
    prev_bearish = prev["close"] < prev["open"]
    curr_bullish = curr["close"] > curr["open"]
    body_engulfed = (
        curr["open"] <= prev["close"] and
        curr["close"] >= prev["open"]
    )
    return bool(prev_bearish and curr_bullish and body_engulfed)


def pullback_engulfing_confirm(df: pd.DataFrame) -> pd.Series:
    raise NotImplementedError("Use entry_handlers for PULLBACK_ENGULFING")


def bullish_hikkake_confirm(df: pd.DataFrame) -> pd.Series:
    raise NotImplementedError("Use entry_handlers for BULLISH_HIKKAKE")


def no_candle_confirm(df: pd.DataFrame) -> pd.Series:
    return pd.Series(True, index=df.index)


def trend_segment_entry_confirm(df: pd.DataFrame) -> pd.Series:
    raise NotImplementedError("Use entry_handlers for TREND_SEGMENT_ENTRY")
