"""Strict S2.7 validation for the IDLE_MR1 post-P4-exit window."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from research_core.common import RESEARCH_ROOT
from research_core.event_table import HORIZONS, load_ohlcv_1m
from research_core.second_alpha_source_s2.candidate_event_study_s2 import (
    IDLE_CANDIDATE,
    SYMBOLS,
    EventConfigS2,
    build_candidate_events_s2,
    build_market_state_pool_s2,
    top_positive_contribution,
)


S2_DIR = RESEARCH_ROOT / "second_alpha_source_s2"
S26_DIR = RESEARCH_ROOT / "second_alpha_source_s26"
S27_DIR = RESEARCH_ROOT / "second_alpha_source_s27"
DATA_ROOT_1Y = Path("/Users/muce/1m_data/new_backtest_data_1year_1m")
LONG_HISTORY_ROOT = Path("/Users/muce/1m_data/long_history_1m/merged")
START_UTC = pd.Timestamp("2024-12-01 00:00:00+00:00")
END_UTC = pd.Timestamp("2026-06-28 01:05:00+00:00")
EXIT_BUCKET = "after_p4_exit_5_16_bars"
NEIGHBOR_BUCKETS = [
    "after_p4_exit_0_4_bars",
    "after_p4_exit_5_16_bars",
    "after_p4_exit_17_64_bars",
    "deep_idle",
]
RANDOM_SEED = 20260624
HORIZON = 16


def load_events() -> pd.DataFrame:
    path = S2_DIR / "candidate_event_table.parquet"
    if not path.exists():
        return pd.DataFrame()
    events = pd.read_parquet(path)
    for col in ["signal_time", "execution_time"]:
        events[col] = pd.to_datetime(events[col], utc=True)
    events["month"] = events["signal_time"].dt.to_period("M").astype(str)
    events["quarter"] = events["signal_time"].dt.to_period("Q").astype(str)
    events["bars_since_p4_exit_bucket"] = events["p4_state_bucket"]
    return events


def input_validation() -> pd.DataFrame:
    canonical_path = S2_DIR / "candidate_event_table.parquet"
    s26_decision_path = S26_DIR / "exit_window_decision_summary.csv"
    s26_validation_path = S26_DIR / "canonical_s2_validation.csv"
    canonical_exists = canonical_path.exists()
    s26_exists = s26_decision_path.exists() and s26_validation_path.exists()
    s26_decision = ""
    idle_held = np.nan
    event_count = np.nan
    mean_16 = np.nan
    if s26_exists:
        decision = pd.read_csv(s26_decision_path)
        validation = pd.read_csv(s26_validation_path)
        s26_decision = str(decision.get("decision_letter", pd.Series([""])).iloc[0])
        idle_held = int(validation.get("idle_mr1_p4_held_count", pd.Series([999])).iloc[0])
        event_count = int(decision.get("event_count", pd.Series([0])).iloc[0])
        mean_16 = float(decision.get("mean_fwd_ret_16", pd.Series([np.nan])).iloc[0])
    passed = canonical_exists and s26_exists and idle_held == 0 and s26_decision == "A" and event_count >= 300
    return pd.DataFrame([{
        "canonical_s2_exists": bool(canonical_exists),
        "s26_exists": bool(s26_exists),
        "s26_decision": s26_decision,
        "idle_mr1_p4_held_count": idle_held,
        "s26_event_count": event_count,
        "s26_mean_fwd_ret_16": mean_16,
        "input_validation_status": "pass" if passed else "blocked",
    }])


def idle_events(events: pd.DataFrame) -> pd.DataFrame:
    return events[events["candidate"] == IDLE_CANDIDATE].copy()


def target_events(events: pd.DataFrame) -> pd.DataFrame:
    return idle_events(events)[idle_events(events)["p4_state_bucket"] == EXIT_BUCKET].copy()


def _remove_top_mean(part: pd.DataFrame, n: int, col: str = "fwd_ret_16") -> float:
    vals = part[col].dropna().sort_values(ascending=False)
    return float(vals.iloc[n:].mean()) if len(vals) > n else np.nan


def _summary(part: pd.DataFrame, extra: dict | None = None) -> dict:
    extra = extra or {}
    row = {**extra, "event_count": int(len(part))}
    for h in HORIZONS:
        row[f"mean_fwd_ret_{h}"] = part[f"fwd_ret_{h}"].mean()
    row.update({
        "median_fwd_ret_16": part["fwd_ret_16"].median(),
        "plus_1atr_first_rate_16": part["plus_1atr_first_16"].mean(),
        "minus_1atr_first_rate_16": part["minus_1atr_first_16"].mean(),
        "mean_mae_16": part["fwd_mae_16"].mean(),
        "mean_mfe_16": part["fwd_mfe_16"].mean(),
        "top1_positive_contribution": top_positive_contribution(part["fwd_ret_16"], 1),
        "remove_top3_mean_fwd_ret": _remove_top_mean(part, 3),
    })
    return row


def neighbor_comparison(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    idle = idle_events(events)
    for bucket in NEIGHBOR_BUCKETS:
        rows.append(_summary(idle[idle["p4_state_bucket"] == bucket], {"p4_state_bucket": bucket}))
    return pd.DataFrame(rows)


def direction_symbol_matrix(events: pd.DataFrame) -> pd.DataFrame:
    target = target_events(events)
    rows = []
    for keys, part in target.groupby(["symbol", "side"], dropna=False):
        rows.append(_summary(part, {"symbol": keys[0], "side": keys[1]}))
    return pd.DataFrame(rows)


def period_stability(events: pd.DataFrame, period_col: str) -> tuple[pd.DataFrame, dict]:
    target = target_events(events)
    rows = []
    for period, part in target.groupby(period_col, dropna=False):
        row = _summary(part, {"period": period})
        row["positive_period"] = bool(row["mean_fwd_ret_16"] > 0)
        rows.append(row)
    out = pd.DataFrame(rows).sort_values("period") if rows else pd.DataFrame()
    if out.empty:
        return out, {
            f"positive_{period_col}_rate": np.nan,
            f"worst_{period_col}_mean": np.nan,
            f"max_consecutive_negative_{period_col}s": np.nan,
        }
    neg_run = 0
    max_neg = 0
    for is_pos in out["positive_period"]:
        neg_run = 0 if is_pos else neg_run + 1
        max_neg = max(max_neg, neg_run)
    return out, {
        f"positive_{period_col}_rate": float(out["positive_period"].mean()),
        f"worst_{period_col}_mean": float(out["mean_fwd_ret_16"].min()),
        f"max_consecutive_negative_{period_col}s": int(max_neg),
    }


def random_direction_baseline(events: pd.DataFrame, runs: int = 1000, seed: int = RANDOM_SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    target = target_events(events)
    vals = target["fwd_ret_16"].dropna().to_numpy(float)
    if len(vals) == 0:
        return pd.DataFrame([{"observed_mean": np.nan, "random_runs": 0}])
    sims = []
    for _ in range(runs):
        signs = rng.choice(np.array([1.0, -1.0]), size=len(vals), replace=True)
        sims.append(float(np.mean(vals * signs)))
    sims = np.asarray(sims)
    observed = float(np.mean(vals))
    return pd.DataFrame([{
        "observed_mean": observed,
        "random_direction_mean": float(np.mean(sims)),
        "random_p05": float(np.percentile(sims, 5)),
        "random_p50": float(np.percentile(sims, 50)),
        "random_p95": float(np.percentile(sims, 95)),
        "percentile_vs_random_direction": float((np.sum(sims <= observed) + 1) / (len(sims) + 1)),
        "random_runs": int(len(sims)),
    }])


def build_strict_market_pool(symbols: list[str] | None = None, config: EventConfigS2 = EventConfigS2()) -> pd.DataFrame:
    pools = []
    for symbol in symbols or SYMBOLS:
        path = DATA_ROOT_1Y / f"{symbol}.csv"
        if not path.exists():
            continue
        data = load_ohlcv_1m(path)
        data = data[(data.index >= START_UTC) & (data.index <= END_UTC)].copy()
        pool = build_market_state_pool_s2(data, symbol, config, horizon=HORIZON)
        if pool.empty:
            continue
        pool["month"] = pd.to_datetime(pool["signal_time"], utc=True).dt.to_period("M").astype(str)
        pool["bars_since_p4_exit_bucket"] = pool["p4_state_bucket"]
        pools.append(pool)
    return pd.concat(pools, ignore_index=True) if pools else pd.DataFrame()


def random_time_baseline(events: pd.DataFrame, pool: pd.DataFrame, runs: int = 3000, seed: int = RANDOM_SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    target = target_events(events)
    if target.empty or pool.empty:
        return pd.DataFrame([{"event_count": int(len(target)), "random_runs": 0, "fallback_match_rate": np.nan}])
    primary_cols = [
        "symbol", "side", "month", "volatility_regime", "trend_strength_bucket",
        "p4_state_bucket", "bars_since_p4_exit_bucket",
    ]
    fallback_cols = ["symbol", "side", "volatility_regime", "trend_strength_bucket", "p4_state_bucket"]
    primary_lookup = {
        key: g["fwd_ret_16"].dropna().to_numpy(float)
        for key, g in pool.groupby(primary_cols, observed=True, dropna=False)
    }
    fallback_lookup = {
        key: g["fwd_ret_16"].dropna().to_numpy(float)
        for key, g in pool.groupby(fallback_cols, observed=True, dropna=False)
    }
    match_sets = []
    fallback_count = 0
    for _, event in target.iterrows():
        pkey = tuple(event.get(c) for c in primary_cols)
        fkey = tuple(event.get(c) for c in fallback_cols)
        vals = primary_lookup.get(pkey)
        fallback = False
        if vals is None or len(vals) == 0:
            vals = fallback_lookup.get(fkey)
            fallback = True
        if vals is not None and len(vals) > 0:
            match_sets.append(vals)
            fallback_count += int(fallback)
    sims = []
    for _ in range(runs):
        sample = [float(vals[int(rng.integers(0, len(vals)))]) for vals in match_sets]
        if sample:
            sims.append(float(np.mean(sample)))
    sims = np.asarray(sims)
    observed = float(target["fwd_ret_16"].mean())
    return pd.DataFrame([{
        "event_count": int(len(target)),
        "observed_mean": observed,
        "random_mean": float(np.mean(sims)) if len(sims) else np.nan,
        "random_p05": float(np.percentile(sims, 5)) if len(sims) else np.nan,
        "random_p50": float(np.percentile(sims, 50)) if len(sims) else np.nan,
        "random_p95": float(np.percentile(sims, 95)) if len(sims) else np.nan,
        "percentile_vs_random_time": float((np.sum(sims <= observed) + 1) / (len(sims) + 1)) if len(sims) else np.nan,
        "matched_event_count": int(len(match_sets)),
        "fallback_match_rate": float(fallback_count / len(target)) if len(target) else np.nan,
        "random_runs": int(len(sims)),
    }])


def top_trade_dependency(events: pd.DataFrame) -> pd.DataFrame:
    target = target_events(events)
    vals = target["fwd_ret_16"].dropna().sort_values(ascending=False)
    return pd.DataFrame([{
        "event_count": int(len(target)),
        "top1_positive_contribution": top_positive_contribution(vals, 1),
        "top3_positive_contribution": top_positive_contribution(vals, 3),
        "top5_positive_contribution": top_positive_contribution(vals, 5),
        "remove_top1_mean_fwd_ret": vals.iloc[1:].mean() if len(vals) > 1 else np.nan,
        "remove_top3_mean_fwd_ret": vals.iloc[3:].mean() if len(vals) > 3 else np.nan,
        "remove_top5_mean_fwd_ret": vals.iloc[5:].mean() if len(vals) > 5 else np.nan,
    }])


def long_history_check(config: EventConfigS2 = EventConfigS2()) -> pd.DataFrame:
    if not LONG_HISTORY_ROOT.exists():
        return pd.DataFrame([{"long_history_status": "unavailable"}])
    rows = []
    for symbol in SYMBOLS:
        path = LONG_HISTORY_ROOT / f"{symbol}.csv"
        if not path.exists():
            rows.append({"symbol": symbol, "long_history_status": "unavailable", "sample_status": "missing_symbol"})
            continue
        data = load_ohlcv_1m(path)
        events, _ = build_candidate_events_s2(data, symbol, config)
        target = events[(events["candidate"] == IDLE_CANDIDATE) & (events["p4_state_bucket"] == EXIT_BUCKET)].copy()
        if target.empty:
            rows.append({"symbol": symbol, "long_history_status": "available", "event_count": 0, "sample_status": "insufficient_sample"})
            continue
        target["year"] = pd.to_datetime(target["signal_time"], utc=True).dt.year
        for year, part in target.groupby("year"):
            rows.append({
                "symbol": symbol,
                "year": int(year),
                "event_count": int(len(part)),
                "mean_fwd_ret_16": part["fwd_ret_16"].mean(),
                "plus_1atr_first_rate_16": part["plus_1atr_first_16"].mean(),
                "minus_1atr_first_rate_16": part["minus_1atr_first_16"].mean(),
                "sample_status": "valid" if len(part) >= 30 else "insufficient_sample",
                "data_layer": "expanded_discovery_long_history",
                "oos_status": "not_oos",
                "long_history_status": "available",
            })
    return pd.DataFrame(rows)


def p4_monthly_proxy() -> pd.DataFrame:
    candidates = [
        RESEARCH_ROOT / "rb2_low_leverage_portfolio" / "rb2_monthly_summary.csv",
        RESEARCH_ROOT / "realistic_replay_4_symbol" / "realistic_monthly_summary.csv",
    ]
    for path in candidates:
        if path.exists():
            frame = pd.read_csv(path)
            return frame
    return pd.DataFrame()


def p4_correlation(events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    target = target_events(events).copy()
    target["month"] = target["signal_time"].dt.to_period("M").astype(str)
    p4 = p4_monthly_proxy()
    corr_rows = []
    overlap_rows = []
    if p4.empty:
        for symbol in sorted(target["symbol"].unique()):
            corr_rows.append({"symbol": symbol, "overlap_month_count": 0, "monthly_corr": np.nan, "corr_status": "insufficient_overlap"})
            overlap_rows.append({"symbol": symbol, "p4_negative_month_count": 0, "s27_positive_in_p4_negative_month_rate": np.nan, "both_negative_month_count": np.nan, "overlap_status": "insufficient_overlap"})
        return pd.DataFrame(corr_rows), pd.DataFrame(overlap_rows)
    p4 = p4.copy()
    if "month" not in p4.columns:
        if "period" in p4.columns:
            p4["month"] = p4["period"].astype(str)
        elif "year" in p4.columns and "quarter" in p4.columns:
            p4["month"] = p4["year"].astype(str)
    ret_col = "return" if "return" in p4.columns else "total_return" if "total_return" in p4.columns else None
    if ret_col is None:
        for symbol in sorted(target["symbol"].unique()):
            corr_rows.append({"symbol": symbol, "overlap_month_count": 0, "monthly_corr": np.nan, "corr_status": "insufficient_overlap"})
            overlap_rows.append({"symbol": symbol, "p4_negative_month_count": 0, "s27_positive_in_p4_negative_month_rate": np.nan, "both_negative_month_count": np.nan, "overlap_status": "insufficient_overlap"})
        return pd.DataFrame(corr_rows), pd.DataFrame(overlap_rows)
    for symbol, part in target.groupby("symbol"):
        s27 = part.groupby("month")["fwd_ret_16"].mean()
        p4_part = p4[p4.get("symbol", symbol) == symbol] if "symbol" in p4.columns else p4
        if "prototype" in p4_part.columns:
            p4_part = p4_part[p4_part["prototype"].astype(str).str.contains("P4", na=False)]
        p4_m = p4_part.groupby("month")[ret_col].mean()
        common = sorted(set(s27.index) & set(p4_m.index))
        if len(common) < 4:
            corr = np.nan
            status = "insufficient_overlap"
        else:
            corr = float(np.corrcoef(s27.loc[common], p4_m.loc[common])[0, 1])
            status = "low_corr" if abs(corr) < 0.3 else "medium_corr" if abs(corr) < 0.7 else "high_corr"
        p4_neg = p4_m[p4_m < 0]
        common_neg = sorted(set(s27.index) & set(p4_neg.index))
        if common_neg:
            pos_rate = float((s27.loc[common_neg] > 0).mean())
            both_neg = int(((s27.loc[common_neg] < 0) & (p4_neg.loc[common_neg] < 0)).sum())
            overlap_status = "helpful_in_p4_negative" if pos_rate >= 0.4 else "weak_in_p4_negative"
        else:
            pos_rate = np.nan
            both_neg = np.nan
            overlap_status = "insufficient_overlap"
        corr_rows.append({"symbol": symbol, "overlap_month_count": len(common), "monthly_corr": corr, "corr_status": status})
        overlap_rows.append({"symbol": symbol, "p4_negative_month_count": int(len(p4_neg)), "s27_positive_in_p4_negative_month_rate": pos_rate, "both_negative_month_count": both_neg, "overlap_status": overlap_status})
    return pd.DataFrame(corr_rows), pd.DataFrame(overlap_rows)


def stress_summary(events: pd.DataFrame) -> pd.DataFrame:
    target = target_events(events).copy()

    def row(name: str, part: pd.DataFrame, status_hint: str | None = None) -> dict:
        mean = part["fwd_ret_16"].mean() if len(part) else np.nan
        pos_sym = int((part.groupby("symbol")["fwd_ret_16"].mean() > 0).sum()) if len(part) else 0
        if len(part) < 100:
            status = "insufficient_sample"
        elif status_hint:
            status = status_hint
        elif mean >= 0 and pos_sym >= 2:
            status = "stress_pass"
        else:
            status = "stress_fail"
        return {"stress_case": name, "event_count": int(len(part)), "mean_fwd_ret_16": mean, "positive_symbol_count": pos_sym, "stress_status": status}

    rows = []
    rows.append(row("original", target))
    vals = target.sort_values("fwd_ret_16", ascending=False)
    rows.append(row("remove_best_1_event", vals.iloc[1:], "single_event_dependent" if vals.iloc[1:]["fwd_ret_16"].mean() < 0 else None))
    rows.append(row("remove_best_3_events", vals.iloc[3:], "single_event_dependent" if vals.iloc[3:]["fwd_ret_16"].mean() < 0 else None))
    rows.append(row("remove_best_5_events", vals.iloc[5:], "single_event_dependent" if vals.iloc[5:]["fwd_ret_16"].mean() < 0 else None))
    by_month = target.groupby("month")["fwd_ret_16"].mean().sort_values(ascending=False)
    if len(by_month):
        rows.append(row("remove_best_1_month", target[target["month"] != by_month.index[0]], "month_dependent" if target[target["month"] != by_month.index[0]]["fwd_ret_16"].mean() < 0 else None))
    by_quarter = target.groupby("quarter")["fwd_ret_16"].mean().sort_values(ascending=False)
    if len(by_quarter):
        rows.append(row("remove_best_quarter", target[target["quarter"] != by_quarter.index[0]], "quarter_dependent" if target[target["quarter"] != by_quarter.index[0]]["fwd_ret_16"].mean() < 0 else None))
    rows.append(row("only_ETH_BTC", target[target["symbol"].isin(["ETHUSDT", "BTCUSDT"])], "symbol_dependent" if target[target["symbol"].isin(["ETHUSDT", "BTCUSDT"])]["fwd_ret_16"].mean() < 0 else None))
    rows.append(row("only_SOL_BNB", target[target["symbol"].isin(["SOLUSDT", "BNBUSDT"])], "symbol_dependent" if target[target["symbol"].isin(["SOLUSDT", "BNBUSDT"])]["fwd_ret_16"].mean() < 0 else None))
    rows.append(row("only_long", target[target["side"] == "long"], "direction_dependent" if target[target["side"] == "long"]["fwd_ret_16"].mean() < 0 else None))
    rows.append(row("only_short", target[target["side"] == "short"], "direction_dependent" if target[target["side"] == "short"]["fwd_ret_16"].mean() < 0 else None))
    return pd.DataFrame(rows)


def decision_summary(
    input_val: pd.DataFrame,
    neighbor: pd.DataFrame,
    random_dir: pd.DataFrame,
    random_time: pd.DataFrame,
    monthly_detail: pd.DataFrame,
    quarterly_detail: pd.DataFrame,
    matrix: pd.DataFrame,
    dep: pd.DataFrame,
    stress: pd.DataFrame,
    corr: pd.DataFrame,
    overlap: pd.DataFrame,
    long_history: pd.DataFrame,
) -> pd.DataFrame:
    input_pass = input_val["input_validation_status"].iloc[0] == "pass"
    by_bucket = dict(zip(neighbor["p4_state_bucket"], neighbor["mean_fwd_ret_16"]))
    target_mean = by_bucket.get(EXIT_BUCKET, np.nan)
    better_deep = target_mean > by_bucket.get("deep_idle", np.inf)
    better_early = target_mean > by_bucket.get("after_p4_exit_0_4_bars", np.inf)
    random_time_pct = float(random_time["percentile_vs_random_time"].iloc[0]) if "percentile_vs_random_time" in random_time else np.nan
    random_dir_pct = float(random_dir["percentile_vs_random_direction"].iloc[0]) if "percentile_vs_random_direction" in random_dir else np.nan
    positive_month_rate = float((monthly_detail["positive_period"]).mean()) if not monthly_detail.empty else np.nan
    positive_quarter_rate = float((quarterly_detail["positive_period"]).mean()) if not quarterly_detail.empty else np.nan
    pos_symbols = int((matrix.groupby("symbol")["mean_fwd_ret_16"].mean() > 0).sum()) if not matrix.empty else 0
    top1 = float(dep["top1_positive_contribution"].iloc[0]) if not dep.empty else np.nan
    remove_top3 = float(dep["remove_top3_mean_fwd_ret"].iloc[0]) if not dep.empty else np.nan
    best_month_row = stress[stress["stress_case"] == "remove_best_1_month"]
    best_month_ok = (not best_month_row.empty) and float(best_month_row["mean_fwd_ret_16"].iloc[0]) >= 0
    high_corr = bool((corr["corr_status"] == "high_corr").any()) if not corr.empty else False
    p4_help = overlap["s27_positive_in_p4_negative_month_rate"].dropna()
    p4_help_rate = float(p4_help.mean()) if len(p4_help) else np.nan
    long_history_status = "not_run"
    if not long_history.empty and "mean_fwd_ret_16" in long_history.columns:
        valid = long_history[long_history.get("sample_status", "") == "valid"]
        if not valid.empty:
            long_history_status = "supports" if valid.groupby("symbol")["mean_fwd_ret_16"].mean().mean() >= 0 else "weakens"
        else:
            long_history_status = "insufficient_sample"
    pass_rules = [
        input_pass,
        better_deep,
        better_early,
        random_time_pct >= 0.80,
        random_dir_pct >= 0.70,
        positive_month_rate >= 0.60,
        positive_quarter_rate >= 0.60,
        pos_symbols >= 2,
        top1 <= 0.20,
        remove_top3 >= 0,
        best_month_ok,
        not high_corr,
        (np.isnan(p4_help_rate) or p4_help_rate >= 0.40),
        long_history_status != "weakens",
    ]
    if all(pass_rules):
        letter = "A"
    elif not input_pass:
        letter = "E"
    elif random_time_pct < 0.50 or target_mean <= 0:
        letter = "D"
    elif not better_deep or not better_early or pos_symbols < 2:
        letter = "C"
    else:
        letter = "B"
    return pd.DataFrame([{
        "input_validation_status": input_val["input_validation_status"].iloc[0],
        "target_mean_fwd_ret_16": target_mean,
        "better_than_deep_idle": better_deep,
        "better_than_after_exit_0_4": better_early,
        "random_time_percentile": random_time_pct,
        "random_direction_percentile": random_dir_pct,
        "positive_month_rate": positive_month_rate,
        "positive_quarter_rate": positive_quarter_rate,
        "positive_symbol_count": pos_symbols,
        "top1_positive_contribution": top1,
        "remove_top3_mean_fwd_ret": remove_top3,
        "best_month_removal_ok": best_month_ok,
        "has_high_p4_corr": high_corr,
        "p4_negative_month_help_rate": p4_help_rate,
        "long_history_status": long_history_status,
        "decision_letter": letter,
        "decision_status": {
            "A": "candidate_for_S3_minimal_strategy_prototype",
            "B": "weak_edge_needs_more_validation",
            "C": "window_month_direction_or_symbol_dependent",
            "D": "not_significant_vs_random_state",
            "E": "input_or_implementation_problem",
        }[letter],
        "strategy_backtest_generated": False,
        "data_layer": "expanded_discovery",
        "oos_status": "not_oos",
    }])
