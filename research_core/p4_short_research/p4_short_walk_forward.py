"""Walk-forward and bootstrap helpers for P4 short mirror research."""

from __future__ import annotations

import numpy as np
import pandas as pd


def ordinary_bootstrap(events: pd.DataFrame, horizon: int = 16, runs: int = 1000, seed: int = 20260624) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    rng = np.random.default_rng(seed)
    vals = events[f"short_fwd_ret_{horizon}"].dropna().to_numpy(float)
    means = [float(np.mean(rng.choice(vals, size=len(vals), replace=True))) for _ in range(runs)] if len(vals) else []
    arr = np.asarray(means)
    return pd.DataFrame([{
        "horizon": horizon,
        "runs": len(arr),
        "mean": float(arr.mean()) if len(arr) else np.nan,
        "p05": float(np.quantile(arr, 0.05)) if len(arr) else np.nan,
        "p50": float(np.quantile(arr, 0.50)) if len(arr) else np.nan,
        "p95": float(np.quantile(arr, 0.95)) if len(arr) else np.nan,
        "positive_rate": float((arr > 0).mean()) if len(arr) else np.nan,
        "bootstrap_status": "pass" if len(arr) and (arr > 0).mean() >= 0.6 else "weak",
    }])


def block_bootstrap(events: pd.DataFrame, block_col: str, horizon: int = 16, runs: int = 1000, seed: int = 20260624) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    work = events.copy()
    work["signal_time"] = pd.to_datetime(work["signal_time"], utc=True)
    if block_col == "month":
        work["block"] = work["signal_time"].dt.to_period("M").astype(str)
    elif block_col == "quarter":
        work["block"] = work["signal_time"].dt.to_period("Q").astype(str)
    else:
        work["block"] = work[block_col].astype(str)
    blocks = [g for _, g in work.groupby("block")]
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(runs):
        picked = [blocks[int(rng.integers(0, len(blocks)))] for _ in blocks]
        sample = pd.concat(picked, ignore_index=True)
        means.append(float(sample[f"short_fwd_ret_{horizon}"].mean()))
    arr = np.asarray(means)
    return pd.DataFrame([{
        "block": block_col,
        "horizon": horizon,
        "runs": len(arr),
        "mean": float(arr.mean()),
        "p05": float(np.quantile(arr, 0.05)),
        "p50": float(np.quantile(arr, 0.50)),
        "p95": float(np.quantile(arr, 0.95)),
        "positive_rate": float((arr > 0).mean()),
        "bootstrap_status": "pass" if (arr > 0).mean() >= 0.6 else "weak",
    }])

