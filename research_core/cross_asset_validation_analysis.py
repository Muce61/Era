"""Cross-asset validation helpers for BTC/SOL/BNB."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from research_core.event_table import build_event_candidates, load_ohlcv_1m
from research_core.minimal_backtest_analysis import (
    BacktestParams,
    SIZING_MODES,
    enrich_events_with_exit_info,
    period_trade_summary,
    prepare_market_data,
    run_prototype_backtest,
    summarize_backtest,
    trade_tail_dependence,
)
from research_core.oos_validation_analysis import discovery_score_thresholds, oos_prototype_masks, transform_oos_scores


CROSS_ASSET_SYMBOLS = ["BTCUSDT", "SOLUSDT", "BNBUSDT"]
CROSS_ASSET_PROTOTYPES = [
    "P1_C1_FIRST_BREAKOUT",
    "P2_STRONG_BREAKOUT",
    "P3_MOMENTUM_TOP20",
    "P4_BREAKOUT_TOP20",
    "P5_MOMENTUM_AND_BREAKOUT_TOP40",
    "P6_MOMENTUM_OR_BREAKOUT_TOP20",
]


def default_symbol_paths(symbol: str) -> list[Path]:
    return [
        Path(f"/Users/muce/1m_data/2024_validation_1m/{symbol}.csv"),
        Path(f"/Users/muce/1m_data/new_backtest_data_1year_1m/{symbol}.csv"),
    ]


def merge_symbol_1m(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for path in paths:
        if path.exists():
            frames.append(load_ohlcv_1m(path))
    if not frames:
        raise FileNotFoundError(f"No readable symbol data in {paths}")
    merged = pd.concat(frames).sort_index()
    return merged[~merged.index.duplicated(keep="last")]


def audit_symbol_data(symbol: str, data: pd.DataFrame) -> dict:
    diffs = data.index.to_series().diff()
    missing = diffs[diffs > pd.Timedelta(minutes=1)]
    invalid = (
        (data["low"] > data[["open", "close"]].min(axis=1))
        | (data["high"] < data[["open", "close"]].max(axis=1))
        | (data[["open", "high", "low", "close"]] <= 0).any(axis=1)
        | (data["volume"] < 0)
    )
    outliers = data["close"].pct_change().abs() > 0.10
    return {
        "symbol": symbol,
        "start_utc": data.index.min().isoformat(),
        "end_utc": data.index.max().isoformat(),
        "row_count": int(len(data)),
        "coverage_days": float((data.index.max() - data.index.min()).total_seconds() / 86400),
        "monotonic_increasing": bool(data.index.is_monotonic_increasing),
        "duplicate_timestamp_count": int(data.index.duplicated().sum()),
        "missing_range_count": int(len(missing)),
        "missing_minute_count": int((missing / pd.Timedelta(minutes=1) - 1).sum()) if len(missing) else 0,
        "invalid_ohlc_count": int(invalid.sum()),
        "outlier_count": int(outliers.sum()),
    }


def cross_asset_event_summary(symbol: str, events: pd.DataFrame, masks: dict[str, pd.Series]) -> pd.DataFrame:
    rows = []
    for prototype in CROSS_ASSET_PROTOTYPES:
        part = events[masks[prototype]]
        for horizon in [1, 4, 8, 16, 32]:
            rows.append({
                "symbol": symbol,
                "prototype": prototype,
                "horizon": horizon,
                "event_count": int(len(part)),
                "mean_fwd_ret": float(part[f"fwd_ret_{horizon}"].mean()) if len(part) else np.nan,
                "median_fwd_ret": float(part[f"fwd_ret_{horizon}"].median()) if len(part) else np.nan,
                "mean_mfe": float(part[f"fwd_mfe_{horizon}"].mean()) if len(part) else np.nan,
                "mean_mae": float(part[f"fwd_mae_{horizon}"].mean()) if len(part) else np.nan,
                "plus_1atr_first_rate": float(part[f"plus_1atr_first_{horizon}"].mean()) if len(part) else np.nan,
                "minus_1atr_first_rate": float(part[f"minus_1atr_first_{horizon}"].mean()) if len(part) else np.nan,
                "ambiguous_rate": float(part[f"ambiguous_touch_{horizon}"].mean()) if len(part) else np.nan,
                "sample_status": "valid" if len(part) >= 30 else "insufficient_sample",
            })
    return pd.DataFrame(rows)


def make_cross_asset_frames(events: pd.DataFrame, scores: pd.DataFrame, thresholds: pd.DataFrame) -> dict[str, pd.DataFrame]:
    masks = oos_prototype_masks(scores, events, thresholds)
    return {
        prototype: events[masks[prototype]].sort_values("execution_time").reset_index(drop=True)
        for prototype in CROSS_ASSET_PROTOTYPES
    }


def run_cross_asset_symbol(
    symbol: str,
    paths: list[Path],
    metadata: pd.DataFrame,
    discovery_scores: pd.DataFrame,
    params: BacktestParams,
) -> dict[str, pd.DataFrame]:
    data = merge_symbol_1m(paths)
    events, _ = build_event_candidates(data, symbol=symbol)
    events["signal_time"] = pd.to_datetime(events["signal_time"], utc=True)
    events["execution_time"] = pd.to_datetime(events["execution_time"], utc=True)
    scores = transform_oos_scores(events, metadata)
    thresholds = discovery_score_thresholds(discovery_scores)
    frames = make_cross_asset_frames(events, scores, thresholds)
    event_summary = cross_asset_event_summary(symbol, events, oos_prototype_masks(scores, events, thresholds))
    data_15m = None
    # Use the merged in-memory data for exact symbol coverage rather than rereading a single file.
    from research_core.event_table import add_base_indicators, strict_resample_15m

    data_15m = add_base_indicators(strict_resample_15m(data))
    enriched_events = enrich_events_with_exit_info(events, data, data_15m, params)
    enriched_frames = make_cross_asset_frames(enriched_events, scores, thresholds)
    summary_rows = []
    all_trades = []
    equity_frames = []
    for prototype in CROSS_ASSET_PROTOTYPES:
        for sizing_mode in SIZING_MODES:
            trades, equity = run_prototype_backtest(enriched_frames[prototype], data, data_15m, params, prototype, sizing_mode)
            summary_rows.append({
                "symbol": symbol,
                **summarize_backtest(prototype, sizing_mode, trades, equity, params.initial_balance, data.index.min(), data.index.max()),
            })
            if not trades.empty:
                all_trades.append(trades.assign(symbol=symbol))
            equity_frames.append(equity.assign(symbol=symbol))
    trades_all = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    tail = trade_tail_dependence(trades_all, params.initial_balance)
    if not tail.empty:
        tail.insert(0, "symbol", symbol)
    return {
        "quality": pd.DataFrame([audit_symbol_data(symbol, data)]),
        "events": events,
        "scores": scores,
        "thresholds": thresholds.assign(symbol=symbol),
        "event_summary": event_summary,
        "backtest_summary": pd.DataFrame(summary_rows),
        "trades": trades_all,
        "equity": pd.concat(equity_frames, ignore_index=True) if equity_frames else pd.DataFrame(),
        "tail": tail,
    }


def cross_asset_decision(summary: pd.DataFrame, tail: pd.DataFrame) -> pd.DataFrame:
    fixed = summary[summary["sizing_mode"] == "fixed_2x"].copy()
    rows = []
    for prototype in ["P3_MOMENTUM_TOP20", "P4_BREAKOUT_TOP20", "P5_MOMENTUM_AND_BREAKOUT_TOP40", "P6_MOMENTUM_OR_BREAKOUT_TOP20"]:
        part = fixed[fixed["prototype"] == prototype]
        valid = part[part["trade_count"] >= 30]
        positive_symbol_rate = float((valid["total_return"] > 0).mean()) if not valid.empty else np.nan
        pf_gt_1_rate = float((valid["profit_factor"] > 1).mean()) if not valid.empty else np.nan
        p1 = fixed[fixed["prototype"] == "P1_C1_FIRST_BREAKOUT"].set_index("symbol")
        better_than_p1 = []
        for _, row in valid.iterrows():
            if row["symbol"] in p1.index:
                base = p1.loc[row["symbol"]]
                better_than_p1.append(row["profit_factor"] > base["profit_factor"] and row["total_return"] > base["total_return"])
        better_rate = float(np.mean(better_than_p1)) if better_than_p1 else np.nan
        if len(valid) < 2:
            status = "insufficient_cross_asset_sample"
            step = "needs_more_assets"
        elif positive_symbol_rate >= 2 / 3 and pf_gt_1_rate >= 2 / 3 and better_rate >= 2 / 3:
            status = "cross_asset_supported"
            step = "eligible_for_deeper_cross_asset_validation"
        elif positive_symbol_rate >= 2 / 3 and pf_gt_1_rate >= 2 / 3:
            status = "weak_cross_asset_support"
            step = "needs_cost_and_asset_expansion"
        else:
            status = "cross_asset_failed"
            step = "discard_or_research_only"
        rows.append({
            "prototype": prototype,
            "tested_symbol_count": int(len(part)),
            "valid_symbol_count": int(len(valid)),
            "positive_symbol_rate": positive_symbol_rate,
            "pf_gt_1_symbol_rate": pf_gt_1_rate,
            "better_than_p1_symbol_rate": better_rate,
            "median_total_return": float(valid["total_return"].median()) if not valid.empty else np.nan,
            "median_profit_factor": float(valid["profit_factor"].median()) if not valid.empty else np.nan,
            "decision_status": status,
            "allowed_next_step": step,
        })
    return pd.DataFrame(rows)
