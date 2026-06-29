"""Matched random baseline utilities for canonical S2."""

from __future__ import annotations

import numpy as np
import pandas as pd


def add_match_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["month"] = pd.to_datetime(out["signal_time"], utc=True).dt.to_period("M").astype(str)
    if "trend_strength_bucket" not in out.columns:
        out["trend_strength_bucket"] = pd.cut(
            out["trend_strength_atr"],
            [-np.inf, 0.5, 1.0, 1.5, 2.5, np.inf],
            labels=["0_0.5", "0.5_1.0", "1.0_1.5", "1.5_2.5", "gt_2.5"],
        ).astype("object").fillna("unknown")
    return out


def matched_random_summary_s2(
    events: pd.DataFrame,
    pool: pd.DataFrame | None = None,
    runs: int = 500,
    seed: int = 20260624,
    horizon: int = 16,
) -> pd.DataFrame:
    """Compare each candidate with a matched market-state random pool.

    When ``pool`` is not supplied, the event table itself is used. S2.6 passes
    a full market-time pool to avoid event-only sampling.
    """
    rng = np.random.default_rng(seed)
    if events.empty:
        return pd.DataFrame()
    work = add_match_columns(events)
    random_pool = add_match_columns(pool if pool is not None else events)
    label = f"fwd_ret_{horizon}"
    primary_cols = ["symbol", "side", "month", "volatility_regime", "trend_strength_bucket", "p4_state_bucket"]
    fallback_cols = ["symbol", "side", "volatility_regime", "p4_state_bucket"]
    primary_lookup = {
        key: group[label].dropna().to_numpy(float)
        for key, group in random_pool.groupby(primary_cols, observed=True, dropna=False)
    }
    fallback_lookup = {
        key: group[label].dropna().to_numpy(float)
        for key, group in random_pool.groupby(fallback_cols, observed=True, dropna=False)
    }
    rows = []
    for candidate, part in work.groupby("candidate", dropna=False):
        match_sets = []
        fallback_count = 0
        for _, event in part.iterrows():
            pkey = tuple(event.get(col) for col in primary_cols)
            fkey = tuple(event.get(col) for col in fallback_cols)
            vals = primary_lookup.get(pkey)
            used_fallback = False
            if vals is None or len(vals) == 0:
                vals = fallback_lookup.get(fkey)
                used_fallback = True
            if vals is not None and len(vals) > 0:
                match_sets.append(vals)
                fallback_count += int(used_fallback)
        simulated = []
        for _ in range(runs):
            sample = [float(vals[int(rng.integers(0, len(vals)))]) for vals in match_sets if len(vals)]
            if sample:
                simulated.append(float(np.mean(sample)))
        sim = np.asarray(simulated, dtype=float)
        observed = float(part[label].mean()) if len(part) else np.nan
        rows.append({
            "candidate": candidate,
            "horizon": horizon,
            "event_count": int(len(part)),
            "observed_mean": observed,
            "random_mean": float(np.nanmean(sim)) if len(sim) else np.nan,
            "random_p05": float(np.nanpercentile(sim, 5)) if len(sim) else np.nan,
            "random_p50": float(np.nanpercentile(sim, 50)) if len(sim) else np.nan,
            "random_p95": float(np.nanpercentile(sim, 95)) if len(sim) else np.nan,
            "percentile_vs_random": float((np.sum(sim <= observed) + 1) / (len(sim) + 1)) if len(sim) else np.nan,
            "matched_event_count": int(len(match_sets)),
            "fallback_match_rate": float(fallback_count / len(part)) if len(part) else np.nan,
            "random_runs": int(len(sim)),
            "pool_source": "full_market_state_pool" if pool is not None else "event_table_fallback",
        })
    return pd.DataFrame(rows)

