import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from strategy.multitimeframe_candlestick import MultiTimeframeCandlestickResearch, load_csv


DEFAULT_DATA_DIR = Path("/Users/muce/1m_data/new_backtest_data_1year_1m")
DEFAULT_OUTPUT_DIR = Path("analysis/results/candlestick_event_study")
HORIZONS = [5, 15, 30, 60, 120]
TARGETS_R = [0.5, 1.0, 1.5, 2.0]


def parse_args():
    parser = argparse.ArgumentParser(description="Diagnose candlestick event MFE/MAE in R multiples.")
    parser.add_argument("--symbol", default="ETHUSDT")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--start", default="2024-12-01")
    parser.add_argument("--end", default="2025-12-01")
    return parser.parse_args()


def candle_strength(row, prev, atr):
    body = abs(row["close"] - row["open"])
    prev_body = abs(prev["close"] - prev["open"])
    candle_range = max(row["high"] - row["low"], 1e-12)
    upper = row["high"] - max(row["open"], row["close"])
    lower = min(row["open"], row["close"]) - row["low"]
    body_low = min(row["open"], row["close"])
    body_high = max(row["open"], row["close"])
    prev_body_low = min(prev["open"], prev["close"])
    prev_body_high = max(prev["open"], prev["close"])
    engulf_depth = max(0.0, min(body_high, prev_body_high) - max(body_low, prev_body_low))
    return {
        "body_atr": body / atr if atr else np.nan,
        "range_atr": candle_range / atr if atr else np.nan,
        "upper_shadow_body": upper / max(body, 1e-12),
        "lower_shadow_body": lower / max(body, 1e-12),
        "close_position": (row["close"] - row["low"]) / candle_range,
        "engulf_body_ratio": body / max(prev_body, 1e-12),
        "engulf_depth_prev_body": engulf_depth / max(prev_body, 1e-12),
    }


def local_trend_features(side, df_5m, idx, atr):
    row = df_5m.iloc[idx]
    features = {}
    for bars in [3, 6, 12]:
        if idx - bars < 0:
            features[f"pre_return_{bars}_atr"] = np.nan
            continue
        prev_close = df_5m["close"].iloc[idx - bars]
        raw = row["close"] - prev_close
        signed = raw if side == "LONG" else -raw
        features[f"pre_return_{bars}_atr"] = signed / atr if atr else np.nan

    lookback = df_5m.iloc[max(0, idx - 12): idx + 1]
    if len(lookback) >= 2 and atr:
        if side == "LONG":
            features["pullback_depth_atr"] = (lookback["high"].max() - row["low"]) / atr
            features["distance_from_swing_atr"] = (row["close"] - lookback["low"].min()) / atr
        else:
            features["pullback_depth_atr"] = (row["high"] - lookback["low"].min()) / atr
            features["distance_from_swing_atr"] = (lookback["high"].max() - row["close"]) / atr
        path = lookback["close"].diff().abs().sum()
        net = abs(lookback["close"].iloc[-1] - lookback["close"].iloc[0])
        features["directional_efficiency"] = net / path if path > 0 else np.nan
    else:
        features["pullback_depth_atr"] = np.nan
        features["distance_from_swing_atr"] = np.nan
        features["directional_efficiency"] = np.nan
    return features


def first_touch(path, side, entry, risk, target_r):
    target = entry + target_r * risk if side == "LONG" else entry - target_r * risk
    stop = entry - risk if side == "LONG" else entry + risk
    for ts, row in path.iterrows():
        if side == "LONG":
            hit_stop = row["low"] <= stop
            hit_target = row["high"] >= target
        else:
            hit_stop = row["high"] >= stop
            hit_target = row["low"] <= target
        if hit_stop and hit_target:
            return "stop_first", ts
        if hit_target:
            return "target_first", ts
        if hit_stop:
            return "stop_first", ts
    return "neither", pd.NaT


def event_metrics(event, df_1m, df_5m, idx, research):
    entry_time = event["event_time"]
    if entry_time not in df_1m.index:
        return None

    side = event["side"]
    entry = float(df_1m.loc[entry_time, "open"])
    risk = abs(entry - event["stop"])
    if risk <= 0:
        return None

    row = df_5m.iloc[idx]
    prev = df_5m.iloc[idx - 1]
    base = {
        "symbol": event["symbol"],
        "event_time": entry_time,
        "side": side,
        "candle": event["candle"],
        "entry": entry,
        "stop": event["stop"],
        "risk": risk,
        "risk_pct": risk / entry,
        "location": event["location"],
        "one_min_confirmed": research._confirmed_entry(event, df_1m)[0] is not None,
    }
    base.update(candle_strength(row, prev, event["atr5"]))
    base.update(local_trend_features(side, df_5m, idx, event["atr5"]))

    for minutes in HORIZONS:
        path = df_1m.loc[entry_time: entry_time + pd.Timedelta(minutes=minutes - 1)]
        if path.empty:
            continue
        if side == "LONG":
            mfe = (path["high"].max() - entry) / risk
            mae = (entry - path["low"].min()) / risk
            close_r = (path["close"].iloc[-1] - entry) / risk
            mfe_idx = path["high"].idxmax()
        else:
            mfe = (entry - path["low"].min()) / risk
            mae = (path["high"].max() - entry) / risk
            close_r = (entry - path["close"].iloc[-1]) / risk
            mfe_idx = path["low"].idxmin()
        base[f"mfe_{minutes}m_r"] = mfe
        base[f"mae_{minutes}m_r"] = mae
        base[f"close_{minutes}m_r"] = close_r
        base[f"time_to_mfe_{minutes}m_min"] = (mfe_idx - entry_time).total_seconds() / 60
        for target_r in TARGETS_R:
            result, touch_time = first_touch(path, side, entry, risk, target_r)
            base[f"first_{target_r:g}r_vs_1r_{minutes}m"] = result
            base[f"first_{target_r:g}r_vs_1r_time_{minutes}m"] = touch_time

    return base


