"""R5 factor-family bootstrap and stress-test helpers."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

import numpy as np
import pandas as pd

from research_core.factor_analysis import assign_quintile
from research_core.stability_analysis import add_time_groups, sign_or_zero


HORIZONS = [1, 4, 8, 16, 32]


def stable_seed(*parts: object) -> int:
    raw = "|".join(str(part) for part in parts).encode("utf-8")
    return int(hashlib.sha256(raw).hexdigest()[:8], 16)


def parse_factor_list(raw: str) -> list[str]:
    if not isinstance(raw, str):
        return []
    blocked_tokens = {"future candidates", "future liquidity proxies", "trend_regime", "volatility_regime"}
    out = [part.strip() for part in raw.split(";") if part.strip()]
    return [factor for factor in out if factor not in blocked_tokens]


def family_map(queue: pd.DataFrame) -> dict[str, dict[str, str]]:
    mapping = {}
    for _, row in queue.iterrows():
        for factor in parse_factor_list(row.get("related_existing_factors", "")):
            mapping[factor] = {
                "family": row["family"],
                "role": row["role"],
                "family_status": row.get("status", ""),
            }
    return mapping


def attach_family(candidates: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
    mapping = family_map(queue)
    out = candidates.copy()
    out["family"] = out["factor"].map(lambda factor: mapping.get(factor, {}).get("family", "unmapped"))
    out["role"] = out["factor"].map(lambda factor: mapping.get(factor, {}).get("role", "unmapped"))
    return out


def factor_edge(events: pd.DataFrame, factor: str, horizon: int, direction: int = 1) -> float:
    target = f"fwd_ret_{horizon}"
    if factor not in events.columns or target not in events.columns or events.empty:
        return np.nan
    q = assign_quintile(events[factor])
    tmp = events.assign(quintile=q)
    q1 = tmp[tmp["quintile"] == "Q1"][target].dropna()
    q5 = tmp[tmp["quintile"] == "Q5"][target].dropna()
    if q1.empty or q5.empty:
        return np.nan
    return float((q5.mean() - q1.mean()) * direction)


def labeled_factor_events(events: pd.DataFrame, factor: str, horizon: int) -> pd.DataFrame:
    target = f"fwd_ret_{horizon}"
    if "year_group" not in events.columns or "quarter_group" not in events.columns:
        events = add_time_groups(events)
    if "month_group" not in events.columns:
        events = events.copy()
        events["month_group"] = pd.to_datetime(events["signal_time"], utc=True).dt.strftime("%Y-%m")
    q = assign_quintile(events[factor])
    out = events[["signal_time", "year_group", "quarter_group", "month_group", target]].copy()
    out["quintile"] = q
    out = out[out["quintile"].isin(["Q1", "Q5"])].dropna(subset=[target])
    out = out.rename(columns={target: "forward_return"})
    return out


def edge_from_labeled(events: pd.DataFrame, direction: int) -> float:
    q1 = events[events["quintile"] == "Q1"]["forward_return"].dropna()
    q5 = events[events["quintile"] == "Q5"]["forward_return"].dropna()
    if q1.empty or q5.empty:
        return np.nan
    return float((q5.mean() - q1.mean()) * direction)


def bootstrap_sample(events: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    idx = rng.integers(0, len(events), size=len(events))
    return events.iloc[idx].reset_index(drop=True)


def block_bootstrap_sample(events: pd.DataFrame, block_col: str, rng: np.random.Generator) -> pd.DataFrame:
    groups = list(events.groupby(block_col, sort=True).groups.keys())
    if not groups:
        return events.iloc[[]].copy()
    sampled_groups = rng.choice(groups, size=len(groups), replace=True)
    parts = [events[events[block_col] == group] for group in sampled_groups]
    return pd.concat(parts, ignore_index=True)


def edge_distribution(
    events: pd.DataFrame,
    factor: str,
    horizon: int,
    direction: int,
    method: str,
    n_runs: int,
    random_seed: int,
) -> np.ndarray:
    labeled = labeled_factor_events(events, factor, horizon)
    rng = np.random.default_rng(stable_seed(random_seed, factor, horizon, method))
    q1 = labeled[labeled["quintile"] == "Q1"]["forward_return"].to_numpy(dtype=float)
    q5 = labeled[labeled["quintile"] == "Q5"]["forward_return"].to_numpy(dtype=float)
    if len(q1) == 0 or len(q5) == 0:
        return np.full(n_runs, np.nan)
    if method == "ordinary":
        q1_idx = rng.integers(0, len(q1), size=(n_runs, len(q1)))
        q5_idx = rng.integers(0, len(q5), size=(n_runs, len(q5)))
        return (q5[q5_idx].mean(axis=1) - q1[q1_idx].mean(axis=1)) * direction
    if method not in {"monthly", "quarterly"}:
        raise ValueError(f"Unknown bootstrap method: {method}")
    block_col = "month_group" if method == "monthly" else "quarter_group"
    grouped = []
    for _, part in labeled.groupby(block_col, sort=True):
        q1_part = part[part["quintile"] == "Q1"]["forward_return"]
        q5_part = part[part["quintile"] == "Q5"]["forward_return"]
        grouped.append((float(q1_part.sum()), int(q1_part.count()), float(q5_part.sum()), int(q5_part.count())))
    if not grouped:
        return np.full(n_runs, np.nan)
    arr = np.asarray(grouped, dtype=float)
    sample_idx = rng.integers(0, len(arr), size=(n_runs, len(arr)))
    sampled = arr[sample_idx]
    q1_sum = sampled[:, :, 0].sum(axis=1)
    q1_count = sampled[:, :, 1].sum(axis=1)
    q5_sum = sampled[:, :, 2].sum(axis=1)
    q5_count = sampled[:, :, 3].sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return ((q5_sum / q5_count) - (q1_sum / q1_count)) * direction


def distribution_stats(values: np.ndarray, direction: int) -> dict[str, float]:
    clean = values[np.isfinite(values)]
    if len(clean) == 0:
        return {"mean": np.nan, "p05": np.nan, "p50": np.nan, "p95": np.nan, "positive_rate": np.nan, "same_direction_rate": np.nan}
    positive_rate = float(np.mean(clean > 0))
    return {
        "mean": float(np.mean(clean)),
        "p05": float(np.quantile(clean, 0.05)),
        "p50": float(np.quantile(clean, 0.50)),
        "p95": float(np.quantile(clean, 0.95)),
        "positive_rate": positive_rate,
        "same_direction_rate": positive_rate if direction else np.nan,
    }


def bootstrap_status(ordinary_rate: float, monthly_rate: float, quarterly_rate: float) -> str:
    if any(pd.isna(x) for x in [ordinary_rate, monthly_rate, quarterly_rate]):
        return "invalid_or_sparse"
    if ordinary_rate >= 0.70 and monthly_rate >= 0.60 and quarterly_rate >= 0.60:
        return "robust_candidate"
    if ordinary_rate >= 0.70:
        return "fragile_time_block"
    return "fragile_event_sample"


def factor_bootstrap_summary(
    events: pd.DataFrame,
    candidates: pd.DataFrame,
    n_runs: int,
    random_seed: int,
) -> pd.DataFrame:
    events = add_time_groups(events)
    events["month_group"] = pd.to_datetime(events["signal_time"], utc=True).dt.strftime("%Y-%m")
    rows = []
    for _, candidate in candidates.iterrows():
        factor = candidate["factor"]
        horizon = int(candidate["horizon"])
        direction = int(candidate["direction"])
        original_edge = float(candidate["observed_q5_minus_q1"])
        stats_by_method = {}
        for method in ["ordinary", "monthly", "quarterly"]:
            dist = edge_distribution(events, factor, horizon, direction, method, n_runs, random_seed)
            stats_by_method[method] = distribution_stats(dist, direction)
        rows.append({
            "factor": factor,
            "common": candidate.get("common", ""),
            "family": candidate.get("family", "unmapped"),
            "role": candidate.get("role", "unmapped"),
            "horizon": horizon,
            "direction": direction,
            "original_q5_minus_q1": original_edge,
            "ordinary_bootstrap_mean": stats_by_method["ordinary"]["mean"],
            "ordinary_bootstrap_p05": stats_by_method["ordinary"]["p05"],
            "ordinary_bootstrap_p50": stats_by_method["ordinary"]["p50"],
            "ordinary_bootstrap_p95": stats_by_method["ordinary"]["p95"],
            "ordinary_positive_rate": stats_by_method["ordinary"]["positive_rate"],
            "ordinary_same_direction_rate": stats_by_method["ordinary"]["same_direction_rate"],
            "monthly_bootstrap_mean": stats_by_method["monthly"]["mean"],
            "monthly_bootstrap_p05": stats_by_method["monthly"]["p05"],
            "monthly_bootstrap_p50": stats_by_method["monthly"]["p50"],
            "monthly_bootstrap_p95": stats_by_method["monthly"]["p95"],
            "monthly_positive_rate": stats_by_method["monthly"]["positive_rate"],
            "monthly_same_direction_rate": stats_by_method["monthly"]["same_direction_rate"],
            "quarterly_bootstrap_mean": stats_by_method["quarterly"]["mean"],
            "quarterly_bootstrap_p05": stats_by_method["quarterly"]["p05"],
            "quarterly_bootstrap_p50": stats_by_method["quarterly"]["p50"],
            "quarterly_bootstrap_p95": stats_by_method["quarterly"]["p95"],
            "quarterly_positive_rate": stats_by_method["quarterly"]["positive_rate"],
            "quarterly_same_direction_rate": stats_by_method["quarterly"]["same_direction_rate"],
            "bootstrap_status": bootstrap_status(
                stats_by_method["ordinary"]["same_direction_rate"],
                stats_by_method["monthly"]["same_direction_rate"],
                stats_by_method["quarterly"]["same_direction_rate"],
            ),
        })
    return pd.DataFrame(rows)


def top_contribution(frame: pd.DataFrame, key: str) -> float:
    contributions = frame.groupby(key)["directional_edge"].sum().abs()
    total = contributions.sum()
    if total == 0 or pd.isna(total):
        return np.nan
    return float(contributions.max() / total)


def family_bootstrap_summary(factor_summary: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, family_row in queue.iterrows():
        family = family_row["family"]
        role = family_row["role"]
        part = factor_summary[factor_summary["family"] == family].copy()
        if part.empty:
            rows.append({
                "family": family,
                "role": role,
                "factor_count": 0,
                "factor_horizon_count": 0,
                "horizon_count": 0,
                "member_factors": "",
                "mean_directional_edge": np.nan,
                "ordinary_same_direction_rate": np.nan,
                "monthly_same_direction_rate": np.nan,
                "quarterly_same_direction_rate": np.nan,
                "top_factor_contribution": np.nan,
                "top_horizon_contribution": np.nan,
                "family_bootstrap_status": "family_invalid_or_sparse",
            })
            continue
        part["directional_edge"] = part["original_q5_minus_q1"] * part["direction"]
        top_factor = top_contribution(part, "factor")
        top_horizon = top_contribution(part, "horizon")
        ordinary = float(part["ordinary_same_direction_rate"].mean())
        monthly = float(part["monthly_same_direction_rate"].mean())
        quarterly = float(part["quarterly_same_direction_rate"].mean())
        if top_factor > 0.60 or top_horizon > 0.60:
            status = "family_concentrated"
        elif monthly < 0.60 or quarterly < 0.60:
            status = "family_time_fragile"
        elif ordinary >= 0.70:
            status = "family_robust_candidate"
        else:
            status = "family_invalid_or_sparse"
        rows.append({
            "family": family,
            "role": role,
            "factor_count": int(part["factor"].nunique()),
            "factor_horizon_count": int(len(part)),
            "horizon_count": int(part["horizon"].nunique()),
            "member_factors": ";".join(sorted(part["factor"].unique())),
            "mean_directional_edge": float(part["directional_edge"].mean()),
            "ordinary_same_direction_rate": ordinary,
            "monthly_same_direction_rate": monthly,
            "quarterly_same_direction_rate": quarterly,
            "top_factor_contribution": top_factor,
            "top_horizon_contribution": top_horizon,
            "family_bootstrap_status": status,
        })
    return pd.DataFrame(rows)


def edge_on_subset(events: pd.DataFrame, factor: str, horizon: int, direction: int, drop_months: Iterable[str] = (), repeat_months: Iterable[str] = (), drop_quarters: Iterable[str] = ()) -> float:
    data = labeled_factor_events(events, factor, horizon)
    if drop_months:
        data = data[~data["month_group"].isin(list(drop_months))]
    if drop_quarters:
        data = data[~data["quarter_group"].isin(list(drop_quarters))]
    if repeat_months:
        repeats = [data[data["month_group"] == month] for month in repeat_months]
        repeats = [part for part in repeats if not part.empty]
        if repeats:
            data = pd.concat([data, *repeats], ignore_index=True)
    return edge_from_labeled(data, direction)


def month_stress_summary(events: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    events = add_time_groups(events)
    events["month_group"] = pd.to_datetime(events["signal_time"], utc=True).dt.strftime("%Y-%m")
    rows = []
    for _, candidate in candidates.iterrows():
        factor = candidate["factor"]
        horizon = int(candidate["horizon"])
        direction = int(candidate["direction"])
        labeled = labeled_factor_events(events, factor, horizon)
        months = sorted(labeled["month_group"].dropna().unique())
        quarters = sorted(labeled["quarter_group"].dropna().unique())
        if not months:
            status = "invalid_or_sparse"
            rows.append({"factor": factor, "family": candidate.get("family", ""), "horizon": horizon, "original_edge": np.nan, "remove_best_1_month_edge": np.nan, "remove_best_2_month_edge": np.nan, "remove_best_quarter_edge": np.nan, "repeat_worst_1_month_edge": np.nan, "repeat_worst_2_month_edge": np.nan, "stress_status": status})
            continue
        original = factor_edge(events, factor, horizon, direction)
        remove_month_edges = [(month, edge_on_subset(events, factor, horizon, direction, drop_months=[month])) for month in months]
        remove_month_df = pd.DataFrame(remove_month_edges, columns=["month", "edge"]).dropna().sort_values("edge")
        best_months = remove_month_df["month"].head(2).tolist()
        repeat_month_edges = [(month, edge_on_subset(events, factor, horizon, direction, repeat_months=[month])) for month in months]
        repeat_month_df = pd.DataFrame(repeat_month_edges, columns=["month", "edge"]).dropna().sort_values("edge")
        worst_months = repeat_month_df["month"].head(2).tolist()
        remove_quarter_edges = [(quarter, edge_on_subset(events, factor, horizon, direction, drop_quarters=[quarter])) for quarter in quarters]
        quarter_df = pd.DataFrame(remove_quarter_edges, columns=["quarter", "edge"]).dropna().sort_values("edge")
        best_quarter = quarter_df["quarter"].head(1).tolist()
        remove_best_1 = edge_on_subset(events, factor, horizon, direction, drop_months=best_months[:1])
        remove_best_2 = edge_on_subset(events, factor, horizon, direction, drop_months=best_months[:2])
        remove_best_q = edge_on_subset(events, factor, horizon, direction, drop_quarters=best_quarter)
        repeat_worst_1 = edge_on_subset(events, factor, horizon, direction, repeat_months=worst_months[:1])
        repeat_worst_2 = edge_on_subset(events, factor, horizon, direction, repeat_months=worst_months[:2])
        if any(pd.isna(x) for x in [original, remove_best_1, remove_best_2, remove_best_q, repeat_worst_1, repeat_worst_2]):
            status = "invalid_or_sparse"
        elif remove_best_1 <= 0 or remove_best_2 <= 0:
            status = "best_month_dependent"
        elif remove_best_q <= 0:
            status = "best_quarter_dependent"
        elif repeat_worst_1 <= 0 or repeat_worst_2 <= 0:
            status = "worst_month_fragile"
        else:
            status = "stress_survives"
        rows.append({
            "factor": factor,
            "family": candidate.get("family", ""),
            "horizon": horizon,
            "original_edge": original,
            "remove_best_1_month_edge": remove_best_1,
            "remove_best_2_month_edge": remove_best_2,
            "remove_best_quarter_edge": remove_best_q,
            "repeat_worst_1_month_edge": repeat_worst_1,
            "repeat_worst_2_month_edge": repeat_worst_2,
            "stress_status": status,
        })
    return pd.DataFrame(rows)


def horizon_decay_summary(factor_summary: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, family_row in queue.iterrows():
        family = family_row["family"]
        role = family_row["role"]
        part = factor_summary[factor_summary["family"] == family].copy()
        if part.empty:
            rows.append({"family": family, "role": role, "horizons_available": "", "direction_consistent": False, "best_horizon": np.nan, "best_horizon_contribution": np.nan, "decay_pattern": "invalid_or_sparse"})
            continue
        part["directional_edge"] = part["original_q5_minus_q1"] * part["direction"]
        by_h = part.groupby("horizon")["directional_edge"].mean()
        signs = by_h.apply(sign_or_zero)
        direction_consistent = bool(len(set(signs[signs != 0])) <= 1)
        abs_by_h = by_h.abs()
        best_h = int(abs_by_h.idxmax())
        contribution = float(abs_by_h.max() / abs_by_h.sum()) if abs_by_h.sum() else np.nan
        horizons = sorted(int(x) for x in by_h.index)
        if not direction_consistent:
            pattern = "horizon_reversal"
        elif contribution > 0.60:
            pattern = "single_horizon_dependent"
        elif max(horizons) <= 8:
            pattern = "short_horizon_only"
        elif min(horizons) >= 16:
            pattern = "long_horizon_only"
        else:
            pattern = "stable_across_horizons"
        rows.append({
            "family": family,
            "role": role,
            "horizons_available": ";".join(map(str, horizons)),
            "direction_consistent": direction_consistent,
            "best_horizon": best_h,
            "best_horizon_contribution": contribution,
            "decay_pattern": pattern,
        })
    return pd.DataFrame(rows)


def role_classification(family_summary: pd.DataFrame, decay: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
    rows = []
    family_summary = family_summary.set_index("family", drop=False)
    decay = decay.set_index("family", drop=False)
    for _, row in queue.iterrows():
        family = row["family"]
        initial_role = row["role"]
        source_status = row.get("status", "")
        f = family_summary.loc[family] if family in family_summary.index else None
        d = decay.loc[family] if family in decay.index else None
        if "blocked" in str(source_status) or f is None or f["family_bootstrap_status"] == "family_invalid_or_sparse":
            final_role = "blocked"
            allowed = "blocked_missing_data" if "blocked" in str(source_status) else "needs_more_data"
            reason = "No usable current factor evidence or required data is unavailable."
        elif f["family_bootstrap_status"] == "family_robust_candidate" and d is not None and d["decay_pattern"] in {"stable_across_horizons", "long_horizon_only"} and initial_role == "alpha":
            final_role = "alpha"
            allowed = "eligible_for_R6_validation"
            reason = "Family survived R5 bootstrap and horizon decay is not single-horizon dependent."
        elif initial_role == "risk":
            final_role = "risk"
            allowed = "keep_as_risk_monitor"
            reason = "Literature role is risk; preserve as monitor until alpha-vs-risk decomposition is stronger."
        elif initial_role in {"avoid", "alpha_or_avoid"}:
            final_role = "avoid"
            allowed = "keep_as_avoid_candidate"
            reason = "Evidence should be checked against MAE/tail loss before use as alpha."
        elif f["family_bootstrap_status"] == "family_concentrated":
            final_role = "alpha"
            allowed = "needs_more_data"
            reason = "Family evidence is concentrated in one factor or horizon."
        else:
            final_role = initial_role if initial_role in {"alpha", "risk", "execution"} else "blocked"
            allowed = "needs_more_data"
            reason = "Current discovery evidence is not strong enough for R6 eligibility."
        rows.append({
            "family": family,
            "initial_role": initial_role,
            "r5_evidence": f["family_bootstrap_status"] if f is not None else "family_invalid_or_sparse",
            "final_research_role": final_role,
            "reason": reason,
            "allowed_next_step": allowed,
        })
    return pd.DataFrame(rows)
