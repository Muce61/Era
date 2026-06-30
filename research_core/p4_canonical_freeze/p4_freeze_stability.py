"""Stability helpers for P4 canonical freeze candidates."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research_core.leverage_research_analysis import INITIAL_BALANCE, profit_factor
from research_core.minimal_backtest_analysis import max_drawdown
from research_core.p4_canonical_freeze.p4_freeze_replay import summarize_trades


def period_summary(trades_map: dict[str, pd.DataFrame], freq: str) -> pd.DataFrame:
    rows = []
    for candidate_id, trades in trades_map.items():
        if trades.empty:
            continue
        work = trades.copy()
        work["exit_time"] = pd.to_datetime(work["exit_time"], utc=True)
        work["period"] = work["exit_time"].dt.to_period(freq)
        for period, part in work.groupby("period"):
            pnl = part["net_pnl"].astype(float)
            curve = pd.DataFrame({"equity": INITIAL_BALANCE + pnl.cumsum()})
            year = int(str(period)[:4])
            rows.append({
                "candidate_id": candidate_id,
                "period": str(period),
                "year": year,
                "trade_count": int(len(part)),
                "return": float(pnl.sum() / INITIAL_BALANCE),
                "profit_factor": profit_factor(pnl),
                "max_drawdown": max_drawdown(curve["equity"]),
                "win_rate": float((pnl > 0).mean()) if len(part) else np.nan,
                "sample_status": "partial_year" if year == 2026 else ("insufficient_sample" if len(part) < 5 else "valid"),
            })
    return pd.DataFrame(rows)


def profit_dependency(trades_map: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for candidate_id, trades in trades_map.items():
        pnl = trades["net_pnl"].astype(float) if not trades.empty else pd.Series(dtype=float)
        base = float(pnl.sum() / INITIAL_BALANCE) if len(pnl) else 0.0
        pos = pnl[pnl > 0].sort_values(ascending=False)
        total_pos = float(pos.sum())
        def contribution(n: int) -> float:
            return float(pos.head(n).sum() / total_pos) if total_pos > 0 else np.nan
        def remove_top(n: int) -> float:
            if len(pnl) == 0:
                return 0.0
            drop_idx = pos.head(n).index
            return float(pnl.drop(drop_idx).sum() / INITIAL_BALANCE)
        rows.append({
            "candidate_id": candidate_id,
            "top1_profit_contribution": contribution(1),
            "top3_profit_contribution": contribution(3),
            "top5_profit_contribution": contribution(5),
            "remove_top1_return": remove_top(1),
            "remove_top3_return": remove_top(3),
            "remove_top5_return": remove_top(5),
            "best_month_removed_return": _remove_best_period(trades, "M"),
            "best_quarter_removed_return": _remove_best_period(trades, "Q"),
            "original_return": base,
        })
    return pd.DataFrame(rows)


def _remove_best_period(trades: pd.DataFrame, freq: str) -> float:
    if trades.empty:
        return 0.0
    work = trades.copy()
    work["period"] = pd.to_datetime(work["exit_time"], utc=True).dt.to_period(freq)
    period_pnl = work.groupby("period")["net_pnl"].sum()
    if period_pnl.empty:
        return float(work["net_pnl"].sum() / INITIAL_BALANCE)
    best = period_pnl.idxmax()
    return float(work.loc[work["period"] != best, "net_pnl"].sum() / INITIAL_BALANCE)


def bootstrap_summary(trades_map: dict[str, pd.DataFrame], runs: int = 500, seed: int = 20260624) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for candidate_id, trades in trades_map.items():
        pnl = trades["net_pnl"].to_numpy(float) if not trades.empty else np.array([])
        if len(pnl) == 0:
            rows.append({"candidate_id": candidate_id, "positive_return_probability": np.nan, "mean_return_p50": np.nan})
            continue
        samples = []
        pfs = []
        for _ in range(runs):
            draw = rng.choice(pnl, size=len(pnl), replace=True)
            samples.append(draw.sum() / INITIAL_BALANCE)
            pfs.append(profit_factor(pd.Series(draw)))
        rows.append({
            "candidate_id": candidate_id,
            "bootstrap_runs": runs,
            "mean_return_p05": float(np.quantile(samples, 0.05)),
            "mean_return_p50": float(np.quantile(samples, 0.50)),
            "mean_return_p95": float(np.quantile(samples, 0.95)),
            "pf_p50": float(np.nanmedian(pfs)),
            "positive_return_probability": float(np.mean(np.array(samples) > 0)),
        })
    return pd.DataFrame(rows)


def block_bootstrap_summary(trades_map: dict[str, pd.DataFrame], runs: int = 500, seed: int = 20260625) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for candidate_id, trades in trades_map.items():
        if trades.empty:
            rows.append({"candidate_id": candidate_id, "block_bootstrap_positive_probability": np.nan})
            continue
        work = trades.copy()
        work["quarter"] = pd.to_datetime(work["exit_time"], utc=True).dt.to_period("Q")
        blocks = [g["net_pnl"].to_numpy(float) for _, g in work.groupby("quarter")]
        if not blocks:
            rows.append({"candidate_id": candidate_id, "block_bootstrap_positive_probability": np.nan})
            continue
        returns = []
        for _ in range(runs):
            draw_blocks = rng.choice(len(blocks), size=len(blocks), replace=True)
            returns.append(sum(blocks[i].sum() for i in draw_blocks) / INITIAL_BALANCE)
        rows.append({
            "candidate_id": candidate_id,
            "bootstrap_runs": runs,
            "block_length": "quarter",
            "block_return_p05": float(np.quantile(returns, 0.05)),
            "block_return_p50": float(np.quantile(returns, 0.50)),
            "block_return_p95": float(np.quantile(returns, 0.95)),
            "block_bootstrap_positive_probability": float(np.mean(np.array(returns) > 0)),
        })
    return pd.DataFrame(rows)


def walk_forward_from_trades(trades_map: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    windows = []
    train_start = start
    window_id = 1
    while True:
        train_end = train_start + pd.DateOffset(months=24)
        test_start = train_end
        test_end = min(test_start + pd.DateOffset(months=6), end)
        if test_start >= end:
            break
        windows.append((window_id, train_start, train_end, test_start, test_end))
        train_start = train_start + pd.DateOffset(months=6)
        window_id += 1
    rows = []
    for candidate_id, trades in trades_map.items():
        work = trades.copy()
        if work.empty:
            continue
        work["exit_time"] = pd.to_datetime(work["exit_time"], utc=True)
        for window_id, train_start, train_end, test_start, test_end in windows:
            part = work[(work["exit_time"] >= test_start) & (work["exit_time"] < test_end)]
            pnl = part["net_pnl"].astype(float)
            rows.append({
                "window_id": window_id,
                "train_start": train_start,
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
                "candidate_id": candidate_id,
                "trade_count": int(len(part)),
                "total_return": float(pnl.sum() / INITIAL_BALANCE) if len(part) else 0.0,
                "profit_factor": profit_factor(pnl),
                "sample_status": "insufficient_sample" if len(part) < 5 else "valid",
            })
    win_df = pd.DataFrame(rows)
    agg = []
    if not win_df.empty:
        for candidate_id, part in win_df.groupby("candidate_id"):
            valid = part[part["sample_status"] == "valid"]
            agg.append({
                "candidate_id": candidate_id,
                "window_count": int(len(part)),
                "valid_window_count": int(len(valid)),
                "positive_walk_forward_window_rate": float((valid["total_return"] > 0).mean()) if len(valid) else np.nan,
                "pf_gt_1_walk_forward_window_rate": float((valid["profit_factor"] > 1).mean()) if len(valid) else np.nan,
                "median_return": float(valid["total_return"].median()) if len(valid) else np.nan,
                "median_pf": float(valid["profit_factor"].median()) if len(valid) else np.nan,
            })
    return win_df, pd.DataFrame(agg)


def positive_valid_year_rate(yearly: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if yearly.empty:
        return pd.DataFrame(columns=["candidate_id", "positive_valid_year_rate"])
    for candidate_id, part in yearly.groupby("candidate_id"):
        valid = part[part["sample_status"].isin(["valid", "partial_year"])]
        rows.append({
            "candidate_id": candidate_id,
            "positive_valid_year_rate": float((valid["return"] > 0).mean()) if len(valid) else np.nan,
        })
    return pd.DataFrame(rows)


def prefix_invariance_status(full_trades: pd.DataFrame, prefix_trades: pd.DataFrame, cutoff: pd.Timestamp) -> str:
    full = full_trades[pd.to_datetime(full_trades["exit_time"], utc=True) < cutoff].copy()
    cols = ["signal_time", "entry_time", "exit_time", "entry_price", "exit_price", "quantity", "net_pnl", "exit_reason"]
    if len(full) != len(prefix_trades):
        return "fail"
    if full.empty and prefix_trades.empty:
        return "pass"
    left = full[cols].astype(str).reset_index(drop=True)
    right = prefix_trades[cols].astype(str).reset_index(drop=True)
    return "pass" if left.equals(right) else "fail"
