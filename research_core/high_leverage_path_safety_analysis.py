"""H1 high-leverage path-safety research helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from research_core.common import DISCOVERY_DATA_PATH, RESEARCH_ROOT
from research_core.cross_asset_validation_analysis import CROSS_ASSET_SYMBOLS, default_symbol_paths, merge_symbol_1m
from research_core.event_table import FACTOR_COMMON, load_ohlcv_1m
from research_core.leverage_research_analysis import TARGET_PROTOTYPES, liquidation_price


SYMBOLS = ["ETHUSDT", *CROSS_ASSET_SYMBOLS]
WINDOWS_MINUTES = [1, 3, 5, 15, 30, 60]
LEVERAGE_REFS = [10, 20]
PATH_LABELS = [
    "safe_for_10x",
    "safe_for_20x",
    "fast_follow_through",
    "hit_liquidation_10x",
    "hit_liquidation_20x",
    "mae_pct",
    "mfe_pct",
]
PATH_FACTOR_COLUMNS = [
    "momentum_score_quantile",
    "breakout_score_quantile",
    "breakout_distance_atr",
    "range_atr",
    "body_ratio",
    "close_location",
    "bars_after_breakout",
    "ema_gap_atr",
    "atr_pct",
    "atr_pct_rank",
    "volatility_ratio_short_long",
    "atr_percentile_200",
    "prior_5m_range_pct",
    "prior_15m_range_pct",
    "prior_30m_range_pct",
    "prior_5m_return",
    "prior_15m_return",
    "prior_30m_return",
    "prior_5m_lower_wick_ratio",
    "prior_15m_lower_wick_ratio",
]
PATH_FACTOR_COMMON = {
    **FACTOR_COMMON,
    "momentum_score_quantile": "Existing R6 momentum family score percentile.",
    "breakout_score_quantile": "Existing R6 breakout conviction family score percentile.",
    "atr_pct_rank": "Symbol-level ATR percentage rank within the available internal dataset.",
    "prior_5m_range_pct": "Immediate pre-entry 5-minute high-low range as a share of entry price.",
    "prior_15m_range_pct": "Immediate pre-entry 15-minute high-low range as a share of entry price.",
    "prior_30m_range_pct": "Immediate pre-entry 30-minute high-low range as a share of entry price.",
    "prior_5m_return": "Immediate pre-entry 5-minute close-to-open return.",
    "prior_15m_return": "Immediate pre-entry 15-minute close-to-open return.",
    "prior_30m_return": "Immediate pre-entry 30-minute close-to-open return.",
    "prior_5m_lower_wick_ratio": "Lower wick share of the aggregate pre-entry 5-minute range.",
    "prior_15m_lower_wick_ratio": "Lower wick share of the aggregate pre-entry 15-minute range.",
}
FORWARD_LABEL_PREFIXES = (
    "mae_",
    "mfe_",
    "first_touch_",
    "ambiguous_touch",
    "min_low",
    "max_high",
    "hit_liquidation_",
    "safe_for_",
    "fast_follow_through",
)


def load_symbol_1m(symbol: str) -> pd.DataFrame:
    if symbol == "ETHUSDT":
        return load_ohlcv_1m(DISCOVERY_DATA_PATH)
    return merge_symbol_1m(default_symbol_paths(symbol))


def load_symbol_events(symbol: str) -> pd.DataFrame:
    if symbol == "ETHUSDT":
        events = pd.read_parquet(RESEARCH_ROOT / "events" / "event_candidates.parquet")
        scores = pd.read_parquet(RESEARCH_ROOT / "family_validation" / "family_scores.parquet")
        scores = scores[["event_id", "momentum_score_quantile", "breakout_score_quantile"]]
    else:
        events = pd.read_parquet(RESEARCH_ROOT / "cross_asset_validation" / "events" / f"{symbol}_event_candidates.parquet")
        scores = pd.read_parquet(RESEARCH_ROOT / "cross_asset_validation" / "scores" / f"{symbol}_family_scores.parquet")
        scores = scores[["event_id", "momentum_score", "breakout_score"]].copy()
        scores["momentum_score_quantile"] = scores["momentum_score"].rank(pct=True, method="first")
        scores["breakout_score_quantile"] = scores["breakout_score"].rank(pct=True, method="first")
        scores = scores[["event_id", "momentum_score_quantile", "breakout_score_quantile"]]
    events = events.merge(scores, on="event_id", how="left")
    events["symbol"] = symbol
    events["atr_pct_rank"] = events["atr_pct"].rank(pct=True, method="average")
    return events


def load_prototype_trades(symbol: str) -> pd.DataFrame:
    frames = []
    if symbol == "ETHUSDT":
        for prototype in TARGET_PROTOTYPES:
            path = RESEARCH_ROOT / "minimal_backtest" / "prototype_trades" / f"{prototype}_fixed_2x_trades.csv"
            part = pd.read_csv(path)
            part["symbol"] = symbol
            frames.append(part)
    else:
        path = RESEARCH_ROOT / "cross_asset_validation" / "prototype_trades" / f"{symbol}_trades.csv"
        frame = pd.read_csv(path)
        part = frame[(frame["prototype"].isin(TARGET_PROTOTYPES)) & (frame["sizing_mode"] == "fixed_2x")].copy()
        frames.append(part)
    out = pd.concat(frames, ignore_index=True)
    out["entry_time"] = pd.to_datetime(out["entry_time"], utc=True)
    out["signal_time"] = pd.to_datetime(out["signal_time"], utc=True)
    return out


def first_touch(window: pd.DataFrame, entry_price: float, atr: float, mult: float) -> str:
    if window.empty or not np.isfinite(entry_price) or not np.isfinite(atr) or atr <= 0:
        return "none"
    up = entry_price + atr * mult
    down = entry_price - atr * mult
    for _, bar in window.iterrows():
        hit_up = bool(bar["high"] >= up)
        hit_down = bool(bar["low"] <= down)
        if hit_up and hit_down:
            return "ambiguous"
        if hit_up:
            return "plus"
        if hit_down:
            return "minus"
    return "none"


def aggregate_prior_features(data_1m: pd.DataFrame, entry_time: pd.Timestamp, entry_price: float, minutes: int) -> dict[str, float]:
    start = entry_time - pd.Timedelta(minutes=minutes)
    end = entry_time - pd.Timedelta(minutes=1)
    window = data_1m.loc[(data_1m.index >= start) & (data_1m.index <= end)]
    prefix = f"prior_{minutes}m"
    if window.empty:
        return {
            f"{prefix}_range_pct": np.nan,
            f"{prefix}_return": np.nan,
            f"{prefix}_lower_wick_ratio": np.nan,
        }
    high = float(window["high"].max())
    low = float(window["low"].min())
    open_ = float(window["open"].iloc[0])
    close = float(window["close"].iloc[-1])
    range_ = high - low
    return {
        f"{prefix}_range_pct": high / low - 1 if low > 0 else np.nan,
        f"{prefix}_return": close / open_ - 1 if open_ > 0 else np.nan,
        f"{prefix}_lower_wick_ratio": (min(open_, close) - low) / range_ if range_ > 0 else np.nan,
    }


def compute_path_row(base: dict, data_1m: pd.DataFrame, forward_minutes: int) -> dict:
    entry_time = pd.Timestamp(base["entry_time"])
    entry_price = float(base["entry_price"])
    atr = float(base["atr"])
    end = entry_time + pd.Timedelta(minutes=forward_minutes - 1)
    window = data_1m.loc[(data_1m.index >= entry_time) & (data_1m.index <= end)]
    row = dict(base)
    row["forward_window"] = f"{forward_minutes}m"
    row["forward_minutes"] = forward_minutes
    if window.empty:
        for col in ["mae_pct", "mfe_pct", "mae_atr", "mfe_atr", "min_low", "max_high"]:
            row[col] = np.nan
        for col in [
            "first_touch_plus_0_5atr",
            "first_touch_minus_0_5atr",
            "first_touch_plus_1atr",
            "first_touch_minus_1atr",
            "ambiguous_touch",
            "hit_liquidation_10x",
            "hit_liquidation_20x",
            "safe_for_10x",
            "safe_for_20x",
            "fast_follow_through",
        ]:
            row[col] = False
        return row
    min_low = float(window["low"].min())
    max_high = float(window["high"].max())
    row["min_low"] = min_low
    row["max_high"] = max_high
    row["mae_pct"] = min_low / entry_price - 1
    row["mfe_pct"] = max_high / entry_price - 1
    row["mae_atr"] = (min_low - entry_price) / atr if atr > 0 else np.nan
    row["mfe_atr"] = (max_high - entry_price) / atr if atr > 0 else np.nan
    touch_05 = first_touch(window, entry_price, atr, 0.5)
    touch_10 = first_touch(window, entry_price, atr, 1.0)
    row["first_touch_plus_0_5atr"] = touch_05 == "plus"
    row["first_touch_minus_0_5atr"] = touch_05 == "minus"
    row["first_touch_plus_1atr"] = touch_10 == "plus"
    row["first_touch_minus_1atr"] = touch_10 == "minus"
    row["ambiguous_touch"] = touch_05 == "ambiguous" or touch_10 == "ambiguous"
    for leverage in LEVERAGE_REFS:
        liq = liquidation_price(entry_price, leverage)
        row[f"liquidation_price_{leverage}x"] = liq
        row[f"distance_to_liquidation_{leverage}x_pct"] = entry_price / liq - 1 if liq > 0 else np.nan
        row[f"hit_liquidation_{leverage}x"] = bool(min_low <= liq)
    row["safe_for_10x"] = (
        not row["hit_liquidation_10x"]
        and row["mae_pct"] > -0.05
        and not row["first_touch_minus_1atr"]
    )
    row["safe_for_20x"] = (
        not row["hit_liquidation_20x"]
        and row["mae_pct"] > -0.025
        and not row["first_touch_minus_0_5atr"]
    )
    row["fast_follow_through"] = (
        row["first_touch_plus_0_5atr"]
        and not row["first_touch_minus_0_5atr"]
        and not row["ambiguous_touch"]
    )
    return row


def build_path_safety_labels() -> pd.DataFrame:
    rows = []
    for symbol in SYMBOLS:
        data_1m = load_symbol_1m(symbol)
        events = load_symbol_events(symbol)
        trades = load_prototype_trades(symbol)
        factors = events[[
            "event_id",
            "symbol",
            "breakout_distance_atr",
            "range_atr",
            "body_ratio",
            "close_location",
            "bars_after_breakout",
            "ema_gap_atr",
            "atr_pct",
            "atr_pct_rank",
            "volatility_ratio_short_long",
            "atr_percentile_200",
            "momentum_score_quantile",
            "breakout_score_quantile",
        ]]
        merged = trades.merge(factors, on=["event_id", "symbol"], how="left", suffixes=("", "_event"))
        for _, trade in merged.iterrows():
            base = {
                "symbol": symbol,
                "prototype": trade["prototype"],
                "event_id": trade["event_id"],
                "entry_time": trade["entry_time"],
                "entry_price": float(trade["entry_price"]),
                "atr": float(trade["atr"]),
                "atr_pct": trade.get("atr_pct", np.nan),
                "atr_pct_rank": trade.get("atr_pct_rank", np.nan),
                "breakout_score_quantile": trade.get("breakout_score_quantile", np.nan),
                "momentum_score_quantile": trade.get("momentum_score_quantile", np.nan),
            }
            for col in PATH_FACTOR_COLUMNS:
                if col not in base:
                    base[col] = trade.get(col, np.nan)
            for minutes in [5, 15, 30]:
                base.update(aggregate_prior_features(data_1m, trade["entry_time"], float(trade["entry_price"]), minutes))
            for forward in WINDOWS_MINUTES:
                rows.append(compute_path_row(base, data_1m, forward))
    return pd.DataFrame(rows)


def _factor_groups(frame: pd.DataFrame, factor: str) -> pd.Series | None:
    values = frame[factor].replace([np.inf, -np.inf], np.nan)
    valid = values.dropna()
    if len(valid) < 30 or valid.nunique() < 5:
        return None
    try:
        return pd.qcut(values.rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
    except ValueError:
        return None


def directional_edge(frame: pd.DataFrame, factor: str, label: str) -> dict:
    groups = _factor_groups(frame, factor)
    if groups is None:
        return {"status": "invalid_or_sparse"}
    helper_cols = [c for c in ["safe_for_20x", "hit_liquidation_20x"] if c in frame.columns and c not in [factor, label, "symbol"]]
    tmp = frame[[factor, label, "symbol", *helper_cols]].copy()
    tmp["q"] = groups
    tmp = tmp.dropna(subset=["q", label])
    if len(tmp) < 30:
        return {"status": "invalid_or_sparse"}
    q_means = tmp.groupby("q", observed=False)[label].mean()
    q1 = float(q_means.get(1, np.nan))
    q5 = float(q_means.get(5, np.nan))
    top = tmp[tmp["q"] == 5][label].mean()
    bottom = tmp[tmp["q"] == 1][label].mean()
    if label.startswith("hit_liquidation"):
        edge = float(bottom - top)
        q_edge = float(q1 - q5)
    else:
        edge = float(top - bottom)
        q_edge = float(q5 - q1)
    status = "path_safety_candidate" if edge > 0 else "risk_only_candidate"
    return {
        "q5_minus_q1": q_edge,
        "top20_minus_bottom20": edge,
        "safe_rate_top20": float(tmp[tmp["q"] == 5]["safe_for_20x"].mean()) if "safe_for_20x" in frame else np.nan,
        "safe_rate_bottom20": float(tmp[tmp["q"] == 1]["safe_for_20x"].mean()) if "safe_for_20x" in frame else np.nan,
        "hit_liq_rate_top20": float(tmp[tmp["q"] == 5]["hit_liquidation_20x"].mean()) if "hit_liquidation_20x" in frame else np.nan,
        "hit_liq_rate_bottom20": float(tmp[tmp["q"] == 1]["hit_liquidation_20x"].mean()) if "hit_liquidation_20x" in frame else np.nan,
        "status": status,
    }


def factor_safety_analysis(labels: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summary_rows = []
    quintile_rows = []
    symbol_rows = []
    monthly_rows = []
    for prototype in TARGET_PROTOTYPES:
        proto = labels[labels["prototype"] == prototype].copy()
        for factor in PATH_FACTOR_COLUMNS:
            if factor not in proto.columns or factor.startswith(FORWARD_LABEL_PREFIXES):
                continue
            for label in PATH_LABELS:
                for symbol_scope, scope_frame in [("all_symbols", proto)]:
                    groups = _factor_groups(scope_frame, factor)
                    if groups is not None:
                        qtmp = scope_frame[[factor, label, "symbol", "entry_time"]].copy()
                        qtmp["q"] = groups
                        for q, part in qtmp.dropna(subset=["q", label]).groupby("q", observed=False):
                            quintile_rows.append({
                                "factor": factor,
                                "common": PATH_FACTOR_COMMON.get(factor, ""),
                                "label": label,
                                "prototype": prototype,
                                "symbol_scope": symbol_scope,
                                "quintile": int(q),
                                "event_count": int(len(part)),
                                "label_mean": float(part[label].mean()),
                            })
                    edge = directional_edge(scope_frame, factor, label)
                    if edge.get("status") == "invalid_or_sparse":
                        summary_rows.append({
                            "factor": factor,
                            "common": PATH_FACTOR_COMMON.get(factor, ""),
                            "label": label,
                            "prototype": prototype,
                            "symbol_scope": symbol_scope,
                            "event_count": int(len(scope_frame)),
                            "q5_minus_q1": np.nan,
                            "top20_minus_bottom20": np.nan,
                            "safe_rate_top20": np.nan,
                            "safe_rate_bottom20": np.nan,
                            "hit_liq_rate_top20": np.nan,
                            "hit_liq_rate_bottom20": np.nan,
                            "monthly_positive_rate": np.nan,
                            "cross_symbol_positive_count": np.nan,
                            "status": "invalid_or_sparse",
                        })
                        continue
                    month_edges = []
                    scope_frame = scope_frame.copy()
                    scope_frame["month"] = pd.to_datetime(scope_frame["entry_time"], utc=True).dt.strftime("%Y-%m")
                    for month, part in scope_frame.groupby("month"):
                        m_edge = directional_edge(part, factor, label)
                        if m_edge.get("status") != "invalid_or_sparse":
                            month_edges.append(m_edge["top20_minus_bottom20"] > 0)
                            monthly_rows.append({
                                "factor": factor,
                                "label": label,
                                "prototype": prototype,
                                "month": month,
                                "event_count": int(len(part)),
                                "top20_minus_bottom20": m_edge["top20_minus_bottom20"],
                            })
                    symbol_positive = 0
                    for symbol, part in scope_frame.groupby("symbol"):
                        s_edge = directional_edge(part, factor, label)
                        if s_edge.get("status") != "invalid_or_sparse":
                            symbol_positive += int(s_edge["top20_minus_bottom20"] > 0)
                            symbol_rows.append({
                                "factor": factor,
                                "label": label,
                                "prototype": prototype,
                                "symbol": symbol,
                                "event_count": int(len(part)),
                                "top20_minus_bottom20": s_edge["top20_minus_bottom20"],
                            })
                    monthly_rate = float(np.mean(month_edges)) if month_edges else np.nan
                    status = edge["status"]
                    if status == "path_safety_candidate" and (monthly_rate < 0.55 or symbol_positive < 2):
                        status = "weak_path_safety_candidate"
                    summary_rows.append({
                        "factor": factor,
                        "common": PATH_FACTOR_COMMON.get(factor, ""),
                        "label": label,
                        "prototype": prototype,
                        "symbol_scope": symbol_scope,
                        "event_count": int(len(scope_frame)),
                        "q5_minus_q1": edge["q5_minus_q1"],
                        "top20_minus_bottom20": edge["top20_minus_bottom20"],
                        "safe_rate_top20": edge["safe_rate_top20"],
                        "safe_rate_bottom20": edge["safe_rate_bottom20"],
                        "hit_liq_rate_top20": edge["hit_liq_rate_top20"],
                        "hit_liq_rate_bottom20": edge["hit_liq_rate_bottom20"],
                        "monthly_positive_rate": monthly_rate,
                        "cross_symbol_positive_count": symbol_positive,
                        "status": status,
                    })
    return (
        pd.DataFrame(summary_rows),
        pd.DataFrame(quintile_rows),
        pd.DataFrame(symbol_rows),
        pd.DataFrame(monthly_rows),
    )


def build_failure_cases(labels: pd.DataFrame) -> pd.DataFrame:
    required_label_cols = [
        "symbol",
        "prototype",
        "event_id",
        "entry_time",
        "forward_window",
        "safe_for_10x",
        "safe_for_20x",
        "hit_liquidation_10x",
        "hit_liquidation_20x",
        "mae_pct",
        "mfe_pct",
        "atr_pct_rank",
        "breakout_score_quantile",
        "momentum_score_quantile",
        "bars_after_breakout",
    ]
    if labels.empty or any(col not in labels.columns for col in required_label_cols):
        return pd.DataFrame(columns=["failure_source", "symbol", "prototype", "event_id", "entry_time"])
    frames = []
    l1_path = RESEARCH_ROOT / "leverage_research" / "liquidation_events.csv"
    if l1_path.exists():
        l1 = pd.read_csv(l1_path)
        if not l1.empty:
            l1["failure_source"] = "L1_liquidation"
            frames.append(l1)
    l2_dir = RESEARCH_ROOT / "leverage_research_l2" / "leverage_l2_trades"
    if l2_dir.exists():
        rows = []
        for path in l2_dir.glob("*_trades.csv"):
            frame = pd.read_csv(path)
            if frame.empty or "trade_return" not in frame:
                continue
            bad = frame[frame["trade_return"] <= -0.20].copy()
            if not bad.empty:
                bad["failure_source"] = "L2_extreme_trade_loss"
                rows.append(bad)
        if rows:
            frames.append(pd.concat(rows, ignore_index=True))
    if not frames:
        return pd.DataFrame(columns=["failure_source", "symbol", "prototype", "event_id", "entry_time"])
    failures = pd.concat(frames, ignore_index=True, sort=False)
    failures["entry_time"] = pd.to_datetime(failures["entry_time"], utc=True)
    label_sample = labels[labels["forward_window"] == "60m"][required_label_cols].copy()
    label_sample["entry_time"] = pd.to_datetime(label_sample["entry_time"], utc=True)
    return failures.merge(label_sample, on=["symbol", "prototype", "event_id", "entry_time"], how="left", suffixes=("", "_h1"))


def failure_review_markdown(failures: pd.DataFrame) -> str:
    lines = ["# High Leverage Failure Review", ""]
    if failures.empty:
        lines += [
            "No L1 liquidation or L2 extreme-loss cases were available.",
            "",
            "This does not prove safety; it only means no cases were present in the current inputs.",
        ]
        return "\n".join(lines) + "\n"
    lines += [
        f"failure_case_count: {len(failures)}",
        "",
        "## Concentration",
        "",
        failures.groupby(["failure_source", "symbol", "prototype"]).size().reset_index(name="count").to_markdown(index=False),
        "",
        "## Common Traits",
        "",
        f"- median_atr_pct_rank: {failures['atr_pct_rank'].median(skipna=True):.4f}",
        f"- median_breakout_score_quantile: {failures['breakout_score_quantile'].median(skipna=True):.4f}",
        f"- median_momentum_score_quantile: {failures['momentum_score_quantile'].median(skipna=True):.4f}",
        f"- median_bars_after_breakout: {failures['bars_after_breakout'].median(skipna=True):.4f}",
        f"- 60m safe_for_20x rate: {failures['safe_for_20x'].mean(skipna=True):.4f}",
        "",
        "## Plain Answers",
        "",
        "1. 爆仓交易在入场前有哪些共同特征：见 Common Traits。",
        "2. 是否集中在某个 symbol：见 Concentration。",
        "3. 是否集中在 P4 或 P6：见 Concentration。",
        "4. 是否发生在高 ATR 环境：以 median_atr_pct_rank 判断。",
        "5. 是否发生在连续亏损之后：L1/L2 交易文件保留权益路径和 trade_return，可进一步逐笔追踪。",
        "6. 是否发生在趋势后半段：以 bars_after_breakout 判断。",
        "7. P4/P6 原因子是否能提前识别这些风险：需要结合 path_safety_factor_summary。",
        "8. 需要的是新 alpha，还是 risk/execution filter：H1 定位为 risk/execution filter 研究，不生成策略规则。",
    ]
    return "\n".join(lines) + "\n"
