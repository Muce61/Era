"""Bullish Hikkake pattern detection."""

import pandas as pd


def is_inside_bar(df: pd.DataFrame, idx: int) -> bool:
    if idx < 1:
        return False
    prev = df.iloc[idx - 1]
    curr = df.iloc[idx]
    return bool(curr["high"] < prev["high"] and curr["low"] > prev["low"])


def is_bullish_hikkake_setup(df: pd.DataFrame, inside_idx: int) -> bool:
    setup_idx = inside_idx + 1
    if setup_idx >= len(df):
        return False
    inside = df.iloc[inside_idx]
    setup = df.iloc[setup_idx]
    return bool(setup["high"] < inside["high"] and setup["low"] < inside["low"])


def is_bullish_hikkake_confirm(row: pd.Series, inside_bar_high: float) -> bool:
    return bool(row["high"] > inside_bar_high)
