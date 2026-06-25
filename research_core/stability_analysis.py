"""R3 factor stability helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research_core.factor_analysis import summarize_factor


def sign_or_zero(value: float) -> int:
    if pd.isna(value) or value == 0:
        return 0
    return 1 if value > 0 else -1


def add_time_groups(events: pd.DataFrame) -> pd.DataFrame:
    out = events.copy()
    signal_time = pd.to_datetime(out["signal_time"], utc=True)
    out["year_group"] = signal_time.dt.year.astype(str)
    out["quarter_group"] = signal_time.dt.year.astype(str) + "Q" + signal_time.dt.quarter.astype(str)
    max_time = signal_time.max()
    out["partial_year"] = signal_time.dt.year == max_time.year
    return out


def group_stability_rows(
    events: pd.DataFrame,
    factor: str,
    horizon: int,
    full_q5_minus_q1: float,
    group_column: str,
) -> list[dict]:
    full_direction = sign_or_zero(full_q5_minus_q1)
    rows = []
    for group_value, part in events.groupby(group_column, dropna=False):
        group_value = "missing" if pd.isna(group_value) else str(group_value)
        summary, meta = summarize_factor(part, factor, horizon)
        group_direction = sign_or_zero(meta["q5_minus_q1"])
        same_direction = (
            bool(full_direction != 0 and group_direction == full_direction)
            if meta["sample_sufficient"]
            else False
        )
        rows.append({
            "factor": factor,
            "horizon": horizon,
            "group_type": group_column,
            "group_value": group_value,
            "event_count": int(len(part)),
            "sample_sufficient": bool(meta["sample_sufficient"]),
            "q5_minus_q1": meta["q5_minus_q1"],
            "direction_consistency": meta["direction_consistency"],
            "monotonicity_violations": meta["monotonicity_violations"],
            "same_direction_as_full": same_direction,
            "candidate_status": meta["candidate_status"],
            "status_note": "ok" if summary["quintile"].nunique() >= 5 else "invalid_or_sparse",
        })
    return rows


def same_direction_rate(rows: pd.DataFrame, group_type: str) -> float:
    part = rows[(rows["group_type"] == group_type) & (rows["sample_sufficient"])]
    if part.empty:
        return np.nan
    return float(part["same_direction_as_full"].mean())


def stability_status(
    full_candidate_status: str,
    full_q5_minus_q1: float,
    year_same_direction_rate: float,
    quarter_same_direction_rate: float,
    valid_year_count: int,
    valid_quarter_count: int,
) -> str:
    if full_candidate_status == "invalid_or_sparse" or sign_or_zero(full_q5_minus_q1) == 0:
        return "invalid_or_sparse"
    if valid_year_count < 2 or valid_quarter_count < 4:
        return "insufficient_stability_sample"
    if (
        full_candidate_status == "candidate_for_validation"
        and year_same_direction_rate >= 0.60
        and quarter_same_direction_rate >= 0.55
    ):
        return "candidate_for_random_baseline"
    if full_candidate_status in {"candidate_for_validation", "weak_candidate"}:
        return "unstable_descriptive"
    return "descriptive_only"


def summarize_stability(events: pd.DataFrame, r2_meta: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    events = add_time_groups(events)
    detail_rows = []
    summary_rows = []
    group_columns = ["year_group", "quarter_group", "trend_regime", "volatility_regime"]
    for _, full in r2_meta.iterrows():
        factor = full["factor"]
        horizon = int(full["horizon"])
        if factor not in events.columns:
            continue
        for group_column in group_columns:
            if group_column not in events.columns:
                continue
            detail_rows.extend(group_stability_rows(events, factor, horizon, full["q5_minus_q1"], group_column))
    detail = pd.DataFrame(detail_rows)
    for _, full in r2_meta.iterrows():
        factor = full["factor"]
        horizon = int(full["horizon"])
        part = detail[(detail["factor"] == factor) & (detail["horizon"] == horizon)]
        years = part[part["group_type"] == "year_group"]
        quarters = part[part["group_type"] == "quarter_group"]
        valid_year_count = int(years["sample_sufficient"].sum()) if not years.empty else 0
        valid_quarter_count = int(quarters["sample_sufficient"].sum()) if not quarters.empty else 0
        year_rate = same_direction_rate(part, "year_group")
        quarter_rate = same_direction_rate(part, "quarter_group")
        median_group_direction_consistency = float(part[part["sample_sufficient"]]["direction_consistency"].median()) if not part.empty and part["sample_sufficient"].any() else np.nan
        status = stability_status(
            str(full["candidate_status"]),
            float(full["q5_minus_q1"]) if pd.notna(full["q5_minus_q1"]) else np.nan,
            year_rate,
            quarter_rate,
            valid_year_count,
            valid_quarter_count,
        )
        summary_rows.append({
            "factor": factor,
            "common": full.get("common", ""),
            "horizon": horizon,
            "r2_candidate_status": full["candidate_status"],
            "full_q5_minus_q1": full["q5_minus_q1"],
            "full_direction_consistency": full["direction_consistency"],
            "valid_year_count": valid_year_count,
            "year_same_direction_rate": year_rate,
            "valid_quarter_count": valid_quarter_count,
            "quarter_same_direction_rate": quarter_rate,
            "median_group_direction_consistency": median_group_direction_consistency,
            "stability_status": status,
            "state_regime_note": "unavailable_in_current_event_table",
        })
    return pd.DataFrame(detail_rows), pd.DataFrame(summary_rows)
