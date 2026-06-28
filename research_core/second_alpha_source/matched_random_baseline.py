"""Matched random baselines for second-alpha candidate events."""

from __future__ import annotations

import numpy as np
import pandas as pd


def build_random_pool(events: pd.DataFrame) -> pd.DataFrame:
    pool = events.copy()
    pool["month"] = pd.to_datetime(pool["signal_time"], utc=True).dt.to_period("M").astype(str)
    pool["trend_bucket"] = pd.cut(pool["trend_strength_atr"], [-np.inf, 1, 2, 3, np.inf], labels=["t0", "t1", "t2", "t3"]).astype("object")
    pool["vol_bucket"] = pool["volatility_regime"].astype(str)
    return pool


def matched_random_summary(events: pd.DataFrame, runs: int = 500, seed: int = 20260624, horizon: int = 16) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    pool = build_random_pool(events)
    rows = []
    label = f"fwd_ret_{horizon}"
    for candidate, candidate_events in pool.groupby("candidate"):
        observed = float(candidate_events[label].mean())
        other = pool[pool["candidate"] != candidate].copy()
        primary_cols = ["symbol", "side", "month", "vol_bucket", "trend_bucket"]
        fallback_cols = ["symbol", "side", "vol_bucket"]
        primary_lookup = {
            key: group[label].dropna().to_numpy(float)
            for key, group in other.groupby(primary_cols, observed=True)
        }
        fallback_lookup = {
            key: group[label].dropna().to_numpy(float)
            for key, group in other.groupby(fallback_cols, observed=True)
        }
        match_sets = []
        for _, event in candidate_events.iterrows():
            primary_key = tuple(event[col] for col in primary_cols)
            fallback_key = tuple(event[col] for col in fallback_cols)
            vals = primary_lookup.get(primary_key)
            if vals is None or len(vals) == 0:
                vals = fallback_lookup.get(fallback_key)
            if vals is not None and len(vals) > 0:
                match_sets.append(vals)
        simulated = []
        for _ in range(runs):
            samples = []
            for vals in match_sets:
                samples.append(float(vals[int(rng.integers(0, len(vals)))]))
            if samples:
                simulated.append(float(np.mean(samples)))
        sim = np.array(simulated, dtype=float)
        rows.append({
            "candidate": candidate,
            "horizon": horizon,
            "event_count": int(len(candidate_events)),
            "observed_mean": observed,
            "random_mean": float(np.nanmean(sim)) if len(sim) else np.nan,
            "random_p05": float(np.nanpercentile(sim, 5)) if len(sim) else np.nan,
            "random_p50": float(np.nanpercentile(sim, 50)) if len(sim) else np.nan,
            "random_p95": float(np.nanpercentile(sim, 95)) if len(sim) else np.nan,
            "percentile_vs_random": float((np.sum(sim <= observed) + 1) / (len(sim) + 1)) if len(sim) else np.nan,
            "random_runs": int(len(sim)),
        })
    return pd.DataFrame(rows)
