"""P4 short mirror event construction and event-level diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from research_core.event_table import HORIZONS, load_ohlcv_1m, next_1m_open, strict_resample_15m
from strategy.candlestick_patterns import add_candle_metrics


SYMBOLS = ["ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT"]
PROTOTYPE = "P4_SHORT_MIRROR_V1"
START_UTC = pd.Timestamp("2020-01-01 00:00:00+00:00")
END_UTC = pd.Timestamp("2026-06-28 01:05:00+00:00")
DATA_ROOT = Path("/Users/muce/1m_data/long_history_1m/merged")


@dataclass(frozen=True)
class ShortEventCriteria:
    entry_donchian: int = 55
    exit_donchian: int = 20
    ema_fast: int = 50
    ema_slow: int = 200
    atr_period: int = 14
    stop_atr_mult: float = 3.0


def load_symbol_1m(symbol: str, data_root: Path = DATA_ROOT) -> pd.DataFrame:
    data = load_ohlcv_1m(data_root / f"{symbol}.csv")
    return data[(data.index >= START_UTC) & (data.index <= END_UTC)].copy()


def add_short_indicators(data_15m: pd.DataFrame, criteria: ShortEventCriteria = ShortEventCriteria()) -> pd.DataFrame:
    out = add_candle_metrics(data_15m.copy())
    out["ema50"] = out["close"].ewm(span=criteria.ema_fast, adjust=False).mean()
    out["ema200"] = out["close"].ewm(span=criteria.ema_slow, adjust=False).mean()
    prev_close = out["close"].shift(1)
    tr = pd.concat([
        out["high"] - out["low"],
        (out["high"] - prev_close).abs(),
        (out["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    out["atr14"] = tr.rolling(criteria.atr_period).mean()
    out["donchian55_upper"] = out["high"].shift(1).rolling(criteria.entry_donchian).max()
    out["donchian55_lower"] = out["low"].shift(1).rolling(criteria.entry_donchian).min()
    out["donchian20_upper"] = out["high"].shift(1).rolling(criteria.exit_donchian).max()
    out["donchian20_lower"] = out["low"].shift(1).rolling(criteria.exit_donchian).min()
    out["atr_pct"] = out["atr14"] / out["close"]
    out["atr_percentile_200"] = out["atr_pct"].rolling(200, min_periods=50).rank(pct=True)
    out["volatility_ratio_short_long"] = out["close"].pct_change().rolling(16).std() / out["close"].pct_change().rolling(96).std()
    out["short_breakout_distance_atr"] = (out["donchian55_lower"] - out["close"]) / out["atr14"]
    out["volume_mean"] = out["volume"].shift(1).rolling(96, min_periods=20).mean()
    out["trend_regime"] = np.where(out["ema50"] < out["ema200"], "bear", "not_bear")
    out["trend_strength_atr"] = (out["ema200"] - out["ema50"]) / out["atr14"]
    out["trend_strength_bucket"] = pd.cut(
        out["trend_strength_atr"],
        bins=[-np.inf, 0.5, 1.0, 1.5, 2.5, np.inf],
        labels=["0_0_5", "0_5_1_0", "1_0_1_5", "1_5_2_5", "gt_2_5"],
    ).astype("object").fillna("unknown")
    out["volatility_regime"] = pd.cut(
        out["atr_percentile_200"],
        bins=[-np.inf, 0.33, 0.66, np.inf],
        labels=["low_vol", "mid_vol", "high_vol"],
    ).astype("object").fillna("unknown")
    return out


def short_first_touch_outcome(window: pd.DataFrame, entry: float, atr: float) -> str:
    if not np.isfinite(entry) or not np.isfinite(atr) or atr <= 0:
        return "none"
    favorable = entry - atr
    adverse = entry + atr
    for _, bar in window.iterrows():
        hit_plus = float(bar["low"]) <= favorable
        hit_minus = float(bar["high"]) >= adverse
        if hit_plus and hit_minus:
            return "ambiguous"
        if hit_plus:
            return "plus"
        if hit_minus:
            return "minus"
    return "none"


def short_forward_labels(data_15m: pd.DataFrame, signal_time: pd.Timestamp, entry_price: float, atr: float) -> dict:
    labels: dict[str, object] = {}
    loc = data_15m.index.get_loc(signal_time)
    for horizon in HORIZONS:
        window = data_15m.iloc[loc + 1: loc + 1 + horizon]
        if len(window) < horizon:
            labels[f"short_fwd_ret_{horizon}"] = np.nan
            labels[f"short_mfe_{horizon}"] = np.nan
            labels[f"short_mae_{horizon}"] = np.nan
            labels[f"plus_1atr_first_{horizon}"] = np.nan
            labels[f"minus_1atr_first_{horizon}"] = np.nan
            labels[f"ambiguous_touch_{horizon}"] = np.nan
            continue
        labels[f"short_fwd_ret_{horizon}"] = entry_price / float(window["close"].iloc[-1]) - 1.0
        labels[f"short_mfe_{horizon}"] = entry_price / float(window["low"].min()) - 1.0
        labels[f"short_mae_{horizon}"] = float(window["high"].max()) / entry_price - 1.0
        outcome = short_first_touch_outcome(window, entry_price, atr)
        labels[f"plus_1atr_first_{horizon}"] = outcome == "plus"
        labels[f"minus_1atr_first_{horizon}"] = outcome == "minus"
        labels[f"ambiguous_touch_{horizon}"] = outcome == "ambiguous"
    return labels


def build_short_events_for_symbol(symbol: str, data_1m: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    data_15m = add_short_indicators(strict_resample_15m(data_1m))
    base = (
        (data_15m["close"] < data_15m["donchian55_lower"])
        & (data_15m["ema50"] < data_15m["ema200"])
        & data_15m["atr14"].notna()
    )
    rows = []
    for ts, row in data_15m.loc[base].iterrows():
        execution_time, execution_open = next_1m_open(data_1m, ts)
        if execution_time is None:
            continue
        atr = float(row["atr14"])
        event = {
            "event_id": f"{symbol}_SHORT_{ts.isoformat()}",
            "symbol": symbol,
            "prototype": PROTOTYPE,
            "signal_time": ts,
            "execution_time": execution_time,
            "execution_open": execution_open,
            "close_15m": row["close"],
            "donchian55_lower": row["donchian55_lower"],
            "donchian20_upper": row["donchian20_upper"],
            "ema50": row["ema50"],
            "ema200": row["ema200"],
            "atr14": row["atr14"],
            "body_ratio": row.get("body_ratio", np.nan),
            "close_location": row.get("close_location", np.nan),
            "lower_shadow_ratio": row.get("lower_shadow_ratio", np.nan),
            "upper_shadow_ratio": row.get("upper_shadow_ratio", np.nan),
            "volume": row["volume"],
            "volume_mean": row.get("volume_mean", np.nan),
            "trend_regime": row.get("trend_regime", "bear"),
            "volatility_regime": row.get("volatility_regime", "unknown"),
            "trend_strength_bucket": row.get("trend_strength_bucket", "unknown"),
            "short_breakout_distance_atr": row.get("short_breakout_distance_atr", np.nan),
            "data_layer": "expanded_discovery",
            "oos_status": "not_oos",
        }
        event.update(short_forward_labels(data_15m, ts, float(execution_open), atr))
        rows.append(event)
    return pd.DataFrame(rows), data_15m


def summarize_events(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    rows = []
    for symbol, part in events.groupby("symbol"):
        row = {"symbol": symbol, "event_count": len(part)}
        for horizon in HORIZONS:
            row[f"mean_short_fwd_ret_{horizon}"] = float(part[f"short_fwd_ret_{horizon}"].mean())
            row[f"median_short_fwd_ret_{horizon}"] = float(part[f"short_fwd_ret_{horizon}"].median())
            row[f"plus_1atr_first_rate_{horizon}"] = float(part[f"plus_1atr_first_{horizon}"].mean())
            row[f"minus_1atr_first_rate_{horizon}"] = float(part[f"minus_1atr_first_{horizon}"].mean())
            row[f"ambiguous_rate_{horizon}"] = float(part[f"ambiguous_touch_{horizon}"].mean())
        rows.append(row)
    all_row = {"symbol": "ALL", "event_count": len(events)}
    for horizon in HORIZONS:
        all_row[f"mean_short_fwd_ret_{horizon}"] = float(events[f"short_fwd_ret_{horizon}"].mean())
        all_row[f"median_short_fwd_ret_{horizon}"] = float(events[f"short_fwd_ret_{horizon}"].median())
        all_row[f"plus_1atr_first_rate_{horizon}"] = float(events[f"plus_1atr_first_{horizon}"].mean())
        all_row[f"minus_1atr_first_rate_{horizon}"] = float(events[f"minus_1atr_first_{horizon}"].mean())
        all_row[f"ambiguous_rate_{horizon}"] = float(events[f"ambiguous_touch_{horizon}"].mean())
    rows.append(all_row)
    return pd.DataFrame(rows)


def build_bear_state_pool(symbol: str, data_1m: pd.DataFrame) -> pd.DataFrame:
    data_15m = add_short_indicators(strict_resample_15m(data_1m))
    eligible = data_15m[(data_15m["ema50"] < data_15m["ema200"]) & data_15m["atr14"].notna()].copy()
    if eligible.empty:
        return pd.DataFrame()
    execution_open = data_1m["open"].reindex(eligible.index)
    eligible = eligible.loc[execution_open.notna()].copy()
    execution_open = execution_open.loc[eligible.index]
    locs = data_15m.index.get_indexer(eligible.index)
    future_locs = locs + 16
    valid = future_locs < len(data_15m)
    eligible = eligible.iloc[np.flatnonzero(valid)].copy()
    execution_open = execution_open.iloc[np.flatnonzero(valid)]
    future_close = data_15m["close"].iloc[future_locs[valid]].to_numpy(float)
    out = pd.DataFrame({
        "event_id": [f"{symbol}_RANDOM_BEAR_{ts.isoformat()}" for ts in eligible.index],
        "symbol": symbol,
        "signal_time": eligible.index,
        "execution_time": eligible.index,
        "execution_open": execution_open.to_numpy(float),
        "volatility_regime": eligible["volatility_regime"].to_numpy(object),
        "trend_strength_bucket": eligible["trend_strength_bucket"].to_numpy(object),
        "quarter": eligible.index.to_period("Q").astype(str),
        "atr14": eligible["atr14"].to_numpy(float),
        "short_fwd_ret_16": execution_open.to_numpy(float) / future_close - 1.0,
    })
    return out
