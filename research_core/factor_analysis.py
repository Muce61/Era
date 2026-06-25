"""Factor quintile and monotonicity analysis."""

from __future__ import annotations

import numpy as np
import pandas as pd


def assign_quintile(series: pd.Series, min_count: int = 50, min_unique: int = 20) -> pd.Series:
    valid = series.dropna()
    out = pd.Series(index=series.index, dtype="object")
    if len(valid) < min_count or valid.nunique() < min_unique:
        out.loc[valid.index] = "insufficient_sample"
        return out
    ranked = valid.rank(method="first")
    out.loc[valid.index] = pd.qcut(ranked, 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"]).astype(str)
    return out


def monotonicity_violations(values: list[float]) -> int:
    clean = [v for v in values if pd.notna(v)]
    if len(clean) < 2:
        return 0
    direction = 1 if clean[-1] >= clean[0] else -1
    violations = 0
    for prev, cur in zip(clean, clean[1:]):
        if direction == 1 and cur < prev:
            violations += 1
        elif direction == -1 and cur > prev:
            violations += 1
    return violations


def summarize_factor(events: pd.DataFrame, factor: str, horizon: int) -> tuple[pd.DataFrame, dict]:
    q = assign_quintile(events[factor])
    fwd_col = f"fwd_ret_{horizon}"
    mfe_col = f"fwd_mfe_{horizon}"
    mae_col = f"fwd_mae_{horizon}"
    plus_col = f"plus_1atr_first_{horizon}"
    minus_col = f"minus_1atr_first_{horizon}"
    amb_col = f"ambiguous_touch_{horizon}"
    tmp = events.assign(quintile=q)
    rows = []
    columns = [
        "factor",
        "horizon",
        "quintile",
        "event_count",
        "mean_fwd_ret",
        "median_fwd_ret",
        "mean_mfe",
        "mean_mae",
        "plus_1atr_first_rate",
        "minus_1atr_first_rate",
        "ambiguous_rate",
        "mfe_mae_ratio",
    ]
    for quintile in ["Q1", "Q2", "Q3", "Q4", "Q5", "insufficient_sample"]:
        part = tmp[tmp["quintile"] == quintile]
        if part.empty:
            continue
        mean_mae = part[mae_col].mean()
        rows.append({
            "factor": factor,
            "horizon": horizon,
            "quintile": quintile,
            "event_count": int(len(part)),
            "mean_fwd_ret": float(part[fwd_col].mean()),
            "median_fwd_ret": float(part[fwd_col].median()),
            "mean_mfe": float(part[mfe_col].mean()),
            "mean_mae": float(mean_mae),
            "plus_1atr_first_rate": float(part[plus_col].mean()),
            "minus_1atr_first_rate": float(part[minus_col].mean()),
            "ambiguous_rate": float(part[amb_col].mean()),
            "mfe_mae_ratio": float(part[mfe_col].mean() / abs(mean_mae)) if mean_mae and not np.isnan(mean_mae) else np.nan,
        })
    summary = pd.DataFrame(rows, columns=columns)
    q_rows = summary[summary["quintile"].isin(["Q1", "Q2", "Q3", "Q4", "Q5"])]
    if len(q_rows) < 5:
        meta = {
            "factor": factor,
            "horizon": horizon,
            "q5_minus_q1": np.nan,
            "direction_consistency": np.nan,
            "monotonicity_violations": np.nan,
            "sample_sufficient": False,
            "candidate_status": "invalid_or_sparse",
        }
        return summary, meta
    means = q_rows.set_index("quintile").loc[["Q1", "Q2", "Q3", "Q4", "Q5"], "mean_fwd_ret"].tolist()
    q5_minus_q1 = means[-1] - means[0]
    violations = monotonicity_violations(means)
    direction_consistency = 1.0 - violations / 4.0
    if direction_consistency >= 0.75 and abs(q5_minus_q1) > 0:
        status = "candidate_for_validation"
    elif direction_consistency >= 0.5 and abs(q5_minus_q1) > 0:
        status = "weak_candidate"
    else:
        status = "descriptive_only"
    meta = {
        "factor": factor,
        "horizon": horizon,
        "q5_minus_q1": float(q5_minus_q1),
        "direction_consistency": float(direction_consistency),
        "monotonicity_violations": int(violations),
        "sample_sufficient": True,
        "candidate_status": status,
    }
    return summary, meta
