"""R4 random baseline helpers for factor evidence."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from research_core.factor_analysis import assign_quintile
from research_core.stability_analysis import sign_or_zero


def percentile_rank_in_direction(observed: float, random_values: np.ndarray, direction: int) -> tuple[float, float]:
    """Return directional percentile and one-sided p value using (1+count)/(N+1)."""
    if direction == 0 or pd.isna(observed):
        return np.nan, np.nan
    observed_edge = observed * direction
    random_edges = random_values * direction
    n = len(random_edges)
    percentile = (1 + np.sum(random_edges <= observed_edge)) / (n + 1)
    p_value = (1 + np.sum(random_edges >= observed_edge)) / (n + 1)
    return float(percentile), float(p_value)


def classify_random_baseline(percentile: float, p_value: float) -> str:
    if pd.isna(percentile) or pd.isna(p_value):
        return "invalid_or_sparse"
    if percentile >= 0.95 and p_value <= 0.05:
        return "passes_random_baseline"
    if percentile >= 0.80 and p_value <= 0.20:
        return "weak_random_evidence"
    return "not_significant_vs_random"


def benjamini_hochberg_q_values(p_values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(p_values, errors="coerce")
    out = pd.Series(np.nan, index=p_values.index, dtype=float)
    valid = numeric.dropna().sort_values()
    m = len(valid)
    if m == 0:
        return out
    adjusted = valid * m / np.arange(1, m + 1)
    adjusted = np.minimum.accumulate(adjusted.iloc[::-1]).iloc[::-1].clip(upper=1.0)
    out.loc[adjusted.index] = adjusted
    return out


def observed_quintile_edge(events: pd.DataFrame, factor: str, horizon: int) -> tuple[float, dict]:
    q = assign_quintile(events[factor])
    target = f"fwd_ret_{horizon}"
    tmp = events.assign(quintile=q)
    q1 = tmp[tmp["quintile"] == "Q1"][target].dropna()
    q5 = tmp[tmp["quintile"] == "Q5"][target].dropna()
    if q1.empty or q5.empty:
        return np.nan, {"q1_count": len(q1), "q5_count": len(q5), "valid_event_count": int(tmp[target].notna().sum())}
    return float(q5.mean() - q1.mean()), {
        "q1_count": int(len(q1)),
        "q5_count": int(len(q5)),
        "valid_event_count": int(tmp[target].notna().sum()),
        "q1_mean": float(q1.mean()),
        "q5_mean": float(q5.mean()),
    }


def random_q5_minus_q1_distribution(
    events: pd.DataFrame,
    horizon: int,
    q1_count: int,
    q5_count: int,
    n_runs: int,
    rng: np.random.Generator,
) -> np.ndarray:
    values = events[f"fwd_ret_{horizon}"].dropna().to_numpy(dtype=float)
    if len(values) < q1_count + q5_count or q1_count <= 0 or q5_count <= 0:
        return np.array([], dtype=float)
    out = np.empty(n_runs, dtype=float)
    sample_size = q1_count + q5_count
    for i in range(n_runs):
        sample = rng.choice(values, size=sample_size, replace=False)
        out[i] = sample[q1_count:].mean() - sample[:q1_count].mean()
    return out


def summarize_random_baseline(
    events: pd.DataFrame,
    candidates: pd.DataFrame,
    n_runs: int = 5000,
    random_seed: int = 20260624,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary_rows = []
    run_rows = []
    for _, candidate in candidates.iterrows():
        factor = candidate["factor"]
        horizon = int(candidate["horizon"])
        observed, counts = observed_quintile_edge(events, factor, horizon)
        direction = sign_or_zero(candidate["full_q5_minus_q1"])
        seed_payload = int(
            hashlib.sha256(f"{random_seed}|{factor}|{horizon}".encode("utf-8")).hexdigest()[:8],
            16,
        )
        rng = np.random.default_rng(seed_payload)
        random_values = random_q5_minus_q1_distribution(
            events=events,
            horizon=horizon,
            q1_count=int(counts.get("q1_count", 0)),
            q5_count=int(counts.get("q5_count", 0)),
            n_runs=n_runs,
            rng=rng,
        )
        percentile, p_value = percentile_rank_in_direction(observed, random_values, direction)
        status = classify_random_baseline(percentile, p_value)
        if len(random_values):
            run_rows.extend({
                "factor": factor,
                "horizon": horizon,
                "run_id": i,
                "random_q5_minus_q1": float(value),
                "random_edge_in_factor_direction": float(value * direction),
            } for i, value in enumerate(random_values))
        observed_edge = observed * direction if direction else np.nan
        summary_rows.append({
            "factor": factor,
            "common": candidate.get("common", ""),
            "horizon": horizon,
            "direction": direction,
            "observed_q5_minus_q1": observed,
            "observed_edge_in_factor_direction": observed_edge,
            "random_mean_q5_minus_q1": float(np.mean(random_values)) if len(random_values) else np.nan,
            "random_std_q5_minus_q1": float(np.std(random_values, ddof=1)) if len(random_values) > 1 else np.nan,
            "random_p05_q5_minus_q1": float(np.quantile(random_values, 0.05)) if len(random_values) else np.nan,
            "random_p50_q5_minus_q1": float(np.quantile(random_values, 0.50)) if len(random_values) else np.nan,
            "random_p95_q5_minus_q1": float(np.quantile(random_values, 0.95)) if len(random_values) else np.nan,
            "directional_percentile": percentile,
            "one_sided_p_value": p_value,
            "random_baseline_status": status,
            "n_runs": int(len(random_values)),
            **counts,
        })
    summary = pd.DataFrame(summary_rows)
    if not summary.empty:
        summary["bh_fdr_q_value"] = benjamini_hochberg_q_values(summary["one_sided_p_value"])
        summary["passes_after_fdr_5pct"] = summary["bh_fdr_q_value"] <= 0.05
    return summary, pd.DataFrame(run_rows)
