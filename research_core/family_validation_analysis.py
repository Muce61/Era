"""R6 family-score validation helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd


HORIZONS = [1, 4, 8, 16, 32]
FAMILY_FACTORS = {
    "momentum_continuation": ["ret_4h", "ret_12h", "ret_24h"],
    "breakout_conviction": ["breakout_distance_atr", "range_atr", "body_ratio", "close_location"],
}
SCORE_NAMES = {
    "momentum_continuation": "momentum_continuation_score",
    "breakout_conviction": "breakout_conviction_score",
}


def winsor_bounds(series: pd.Series, lower: float = 0.01, upper: float = 0.99) -> tuple[float, float]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return np.nan, np.nan
    return float(clean.quantile(lower)), float(clean.quantile(upper))


def standardize_with_params(series: pd.Series, lower: float, upper: float, mean: float, std: float) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").clip(lower=lower, upper=upper)
    if pd.isna(std) or std == 0:
        return pd.Series(np.nan, index=series.index)
    return (values - mean) / std


def fit_factor_params(events: pd.DataFrame, factors: list[str], directions: dict[str, int]) -> pd.DataFrame:
    rows = []
    for factor in factors:
        lower, upper = winsor_bounds(events[factor])
        clipped = pd.to_numeric(events[factor], errors="coerce").clip(lower=lower, upper=upper)
        rows.append({
            "factor": factor,
            "direction": int(directions.get(factor, 1)),
            "winsor_lower": lower,
            "winsor_upper": upper,
            "mean": float(clipped.mean()),
            "std": float(clipped.std(ddof=0)),
            "missing_rate": float(events[factor].isna().mean()),
        })
    return pd.DataFrame(rows)


def factor_directions(r4_summary: pd.DataFrame) -> dict[str, int]:
    directions = {}
    for factor, part in r4_summary.groupby("factor"):
        vals = part["direction"].dropna()
        directions[factor] = int(vals.mode().iloc[0]) if not vals.empty else 1
    return directions


def compute_family_score(events: pd.DataFrame, factors: list[str], params: pd.DataFrame) -> pd.Series:
    components = []
    params = params.set_index("factor")
    for factor in factors:
        if factor not in params.index or factor not in events.columns:
            continue
        row = params.loc[factor]
        z = standardize_with_params(events[factor], row["winsor_lower"], row["winsor_upper"], row["mean"], row["std"])
        components.append(z * int(row["direction"]))
    if not components:
        return pd.Series(np.nan, index=events.index)
    return pd.concat(components, axis=1).mean(axis=1)


def score_quantile_groups(score: pd.Series) -> pd.Series:
    pct = score.rank(pct=True, method="first")
    out = pd.Series("middle20", index=score.index, dtype="object")
    out[pct <= 0.20] = "bottom20"
    out[(pct > 0.20) & (pct <= 0.40)] = "bottom40"
    out[pct > 0.80] = "top20"
    out[(pct >= 0.60) & (pct < 0.80)] = "top40"
    out[score.isna()] = "invalid"
    return out


def build_family_scores(events: pd.DataFrame, r4_summary: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    directions = factor_directions(r4_summary)
    base = events[["event_id", "signal_time", "execution_time"]].copy()
    metadata_rows = []
    for family, factors in FAMILY_FACTORS.items():
        available = [f for f in factors if f in events.columns]
        params = fit_factor_params(events, available, directions)
        for _, row in params.iterrows():
            metadata_rows.append({"family": family, "score_name": SCORE_NAMES[family], **row.to_dict()})
        score = compute_family_score(events, available, params)
        score_name = SCORE_NAMES[family]
        short = "momentum" if family == "momentum_continuation" else "breakout"
        base[score_name] = score
        base[f"{short}_score_rank"] = score.rank(method="first")
        base[f"{short}_score_quantile"] = score.rank(pct=True, method="first")
    return base, pd.DataFrame(metadata_rows)


def correlation_rows(scores: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    merged = scores.join(events[["bars_after_breakout", "ema_gap_atr", "breakout_distance_atr", "atr_pct"]])
    names = ["momentum_continuation_score", "breakout_conviction_score", "bars_after_breakout", "ema_gap_atr", "breakout_distance_atr", "atr_pct"]
    rows = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            part = merged[[a, b]].dropna()
            if part.empty:
                continue
            a_top20 = set(part[a].nlargest(max(1, int(len(part) * 0.2))).index)
            b_top20 = set(part[b].nlargest(max(1, int(len(part) * 0.2))).index)
            a_top40 = set(part[a].nlargest(max(1, int(len(part) * 0.4))).index)
            b_top40 = set(part[b].nlargest(max(1, int(len(part) * 0.4))).index)
            rows.append({
                "score_a": a,
                "score_b": b,
                "pearson_corr": float(part[a].corr(part[b], method="pearson")),
                "spearman_corr": float(part[a].corr(part[b], method="spearman")),
                "kendall_corr": float(part[a].corr(part[b], method="kendall")),
                "shared_top20_rate": len(a_top20 & b_top20) / len(a_top20),
                "shared_top40_rate": len(a_top40 & b_top40) / len(a_top40),
            })
    return pd.DataFrame(rows)


def group_summary(events: pd.DataFrame, scores: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for family, score_name in SCORE_NAMES.items():
        groups = score_quantile_groups(scores[score_name])
        for horizon in HORIZONS:
            for group in ["top20", "top40", "middle20", "bottom40", "bottom20"]:
                part = events[groups == group]
                rows.append({
                    "family": family,
                    "score_name": score_name,
                    "horizon": horizon,
                    "group": group,
                    "event_count": int(len(part)),
                    "mean_fwd_ret": float(part[f"fwd_ret_{horizon}"].mean()),
                    "median_fwd_ret": float(part[f"fwd_ret_{horizon}"].median()),
                    "mean_mfe": float(part[f"fwd_mfe_{horizon}"].mean()),
                    "mean_mae": float(part[f"fwd_mae_{horizon}"].mean()),
                    "plus_1atr_first_rate": float(part[f"plus_1atr_first_{horizon}"].mean()),
                    "minus_1atr_first_rate": float(part[f"minus_1atr_first_{horizon}"].mean()),
                    "ambiguous_rate": float(part[f"ambiguous_touch_{horizon}"].mean()),
                })
    return pd.DataFrame(rows)


def walk_forward_windows(events: pd.DataFrame, r4_summary: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = events.copy()
    data["signal_time"] = pd.to_datetime(data["signal_time"], utc=True)
    start = data["signal_time"].min().normalize()
    end = data["signal_time"].max()
    rows = []
    window_id = 0
    train_start = start
    while train_start + pd.DateOffset(months=15) <= end + pd.Timedelta(days=1):
        train_end = train_start + pd.DateOffset(months=12)
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=3)
        train = data[(data["signal_time"] >= train_start) & (data["signal_time"] < train_end)]
        test = data[(data["signal_time"] >= test_start) & (data["signal_time"] < test_end)]
        directions = factor_directions(r4_summary)
        for family, factors in FAMILY_FACTORS.items():
            params = fit_factor_params(train, [f for f in factors if f in train.columns], directions)
            score = compute_family_score(test, [f for f in factors if f in test.columns], params)
            groups = score_quantile_groups(score)
            for horizon in HORIZONS:
                top = test[groups == "top20"][f"fwd_ret_{horizon}"].dropna()
                bottom = test[groups == "bottom20"][f"fwd_ret_{horizon}"].dropna()
                sufficient = len(top) >= 10 and len(bottom) >= 10
                diff = float(top.mean() - bottom.mean()) if sufficient else np.nan
                rows.append({
                    "window_id": window_id,
                    "train_start": train_start,
                    "train_end": train_end,
                    "test_start": test_start,
                    "test_end": test_end,
                    "family": family,
                    "horizon": horizon,
                    "top20_event_count": int(len(top)),
                    "bottom20_event_count": int(len(bottom)),
                    "top20_mean_ret": float(top.mean()) if len(top) else np.nan,
                    "bottom20_mean_ret": float(bottom.mean()) if len(bottom) else np.nan,
                    "top20_minus_bottom20": diff,
                    "top20_minus_bottom20_direction": "positive" if diff > 0 else "negative" if diff <= 0 else "invalid",
                    "sample_status": "valid" if sufficient else "insufficient_sample",
                })
        train_start = train_start + pd.DateOffset(months=3)
        window_id += 1
    windows = pd.DataFrame(rows)
    summary_rows = []
    for (family, horizon), part in windows.groupby(["family", "horizon"]):
        valid = part[part["sample_status"] == "valid"]
        rate = float((valid["top20_minus_bottom20"] > 0).mean()) if not valid.empty else np.nan
        if valid.empty:
            status = "insufficient_sample"
        elif rate >= 0.60 and valid["top20_minus_bottom20"].median() > 0:
            status = "wf_pass"
        elif rate >= 0.50:
            status = "wf_weak"
        else:
            status = "wf_fail"
        summary_rows.append({
            "family": family,
            "horizon": horizon,
            "window_count": int(len(part)),
            "valid_window_count": int(len(valid)),
            "positive_window_rate": rate,
            "median_top20_minus_bottom20": float(valid["top20_minus_bottom20"].median()) if not valid.empty else np.nan,
            "worst_top20_minus_bottom20": float(valid["top20_minus_bottom20"].min()) if not valid.empty else np.nan,
            "best_top20_minus_bottom20": float(valid["top20_minus_bottom20"].max()) if not valid.empty else np.nan,
            "walk_forward_status": status,
        })
    return windows, pd.DataFrame(summary_rows)


def c1_overlap(events: pd.DataFrame, scores: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for family, score_name in SCORE_NAMES.items():
        groups = score_quantile_groups(scores[score_name])
        for group in ["top20", "top40", "middle20", "bottom40", "bottom20"]:
            part = events[groups == group]
            rows.append({
                "family": family,
                "score_group": group,
                "event_count": int(len(part)),
                "first_breakout_rate": float(part["first_breakout_after_flat"].mean()),
                "strong_breakout_rate": float(part["strong_breakout"].mean()),
                "avg_bars_after_breakout": float(part["bars_after_breakout"].mean()),
                "avg_breakout_distance_atr": float(part["breakout_distance_atr"].mean()),
                "avg_range_atr": float(part["range_atr"].mean()),
                "avg_body_ratio": float(part["body_ratio"].mean()),
                "avg_close_location": float(part["close_location"].mean()),
            })
    return pd.DataFrame(rows)


def stress_summary(events: pd.DataFrame, scores: pd.DataFrame) -> pd.DataFrame:
    data = events.copy()
    data["month_group"] = pd.to_datetime(data["signal_time"], utc=True).dt.strftime("%Y-%m")
    data["quarter_group"] = pd.to_datetime(data["signal_time"], utc=True).dt.year.astype(str) + "Q" + pd.to_datetime(data["signal_time"], utc=True).dt.quarter.astype(str)
    rows = []
    for family, score_name in SCORE_NAMES.items():
        groups = score_quantile_groups(scores[score_name])
        for horizon in HORIZONS:
            def edge(sub):
                g = groups.loc[sub.index]
                top = sub[g == "top20"][f"fwd_ret_{horizon}"].dropna()
                bottom = sub[g == "bottom20"][f"fwd_ret_{horizon}"].dropna()
                return float(top.mean() - bottom.mean()) if len(top) and len(bottom) else np.nan
            original = edge(data)
            month_edges = data.groupby("month_group").apply(edge, include_groups=False).dropna().sort_values(ascending=False)
            best_months = list(month_edges.head(2).index)
            quarter_edges = data.groupby("quarter_group").apply(edge, include_groups=False).dropna().sort_values(ascending=False)
            best_quarter = list(quarter_edges.head(1).index)
            target = f"fwd_ret_{horizon}"
            top1_cut = data[target].quantile(0.99)
            top5_cut = data[target].quantile(0.95)
            vals = {
                "remove_best_1_month": edge(data[~data["month_group"].isin(best_months[:1])]),
                "remove_best_2_month": edge(data[~data["month_group"].isin(best_months[:2])]),
                "remove_best_quarter": edge(data[~data["quarter_group"].isin(best_quarter)]),
                "remove_top1pct_events": edge(data[data[target] < top1_cut]),
                "remove_top5pct_events": edge(data[data[target] < top5_cut]),
            }
            if pd.isna(original) or any(pd.isna(v) for v in vals.values()):
                status = "invalid_or_sparse"
            elif vals["remove_top1pct_events"] <= 0 or vals["remove_top5pct_events"] <= 0:
                status = "tail_event_dependent"
            elif vals["remove_best_quarter"] <= 0:
                status = "quarter_dependent"
            elif vals["remove_best_1_month"] <= 0 or vals["remove_best_2_month"] <= 0:
                status = "month_dependent"
            elif any(v <= 0 for v in vals.values()):
                status = "stress_fail"
            else:
                status = "stress_pass"
            rows.append({"family": family, "horizon": horizon, "original_top20_minus_bottom20": original, **vals, "stress_status": status})
    return pd.DataFrame(rows)


def decision_summary(wf: pd.DataFrame, corr: pd.DataFrame, c1: pd.DataFrame, stress: pd.DataFrame) -> pd.DataFrame:
    rows = []
    mb_corr = corr[((corr["score_a"] == "momentum_continuation_score") & (corr["score_b"] == "breakout_conviction_score")) | ((corr["score_b"] == "momentum_continuation_score") & (corr["score_a"] == "breakout_conviction_score"))]
    high_corr = bool((mb_corr["spearman_corr"].abs().max() > 0.80) if not mb_corr.empty else False)
    for family in FAMILY_FACTORS:
        wf_part = wf[wf["family"] == family]
        pass_rate = float((wf_part["walk_forward_status"] == "wf_pass").mean()) if not wf_part.empty else 0.0
        stress_part = stress[stress["family"] == family]
        stress_bad = bool(stress_part["stress_status"].isin(["tail_event_dependent", "stress_fail"]).any())
        top20 = c1[(c1["family"] == family) & (c1["score_group"] == "top20")]
        c1_overlap_high = bool((top20["first_breakout_rate"].iloc[0] > 0.80) if not top20.empty else False)
        if pass_rate >= 0.60 and not stress_bad and not c1_overlap_high and not (high_corr and family == "breakout_conviction"):
            status = "eligible_for_R7_candidate_construction"
        elif c1_overlap_high or (high_corr and family == "breakout_conviction"):
            status = "explanatory_only"
        elif stress_bad:
            status = "needs_more_validation"
        else:
            status = "needs_more_validation"
        rows.append({
            "family": family,
            "wf_pass_rate": pass_rate,
            "stress_bad": stress_bad,
            "high_corr_with_other_family": high_corr,
            "top20_first_breakout_rate": float(top20["first_breakout_rate"].iloc[0]) if not top20.empty else np.nan,
            "r6_status": status,
        })
    return pd.DataFrame(rows)
