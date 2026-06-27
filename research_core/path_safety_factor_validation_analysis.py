"""H2 path-safety factor validation helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research_core.high_leverage_path_safety_analysis import TARGET_PROTOTYPES


H2_FACTORS = [
    "range_atr",
    "atr_pct",
    "atr_pct_rank",
    "volatility_ratio_short_long",
    "atr_percentile_200",
    "prior_5m_range_pct",
    "prior_15m_range_pct",
    "prior_30m_range_pct",
    "prior_5m_return",
    "prior_15m_return",
    "prior_30m_return",
    "prior_5m_lower_wick_ratio",
    "prior_15m_lower_wick_ratio",
    "breakout_score_quantile",
    "momentum_score_quantile",
]
H2_WINDOWS = ["1m", "3m", "5m", "15m", "30m", "60m"]
BOOTSTRAP_ITERATIONS = 5000


def add_time_columns(labels: pd.DataFrame) -> pd.DataFrame:
    out = labels.copy()
    out["entry_time"] = pd.to_datetime(out["entry_time"], utc=True)
    out["month"] = out["entry_time"].dt.strftime("%Y-%m")
    return out


def top_bottom_masks(frame: pd.DataFrame, factor: str) -> tuple[pd.Series, pd.Series] | tuple[None, None]:
    if factor not in frame.columns:
        return None, None
    values = frame[factor].replace([np.inf, -np.inf], np.nan)
    valid = values.dropna()
    if len(valid) < 30 or valid.nunique() < 5:
        return None, None
    ranks = values.rank(method="first", pct=True)
    return ranks >= 0.80, ranks <= 0.20


def edge_metrics(frame: pd.DataFrame, factor: str) -> dict:
    top, bottom = top_bottom_masks(frame, factor)
    if top is None or bottom is None:
        return {"valid": False}
    safe_top = frame.loc[top, "safe_for_20x"].mean()
    safe_bottom = frame.loc[bottom, "safe_for_20x"].mean()
    mae_top = frame.loc[top, "mae_pct"].mean()
    mae_bottom = frame.loc[bottom, "mae_pct"].mean()
    liq_top = frame.loc[top, "hit_liquidation_20x"].mean()
    liq_bottom = frame.loc[bottom, "hit_liquidation_20x"].mean()
    mfe_top = frame.loc[top, "mfe_pct"].mean()
    mfe_bottom = frame.loc[bottom, "mfe_pct"].mean()
    fast_top = frame.loc[top, "fast_follow_through"].mean()
    fast_bottom = frame.loc[bottom, "fast_follow_through"].mean()
    return {
        "valid": True,
        "event_count": int(len(frame.dropna(subset=[factor]))),
        "safe20_top20": float(safe_top),
        "safe20_bottom20": float(safe_bottom),
        "safe20_edge": float(safe_top - safe_bottom),
        "mae_top20": float(mae_top),
        "mae_bottom20": float(mae_bottom),
        "mae_edge": float(mae_top - mae_bottom),
        "hit_liq20_top20": float(liq_top),
        "hit_liq20_bottom20": float(liq_bottom),
        "hit_liq20_edge": float(liq_bottom - liq_top),
        "mfe_top20": float(mfe_top),
        "mfe_bottom20": float(mfe_bottom),
        "mfe_edge": float(mfe_top - mfe_bottom),
        "fast_follow_top20": float(fast_top),
        "fast_follow_bottom20": float(fast_bottom),
        "fast_follow_edge": float(fast_top - fast_bottom),
    }


def classify_factor_role(metrics: dict) -> str:
    if not metrics.get("valid"):
        return "invalid_or_sparse"
    safety = metrics["safe20_edge"] > 0 or metrics["mae_edge"] > 0 or metrics["hit_liq20_edge"] > 0
    alpha = metrics["mfe_edge"] > 0 or metrics["fast_follow_edge"] > 0
    risk_monitor = metrics["hit_liq20_edge"] > 0 and metrics["mfe_edge"] < 0
    if risk_monitor:
        return "risk_monitor"
    if safety and alpha:
        return "dual_use_candidate"
    if safety:
        return "path_safety_only"
    if alpha:
        return "alpha_only"
    return "invalid_or_sparse"


def factor_role_decomposition(labels: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for prototype in TARGET_PROTOTYPES:
        for window in H2_WINDOWS:
            frame = labels[(labels["prototype"] == prototype) & (labels["forward_window"] == window)]
            for factor in H2_FACTORS:
                metrics = edge_metrics(frame, factor)
                if not metrics.get("valid"):
                    rows.append({
                        "factor": factor,
                        "prototype": prototype,
                        "forward_window": window,
                        "event_count": int(len(frame)),
                        "factor_role": "invalid_or_sparse",
                    })
                    continue
                rows.append({
                    "factor": factor,
                    "prototype": prototype,
                    "forward_window": window,
                    **{k: v for k, v in metrics.items() if k != "valid"},
                    "factor_role": classify_factor_role(metrics),
                })
    return pd.DataFrame(rows)


def safe20_edge(frame: pd.DataFrame, factor: str) -> float:
    metrics = edge_metrics(frame, factor)
    return float(metrics["safe20_edge"]) if metrics.get("valid") else np.nan


def fixed_group_edge(safe_values: np.ndarray, top_mask: np.ndarray, bottom_mask: np.ndarray, sample_idx: np.ndarray | None = None) -> float:
    if sample_idx is None:
        y = safe_values
        top_bool = top_mask
        bottom_bool = bottom_mask
    else:
        y = safe_values[sample_idx]
        top_bool = top_mask[sample_idx]
        bottom_bool = bottom_mask[sample_idx]
    top = y[top_bool]
    bottom = y[bottom_bool]
    if len(top) == 0 or len(bottom) == 0:
        return np.nan
    return float(np.mean(top) - np.mean(bottom))


def fixed_top_bottom_arrays(frame: pd.DataFrame, factor: str) -> tuple[np.ndarray, np.ndarray, np.ndarray] | tuple[None, None, None]:
    clean = frame.dropna(subset=[factor, "safe_for_20x"]).copy()
    if len(clean) < 30 or clean[factor].nunique() < 5:
        return None, None, None
    ranks = clean[factor].rank(method="first", pct=True).to_numpy()
    safe_values = clean["safe_for_20x"].astype(float).to_numpy()
    return clean, ranks >= 0.80, ranks <= 0.20


def bootstrap_edges(frame: pd.DataFrame, factor: str, rng: np.random.Generator, iterations: int = BOOTSTRAP_ITERATIONS) -> np.ndarray:
    clean, top_mask, bottom_mask = fixed_top_bottom_arrays(frame, factor)
    if clean is None:
        return np.array([])
    safe_values = clean["safe_for_20x"].astype(float).to_numpy()
    idx = np.arange(len(safe_values))
    samples = rng.choice(idx, size=(iterations, len(idx)), replace=True)
    sampled_safe = safe_values[samples]
    sampled_top = top_mask[samples]
    sampled_bottom = bottom_mask[samples]
    top_counts = sampled_top.sum(axis=1)
    bottom_counts = sampled_bottom.sum(axis=1)
    valid = (top_counts > 0) & (bottom_counts > 0)
    values = np.full(iterations, np.nan)
    values[valid] = (
        (sampled_safe * sampled_top).sum(axis=1)[valid] / top_counts[valid]
        - (sampled_safe * sampled_bottom).sum(axis=1)[valid] / bottom_counts[valid]
    )
    return values[np.isfinite(values)]


def block_bootstrap_edges(
    frame: pd.DataFrame,
    factor: str,
    block_col: str,
    rng: np.random.Generator,
    iterations: int = BOOTSTRAP_ITERATIONS,
) -> np.ndarray:
    clean = frame.dropna(subset=[factor, "safe_for_20x", block_col])
    if len(clean) < 30 or clean[factor].nunique() < 5 or clean[block_col].nunique() < 2:
        return np.array([])
    clean = clean.reset_index(drop=True)
    ranks = clean[factor].rank(method="first", pct=True).to_numpy()
    top_mask = ranks >= 0.80
    bottom_mask = ranks <= 0.20
    safe_values = clean["safe_for_20x"].astype(float).to_numpy()
    block_stats = []
    for idx in clean.groupby(block_col).groups.values():
        block_idx = idx.to_numpy(dtype=int)
        block_top = top_mask[block_idx]
        block_bottom = bottom_mask[block_idx]
        block_safe = safe_values[block_idx]
        block_stats.append((
            float((block_safe * block_top).sum()),
            int(block_top.sum()),
            float((block_safe * block_bottom).sum()),
            int(block_bottom.sum()),
        ))
    stats = np.asarray(block_stats, dtype=float)
    chosen = rng.choice(np.arange(len(stats)), size=(iterations, len(stats)), replace=True)
    sampled = stats[chosen]
    top_sums = sampled[:, :, 0].sum(axis=1)
    top_counts = sampled[:, :, 1].sum(axis=1)
    bottom_sums = sampled[:, :, 2].sum(axis=1)
    bottom_counts = sampled[:, :, 3].sum(axis=1)
    valid = (top_counts > 0) & (bottom_counts > 0)
    values = np.full(iterations, np.nan)
    values[valid] = (top_sums[valid] / top_counts[valid]) - (bottom_sums[valid] / bottom_counts[valid])
    return values[np.isfinite(values)]


def summarize_distribution(values: np.ndarray, prefix: str) -> dict:
    if len(values) == 0:
        return {
            f"{prefix}_mean": np.nan,
            f"{prefix}_p05": np.nan,
            f"{prefix}_p50": np.nan,
            f"{prefix}_p95": np.nan,
            f"{prefix}_positive_rate": np.nan,
        }
    return {
        f"{prefix}_mean": float(np.mean(values)),
        f"{prefix}_p05": float(np.percentile(values, 5)),
        f"{prefix}_p50": float(np.percentile(values, 50)),
        f"{prefix}_p95": float(np.percentile(values, 95)),
        f"{prefix}_positive_rate": float(np.mean(values > 0)),
    }


def bootstrap_status(ordinary: np.ndarray, monthly: np.ndarray, symbol: np.ndarray) -> str:
    if len(ordinary) == 0:
        return "invalid_or_sparse"
    ordinary_rate = float(np.mean(ordinary > 0))
    monthly_rate = float(np.mean(monthly > 0)) if len(monthly) else 0.0
    symbol_rate = float(np.mean(symbol > 0)) if len(symbol) else 0.0
    if ordinary_rate >= 0.70 and monthly_rate >= 0.60 and symbol_rate >= 0.60:
        return "robust_path_safety_candidate"
    if ordinary_rate < 0.60:
        return "event_sample_fragile"
    if monthly_rate < 0.60:
        return "time_fragile"
    if symbol_rate < 0.60:
        return "symbol_fragile"
    return "event_sample_fragile"


def path_safety_bootstrap(labels: pd.DataFrame, seed: int = 20260624) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for prototype in TARGET_PROTOTYPES:
        for window in H2_WINDOWS:
            frame = labels[(labels["prototype"] == prototype) & (labels["forward_window"] == window)]
            for factor in H2_FACTORS:
                original = safe20_edge(frame, factor)
                ordinary = bootstrap_edges(frame, factor, rng)
                monthly = block_bootstrap_edges(frame, factor, "month", rng)
                symbol = block_bootstrap_edges(frame, factor, "symbol", rng)
                rows.append({
                    "factor": factor,
                    "prototype": prototype,
                    "forward_window": window,
                    "label_edge": original,
                    **summarize_distribution(ordinary, "ordinary"),
                    **summarize_distribution(monthly, "monthly"),
                    **summarize_distribution(symbol, "symbol"),
                    "bootstrap_status": bootstrap_status(ordinary, monthly, symbol),
                })
    return pd.DataFrame(rows)


def remove_best_month(frame: pd.DataFrame, factor: str, n: int) -> pd.DataFrame:
    month_edges = []
    for month, part in frame.groupby("month"):
        edge = safe20_edge(part, factor)
        if np.isfinite(edge):
            month_edges.append((month, edge))
    remove = [m for m, _ in sorted(month_edges, key=lambda x: x[1], reverse=True)[:n]]
    return frame[~frame["month"].isin(remove)]


def repeat_worst_month(frame: pd.DataFrame, factor: str) -> pd.DataFrame:
    month_edges = []
    for month, part in frame.groupby("month"):
        edge = safe20_edge(part, factor)
        if np.isfinite(edge):
            month_edges.append((month, edge))
    if not month_edges:
        return frame
    worst = sorted(month_edges, key=lambda x: x[1])[0][0]
    return pd.concat([frame, frame[frame["month"] == worst]], ignore_index=True)


def path_safety_stress(labels: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for prototype in TARGET_PROTOTYPES:
        for window in H2_WINDOWS:
            frame = labels[(labels["prototype"] == prototype) & (labels["forward_window"] == window)].copy()
            for factor in H2_FACTORS:
                if factor not in frame.columns:
                    rows.append({"factor": factor, "prototype": prototype, "forward_window": window, "stress_status": "invalid_or_sparse"})
                    continue
                original = safe20_edge(frame, factor)
                if not np.isfinite(original):
                    rows.append({"factor": factor, "prototype": prototype, "forward_window": window, "stress_status": "invalid_or_sparse"})
                    continue
                remove_1 = safe20_edge(remove_best_month(frame, factor, 1), factor)
                remove_2 = safe20_edge(remove_best_month(frame, factor, 2), factor)
                symbol_edges = [(s, safe20_edge(part, factor)) for s, part in frame.groupby("symbol")]
                best_symbol = sorted([(s, e) for s, e in symbol_edges if np.isfinite(e)], key=lambda x: x[1], reverse=True)
                no_symbol = frame[frame["symbol"] != best_symbol[0][0]] if best_symbol else frame
                remove_symbol = safe20_edge(no_symbol, factor)
                no_top1 = frame[frame["mfe_pct"] <= frame["mfe_pct"].quantile(0.99)]
                no_top5 = frame[frame["mfe_pct"] <= frame["mfe_pct"].quantile(0.95)]
                remove_top1 = safe20_edge(no_top1, factor)
                remove_top5 = safe20_edge(no_top5, factor)
                repeat_worst = safe20_edge(repeat_worst_month(frame, factor), factor)
                if np.isfinite(remove_1) and remove_1 <= 0:
                    status = "month_dependent"
                elif np.isfinite(remove_symbol) and remove_symbol <= 0:
                    status = "symbol_dependent"
                elif (np.isfinite(remove_top1) and remove_top1 <= 0) or (np.isfinite(remove_top5) and remove_top5 <= 0):
                    status = "tail_event_dependent"
                elif np.isfinite(repeat_worst) and repeat_worst <= 0:
                    status = "worst_month_fragile"
                else:
                    status = "stress_pass"
                rows.append({
                    "factor": factor,
                    "prototype": prototype,
                    "forward_window": window,
                    "original_safe20_edge": original,
                    "remove_best_1_month": remove_1,
                    "remove_best_2_month": remove_2,
                    "remove_best_symbol": remove_symbol,
                    "remove_top1pct_mfe": remove_top1,
                    "remove_top5pct_mfe": remove_top5,
                    "repeat_worst_1_month": repeat_worst,
                    "stress_status": status,
                })
    return pd.DataFrame(rows)


def horizon_consistency(role: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for prototype in TARGET_PROTOTYPES:
        for factor in H2_FACTORS:
            part = role[(role["prototype"] == prototype) & (role["factor"] == factor)].copy()
            valid = part[part["factor_role"] != "invalid_or_sparse"]
            if valid.empty:
                rows.append({
                    "factor": factor,
                    "prototype": prototype,
                    "windows_available": 0,
                    "safe20_positive_window_count": 0,
                    "mae_positive_window_count": 0,
                    "mfe_positive_window_count": 0,
                    "direction_consistency": "invalid_or_sparse",
                    "best_window": "",
                    "window_role": "invalid_or_sparse",
                })
                continue
            safe_count = int((valid["safe20_edge"] > 0).sum())
            mae_count = int((valid["mae_edge"] > 0).sum())
            mfe_count = int((valid["mfe_edge"] > 0).sum())
            best = valid.sort_values("safe20_edge", ascending=False).iloc[0]["forward_window"]
            windows = valid["forward_window"].tolist()
            short_positive = any(w in ["1m", "3m"] for w in valid[valid["safe20_edge"] > 0]["forward_window"])
            long_positive = any(w in ["15m", "30m", "60m"] for w in valid[valid["safe20_edge"] > 0]["forward_window"])
            if safe_count == len(valid):
                consistency = "consistent_positive"
            elif safe_count == 0:
                consistency = "consistent_nonpositive"
            else:
                consistency = "mixed"
            if safe_count == 0 and mfe_count > 0:
                role_name = "alpha_mfe_only"
            elif mae_count > 0 and mfe_count == 0:
                role_name = "risk_monitor_mae_only"
            elif short_positive and not long_positive:
                role_name = "execution_risk_short_window"
            elif long_positive and safe_count >= 2:
                role_name = "path_safety_multi_window"
            elif consistency == "mixed":
                role_name = "window_reversal"
            else:
                role_name = "risk_monitor_mae_only"
            rows.append({
                "factor": factor,
                "prototype": prototype,
                "windows_available": int(len(valid)),
                "safe20_positive_window_count": safe_count,
                "mae_positive_window_count": mae_count,
                "mfe_positive_window_count": mfe_count,
                "direction_consistency": consistency,
                "best_window": best,
                "window_role": role_name,
            })
    return pd.DataFrame(rows)


def failure_case_explainability(labels: pd.DataFrame, failures: pd.DataFrame) -> pd.DataFrame:
    rows = []
    base = labels[labels["forward_window"] == "60m"].copy()
    if base.empty:
        base = labels.copy()
    failed_keys = set(zip(failures.get("prototype", []), failures.get("event_id", [])))
    base["is_failure"] = list(zip(base["prototype"], base["event_id"]))
    base["is_failure"] = base["is_failure"].isin(failed_keys)
    for prototype in TARGET_PROTOTYPES:
        frame = base[base["prototype"] == prototype].copy()
        for factor in H2_FACTORS:
            if factor not in frame.columns:
                rows.append({"factor": factor, "prototype": prototype, "explainability_status": "invalid_or_sparse"})
                continue
            top, bottom = top_bottom_masks(frame, factor)
            if top is None:
                rows.append({"factor": factor, "prototype": prototype, "explainability_status": "invalid_or_sparse"})
                continue
            metrics = edge_metrics(frame, factor)
            high_is_risk = metrics.get("safe20_edge", np.nan) < 0
            risk_mask = top if high_is_risk else bottom
            failures_part = frame[frame["is_failure"]]
            failure_count = int(len(failures_part))
            if failure_count == 0:
                status = "invalid_or_sparse"
                failure_rate = np.nan
            else:
                failure_rate = float(risk_mask.loc[failures_part.index].mean())
                status = "explains_failures" if failure_rate >= 0.35 else "weak_explanation" if failure_rate >= 0.22 else "no_explanation"
            all_rate = float(risk_mask.mean())
            lift = float(failure_rate / all_rate) if np.isfinite(failure_rate) and all_rate > 0 else np.nan
            rows.append({
                "factor": factor,
                "prototype": prototype,
                "failure_case_count": failure_count,
                "risk_direction": "high_factor_risk" if high_is_risk else "low_factor_risk",
                "failure_in_risk_quintile_rate": failure_rate,
                "all_events_in_risk_quintile_rate": all_rate,
                "lift": lift,
                "explainability_status": status,
            })
    return pd.DataFrame(rows)


def h2_decision_summary(role: pd.DataFrame, boot: pd.DataFrame, stress: pd.DataFrame, horizon: pd.DataFrame, failure: pd.DataFrame) -> pd.DataFrame:
    candidates = role[role["factor_role"].isin(["path_safety_only", "dual_use_candidate"])][["factor", "prototype"]].drop_duplicates()
    rows = []
    for _, candidate in candidates.iterrows():
        factor = candidate["factor"]
        prototype = candidate["prototype"]
        boot_ok = ((boot["factor"] == factor) & (boot["prototype"] == prototype) & (boot["bootstrap_status"] == "robust_path_safety_candidate")).any()
        stress_ok = ((stress["factor"] == factor) & (stress["prototype"] == prototype) & (stress["stress_status"] == "stress_pass")).any()
        hrow = horizon[(horizon["factor"] == factor) & (horizon["prototype"] == prototype)]
        horizon_ok = not hrow.empty and hrow.iloc[0]["window_role"] != "invalid_or_sparse"
        frow = failure[(failure["factor"] == factor) & (failure["prototype"] == prototype)]
        failure_status = frow.iloc[0]["explainability_status"] if not frow.empty else "invalid_or_sparse"
        failure_ok = failure_status in ["explains_failures", "weak_explanation"]
        eligible = boot_ok and stress_ok and horizon_ok and failure_ok
        rows.append({
            "factor": factor,
            "prototype": prototype,
            "bootstrap_ok": bool(boot_ok),
            "stress_ok": bool(stress_ok),
            "horizon_ok": bool(horizon_ok),
            "failure_explainability": failure_status,
            "decision_status": "candidate_for_H3_prototype" if eligible else "needs_more_validation",
            "allowed_next_step": "H3_minimal_gate_prototype" if eligible else "research_only",
        })
    if not rows:
        return pd.DataFrame(columns=["factor", "prototype", "decision_status", "allowed_next_step"])
    return pd.DataFrame(rows)
