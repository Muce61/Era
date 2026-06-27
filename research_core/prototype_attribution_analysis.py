"""R7 prototype attribution helpers.

The functions in this module work at the event-label layer only. They do not
create trading rules, run position accounting, or optimize thresholds.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd


HORIZONS = [1, 4, 8, 16, 32]
PROTOTYPES = [
    "P0_ALL_TREND_CONTEXT",
    "P1_C1_FIRST_BREAKOUT",
    "P2_STRONG_BREAKOUT",
    "P3_MOMENTUM_TOP20",
    "P4_BREAKOUT_TOP20",
    "P5_MOMENTUM_AND_BREAKOUT_TOP40",
    "P6_MOMENTUM_OR_BREAKOUT_TOP20",
    "P7_C1_PLUS_MOMENTUM_TOP40",
    "P8_C1_PLUS_BREAKOUT_TOP40",
]


def prototype_masks(events: pd.DataFrame, scores: pd.DataFrame) -> dict[str, pd.Series]:
    """Return fixed R7 prototype masks aligned to ``events``."""
    c1 = events["first_breakout_after_flat"].fillna(False).astype(bool)
    strong = events["strong_breakout"].fillna(False).astype(bool)
    momentum_q = pd.to_numeric(scores["momentum_score_quantile"], errors="coerce")
    breakout_q = pd.to_numeric(scores["breakout_score_quantile"], errors="coerce")
    base = pd.Series(True, index=events.index)
    return {
        "P0_ALL_TREND_CONTEXT": base,
        "P1_C1_FIRST_BREAKOUT": c1,
        "P2_STRONG_BREAKOUT": strong,
        "P3_MOMENTUM_TOP20": momentum_q >= 0.80,
        "P4_BREAKOUT_TOP20": breakout_q >= 0.80,
        "P5_MOMENTUM_AND_BREAKOUT_TOP40": (momentum_q >= 0.60) & (breakout_q >= 0.60),
        "P6_MOMENTUM_OR_BREAKOUT_TOP20": (momentum_q >= 0.80) | (breakout_q >= 0.80),
        "P7_C1_PLUS_MOMENTUM_TOP40": c1 & (momentum_q >= 0.60),
        "P8_C1_PLUS_BREAKOUT_TOP40": c1 & (breakout_q >= 0.60),
    }


def top_positive_contribution(values: pd.Series, n: int) -> float:
    """Contribution of the top ``n`` positive events to total positive return."""
    positive = pd.to_numeric(values, errors="coerce").dropna()
    positive = positive[positive > 0].sort_values(ascending=False)
    total = positive.sum()
    if total <= 0:
        return np.nan
    return float(positive.head(n).sum() / total)


def event_summary(events: pd.DataFrame, masks: dict[str, pd.Series]) -> pd.DataFrame:
    rows = []
    for prototype in PROTOTYPES:
        part = events[masks[prototype]]
        for horizon in HORIZONS:
            ret = pd.to_numeric(part[f"fwd_ret_{horizon}"], errors="coerce")
            rows.append({
                "prototype": prototype,
                "horizon": horizon,
                "event_count": int(len(part)),
                "mean_fwd_ret": float(ret.mean()) if len(ret) else np.nan,
                "median_fwd_ret": float(ret.median()) if len(ret) else np.nan,
                "mean_mfe": float(pd.to_numeric(part[f"fwd_mfe_{horizon}"], errors="coerce").mean()) if len(part) else np.nan,
                "mean_mae": float(pd.to_numeric(part[f"fwd_mae_{horizon}"], errors="coerce").mean()) if len(part) else np.nan,
                "plus_1atr_first_rate": float(part[f"plus_1atr_first_{horizon}"].mean()) if len(part) else np.nan,
                "minus_1atr_first_rate": float(part[f"minus_1atr_first_{horizon}"].mean()) if len(part) else np.nan,
                "ambiguous_rate": float(part[f"ambiguous_touch_{horizon}"].mean()) if len(part) else np.nan,
                "top1_event_contribution": top_positive_contribution(ret, 1),
                "top5_event_contribution": top_positive_contribution(ret, 5),
                "top10_event_contribution": top_positive_contribution(ret, 10),
                "sample_status": "valid" if len(part) >= 30 else "insufficient_sample",
            })
    return pd.DataFrame(rows)


INCREMENTAL_COMPARISONS = [
    ("P3_vs_P0", "P0_ALL_TREND_CONTEXT", "P3_MOMENTUM_TOP20"),
    ("P4_vs_P0", "P0_ALL_TREND_CONTEXT", "P4_BREAKOUT_TOP20"),
    ("P5_vs_P0", "P0_ALL_TREND_CONTEXT", "P5_MOMENTUM_AND_BREAKOUT_TOP40"),
    ("P6_vs_P0", "P0_ALL_TREND_CONTEXT", "P6_MOMENTUM_OR_BREAKOUT_TOP20"),
    ("P7_vs_P1", "P1_C1_FIRST_BREAKOUT", "P7_C1_PLUS_MOMENTUM_TOP40"),
    ("P8_vs_P1", "P1_C1_FIRST_BREAKOUT", "P8_C1_PLUS_BREAKOUT_TOP40"),
    ("P4_vs_P2", "P2_STRONG_BREAKOUT", "P4_BREAKOUT_TOP20"),
    ("P8_vs_P2", "P2_STRONG_BREAKOUT", "P8_C1_PLUS_BREAKOUT_TOP40"),
]


def classify_increment(base_count: int, test_count: int, mean_diff: float, plus_diff: float, mae_improvement: float) -> str:
    if base_count < 30 or test_count < 30 or pd.isna(mean_diff):
        return "insufficient_sample"
    if mean_diff <= 0:
        return "worse_than_base" if mean_diff < 0 else "no_incremental"
    if plus_diff >= 0 and mae_improvement >= 0:
        return "clear_incremental"
    return "weak_incremental"


def incremental_attribution(summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    keyed = summary.set_index(["prototype", "horizon"])
    for comparison, base, test in INCREMENTAL_COMPARISONS:
        for horizon in HORIZONS:
            b = keyed.loc[(base, horizon)]
            t = keyed.loc[(test, horizon)]
            mean_diff = float(t["mean_fwd_ret"] - b["mean_fwd_ret"])
            plus_diff = float(t["plus_1atr_first_rate"] - b["plus_1atr_first_rate"])
            mae_improvement = float(t["mean_mae"] - b["mean_mae"])
            rows.append({
                "comparison": comparison,
                "base_prototype": base,
                "test_prototype": test,
                "horizon": horizon,
                "base_event_count": int(b["event_count"]),
                "test_event_count": int(t["event_count"]),
                "base_mean_ret": float(b["mean_fwd_ret"]),
                "test_mean_ret": float(t["mean_fwd_ret"]),
                "incremental_mean_ret": mean_diff,
                "base_plus_1atr_rate": float(b["plus_1atr_first_rate"]),
                "test_plus_1atr_rate": float(t["plus_1atr_first_rate"]),
                "incremental_plus_1atr_rate": plus_diff,
                "base_mean_mae": float(b["mean_mae"]),
                "test_mean_mae": float(t["mean_mae"]),
                "incremental_mae_improvement": mae_improvement,
                "interpretation": classify_increment(int(b["event_count"]), int(t["event_count"]), mean_diff, plus_diff, mae_improvement),
            })
    return pd.DataFrame(rows)


def add_period_columns(events: pd.DataFrame) -> pd.DataFrame:
    data = events.copy()
    ts = pd.to_datetime(data["signal_time"], utc=True)
    data["month_group"] = ts.dt.strftime("%Y-%m")
    data["quarter_group"] = ts.dt.year.astype(str) + "Q" + ts.dt.quarter.astype(str)
    return data


def period_summary(events: pd.DataFrame, masks: dict[str, pd.Series], period_col: str) -> pd.DataFrame:
    data = add_period_columns(events)
    rows = []
    for prototype in PROTOTYPES:
        part = data[masks[prototype]]
        for horizon in HORIZONS:
            for period, group in part.groupby(period_col):
                rows.append({
                    "prototype": prototype,
                    "horizon": horizon,
                    "period": period,
                    "event_count": int(len(group)),
                    "mean_fwd_ret": float(group[f"fwd_ret_{horizon}"].mean()),
                    "plus_1atr_first_rate": float(group[f"plus_1atr_first_{horizon}"].mean()),
                    "minus_1atr_first_rate": float(group[f"minus_1atr_first_{horizon}"].mean()),
                })
    return pd.DataFrame(rows)


def stability_summary(monthly: pd.DataFrame, quarterly: pd.DataFrame, min_events_per_period: int = 5) -> pd.DataFrame:
    rows = []
    for prototype in PROTOTYPES:
        for horizon in HORIZONS:
            m = monthly[(monthly["prototype"] == prototype) & (monthly["horizon"] == horizon)]
            q = quarterly[(quarterly["prototype"] == prototype) & (quarterly["horizon"] == horizon)]
            valid_m = m[m["event_count"] >= min_events_per_period]
            valid_q = q[q["event_count"] >= min_events_per_period]
            month_rate = float((valid_m["mean_fwd_ret"] > 0).mean()) if not valid_m.empty else np.nan
            quarter_rate = float((valid_q["mean_fwd_ret"] > 0).mean()) if not valid_q.empty else np.nan
            if len(valid_m) < 3 or len(valid_q) < 2:
                status = "insufficient_sample"
            elif month_rate >= 0.60 and quarter_rate >= 0.60:
                status = "stable"
            elif month_rate < 0.60:
                status = "month_fragile"
            else:
                status = "quarter_fragile"
            rows.append({
                "prototype": prototype,
                "horizon": horizon,
                "valid_month_count": int(len(valid_m)),
                "positive_month_rate": month_rate,
                "valid_quarter_count": int(len(valid_q)),
                "positive_quarter_rate": quarter_rate,
                "worst_month_ret": float(valid_m["mean_fwd_ret"].min()) if not valid_m.empty else np.nan,
                "worst_quarter_ret": float(valid_q["mean_fwd_ret"].min()) if not valid_q.empty else np.nan,
                "stability_status": status,
            })
    return pd.DataFrame(rows)


def _mean_after_removing_best_events(part: pd.DataFrame, horizon: int, count: int) -> float:
    if len(part) <= count:
        return np.nan
    ret = pd.to_numeric(part[f"fwd_ret_{horizon}"], errors="coerce").dropna().sort_values(ascending=False)
    return float(ret.iloc[count:].mean()) if len(ret) > count else np.nan


def _mean_after_removing_best_positive_fraction(part: pd.DataFrame, horizon: int, fraction: float) -> float:
    ret = pd.to_numeric(part[f"fwd_ret_{horizon}"], errors="coerce").dropna()
    positive_count = int(math.ceil((ret > 0).sum() * fraction))
    if positive_count <= 0:
        return float(ret.mean())
    remove_idx = ret[ret > 0].sort_values(ascending=False).head(positive_count).index
    kept = ret.drop(index=remove_idx)
    return float(kept.mean()) if len(kept) else np.nan


def _mean_after_removing_best_period(part: pd.DataFrame, horizon: int, period_col: str) -> float:
    if part.empty or period_col not in part.columns:
        return np.nan
    period_mean = part.groupby(period_col)[f"fwd_ret_{horizon}"].mean().dropna()
    if period_mean.empty:
        return np.nan
    best = period_mean.sort_values(ascending=False).index[0]
    kept = part[part[period_col] != best]
    return float(kept[f"fwd_ret_{horizon}"].mean()) if len(kept) else np.nan


def classify_tail_dependence(event_count: int, values: dict[str, float]) -> str:
    if event_count < 30:
        return "insufficient_sample"
    checks = [
        ("remove_best_1_event", "single_event_dependent"),
        ("remove_best_5_events", "top5_event_dependent"),
        ("remove_best_10pct_positive_events", "top10pct_dependent"),
        ("remove_best_1_month", "best_month_dependent"),
        ("remove_best_quarter", "best_quarter_dependent"),
    ]
    for key, status in checks:
        if pd.notna(values.get(key)) and values[key] <= 0:
            return status
    return "not_tail_dependent"


def tail_dependence(events: pd.DataFrame, masks: dict[str, pd.Series]) -> pd.DataFrame:
    data = add_period_columns(events)
    rows = []
    for prototype in PROTOTYPES:
        part = data[masks[prototype]]
        for horizon in HORIZONS:
            values = {
                "original_mean_ret": float(part[f"fwd_ret_{horizon}"].mean()) if len(part) else np.nan,
                "remove_best_1_event": _mean_after_removing_best_events(part, horizon, 1),
                "remove_best_5_events": _mean_after_removing_best_events(part, horizon, 5),
                "remove_best_10pct_positive_events": _mean_after_removing_best_positive_fraction(part, horizon, 0.10),
                "remove_best_1_month": _mean_after_removing_best_period(part, horizon, "month_group"),
                "remove_best_quarter": _mean_after_removing_best_period(part, horizon, "quarter_group"),
            }
            rows.append({
                "prototype": prototype,
                "horizon": horizon,
                **values,
                "tail_dependence_status": classify_tail_dependence(len(part), values),
            })
    return pd.DataFrame(rows)


def prototype_c1_overlap(events: pd.DataFrame, masks: dict[str, pd.Series], prototype: str) -> float:
    part = events[masks[prototype]]
    if part.empty:
        return np.nan
    return float(part["first_breakout_after_flat"].mean())


def decision_summary(
    event_summary_df: pd.DataFrame,
    incremental_df: pd.DataFrame,
    stability_df: pd.DataFrame,
    tail_df: pd.DataFrame,
    events: pd.DataFrame,
    masks: dict[str, pd.Series],
) -> pd.DataFrame:
    event_h16 = event_summary_df[event_summary_df["horizon"] == 16].set_index("prototype")
    stability_h16 = stability_df[stability_df["horizon"] == 16].set_index("prototype")
    tail_h16 = tail_df[tail_df["horizon"] == 16].set_index("prototype")
    inc_lookup = {
        row["test_prototype"]: row["incremental_mean_ret"]
        for _, row in incremental_df[incremental_df["horizon"] == 16].iterrows()
    }
    rows = []
    for prototype in PROTOTYPES:
        event_count = int(event_h16.loc[prototype, "event_count"])
        incremental = float(inc_lookup.get(prototype, 0.0))
        positive_month_rate = float(stability_h16.loc[prototype, "positive_month_rate"])
        tail_status = str(tail_h16.loc[prototype, "tail_dependence_status"])
        c1_rate = prototype_c1_overlap(events, masks, prototype)
        c1_high_overlap = pd.notna(c1_rate) and c1_rate >= 0.80
        if event_count < 50:
            decision = "insufficient_sample"
            next_step = "needs_more_data"
        elif prototype in {"P0_ALL_TREND_CONTEXT", "P1_C1_FIRST_BREAKOUT", "P2_STRONG_BREAKOUT"}:
            decision = "explanatory_only"
            next_step = "keep_as_explanation"
        elif c1_high_overlap:
            decision = "explanatory_only"
            next_step = "keep_as_explanation"
        elif incremental > 0 and positive_month_rate >= 0.60 and tail_status == "not_tail_dependent":
            decision = "candidate_for_R8_backtest"
            next_step = "R8_minimal_backtest"
        elif incremental > 0:
            decision = "weak_candidate"
            next_step = "needs_more_data"
        else:
            decision = "discard_for_now"
            next_step = "discard"
        rows.append({
            "prototype": prototype,
            "event_count_h16": event_count,
            "mean_ret_h16": float(event_h16.loc[prototype, "mean_fwd_ret"]),
            "incremental_vs_base_h16": incremental,
            "positive_month_rate_h16": positive_month_rate,
            "tail_dependence_status_h16": tail_status,
            "c1_overlap_rate": c1_rate,
            "decision_status": decision,
            "allowed_next_step": next_step,
        })
    return pd.DataFrame(rows)


def stage_strategy_overlap_note(repo_root: Path) -> str:
    paths = [
        "backtest_results/stage2/stage2_conclusion.md",
        "backtest_results/stage3/stage3_conclusion.md",
        "backtest_results/stage4/stage4_conclusion.md",
        "backtest_results/stage4/available_history/C1/trades.csv",
    ]
    rows = []
    for rel in paths:
        path = repo_root / rel
        rows.append(f"- `{rel}`: {'available' if path.exists() else 'unavailable'}")
    return "\n".join([
        "# R7 Stage Strategy Overlap Note",
        "",
        "R7 prototypes are event-label research objects, not executable trading strategies.",
        "",
        "## Source Availability",
        "",
        *rows,
        "",
        "## Answers",
        "",
        "1. 当前 prototype 更接近 Donchian55 + EMA50/200 趋势背景事件，不是 B3 Hikkake 形态。",
        "2. P1/P7/P8 明确与 C1 FIRST_BREAKOUT 相关；P3/P4/P5/P6 用 family score 描述趋势背景质量。",
        "3. C1 已有交易结果需要在 R8 最小回测中与 prototype forward return 再核对；R7 不做交易会计。",
        "4. 有必要在 R8 做真实交易回测，但只能验证候选原型，不允许宣称 OOS。",
        "5. 当前全部结果仍只能作为 discovery 研究候选。",
        "",
    ])
