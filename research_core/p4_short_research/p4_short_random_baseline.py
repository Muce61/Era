"""Matched random bear-regime baseline for P4 short mirror events."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research_core.common import RANDOM_SEED


def add_match_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["signal_time"] = pd.to_datetime(out["signal_time"], utc=True)
    out["quarter"] = out["signal_time"].dt.to_period("Q").astype(str)
    return out


def matched_random_baseline(events: pd.DataFrame, pools: pd.DataFrame, runs: int = 1000, horizon: int = 16, seed: int = RANDOM_SEED) -> tuple[pd.DataFrame, pd.DataFrame]:
    if events.empty or pools.empty:
        return pd.DataFrame(), pd.DataFrame()
    rng = np.random.default_rng(seed)
    events = add_match_columns(events)
    pools = add_match_columns(pools)
    observed = float(events[f"short_fwd_ret_{horizon}"].mean())
    pool_groups = {k: v.reset_index(drop=True) for k, v in pools.groupby(["symbol", "quarter", "volatility_regime", "trend_strength_bucket"], dropna=False)}
    loose_groups = {k: v.reset_index(drop=True) for k, v in pools.groupby(["symbol", "volatility_regime", "trend_strength_bucket"], dropna=False)}
    all_groups = {k: v.reset_index(drop=True) for k, v in pools.groupby(["symbol"], dropna=False)}
    group_needs: dict[tuple[str, object], int] = {}
    matched_total = 0
    fallback_total = 0
    samples = []
    value_cache: dict[tuple[str, object], np.ndarray] = {}
    id_cache: dict[tuple[str, object], pd.Series] = {}
    for _, event in events.iterrows():
        strict_key = (event["symbol"], event["quarter"], event["volatility_regime"], event["trend_strength_bucket"])
        loose_key = (event["symbol"], event["volatility_regime"], event["trend_strength_bucket"])
        sym_key = (event["symbol"],)
        fallback = False
        source = pool_groups.get(strict_key)
        source_id: tuple[str, object] = ("strict", strict_key)
        if source is None or source.empty:
            source = loose_groups.get(loose_key)
            source_id = ("loose", loose_key)
            fallback = True
        if source is None or source.empty:
            source = all_groups.get(sym_key)
            source_id = ("symbol", sym_key)
            fallback = True
        if source is None or source.empty:
            continue
        group_needs[source_id] = group_needs.get(source_id, 0) + 1
        matched_total += 1
        fallback_total += int(fallback)
        if source_id not in value_cache:
            value_cache[source_id] = source[f"short_fwd_ret_{horizon}"].astype(float).dropna().to_numpy()
            id_cache[source_id] = source["event_id"]
        pick_idx = int(rng.integers(0, len(source)))
        samples.append({
            "event_id": event["event_id"],
            "matched_random_event_id": source.iloc[pick_idx]["event_id"],
            "fallback": fallback,
        })
    baseline_means = []
    for _ in range(runs):
        vals = []
        for source_id, need in group_needs.items():
            source_vals = value_cache[source_id]
            if len(source_vals) == 0:
                continue
            vals.append(rng.choice(source_vals, size=need, replace=True))
        if vals:
            baseline_means.append(float(np.mean(np.concatenate(vals))))
        else:
            baseline_means.append(np.nan)
    arr = np.asarray([x for x in baseline_means if np.isfinite(x)], dtype=float)
    summary = pd.DataFrame([{
        "event_count": int(len(events)),
        "observed_mean": observed,
        "random_mean": float(np.mean(arr)) if len(arr) else np.nan,
        "random_p05": float(np.quantile(arr, 0.05)) if len(arr) else np.nan,
        "random_p50": float(np.quantile(arr, 0.50)) if len(arr) else np.nan,
        "random_p95": float(np.quantile(arr, 0.95)) if len(arr) else np.nan,
        "percentile_vs_random": float((arr <= observed).mean()) if len(arr) else np.nan,
        "matched_event_count": matched_total,
        "fallback_match_rate": float(fallback_total / matched_total) if matched_total else np.nan,
        "random_runs": int(len(arr)),
        "horizon": horizon,
    }])
    return summary, pd.DataFrame(samples)
