"""Second alpha source event-study helpers.

The module studies mean-reversion style candidates independently from P4.
It uses close-labeled 15m bars and next 1m open execution.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from research_core.event_table import HORIZONS, add_base_indicators, next_1m_open, strict_resample_15m


SYMBOLS = ["ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT"]
CANDIDATES = ["FB1_FAILED_BREAKOUT_REVERSION", "MR1_SHORT_TERM_DEVIATION_REVERSION"]
RANGE_N = 32
MR_ATR_MULT = 1.5
MAX_TREND_STRENGTH = 3.0
RANDOM_SEED = 20260624


@dataclass(frozen=True)
class EventConfig:
    range_n: int = RANGE_N
    mr_atr_mult: float = MR_ATR_MULT
    max_trend_strength: float = MAX_TREND_STRENGTH


def add_second_alpha_indicators(df_15m: pd.DataFrame, config: EventConfig = EventConfig()) -> pd.DataFrame:
    out = add_base_indicators(df_15m)
    out["ema20"] = out["close"].ewm(span=20, adjust=False).mean()
    out["range_upper"] = out["high"].shift(1).rolling(config.range_n).max()
    out["range_lower"] = out["low"].shift(1).rolling(config.range_n).min()
    out["range_mid"] = (out["range_upper"] + out["range_lower"]) / 2
    out["trend_strength_atr"] = (out["ema50"] - out["ema200"]).abs() / out["atr14"]
    out["atr_pct"] = out["atr14"] / out["close"]
    out["atr_percentile_200"] = out["atr_pct"].rolling(200, min_periods=50).rank(pct=True)
    out["volatility_regime"] = pd.cut(
        out["atr_percentile_200"],
        bins=[-np.inf, 0.33, 0.67, np.inf],
        labels=["low_vol", "mid_vol", "high_vol"],
    ).astype("object").fillna("unknown")
    out["trend_regime"] = np.select(
        [
            (out["ema50"] > out["ema200"]) & (out["trend_strength_atr"] >= config.max_trend_strength),
            (out["ema50"] < out["ema200"]) & (out["trend_strength_atr"] >= config.max_trend_strength),
        ],
        ["strong_up", "strong_down"],
        default="weak_or_range",
    )
    out["deviation_ema20_atr"] = (out["close"] - out["ema20"]) / out["atr14"]
    return out


def first_touch_directional(window: pd.DataFrame, entry: float, atr: float, direction: int) -> str:
    if not np.isfinite(entry) or not np.isfinite(atr) or atr <= 0:
        return "none"
    favorable = entry + direction * atr
    adverse = entry - direction * atr
    for _, bar in window.iterrows():
        hit_fav = bar["high"] >= favorable if direction > 0 else bar["low"] <= favorable
        hit_adv = bar["low"] <= adverse if direction > 0 else bar["high"] >= adverse
        if hit_fav and hit_adv:
            return "ambiguous"
        if hit_fav:
            return "plus"
        if hit_adv:
            return "minus"
    return "none"


def directional_labels(df_15m: pd.DataFrame, signal_time: pd.Timestamp, entry: float, atr: float, direction: int) -> dict:
    return directional_labels_at_pos(df_15m, df_15m.index.get_loc(signal_time), entry, atr, direction)


def directional_labels_at_pos(df_15m: pd.DataFrame, loc: int, entry: float, atr: float, direction: int) -> dict:
    labels = {}
    for h in HORIZONS:
        window = df_15m.iloc[loc + 1: loc + 1 + h]
        if len(window) < h:
            labels[f"fwd_ret_{h}"] = np.nan
            labels[f"fwd_mfe_{h}"] = np.nan
            labels[f"fwd_mae_{h}"] = np.nan
            labels[f"plus_1atr_first_{h}"] = np.nan
            labels[f"minus_1atr_first_{h}"] = np.nan
            labels[f"ambiguous_touch_{h}"] = np.nan
            continue
        raw_ret = window["close"].iloc[-1] / entry - 1
        labels[f"fwd_ret_{h}"] = direction * raw_ret
        if direction > 0:
            labels[f"fwd_mfe_{h}"] = window["high"].max() / entry - 1
            labels[f"fwd_mae_{h}"] = window["low"].min() / entry - 1
        else:
            labels[f"fwd_mfe_{h}"] = entry / window["low"].min() - 1
            labels[f"fwd_mae_{h}"] = entry / window["high"].max() - 1
        outcome = first_touch_directional(window, entry, atr, direction)
        labels[f"plus_1atr_first_{h}"] = outcome == "plus"
        labels[f"minus_1atr_first_{h}"] = outcome == "minus"
        labels[f"ambiguous_touch_{h}"] = outcome == "ambiguous"
    return labels


def mean_reversion_time(df_15m: pd.DataFrame, signal_time: pd.Timestamp, direction: int, target: float, max_bars: int = 32) -> int | float:
    return mean_reversion_time_at_pos(df_15m, df_15m.index.get_loc(signal_time), direction, target, max_bars=max_bars)


def mean_reversion_time_at_pos(df_15m: pd.DataFrame, loc: int, direction: int, target: float, max_bars: int = 32) -> int | float:
    window = df_15m.iloc[loc + 1: loc + 1 + max_bars]
    for i, (_, bar) in enumerate(window.iterrows(), start=1):
        if direction > 0 and bar["high"] >= target:
            return i
        if direction < 0 and bar["low"] <= target:
            return i
    return np.nan


def subsequent_trend_breakout(df_15m: pd.DataFrame, signal_time: pd.Timestamp, direction: int, max_bars: int = 32) -> bool:
    return subsequent_trend_breakout_at_pos(df_15m, df_15m.index.get_loc(signal_time), direction, max_bars=max_bars)


def subsequent_trend_breakout_at_pos(df_15m: pd.DataFrame, loc: int, direction: int, max_bars: int = 32) -> bool:
    window = df_15m.iloc[loc + 1: loc + 1 + max_bars]
    if window.empty:
        return False
    if direction > 0:
        return bool((window["close"] > window["donchian55_upper"]).any())
    return bool((window["close"] < window["donchian20_lower"]).any())


def build_candidate_events(data_1m: pd.DataFrame, symbol: str, config: EventConfig = EventConfig()) -> tuple[pd.DataFrame, pd.DataFrame]:
    df_15m = add_second_alpha_indicators(strict_resample_15m(data_1m), config)
    index_1m = data_1m.index
    open_1m = data_1m["open"].to_numpy(float)

    def fast_next_open(signal_time: pd.Timestamp) -> tuple[pd.Timestamp, float] | tuple[None, None]:
        pos = index_1m.searchsorted(signal_time)
        if pos >= len(index_1m):
            return None, None
        return index_1m[pos], float(open_1m[pos])

    weak = df_15m["trend_strength_atr"] < config.max_trend_strength
    valid = df_15m["atr14"].notna() & df_15m["range_upper"].notna() & weak
    fb_long = valid & (df_15m["low"] < df_15m["range_lower"]) & (df_15m["close"] > df_15m["range_lower"]) & (df_15m["close"] < df_15m["range_mid"])
    fb_short = valid & (df_15m["high"] > df_15m["range_upper"]) & (df_15m["close"] < df_15m["range_upper"]) & (df_15m["close"] > df_15m["range_mid"])
    mr_long = valid & (df_15m["close"] < df_15m["ema20"] - config.mr_atr_mult * df_15m["atr14"])
    mr_short = valid & (df_15m["close"] > df_15m["ema20"] + config.mr_atr_mult * df_15m["atr14"])

    specs = [
        ("FB1_FAILED_BREAKOUT_REVERSION", "long", 1, fb_long, "range_mid"),
        ("FB1_FAILED_BREAKOUT_REVERSION", "short", -1, fb_short, "range_mid"),
        ("MR1_SHORT_TERM_DEVIATION_REVERSION", "long", 1, mr_long, "ema20"),
        ("MR1_SHORT_TERM_DEVIATION_REVERSION", "short", -1, mr_short, "ema20"),
    ]
    rows = []
    for candidate, side, direction, mask, target_col in specs:
        for loc in np.flatnonzero(mask.to_numpy()):
            ts = df_15m.index[loc]
            row = df_15m.iloc[loc]
            execution_time, execution_open = fast_next_open(ts)
            if execution_time is None:
                continue
            target = float(row[target_col])
            event = {
                "event_id": f"{candidate}_{symbol}_{side}_{ts.isoformat()}",
                "candidate": candidate,
                "symbol": symbol,
                "signal_time": ts,
                "execution_time": execution_time,
                "execution_open": execution_open,
                "direction": direction,
                "side": side,
                "range_upper": row["range_upper"],
                "range_lower": row["range_lower"],
                "range_mid": row["range_mid"],
                "short_mean": row["ema20"],
                "atr14": row["atr14"],
                "deviation_ema20_atr": row["deviation_ema20_atr"],
                "failed_breakout_depth_atr": ((row["range_lower"] - row["low"]) / row["atr14"]) if direction > 0 else ((row["high"] - row["range_upper"]) / row["atr14"]),
                "trend_strength_atr": row["trend_strength_atr"],
                "trend_regime": row["trend_regime"],
                "volatility_regime": row["volatility_regime"],
                "atr_pct": row["atr_pct"],
                "atr_percentile_200": row["atr_percentile_200"],
                "mean_target": target,
                "mean_reversion_bars": mean_reversion_time_at_pos(df_15m, loc, direction, target),
                "subsequent_trend_breakout": subsequent_trend_breakout_at_pos(df_15m, loc, direction),
            }
            event.update(directional_labels_at_pos(df_15m, loc, execution_open, float(row["atr14"]), direction))
            rows.append(event)
    return pd.DataFrame(rows), df_15m


def summarize_events(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, part in events.groupby(["candidate", "symbol", "side"]):
        row = {"candidate": keys[0], "symbol": keys[1], "side": keys[2], "event_count": len(part)}
        for h in HORIZONS:
            row[f"mean_fwd_ret_{h}"] = part[f"fwd_ret_{h}"].mean()
            row[f"median_fwd_ret_{h}"] = part[f"fwd_ret_{h}"].median()
            row[f"plus_1atr_first_rate_{h}"] = part[f"plus_1atr_first_{h}"].mean()
            row[f"minus_1atr_first_rate_{h}"] = part[f"minus_1atr_first_{h}"].mean()
            row[f"ambiguous_rate_{h}"] = part[f"ambiguous_touch_{h}"].mean()
        row["mean_reversion_rate_32"] = part["mean_reversion_bars"].notna().mean()
        row["median_reversion_bars"] = part["mean_reversion_bars"].median()
        rows.append(row)
    return pd.DataFrame(rows)


def regime_summary(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, part in events.groupby(["candidate", "trend_regime", "volatility_regime"]):
        rows.append({
            "candidate": keys[0],
            "trend_regime": keys[1],
            "volatility_regime": keys[2],
            "event_count": len(part),
            "mean_fwd_ret_16": part["fwd_ret_16"].mean(),
            "plus_1atr_first_rate_16": part["plus_1atr_first_16"].mean(),
            "minus_1atr_first_rate_16": part["minus_1atr_first_16"].mean(),
            "mean_reversion_rate_32": part["mean_reversion_bars"].notna().mean(),
        })
    return pd.DataFrame(rows)


def top_trade_dependency(events: pd.DataFrame, horizon: int = 16) -> pd.DataFrame:
    rows = []
    col = f"fwd_ret_{horizon}"
    for keys, part in events.groupby(["candidate", "symbol"]):
        vals = part[col].dropna().sort_values(ascending=False)
        positive = vals[vals > 0]
        total = positive.sum()
        rows.append({
            "candidate": keys[0],
            "symbol": keys[1],
            "event_count": len(part),
            "top1_positive_contribution": positive.head(1).sum() / total if total > 0 else np.nan,
            "top3_positive_contribution": positive.head(3).sum() / total if total > 0 else np.nan,
            "top5_positive_contribution": positive.head(5).sum() / total if total > 0 else np.nan,
            "remove_top3_mean_fwd_ret": vals.iloc[3:].mean() if len(vals) > 3 else np.nan,
            "top1pct_positive_contribution": positive.head(max(1, int(len(positive) * 0.01))).sum() / total if total > 0 else np.nan,
        })
    return pd.DataFrame(rows)
