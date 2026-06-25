"""Event table generation and forward-label helpers."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from strategy.candlestick_patterns import add_candle_metrics, is_bullish_engulfing, strong_breakout_confirm
from strategy.hikkake_patterns import is_bullish_hikkake_confirm, is_bullish_hikkake_setup, is_inside_bar


HORIZONS = [1, 4, 8, 16, 32]


def load_ohlcv_1m(path: Path | str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df.columns = [c.lower() for c in df.columns]
    df = df.dropna(subset=["timestamp"]).set_index("timestamp").sort_index()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    df = df[~df.index.duplicated(keep="last")]
    required = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing OHLCV columns: {missing}")
    return df[required]


def strict_resample_15m(data_1m: pd.DataFrame) -> pd.DataFrame:
    grouped = data_1m.resample("15min").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        minute_count=("close", "count"),
    )
    return grouped[grouped["minute_count"] == 15].drop(columns=["minute_count"]).dropna()


def add_base_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema50"] = out["close"].ewm(span=50, adjust=False).mean()
    out["ema200"] = out["close"].ewm(span=200, adjust=False).mean()
    prev_close = out["close"].shift(1)
    tr = pd.concat([
        out["high"] - out["low"],
        (out["high"] - prev_close).abs(),
        (out["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    out["atr14"] = tr.rolling(14).mean()
    out["donchian55_upper"] = out["high"].shift(1).rolling(55).max()
    out["donchian20_lower"] = out["low"].shift(1).rolling(20).min()
    out["donchian20_upper"] = out["high"].shift(1).rolling(20).max()
    return out


def next_1m_open(data_1m: pd.DataFrame, signal_time: pd.Timestamp) -> tuple[pd.Timestamp, float] | tuple[None, None]:
    future = data_1m.loc[data_1m.index > signal_time]
    if future.empty:
        return None, None
    ts = future.index[0]
    return ts, float(future.iloc[0]["open"])


def first_touch_outcome(window: pd.DataFrame, entry: float, atr: float) -> str:
    if not np.isfinite(entry) or not np.isfinite(atr) or atr <= 0:
        return "none"
    up = entry + atr
    down = entry - atr
    for _, bar in window.iterrows():
        hit_up = bar["high"] >= up
        hit_down = bar["low"] <= down
        if hit_up and hit_down:
            return "ambiguous"
        if hit_up:
            return "plus"
        if hit_down:
            return "minus"
    return "none"


def forward_labels(df_15m: pd.DataFrame, signal_time: pd.Timestamp, entry_price: float, atr: float, horizons=HORIZONS) -> dict:
    labels = {}
    loc = df_15m.index.get_loc(signal_time)
    for h in horizons:
        window = df_15m.iloc[loc + 1: loc + 1 + h]
        if len(window) < h:
            labels[f"fwd_ret_{h}"] = np.nan
            labels[f"fwd_mfe_{h}"] = np.nan
            labels[f"fwd_mae_{h}"] = np.nan
            labels[f"plus_1atr_first_{h}"] = np.nan
            labels[f"minus_1atr_first_{h}"] = np.nan
            labels[f"ambiguous_touch_{h}"] = np.nan
            continue
        labels[f"fwd_ret_{h}"] = window["close"].iloc[-1] / entry_price - 1.0
        labels[f"fwd_mfe_{h}"] = window["high"].max() / entry_price - 1.0
        labels[f"fwd_mae_{h}"] = window["low"].min() / entry_price - 1.0
        outcome = first_touch_outcome(window, entry_price, atr)
        labels[f"plus_1atr_first_{h}"] = outcome == "plus"
        labels[f"minus_1atr_first_{h}"] = outcome == "minus"
        labels[f"ambiguous_touch_{h}"] = outcome == "ambiguous"
    return labels


def add_factor_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = add_candle_metrics(df)
    out["ema_gap_atr"] = (out["ema50"] - out["ema200"]) / out["atr14"]
    out["ema200_slope_4h"] = out["ema200"] - out["ema200"].shift(16)
    out["ret_4h"] = out["close"] / out["close"].shift(16) - 1
    out["ret_12h"] = out["close"] / out["close"].shift(48) - 1
    out["ret_24h"] = out["close"] / out["close"].shift(96) - 1
    out["breakout_distance_atr"] = (out["close"] - out["donchian55_upper"]) / out["atr14"]
    out["atr_pct"] = out["atr14"] / out["close"]
    out["atr_percentile_200"] = out["atr_pct"].rolling(200, min_periods=50).rank(pct=True)
    out["range_atr"] = (out["high"] - out["low"]) / out["atr14"]
    short_vol = out["close"].pct_change().rolling(16).std()
    long_vol = out["close"].pct_change().rolling(96).std()
    out["volatility_ratio_short_long"] = short_vol / long_vol
    out["lower_shadow_ratio"] = (out[["open", "close"]].min(axis=1) - out["low"]) / (out["high"] - out["low"]).replace(0, np.nan)
    out["pullback_depth_atr"] = (out["donchian55_upper"] - out["low"]) / out["atr14"]
    out["inside_bar_compression"] = (out["high"] - out["low"]) / (out["high"].shift(1) - out["low"].shift(1)).replace(0, np.nan)
    return out


def build_event_candidates(data_1m: pd.DataFrame, symbol: str = "ETHUSDT") -> tuple[pd.DataFrame, pd.DataFrame]:
    df_15m = add_factor_columns(add_base_indicators(strict_resample_15m(data_1m)))
    strong = strong_breakout_confirm(df_15m)
    base = (df_15m["close"] > df_15m["donchian55_upper"]) & (df_15m["ema50"] > df_15m["ema200"]) & df_15m["atr14"].notna()
    rows = []
    bars_after_breakout = 0
    active_breakout = False
    for idx, (ts, row) in enumerate(df_15m.iterrows()):
        is_breakout = bool(base.loc[ts])
        if is_breakout and not active_breakout:
            bars_after_breakout = 0
            active_breakout = True
        elif active_breakout:
            bars_after_breakout += 1
        if active_breakout and (row["close"] < row["donchian20_lower"] or row["ema50"] <= row["ema200"]):
            active_breakout = False
        if not is_breakout:
            continue
        execution_time, execution_open = next_1m_open(data_1m, ts)
        if execution_time is None:
            continue
        inside = is_inside_bar(df_15m, idx)
        hikkake_setup = (
            idx >= 1
            and is_inside_bar(df_15m, idx - 1)
            and is_bullish_hikkake_setup(df_15m, idx - 1)
        )
        hikkake_confirm = False
        if idx >= 2:
            # Conservative label: any recent inside bar confirmed by current high.
            for lookback in [1, 2, 3]:
                inside_idx = idx - lookback
                if inside_idx >= 0 and is_inside_bar(df_15m, inside_idx):
                    hikkake_confirm = is_bullish_hikkake_confirm(row, float(df_15m.iloc[inside_idx]["high"]))
                    if hikkake_confirm:
                        break
        event = {
            "event_id": f"{symbol}_{ts.isoformat()}",
            "symbol": symbol,
            "signal_time": ts,
            "execution_time": execution_time,
            "execution_open": execution_open,
            "close_15m": row["close"],
            "open_15m": row["open"],
            "high_15m": row["high"],
            "low_15m": row["low"],
            "volume_15m": row["volume"],
            "donchian55_upper": row["donchian55_upper"],
            "donchian20_lower": row["donchian20_lower"],
            "ema50": row["ema50"],
            "ema200": row["ema200"],
            "atr14": row["atr14"],
            "strong_breakout": bool(strong.loc[ts]),
            "pullback_engulfing": is_bullish_engulfing(df_15m, idx),
            "bullish_hikkake": bool(hikkake_confirm),
            "first_breakout_after_flat": bars_after_breakout == 0,
            "bars_after_breakout": bars_after_breakout,
            "inside_bar": bool(inside),
            "hikkake_setup": bool(hikkake_setup),
            "hikkake_confirm": bool(hikkake_confirm),
            "trend_regime": "unavailable",
            "volatility_regime": "unavailable",
            "relative_strength_regime": "unavailable",
        }
        for col in FACTOR_COLUMNS:
            event[col] = row.get(col, np.nan)
        event.update(forward_labels(df_15m, ts, execution_open, float(row["atr14"])))
        rows.append(event)
    return pd.DataFrame(rows), df_15m


FACTOR_COLUMNS = [
    "ema_gap_atr",
    "ema200_slope_4h",
    "ret_4h",
    "ret_12h",
    "ret_24h",
    "breakout_distance_atr",
    "atr_pct",
    "atr_percentile_200",
    "range_atr",
    "volatility_ratio_short_long",
    "body_ratio",
    "upper_shadow_ratio",
    "lower_shadow_ratio",
    "close_location",
    "bars_after_breakout",
    "pullback_depth_atr",
    "inside_bar_compression",
]


FACTOR_COMMON = {
    "ema_gap_atr": "Trend separation: EMA50 distance above EMA200 normalized by ATR.",
    "ema200_slope_4h": "Slow trend slope: 4-hour change in EMA200 showing background trend acceleration.",
    "ret_4h": "Short momentum: 4-hour price return before the signal.",
    "ret_12h": "Intraday momentum: 12-hour price return before the signal.",
    "ret_24h": "Daily momentum: 24-hour price return before the signal.",
    "breakout_distance_atr": "Breakout extension: close distance beyond Donchian55 upper normalized by ATR.",
    "atr_pct": "Absolute volatility: ATR as a percentage of close.",
    "atr_percentile_200": "Local volatility regime: ATR percentile within the previous 200 15m bars.",
    "range_atr": "Signal-bar range expansion: current 15m range normalized by ATR.",
    "volatility_ratio_short_long": "Volatility expansion: short ATR level relative to its longer rolling average.",
    "body_ratio": "Candle conviction: real body share of the full candle range.",
    "upper_shadow_ratio": "Upper rejection: upper wick share of the full candle range.",
    "lower_shadow_ratio": "Lower rejection: lower wick share of the full candle range.",
    "close_location": "Close strength: close location within the 15m high-low range.",
    "bars_after_breakout": "Trend age: number of 15m bars since the Donchian55 breakout state began.",
    "pullback_depth_atr": "Pullback depth: distance from recent high to current close normalized by ATR.",
    "inside_bar_compression": "Compression: current range relative to previous range for inside-bar style contraction.",
}
