"""S2.9 attribution for the after-P4-exit reversion edge.

This module is intentionally descriptive. It does not create strategy
backtests, optimize thresholds, or change the S2.8 event definition.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from research_core.common import RESEARCH_ROOT
from research_core.second_alpha_source_s2.candidate_event_study_s2 import top_positive_contribution


S28_DIR = RESEARCH_ROOT / "second_alpha_source_s28"
S29_DIR = RESEARCH_ROOT / "second_alpha_source_s29"
EVENTS_PATH = S28_DIR / "long_history_exit_window_events.parquet"
HORIZON = 16


def load_s28_inputs() -> dict[str, pd.DataFrame]:
    files = {
        "summary": "long_history_exit_window_summary.csv",
        "yearly": "long_history_yearly_summary.csv",
        "quarterly": "long_history_quarterly_summary.csv",
        "matrix": "long_history_symbol_side_matrix.csv",
        "regime": "long_history_regime_summary.csv",
        "p4_proxy": "p4_monthly_proxy.csv",
        "corr": "s28_p4_correlation.csv",
        "overlap": "s28_p4_weak_month_overlap.csv",
        "random": "s28_random_time_baseline_long_history.csv",
        "stress": "s28_stress_summary.csv",
        "decision": "s28_decision_summary.csv",
    }
    out: dict[str, pd.DataFrame] = {}
    for key, name in files.items():
        path = S28_DIR / name
        out[key] = pd.read_csv(path) if path.exists() else pd.DataFrame()
    return out


def input_validation(events_path: Path = EVENTS_PATH) -> pd.DataFrame:
    inputs = load_s28_inputs()
    s28_exists = (S28_DIR / "s28_decision_summary.csv").exists()
    events_available = events_path.exists()
    decision = ""
    if not inputs["decision"].empty:
        decision = str(inputs["decision"].get("decision_letter", pd.Series([""])).iloc[0])
    event_count = 0
    symbols = []
    if events_available:
        try:
            events = pd.read_parquet(events_path, columns=["symbol"])
            event_count = int(len(events))
            symbols = sorted(events["symbol"].dropna().unique().tolist())
        except Exception:
            events_available = False
    ok = s28_exists and events_available and decision in {"A", "B"} and event_count >= 1000 and len(symbols) >= 3
    return pd.DataFrame([{
        "s28_exists": bool(s28_exists),
        "events_available": bool(events_available),
        "s28_decision": decision,
        "event_count": event_count,
        "symbols_available": ",".join(symbols),
        "symbol_count": len(symbols),
        "input_validation_status": "pass" if ok else "blocked",
        "data_layer": "expanded_discovery_long_history",
        "oos_status": "not_oos",
    }])


def _remove_top_mean(part: pd.DataFrame, n: int, col: str = "fwd_ret_16") -> float:
    vals = part[col].dropna().sort_values(ascending=False)
    return float(vals.iloc[n:].mean()) if len(vals) > n else np.nan


def _rate(part: pd.DataFrame, col: str) -> float:
    return float(part[col].mean()) if col in part and len(part) else np.nan


def _safe_mean(part: pd.DataFrame, col: str) -> float:
    return float(part[col].mean()) if col in part and len(part) else np.nan


def _classify_symbol(row: dict) -> str:
    if row["event_count"] < 100:
        return "insufficient_sample"
    if row["mean_fwd_ret_16"] < 0:
        return "negative_mean"
    if row["p4_weak_month_positive_rate"] < 0.45:
        return "weak_p4_complement"
    if row["random_time_percentile"] < 0.70:
        return "random_baseline_weak"
    if row["mean_mae_16"] < -0.025 and abs(row["mean_mae_16"]) > row["mean_mfe_16"]:
        return "mae_too_large"
    if row["remove_top3_mean_fwd_ret"] < 0 or row["top1_positive_contribution"] > 0.20:
        return "positive_but_top_trade_dependent"
    return "positive_and_stable"


def symbol_failure_attribution(events: pd.DataFrame, random_time: pd.DataFrame, overlap: pd.DataFrame) -> pd.DataFrame:
    rows = []
    random_map = random_time.set_index("symbol")["percentile_vs_random_time"].to_dict() if not random_time.empty else {}
    weak_map = overlap.set_index("symbol")["s28_positive_in_p4_weak_month_rate"].to_dict() if not overlap.empty else {}
    neg_map = overlap.set_index("symbol")["s28_positive_in_p4_negative_month_rate"].to_dict() if not overlap.empty else {}
    for symbol, part in events.groupby("symbol", dropna=False):
        row = {
            "symbol": symbol,
            "event_count": int(len(part)),
            "mean_fwd_ret_16": _safe_mean(part, "fwd_ret_16"),
            "median_fwd_ret_16": float(part["fwd_ret_16"].median()) if len(part) else np.nan,
            "remove_top3_mean_fwd_ret": _remove_top_mean(part, 3),
            "plus_1atr_first_rate_16": _rate(part, "plus_1atr_first_16"),
            "minus_1atr_first_rate_16": _rate(part, "minus_1atr_first_16"),
            "mean_mae_16": _safe_mean(part, "fwd_mae_16"),
            "mean_mfe_16": _safe_mean(part, "fwd_mfe_16"),
            "p4_negative_month_positive_rate": float(neg_map.get(symbol, np.nan)),
            "p4_weak_month_positive_rate": float(weak_map.get(symbol, np.nan)),
            "random_time_percentile": float(random_map.get(symbol, np.nan)),
            "top1_positive_contribution": top_positive_contribution(part["fwd_ret_16"], 1),
        }
        row["failure_reason"] = _classify_symbol(row)
        rows.append(row)
    return pd.DataFrame(rows)


def _mix(series: pd.Series) -> str:
    if series.empty:
        return ""
    counts = series.astype(str).value_counts(normalize=True).head(3)
    return ";".join(f"{idx}:{val:.2f}" for idx, val in counts.items())


def _period_failure_reason(part: pd.DataFrame, positive_symbols: int, p4_ret: float) -> str:
    if len(part) < 50:
        return "insufficient_sample"
    mean = float(part["fwd_ret_16"].mean())
    if mean > 0 and positive_symbols >= 2:
        return "valid_positive_period"
    if positive_symbols == 0:
        return "broad_symbol_failure"
    if positive_symbols == 1:
        return "single_symbol_drag"
    if (part["volatility_regime"].astype(str).str.contains("high", na=False)).mean() > 0.5:
        return "high_vol_failure"
    if bool(part.get("subsequent_trend_breakout", pd.Series(False, index=part.index)).mean() > 0.5):
        return "trend_restart_failure"
    if p4_ret <= 0:
        return "p4_also_weak"
    return "single_symbol_drag"


def period_failure_attribution(events: pd.DataFrame, p4_proxy: pd.DataFrame, period_col: str) -> pd.DataFrame:
    proxy = p4_proxy.copy()
    if period_col == "year":
        proxy["period"] = proxy["month"].astype(str).str.slice(0, 4)
    else:
        month = pd.PeriodIndex(proxy["month"].astype(str), freq="M")
        proxy["period"] = month.to_timestamp().to_period("Q").astype(str)
    p4_by_period = proxy.groupby("period")["p4_proxy_return"].sum().to_dict()
    rows = []
    events = events.copy()
    events["period"] = events[period_col].astype(str)
    for period, part in events.groupby("period", dropna=False):
        by_symbol = part.groupby("symbol")["fwd_ret_16"].mean()
        positive_symbols = int((by_symbol > 0).sum())
        dominant_symbol = str(part.groupby("symbol")["fwd_ret_16"].sum().idxmax()) if len(part) else ""
        p4_ret = float(p4_by_period.get(str(period), np.nan))
        row = {
            "period": str(period),
            "event_count": int(len(part)),
            "mean_fwd_ret_16": _safe_mean(part, "fwd_ret_16"),
            "positive_symbol_count": positive_symbols,
            "dominant_symbol": dominant_symbol,
            "volatility_regime_mix": _mix(part.get("volatility_regime", pd.Series(dtype=str))),
            "trend_strength_mix": _mix(part.get("trend_strength_bucket", pd.Series(dtype=str))),
            "p4_proxy_return": p4_ret,
            "s28_return_proxy": _safe_mean(part, "fwd_ret_16"),
        }
        row["failure_reason"] = _period_failure_reason(part, positive_symbols, p4_ret)
        rows.append(row)
    return pd.DataFrame(rows)


def _classify_side(row: dict) -> str:
    if row["event_count"] < 50:
        return "insufficient_sample"
    if row["mean_fwd_ret_16"] < 0:
        return "negative_mean"
    if row["mean_mae_16"] < -0.025 and abs(row["mean_mae_16"]) > row["mean_mfe_16"]:
        return "mae_too_large"
    if row["remove_top3_mean_fwd_ret"] < 0:
        return "positive_but_top_trade_dependent"
    return "positive_and_stable"


def side_failure_attribution(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (symbol, side), part in events.groupby(["symbol", "side"], dropna=False):
        row = {
            "symbol": symbol,
            "side": side,
            "event_count": int(len(part)),
            "mean_fwd_ret_16": _safe_mean(part, "fwd_ret_16"),
            "remove_top3_mean_fwd_ret": _remove_top_mean(part, 3),
            "plus_1atr_first_rate_16": _rate(part, "plus_1atr_first_16"),
            "minus_1atr_first_rate_16": _rate(part, "minus_1atr_first_16"),
            "mean_mae_16": _safe_mean(part, "fwd_mae_16"),
            "mean_mfe_16": _safe_mean(part, "fwd_mfe_16"),
        }
        row["failure_reason"] = _classify_side(row)
        rows.append(row)
    return pd.DataFrame(rows)


def p4_exit_context_attribution(events: pd.DataFrame) -> pd.DataFrame:
    events = events.copy()
    events["bars_since_p4_exit_group"] = pd.cut(
        events["bars_since_p4_exit"].fillna(-1),
        bins=[-2, 4, 8, 12, 16, 10_000],
        labels=["unknown_or_0_4", "5_8", "9_12", "13_16", "outside"],
        right=True,
    ).astype(str)
    events["post_exit_trend_restart_within_16"] = events.get("subsequent_trend_breakout", False).astype(bool)
    events["post_exit_range_bound_within_16"] = ~events["post_exit_trend_restart_within_16"]
    rows = []
    for group, part in events.groupby("bars_since_p4_exit_group", dropna=False):
        rows.append({
            "bars_since_p4_exit": group,
            "p4_exit_reason": "donchian20_exit_proxy",
            "p4_trade_return_before_exit": np.nan,
            "p4_trade_duration_bars": np.nan,
            "p4_exit_drawdown_from_peak": np.nan,
            "event_count": int(len(part)),
            "post_exit_trend_restart_within_16": float(part["post_exit_trend_restart_within_16"].mean()) if len(part) else np.nan,
            "post_exit_range_bound_within_16": float(part["post_exit_range_bound_within_16"].mean()) if len(part) else np.nan,
            "mean_fwd_ret_16": _safe_mean(part, "fwd_ret_16"),
        })
    return pd.DataFrame(rows)


def reversion_vs_continuation_diagnostics(events: pd.DataFrame) -> pd.DataFrame:
    events = events.copy()
    events["reversion_hit"] = events.get("mean_reversion_bars").notna() if "mean_reversion_bars" in events else events["plus_1atr_first_16"].astype(bool)
    events["continuation_breakout"] = events.get("subsequent_trend_breakout", False).astype(bool)
    rows = []
    for (symbol, side), part in events.groupby(["symbol", "side"], dropna=False):
        reverted = part[part["reversion_hit"] == True]  # noqa: E712
        continued = part[part["continuation_breakout"] == True]  # noqa: E712
        rev_rate = float(part["reversion_hit"].mean()) if len(part) else np.nan
        cont_rate = float(part["continuation_breakout"].mean()) if len(part) else np.nan
        if len(part) < 50:
            diagnosis = "insufficient_sample"
        elif rev_rate >= 0.55 and cont_rate < 0.35 and part["fwd_ret_16"].mean() > 0:
            diagnosis = "true_reversion_edge"
        elif cont_rate >= 0.45 and continued["fwd_mae_16"].mean() < part["fwd_mae_16"].mean():
            diagnosis = "continuation_risk_dominates"
        else:
            diagnosis = "mixed_state"
        rows.append({
            "symbol": symbol,
            "side": side,
            "event_count": int(len(part)),
            "mean_reversion_rate_16": rev_rate,
            "continuation_breakout_rate_16": cont_rate,
            "mean_fwd_ret_when_reverted": _safe_mean(reverted, "fwd_ret_16"),
            "mean_fwd_ret_when_continued": _safe_mean(continued, "fwd_ret_16"),
            "mae_when_continued": _safe_mean(continued, "fwd_mae_16"),
            "diagnosis": diagnosis,
        })
    return pd.DataFrame(rows)


def case_samples(events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    events = events.copy()
    events["reversion_hit"] = events.get("mean_reversion_bars").notna() if "mean_reversion_bars" in events else events["plus_1atr_first_16"].astype(bool)
    events["continuation_breakout"] = events.get("subsequent_trend_breakout", False).astype(bool)
    events["p4_exit_context"] = events["p4_state_bucket"].astype(str)
    cols = [
        "event_id", "symbol", "side", "signal_time", "execution_time", "p4_exit_context",
        "bars_since_p4_exit", "trend_strength_bucket", "volatility_regime", "fwd_ret_16",
        "fwd_mae_16", "fwd_mfe_16", "reversion_hit", "continuation_breakout", "case_type",
    ]
    btc_eth = events[events["symbol"].isin(["BTCUSDT", "ETHUSDT"])]
    fail_loss = btc_eth.nsmallest(50, "fwd_ret_16").assign(case_type="btc_eth_max_loss")
    fail_mae = btc_eth.nsmallest(50, "fwd_mae_16").assign(case_type="btc_eth_max_mae")
    failures = pd.concat([fail_loss, fail_mae], ignore_index=True).drop_duplicates("event_id")
    sol_bnb = events[events["symbol"].isin(["SOLUSDT", "BNBUSDT"])]
    success_profit = sol_bnb.nlargest(50, "fwd_ret_16").assign(case_type="sol_bnb_max_profit")
    stable = sol_bnb[sol_bnb["reversion_hit"] == True].nlargest(50, "fwd_ret_16").assign(case_type="sol_bnb_stable_reversion")  # noqa: E712
    successes = pd.concat([success_profit, stable], ignore_index=True).drop_duplicates("event_id")
    return failures.reindex(columns=cols), successes.reindex(columns=cols)


def edge_explainability_summary(
    symbol_attr: pd.DataFrame,
    year_attr: pd.DataFrame,
    rev_diag: pd.DataFrame,
    overlap: pd.DataFrame,
    decision_hint: str,
) -> pd.DataFrame:
    sym_reasons = symbol_attr.set_index("symbol")["failure_reason"].to_dict() if not symbol_attr.empty else {}
    weak_rate = overlap["s28_positive_in_p4_weak_month_rate"].dropna().mean() if not overlap.empty else np.nan
    neg_rate = overlap["s28_positive_in_p4_negative_month_rate"].dropna().mean() if not overlap.empty else np.nan
    broad_fail_years = int((year_attr["failure_reason"] == "broad_symbol_failure").sum()) if not year_attr.empty else 0
    main_diag = rev_diag["diagnosis"].mode().iloc[0] if not rev_diag.empty else "insufficient_sample"
    rows = [
        {
            "question": "BTC 为什么弱",
            "answer": "BTC mean 为负，优先归因为 negative_mean；不是随机基线缺失问题时仍需降级。",
            "evidence_file": "symbol_failure_attribution.csv",
            "evidence_metric": str(sym_reasons.get("BTCUSDT", "")),
            "interpretation": "BTC 是当前候选不能直接进 S3 的核心拖累之一。",
        },
        {
            "question": "ETH 为什么不稳",
            "answer": "ETH 若 remove_top3 后接近 0 或为负，说明稳定性不足。",
            "evidence_file": "symbol_failure_attribution.csv",
            "evidence_metric": str(sym_reasons.get("ETHUSDT", "")),
            "interpretation": "ETH 可保留观察，但不能单独证明 edge。",
        },
        {
            "question": "SOL/BNB 为什么强",
            "answer": "SOL/BNB 的均值、随机基线和 P4 弱月互补性更好。",
            "evidence_file": "symbol_failure_attribution.csv",
            "evidence_metric": f"SOL={sym_reasons.get('SOLUSDT', '')};BNB={sym_reasons.get('BNBUSDT', '')}",
            "interpretation": "优势有标的集中风险，不能直接删掉 ETH/BTC 后策略化。",
        },
        {
            "question": "失败年份原因",
            "answer": "失败年份若不是全标的同时失败，则更像状态/标的混合问题。",
            "evidence_file": "year_failure_attribution.csv",
            "evidence_metric": f"broad_symbol_failure_years={broad_fail_years}",
            "interpretation": "需要先做状态分类，而不是直接回测。",
        },
        {
            "question": "是否真回归",
            "answer": "由 mean_reversion_rate 与 continuation_breakout_rate 判断。",
            "evidence_file": "reversion_vs_continuation_diagnostics.csv",
            "evidence_metric": main_diag,
            "interpretation": "如果 mixed_state 为主，下一阶段应转向 P4 exit 后状态分类。",
        },
        {
            "question": "是否与 P4 互补",
            "answer": "P4 弱/亏损月份中 S2.8 正收益比例接近或高于门槛。",
            "evidence_file": "s28_p4_weak_month_overlap.csv",
            "evidence_metric": f"neg={neg_rate:.3f};weak={weak_rate:.3f}" if not np.isnan(weak_rate) else "NA",
            "interpretation": "互补性初步成立，但还不是策略准入证据。",
        },
        {
            "question": "是否值得进入 S3",
            "answer": decision_hint,
            "evidence_file": "s29_decision_summary.csv",
            "evidence_metric": decision_hint,
            "interpretation": "S2.9 不生成策略回测。",
        },
    ]
    return pd.DataFrame(rows)


def decision_summary(
    input_val: pd.DataFrame,
    symbol_attr: pd.DataFrame,
    year_attr: pd.DataFrame,
    rev_diag: pd.DataFrame,
    overlap: pd.DataFrame,
    explainability: pd.DataFrame | None = None,
) -> pd.DataFrame:
    input_pass = input_val["input_validation_status"].iloc[0] == "pass"
    non_negative_symbols = int((symbol_attr["failure_reason"] != "negative_mean").sum()) if not symbol_attr.empty else 0
    btc_or_eth_ok = False
    if not symbol_attr.empty:
        core = symbol_attr[symbol_attr["symbol"].isin(["BTCUSDT", "ETHUSDT"])]
        btc_or_eth_ok = bool((core["failure_reason"] != "negative_mean").any())
    broad_failure = bool((year_attr["failure_reason"] == "broad_symbol_failure").any()) if not year_attr.empty else True
    continuation_main = bool((rev_diag["diagnosis"] == "continuation_risk_dominates").mean() > 0.5) if not rev_diag.empty else True
    weak_complement = bool((overlap["overlap_status"] == "weak_p4_complement").any()) if "overlap_status" in overlap else False
    if not input_pass:
        letter = "E"
    elif non_negative_symbols >= 3 and btc_or_eth_ok and not broad_failure and not continuation_main and not weak_complement:
        letter = "A"
    elif non_negative_symbols >= 3 and btc_or_eth_ok and not continuation_main:
        letter = "B"
    elif non_negative_symbols >= 2:
        letter = "C"
    else:
        letter = "D"
    status = {
        "A": "explainable_edge_candidate_for_S3",
        "B": "explainable_but_needs_S2_10_state_classification",
        "C": "localized_symbol_or_direction_edge",
        "D": "not_stably_explainable_stop_candidate",
        "E": "input_or_implementation_problem",
    }[letter]
    return pd.DataFrame([{
        "input_validation_status": input_val["input_validation_status"].iloc[0],
        "non_negative_symbol_count": non_negative_symbols,
        "btc_or_eth_not_negative": btc_or_eth_ok,
        "has_broad_symbol_failure_year": broad_failure,
        "continuation_risk_dominates_main": continuation_main,
        "weak_p4_complement": weak_complement,
        "decision_letter": letter,
        "decision_status": status,
        "strategy_backtest_generated": False,
        "data_layer": "expanded_discovery_long_history",
        "oos_status": "not_oos",
    }])