def quantile_table(df, value_col, by_col, buckets=5):
    valid = df[[value_col, "mfe_60m_r", "mae_60m_r", "close_60m_r"]].dropna()
    if valid[value_col].nunique() < buckets:
        return pd.DataFrame()
    valid["bucket"] = pd.qcut(valid[value_col], buckets, duplicates="drop")
    return valid.groupby("bucket", observed=True).agg(
        count=(value_col, "size"),
        median_feature=(value_col, "median"),
        p_mfe_1r=("mfe_60m_r", lambda s: (s >= 1).mean()),
        p_mfe_2r=("mfe_60m_r", lambda s: (s >= 2).mean()),
        median_mfe=("mfe_60m_r", "median"),
        median_mae=("mae_60m_r", "median"),
        median_close=("close_60m_r", "median"),
    ).reset_index()


def main():
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    research = MultiTimeframeCandlestickResearch()
    csv_path = args.data_dir / f"{args.symbol.upper()}.csv"
    df_1m = research._normalize_1m(load_csv(csv_path))
    frames = research._build_timeframes(df_1m)
    df_5m = research._with_indicators(frames["5m"])
    events = research._build_events(args.symbol.upper(), df_1m, frames)
    start = pd.Timestamp(args.start) if args.start else None
    end = pd.Timestamp(args.end) if args.end else None

    rows = []
    for event in events:
        if event["candle"] is None:
            continue
        if start is not None and event["event_time"] < start:
            continue
        if end is not None and event["event_time"] > end:
            continue
        idx = df_5m.index.searchsorted(event["event_time"])
        if idx <= 0 or idx >= len(df_5m) or df_5m.index[idx] != event["event_time"]:
            continue
        row = event_metrics(event, df_1m, df_5m, idx, research)
        if row:
            rows.append(row)

    events_df = pd.DataFrame(rows)
    events_path = args.output_dir / f"{args.symbol.upper()}_events.csv"
    events_df.to_csv(events_path, index=False)

    summary_rows = []
    group_cols = [
        ("all", None),
        ("one_min_confirmed", "one_min_confirmed"),
        ("candle", "candle"),
        ("side", "side"),
    ]
    for label, col in group_cols:
        groups = [("all", events_df)] if col is None else events_df.groupby(col)
        for group_name, group in groups:
            row = {"dimension": label, "group": group_name, "count": len(group)}
            for minutes in HORIZONS:
                mfe_col = f"mfe_{minutes}m_r"
                mae_col = f"mae_{minutes}m_r"
                close_col = f"close_{minutes}m_r"
                row[f"p_mfe_0.5r_{minutes}m"] = (group[mfe_col] >= 0.5).mean()
                row[f"p_mfe_1r_{minutes}m"] = (group[mfe_col] >= 1.0).mean()
                row[f"p_mfe_1.5r_{minutes}m"] = (group[mfe_col] >= 1.5).mean()
                row[f"p_mfe_2r_{minutes}m"] = (group[mfe_col] >= 2.0).mean()
                row[f"median_mfe_{minutes}m"] = group[mfe_col].median()
                row[f"median_mae_{minutes}m"] = group[mae_col].median()
                row[f"median_close_{minutes}m"] = group[close_col].median()
                row[f"median_time_to_mfe_{minutes}m"] = group[f"time_to_mfe_{minutes}m_min"].median()
            summary_rows.append(row)

    summary_df = pd.DataFrame(summary_rows)
    summary_path = args.output_dir / f"{args.symbol.upper()}_summary.csv"
    summary_df.to_csv(summary_path, index=False)

    feature_tables = []
    for feature in [
        "pre_return_3_atr",
        "pre_return_6_atr",
        "pre_return_12_atr",
        "pullback_depth_atr",
        "directional_efficiency",
        "risk_pct",
        "body_atr",
        "range_atr",
        "engulf_body_ratio",
        "close_position",
    ]:
        table = quantile_table(events_df, feature, feature)
        if not table.empty:
            table.insert(0, "feature", feature)
            feature_tables.append(table)
    feature_df = pd.concat(feature_tables, ignore_index=True) if feature_tables else pd.DataFrame()
    feature_path = args.output_dir / f"{args.symbol.upper()}_feature_quantiles.csv"
    feature_df.to_csv(feature_path, index=False)

    cols = [
        "dimension", "group", "count",
        "p_mfe_0.5r_60m", "p_mfe_1r_60m", "p_mfe_1.5r_60m", "p_mfe_2r_60m",
        "median_mfe_60m", "median_mae_60m", "median_close_60m", "median_time_to_mfe_60m",
    ]
    print(summary_df[cols].to_string(index=False))
    print(f"\nSaved events:  {events_path}")
    print(f"Saved summary: {summary_path}")
    print(f"Saved feature quantiles: {feature_path}")


if __name__ == "__main__":
    main()
