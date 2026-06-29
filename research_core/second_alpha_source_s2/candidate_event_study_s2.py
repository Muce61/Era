"""Canonical S2 second-alpha event study helpers.

This module is event research only. It keeps the real 15m close-time
alignment and simulates P4 held state from entry until Donchian20 exit.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from research_core.event_table import HORIZONS, add_base_indicators, strict_resample_15m


SYMBOLS = ["ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT"]
CANDIDATES = [
    "FB2_FAILED_BREAKOUT_FAST_REVERSION",
    "MR2_DEVIATION_CONFIRMED_REVERSION",
    "IDLE_MR1_P4_IDLE_REVERSION",
    "RV1_LITE_ETHBTC_RELATIVE",
]
IDLE_CANDIDATE = "IDLE_MR1_P4_IDLE_REVERSION"
RANDOM_SEED = 20260624


@dataclass(frozen=True)
class EventConfigS2:
    range_n: int = 32
    mr_atr_mult: float = 1.5
    max_trend_strength: float = 2.5
    fb_recover_frac: float = 0.20
    fb_max_depth_atr: float = 1.8
    confirm_bars: int = 3


def add_trend_strength_bucket(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["trend_strength_bucket"] = pd.cut(
        out["trend_strength_atr"],
        bins=[-np.inf, 0.5, 1.0, 1.5, 2.5, np.inf],
        labels=["0_0.5", "0.5_1.0", "1.0_1.5", "1.5_2.5", "gt_2.5"],
    ).astype("object").fillna("unknown")
    return out


def simulate_p4_state(df_15m: pd.DataFrame) -> pd.DataFrame:
    """Attach P4 held state and post-exit phase using current/past bars only."""
    out = df_15m.copy()
    p4_entry = (out["close"] > out["donchian55_upper"]) & (out["ema50"] > out["ema200"]) & out["atr14"].notna()
    p4_exit = out["close"] < out["donchian20_lower"]
    held = False
    last_exit_loc: int | None = None
    p4_held = []
    phase = []
    bars_since_exit = []
    for loc, _ in enumerate(out.itertuples()):
        entry_now = bool(p4_entry.iloc[loc])
        exit_now = bool(p4_exit.iloc[loc])
        if held:
            if exit_now:
                held = False
                last_exit_loc = loc
                p4_held.append(False)
                phase.append("after_p4_exit_0_4_bars")
                bars_since_exit.append(0)
            else:
                p4_held.append(True)
                phase.append("p4_held")
                bars_since_exit.append(loc - last_exit_loc if last_exit_loc is not None else np.nan)
        else:
            if entry_now:
                held = True
                p4_held.append(True)
                phase.append("p4_held")
                bars_since_exit.append(loc - last_exit_loc if last_exit_loc is not None else np.nan)
            elif last_exit_loc is None:
                p4_held.append(False)
                phase.append("deep_idle")
                bars_since_exit.append(np.nan)
            else:
                since = loc - last_exit_loc
                if since <= 4:
                    bucket = "after_p4_exit_0_4_bars"
                elif since <= 16:
                    bucket = "after_p4_exit_5_16_bars"
                elif since <= 64:
                    bucket = "after_p4_exit_17_64_bars"
                else:
                    bucket = "deep_idle"
                p4_held.append(False)
                phase.append(bucket)
                bars_since_exit.append(since)
    out["p4_held"] = p4_held
    out["p4_entry_condition"] = p4_entry.astype(bool)
    out["p4_exit_condition"] = p4_exit.astype(bool)
    out["p4_state_bucket"] = phase
    out["bars_since_p4_exit"] = bars_since_exit
    return out


def add_s2_indicators(df_15m: pd.DataFrame, config: EventConfigS2 = EventConfigS2()) -> pd.DataFrame:
    out = add_base_indicators(df_15m)
    out["ema20"] = out["close"].ewm(span=20, adjust=False).mean()
    out["range_upper"] = out["high"].shift(1).rolling(config.range_n).max()
    out["range_lower"] = out["low"].shift(1).rolling(config.range_n).min()
    out["range_mid"] = (out["range_upper"] + out["range_lower"]) / 2.0
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
    out = simulate_p4_state(out)
    out = add_trend_strength_bucket(out)
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


def directional_labels(df_15m: pd.DataFrame, loc: int, entry: float, atr: float, direction: int) -> dict:
    labels = {}
    for horizon in HORIZONS:
        window = df_15m.iloc[loc + 1: loc + 1 + horizon]
        if len(window) < horizon:
            labels.update({
                f"fwd_ret_{horizon}": np.nan,
                f"fwd_mfe_{horizon}": np.nan,
                f"fwd_mae_{horizon}": np.nan,
                f"plus_1atr_first_{horizon}": np.nan,
                f"minus_1atr_first_{horizon}": np.nan,
                f"ambiguous_touch_{horizon}": np.nan,
            })
            continue
        raw_ret = window["close"].iloc[-1] / entry - 1.0
        labels[f"fwd_ret_{horizon}"] = direction * raw_ret
        if direction > 0:
            labels[f"fwd_mfe_{horizon}"] = window["high"].max() / entry - 1.0
            labels[f"fwd_mae_{horizon}"] = window["low"].min() / entry - 1.0
        else:
            labels[f"fwd_mfe_{horizon}"] = entry / window["low"].min() - 1.0
            labels[f"fwd_mae_{horizon}"] = entry / window["high"].max() - 1.0
        outcome = first_touch_directional(window, entry, atr, direction)
        labels[f"plus_1atr_first_{horizon}"] = outcome == "plus"
        labels[f"minus_1atr_first_{horizon}"] = outcome == "minus"
        labels[f"ambiguous_touch_{horizon}"] = outcome == "ambiguous"
    return labels


def mean_reversion_bars(df_15m: pd.DataFrame, loc: int, direction: int, target: float, max_bars: int = 32) -> float:
    window = df_15m.iloc[loc + 1: loc + 1 + max_bars]
    for offset, (_, bar) in enumerate(window.iterrows(), start=1):
        if direction > 0 and bar["high"] >= target:
            return float(offset)
        if direction < 0 and bar["low"] <= target:
            return float(offset)
    return np.nan


def subsequent_trend_breakout(df_15m: pd.DataFrame, loc: int, direction: int, max_bars: int = 32) -> bool:
    window = df_15m.iloc[loc + 1: loc + 1 + max_bars]
    if window.empty:
        return False
    if direction > 0:
        return bool((window["close"] > window["donchian55_upper"]).any())
    return bool((window["close"] < window["donchian20_lower"]).any())


def _next_open_arrays(data_1m: pd.DataFrame):
    index_1m = data_1m.index
    open_1m = data_1m["open"].to_numpy(float)

    def fast_next_open(signal_time: pd.Timestamp) -> tuple[pd.Timestamp, float] | tuple[None, None]:
        pos = index_1m.searchsorted(signal_time)
        if pos >= len(index_1m):
            return None, None
        return index_1m[pos], float(open_1m[pos])

    return fast_next_open


def _event_row(
    candidate: str,
    symbol: str,
    side: str,
    direction: int,
    ts: pd.Timestamp,
    loc: int,
    row: pd.Series,
    df_15m: pd.DataFrame,
    execution_time: pd.Timestamp,
    execution_open: float,
    target_col: str,
) -> dict:
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
        "ema20": row["ema20"],
        "atr14": row["atr14"],
        "deviation_ema20_atr": row["deviation_ema20_atr"],
        "trend_strength_atr": row["trend_strength_atr"],
        "trend_strength_bucket": row["trend_strength_bucket"],
        "trend_regime": row["trend_regime"],
        "volatility_regime": row["volatility_regime"],
        "atr_pct": row["atr_pct"],
        "atr_percentile_200": row["atr_percentile_200"],
        "p4_held": bool(row["p4_held"]),
        "p4_state_bucket": row["p4_state_bucket"],
        "bars_since_p4_exit": row["bars_since_p4_exit"],
        "mean_target": target,
        "mean_reversion_bars": mean_reversion_bars(df_15m, loc, direction, target),
        "subsequent_trend_breakout": subsequent_trend_breakout(df_15m, loc, direction),
        "data_layer": "expanded_discovery",
        "oos_status": "not_oos",
    }
    event.update(directional_labels(df_15m, loc, execution_open, float(row["atr14"]), direction))
    return event


def build_candidate_events_s2(
    data_1m: pd.DataFrame,
    symbol: str,
    config: EventConfigS2 = EventConfigS2(),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    df_15m = add_s2_indicators(strict_resample_15m(data_1m), config)
    fast_next_open = _next_open_arrays(data_1m)
    has_atr = df_15m["atr14"].notna()
    has_range = df_15m["range_upper"].notna()
    weak_trend = df_15m["trend_strength_atr"] < config.max_trend_strength
    valid_base = has_atr & has_range & weak_trend

    denom_long = (df_15m["range_mid"] - df_15m["range_lower"]).replace(0, np.nan)
    denom_short = (df_15m["range_upper"] - df_15m["range_mid"]).replace(0, np.nan)
    fb2_long = (
        valid_base
        & (df_15m["low"] < df_15m["range_lower"])
        & (df_15m["close"] > df_15m["range_lower"])
        & (((df_15m["range_lower"] - df_15m["low"]) / df_15m["atr14"]) <= config.fb_max_depth_atr)
        & (((df_15m["close"] - df_15m["range_lower"]) / denom_long) >= config.fb_recover_frac)
    )
    fb2_short = (
        valid_base
        & (df_15m["high"] > df_15m["range_upper"])
        & (df_15m["close"] < df_15m["range_upper"])
        & (((df_15m["high"] - df_15m["range_upper"]) / df_15m["atr14"]) <= config.fb_max_depth_atr)
        & (((df_15m["range_upper"] - df_15m["close"]) / denom_short) >= config.fb_recover_frac)
    )

    mr2_long = pd.Series(False, index=df_15m.index)
    mr2_short = pd.Series(False, index=df_15m.index)
    for loc in range(config.confirm_bars, len(df_15m)):
        if not bool(valid_base.iloc[loc]):
            continue
        past = df_15m.iloc[loc - config.confirm_bars: loc]
        if (past["deviation_ema20_atr"] <= -config.mr_atr_mult).any():
            dev_low = past.loc[past["deviation_ema20_atr"] <= -config.mr_atr_mult, "close"].min()
            mr2_long.iloc[loc] = bool(df_15m["close"].iloc[loc] > dev_low)
        if (past["deviation_ema20_atr"] >= config.mr_atr_mult).any():
            dev_high = past.loc[past["deviation_ema20_atr"] >= config.mr_atr_mult, "close"].max()
            mr2_short.iloc[loc] = bool(df_15m["close"].iloc[loc] < dev_high)

    idle = df_15m["p4_state_bucket"] != "p4_held"
    idle_mr_long = idle & valid_base & (df_15m["deviation_ema20_atr"] <= -config.mr_atr_mult)
    idle_mr_short = idle & valid_base & (df_15m["deviation_ema20_atr"] >= config.mr_atr_mult)

    specs = [
        ("FB2_FAILED_BREAKOUT_FAST_REVERSION", "long", 1, fb2_long, "range_mid"),
        ("FB2_FAILED_BREAKOUT_FAST_REVERSION", "short", -1, fb2_short, "range_mid"),
        ("MR2_DEVIATION_CONFIRMED_REVERSION", "long", 1, mr2_long, "ema20"),
        ("MR2_DEVIATION_CONFIRMED_REVERSION", "short", -1, mr2_short, "ema20"),
        (IDLE_CANDIDATE, "long", 1, idle_mr_long, "ema20"),
        (IDLE_CANDIDATE, "short", -1, idle_mr_short, "ema20"),
    ]
    rows = []
    for candidate, side, direction, mask, target_col in specs:
        for loc in np.flatnonzero(mask.to_numpy()):
            ts = df_15m.index[loc]
            row = df_15m.iloc[loc]
            execution_time, execution_open = fast_next_open(ts)
            if execution_time is None:
                continue
            rows.append(_event_row(candidate, symbol, side, direction, ts, loc, row, df_15m, execution_time, execution_open, target_col))
    return pd.DataFrame(rows), df_15m


def build_market_state_pool_s2(
    data_1m: pd.DataFrame,
    symbol: str,
    config: EventConfigS2 = EventConfigS2(),
    horizon: int = 16,
) -> pd.DataFrame:
    """Build a full market-time pool for matched random baselines."""
    df_15m = add_s2_indicators(strict_resample_15m(data_1m), config)
    fast_next_open = _next_open_arrays(data_1m)
    valid = df_15m["atr14"].notna()
    rows = []
    for loc in np.flatnonzero(valid.to_numpy()):
        ts = df_15m.index[loc]
        row = df_15m.iloc[loc]
        execution_time, execution_open = fast_next_open(ts)
        if execution_time is None:
            continue
        for side, direction in [("long", 1), ("short", -1)]:
            labels = directional_labels(df_15m, loc, execution_open, float(row["atr14"]), direction)
            rows.append({
                "symbol": symbol,
                "side": side,
                "direction": direction,
                "signal_time": ts,
                "execution_time": execution_time,
                "execution_open": execution_open,
                "trend_strength_atr": row["trend_strength_atr"],
                "trend_strength_bucket": row["trend_strength_bucket"],
                "volatility_regime": row["volatility_regime"],
                "p4_state_bucket": row["p4_state_bucket"],
                "bars_since_p4_exit": row["bars_since_p4_exit"],
                "bars_since_p4_exit_bucket": row["p4_state_bucket"],
                "is_candidate_event": False,
                f"fwd_ret_{horizon}": labels[f"fwd_ret_{horizon}"],
            })
    return pd.DataFrame(rows)


def build_rv1_lite_events(
    symbol_frames: dict[str, pd.DataFrame],
    data_1m_by_symbol: dict[str, pd.DataFrame],
    threshold: float = 1.5,
) -> pd.DataFrame:
    """Lightweight ETH/BTC relative-value event table for S2 completeness."""
    if "ETHUSDT" not in symbol_frames or "BTCUSDT" not in symbol_frames:
        return pd.DataFrame()
    eth = symbol_frames["ETHUSDT"]["close"]
    btc = symbol_frames["BTCUSDT"]["close"]
    common = eth.index.intersection(btc.index)
    if common.empty:
        return pd.DataFrame()
    ratio = eth.loc[common] / btc.loc[common]
    mean = ratio.shift(1).ewm(span=20, adjust=False).mean()
    std = ratio.shift(1).rolling(96, min_periods=32).std()
    z = (ratio - mean) / std
    rows = []
    eth_1m = data_1m_by_symbol["ETHUSDT"]
    fast_next_open = _next_open_arrays(eth_1m)
    for loc, ts in enumerate(common):
        if not np.isfinite(z.iloc[loc]) or abs(z.iloc[loc]) < threshold:
            continue
        direction = -1 if z.iloc[loc] > 0 else 1
        side = "short_eth_long_btc" if direction < 0 else "long_eth_short_btc"
        execution_time, execution_open = fast_next_open(ts)
        if execution_time is None:
            continue
        window_labels = {}
        for horizon in HORIZONS:
            fut = ratio.iloc[loc + 1: loc + 1 + horizon]
            if len(fut) < horizon:
                window_labels[f"fwd_ret_{horizon}"] = np.nan
                window_labels[f"fwd_mfe_{horizon}"] = np.nan
                window_labels[f"fwd_mae_{horizon}"] = np.nan
                window_labels[f"plus_1atr_first_{horizon}"] = np.nan
                window_labels[f"minus_1atr_first_{horizon}"] = np.nan
                window_labels[f"ambiguous_touch_{horizon}"] = np.nan
                continue
            rel = fut / ratio.iloc[loc] - 1.0
            signed = direction * rel
            window_labels[f"fwd_ret_{horizon}"] = float(signed.iloc[-1])
            window_labels[f"fwd_mfe_{horizon}"] = float(signed.max())
            window_labels[f"fwd_mae_{horizon}"] = float(signed.min())
            window_labels[f"plus_1atr_first_{horizon}"] = bool((signed > 0.005).any())
            window_labels[f"minus_1atr_first_{horizon}"] = bool((signed < -0.005).any())
            window_labels[f"ambiguous_touch_{horizon}"] = False
        row = {
            "event_id": f"RV1_LITE_ETHBTC_RELATIVE_ETHBTC_{side}_{ts.isoformat()}",
            "candidate": "RV1_LITE_ETHBTC_RELATIVE",
            "symbol": "ETHBTC",
            "signal_time": ts,
            "execution_time": execution_time,
            "execution_open": execution_open,
            "direction": direction,
            "side": side,
            "range_upper": np.nan,
            "range_lower": np.nan,
            "range_mid": mean.iloc[loc],
            "ema20": mean.iloc[loc],
            "atr14": std.iloc[loc],
            "deviation_ema20_atr": z.iloc[loc],
            "trend_strength_atr": abs(z.iloc[loc]),
            "trend_strength_bucket": "relative_value",
            "trend_regime": "relative_value",
            "volatility_regime": "unknown",
            "atr_pct": np.nan,
            "atr_percentile_200": np.nan,
            "p4_held": False,
            "p4_state_bucket": "relative_value",
            "bars_since_p4_exit": np.nan,
            "mean_target": mean.iloc[loc],
            "mean_reversion_bars": np.nan,
            "subsequent_trend_breakout": False,
            "data_layer": "expanded_discovery",
            "oos_status": "not_oos",
        }
        row.update(window_labels)
        rows.append(row)
    return pd.DataFrame(rows)


def top_positive_contribution(values: pd.Series, n: int) -> float:
    positives = values.dropna().sort_values(ascending=False)
    positives = positives[positives > 0]
    total = positives.sum()
    return float(positives.head(n).sum() / total) if total > 0 else np.nan


def top_trade_dependency_s2(events: pd.DataFrame, horizon: int = 16) -> pd.DataFrame:
    rows = []
    if events.empty:
        return pd.DataFrame()
    col = f"fwd_ret_{horizon}"
    for keys, part in events.groupby(["candidate", "symbol"], dropna=False):
        vals = part[col].dropna().sort_values(ascending=False)
        rows.append({
            "candidate": keys[0],
            "symbol": keys[1],
            "event_count": int(len(part)),
            "top1_positive_contribution": top_positive_contribution(vals, 1),
            "top3_positive_contribution": top_positive_contribution(vals, 3),
            "top5_positive_contribution": top_positive_contribution(vals, 5),
            "remove_top1_mean_fwd_ret": vals.iloc[1:].mean() if len(vals) > 1 else np.nan,
            "remove_top3_mean_fwd_ret": vals.iloc[3:].mean() if len(vals) > 3 else np.nan,
            "remove_top5_mean_fwd_ret": vals.iloc[5:].mean() if len(vals) > 5 else np.nan,
        })
    return pd.DataFrame(rows)


def summarize_events_s2(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    rows = []
    for keys, part in events.groupby(["candidate", "symbol", "side"], dropna=False):
        row = {"candidate": keys[0], "symbol": keys[1], "side": keys[2], "event_count": int(len(part))}
        for horizon in HORIZONS:
            row[f"mean_fwd_ret_{horizon}"] = part[f"fwd_ret_{horizon}"].mean()
            row[f"median_fwd_ret_{horizon}"] = part[f"fwd_ret_{horizon}"].median()
            row[f"plus_1atr_first_rate_{horizon}"] = part[f"plus_1atr_first_{horizon}"].mean()
            row[f"minus_1atr_first_rate_{horizon}"] = part[f"minus_1atr_first_{horizon}"].mean()
            row[f"ambiguous_rate_{horizon}"] = part[f"ambiguous_touch_{horizon}"].mean()
        row["mean_reversion_rate_32"] = part["mean_reversion_bars"].notna().mean()
        rows.append(row)
    return pd.DataFrame(rows)


def stability_summary_s2(events: pd.DataFrame, horizon: int = 16) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    work = events.copy()
    work["year"] = pd.to_datetime(work["signal_time"], utc=True).dt.year
    work["quarter"] = pd.to_datetime(work["signal_time"], utc=True).dt.to_period("Q").astype(str)
    col = f"fwd_ret_{horizon}"
    rows = []
    for candidate, part in work.groupby("candidate", dropna=False):
        yearly = part.groupby("year")[col].mean()
        quarterly = part.groupby("quarter")[col].mean()
        by_symbol = part.groupby("symbol")[col].mean()
        rows.append({
            "candidate": candidate,
            "event_count": int(len(part)),
            "positive_year_rate": float((yearly > 0).mean()) if len(yearly) else np.nan,
            "positive_quarter_rate": float((quarterly > 0).mean()) if len(quarterly) else np.nan,
            "positive_symbol_count": int((by_symbol > 0).sum()),
            "worst_year_mean": float(yearly.min()) if len(yearly) else np.nan,
        })
    return pd.DataFrame(rows)
