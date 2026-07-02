"""S2.8 long-history stability and P4 complement validation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from research_core.common import RESEARCH_ROOT
from research_core.event_table import add_base_indicators, load_ohlcv_1m, next_1m_open, strict_resample_15m
from research_core.second_alpha_source_s2.candidate_event_study_s2 import (
    IDLE_CANDIDATE,
    SYMBOLS,
    EventConfigS2,
    build_candidate_events_s2,
    build_market_state_pool_s2,
    top_positive_contribution,
)


S27_DIR = RESEARCH_ROOT / "second_alpha_source_s27"
S28_DIR = RESEARCH_ROOT / "second_alpha_source_s28"
LONG_HISTORY_ROOT = Path("/Users/muce/1m_data/long_history_1m/merged")
EXIT_BUCKET = "after_p4_exit_5_16_bars"
RANDOM_SEED = 20260624
HORIZON = 16


def input_validation() -> pd.DataFrame:
    s27_path = S27_DIR / "exit_window_decision_summary.csv"
    s27_exists = s27_path.exists()
    s27_decision = ""
    if s27_exists:
        s27 = pd.read_csv(s27_path)
        s27_decision = str(s27.get("decision_letter", pd.Series([""])).iloc[0])
    available = [s for s in SYMBOLS if (LONG_HISTORY_ROOT / f"{s}.csv").exists()]
    ok = s27_exists and s27_decision in {"A", "B"} and len(available) >= 3
    return pd.DataFrame([{
        "s27_exists": bool(s27_exists),
        "s27_decision": s27_decision,
        "long_history_data_available": bool(LONG_HISTORY_ROOT.exists()),
        "symbols_available": ",".join(available),
        "available_symbol_count": len(available),
        "input_validation_status": "pass" if ok else "blocked",
    }])


def build_long_history_exit_events(config: EventConfigS2 = EventConfigS2()) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    events = []
    data_by_symbol = {}
    for symbol in SYMBOLS:
        path = LONG_HISTORY_ROOT / f"{symbol}.csv"
        if not path.exists():
            continue
        data = load_ohlcv_1m(path)
        data_by_symbol[symbol] = data
        ev, _ = build_candidate_events_s2(data, symbol, config)
        target = ev[(ev["candidate"] == IDLE_CANDIDATE) & (ev["p4_state_bucket"] == EXIT_BUCKET)].copy()
        if not target.empty:
            target["year"] = pd.to_datetime(target["signal_time"], utc=True).dt.year
            target["quarter"] = pd.to_datetime(target["signal_time"], utc=True).dt.to_period("Q").astype(str)
            target["month"] = pd.to_datetime(target["signal_time"], utc=True).dt.to_period("M").astype(str)
            target["data_layer"] = "expanded_discovery_long_history"
            target["oos_status"] = "not_oos"
            target["bars_since_p4_exit_bucket"] = target["p4_state_bucket"]
            events.append(target)
    out = pd.concat(events, ignore_index=True) if events else pd.DataFrame()
    return out, data_by_symbol


def _remove_top_mean(part: pd.DataFrame, n: int, col: str = "fwd_ret_16") -> float:
    vals = part[col].dropna().sort_values(ascending=False)
    return float(vals.iloc[n:].mean()) if len(vals) > n else np.nan


def _summary(part: pd.DataFrame, extra: dict | None = None) -> dict:
    extra = extra or {}
    return {
        **extra,
        "event_count": int(len(part)),
        "mean_fwd_ret_16": part["fwd_ret_16"].mean(),
        "median_fwd_ret_16": part["fwd_ret_16"].median(),
        "plus_1atr_first_rate_16": part["plus_1atr_first_16"].mean(),
        "minus_1atr_first_rate_16": part["minus_1atr_first_16"].mean(),
        "mean_mae_16": part["fwd_mae_16"].mean(),
        "mean_mfe_16": part["fwd_mfe_16"].mean(),
        "top1_positive_contribution": top_positive_contribution(part["fwd_ret_16"], 1),
        "remove_top3_mean_fwd_ret": _remove_top_mean(part, 3),
    }


def long_history_summary(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for symbol, part in events.groupby("symbol", dropna=False):
        rows.append(_summary(part, {"symbol": symbol}))
    return pd.DataFrame(rows)


def period_summary(events: pd.DataFrame, period_col: str) -> pd.DataFrame:
    rows = []
    group_cols = ["symbol", period_col]
    for keys, part in events.groupby(group_cols, dropna=False):
        row = _summary(part, {"symbol": keys[0], period_col: keys[1]})
        row["positive_period"] = bool(row["mean_fwd_ret_16"] > 0)
        row["sample_status"] = "valid" if len(part) >= 30 else "insufficient_sample"
        if period_col == "year" and int(keys[1]) == 2026:
            row["sample_status"] = "partial_year"
        rows.append(row)
    return pd.DataFrame(rows)


def symbol_side_matrix(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, part in events.groupby(["symbol", "side"], dropna=False):
        rows.append(_summary(part, {"symbol": keys[0], "side": keys[1]}))
    return pd.DataFrame(rows)


def regime_summary(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, part in events.groupby(["symbol", "year", "volatility_regime", "trend_strength_bucket"], dropna=False):
        rows.append(_summary(part, {
            "symbol": keys[0],
            "year": keys[1],
            "volatility_regime": keys[2],
            "trend_strength_bucket": keys[3],
        }))
    return pd.DataFrame(rows)


def p4_monthly_proxy(data_by_symbol: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for symbol, data in data_by_symbol.items():
        bars = add_base_indicators(strict_resample_15m(data))
        held = False
        entry_time = None
        entry_price = None
        trades = []
        for ts, row in bars.iterrows():
            entry_cond = row["close"] > row["donchian55_upper"] and row["ema50"] > row["ema200"] and np.isfinite(row["atr14"])
            exit_cond = row["close"] < row["donchian20_lower"]
            if not held and entry_cond:
                et, ep = next_1m_open(data, ts)
                if et is not None:
                    held = True
                    entry_time = et
                    entry_price = ep
            elif held and exit_cond:
                xt, xp = next_1m_open(data, ts)
                if xt is not None and entry_price:
                    trades.append({"symbol": symbol, "exit_time": xt, "ret": xp / entry_price - 1.0})
                    held = False
                    entry_time = None
                    entry_price = None
        if held and entry_price:
            xt = data.index[-1]
            xp = float(data["close"].iloc[-1])
            trades.append({"symbol": symbol, "exit_time": xt, "ret": xp / entry_price - 1.0})
        trades_df = pd.DataFrame(trades)
        months = pd.period_range(data.index.min().to_period("M"), data.index.max().to_period("M"), freq="M")
        if trades_df.empty:
            for month in months:
                rows.append({
                    "symbol": symbol,
                    "month": str(month),
                    "p4_trade_count": 0,
                    "p4_proxy_return": 0.0,
                    "p4_negative_month": False,
                    "p4_weak_month": True,
                    "proxy_method": "realistic_p4_trade_return_1x_exit_month",
                })
            continue
        trades_df["month"] = pd.to_datetime(trades_df["exit_time"], utc=True).dt.to_period("M").astype(str)
        grouped = trades_df.groupby("month")["ret"].agg(["count", "sum"]).to_dict("index")
        for month in months:
            item = grouped.get(str(month), {"count": 0, "sum": 0.0})
            ret = float(item["sum"])
            count = int(item["count"])
            rows.append({
                "symbol": symbol,
                "month": str(month),
                "p4_trade_count": count,
                "p4_proxy_return": ret,
                "p4_negative_month": bool(ret < 0),
                "p4_weak_month": bool(ret <= 0.005 or count == 0),
                "proxy_method": "realistic_p4_trade_return_1x_exit_month",
            })
    return pd.DataFrame(rows)


def s28_monthly_proxy(events: pd.DataFrame) -> pd.DataFrame:
    return events.groupby(["symbol", "month"], dropna=False)["fwd_ret_16"].mean().reset_index(name="s28_proxy_return")


def p4_correlation(events: pd.DataFrame, p4_proxy: pd.DataFrame) -> pd.DataFrame:
    s28 = s28_monthly_proxy(events)
    rows = []
    for symbol in sorted(set(s28["symbol"]) | set(p4_proxy["symbol"])):
        a = s28[s28["symbol"] == symbol]
        b = p4_proxy[p4_proxy["symbol"] == symbol]
        merged = a.merge(b, on=["symbol", "month"], how="inner")
        corr = np.nan
        status = "insufficient_overlap"
        if len(merged) >= 12 and merged["s28_proxy_return"].std() > 0 and merged["p4_proxy_return"].std() > 0:
            corr = float(np.corrcoef(merged["s28_proxy_return"], merged["p4_proxy_return"])[0, 1])
            status = "low_corr" if abs(corr) < 0.3 else "medium_corr" if abs(corr) < 0.7 else "high_corr"
        rows.append({
            "symbol": symbol,
            "overlap_month_count": int(len(merged)),
            "s28_monthly_return_proxy": merged["s28_proxy_return"].mean() if len(merged) else np.nan,
            "p4_monthly_return_proxy": merged["p4_proxy_return"].mean() if len(merged) else np.nan,
            "monthly_corr": corr,
            "corr_status": status,
        })
    merged_all = s28.groupby("month")["s28_proxy_return"].mean().reset_index().merge(
        p4_proxy.groupby("month")["p4_proxy_return"].mean().reset_index(),
        on="month",
        how="inner",
    )
    corr = np.nan
    status = "insufficient_overlap"
    if len(merged_all) >= 12 and merged_all["s28_proxy_return"].std() > 0 and merged_all["p4_proxy_return"].std() > 0:
        corr = float(np.corrcoef(merged_all["s28_proxy_return"], merged_all["p4_proxy_return"])[0, 1])
        status = "low_corr" if abs(corr) < 0.3 else "medium_corr" if abs(corr) < 0.7 else "high_corr"
    rows.append({
        "symbol": "ALL",
        "overlap_month_count": int(len(merged_all)),
        "s28_monthly_return_proxy": merged_all["s28_proxy_return"].mean() if len(merged_all) else np.nan,
        "p4_monthly_return_proxy": merged_all["p4_proxy_return"].mean() if len(merged_all) else np.nan,
        "monthly_corr": corr,
        "corr_status": status,
    })
    return pd.DataFrame(rows)


def weak_month_overlap(events: pd.DataFrame, p4_proxy: pd.DataFrame) -> pd.DataFrame:
    s28 = s28_monthly_proxy(events)
    rows = []
    for symbol in sorted(set(s28["symbol"]) | set(p4_proxy["symbol"])):
        merged = s28[s28["symbol"] == symbol].merge(p4_proxy[p4_proxy["symbol"] == symbol], on=["symbol", "month"], how="inner")
        if merged.empty:
            rows.append({"symbol": symbol, "overlap_status": "insufficient_overlap"})
            continue
        neg = merged[merged["p4_negative_month"] == True]  # noqa: E712
        weak = merged[merged["p4_weak_month"] == True]  # noqa: E712
        pos_in_neg = float((neg["s28_proxy_return"] > 0).mean()) if len(neg) else np.nan
        pos_in_weak = float((weak["s28_proxy_return"] > 0).mean()) if len(weak) else np.nan
        both_negative = int(((merged["p4_negative_month"]) & (merged["s28_proxy_return"] < 0)).sum())
        if len(weak) < 12:
            status = "insufficient_overlap"
        elif (np.isnan(pos_in_neg) or pos_in_neg >= 0.4) and pos_in_weak >= 0.45:
            status = "complementary"
        elif pos_in_weak >= 0.35:
            status = "weak_complementary"
        else:
            status = "not_complementary"
        rows.append({
            "symbol": symbol,
            "p4_negative_month_count": int(len(neg)),
            "p4_weak_month_count": int(len(weak)),
            "s28_positive_in_p4_negative_month_rate": pos_in_neg,
            "s28_positive_in_p4_weak_month_rate": pos_in_weak,
            "both_negative_month_count": both_negative,
            "overlap_status": status,
        })
    return pd.DataFrame(rows)


def random_time_baseline_long_history(
    events: pd.DataFrame,
    data_by_symbol: dict[str, pd.DataFrame],
    runs: int = 3000,
    seed: int = RANDOM_SEED,
    config: EventConfigS2 = EventConfigS2(),
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    primary_cols = ["side", "quarter", "volatility_regime", "trend_strength_bucket", "p4_state_bucket", "bars_since_p4_exit_bucket"]
    fallback_cols = ["side", "volatility_regime", "trend_strength_bucket", "p4_state_bucket"]
    for symbol, part in events.groupby("symbol"):
        pool = build_market_state_pool_s2(data_by_symbol[symbol], symbol, config, horizon=HORIZON)
        pool["quarter"] = pd.to_datetime(pool["signal_time"], utc=True).dt.to_period("Q").astype(str)
        pool["bars_since_p4_exit_bucket"] = pool["p4_state_bucket"]
        primary = {key: g["fwd_ret_16"].dropna().to_numpy(float) for key, g in pool.groupby(primary_cols, observed=True, dropna=False)}
        fallback = {key: g["fwd_ret_16"].dropna().to_numpy(float) for key, g in pool.groupby(fallback_cols, observed=True, dropna=False)}
        match_sets = []
        fallback_count = 0
        for _, event in part.iterrows():
            pkey = tuple(event.get(c) for c in primary_cols)
            fkey = tuple(event.get(c) for c in fallback_cols)
            vals = primary.get(pkey)
            fb = False
            if vals is None or len(vals) == 0:
                vals = fallback.get(fkey)
                fb = True
            if vals is not None and len(vals):
                match_sets.append(vals)
                fallback_count += int(fb)
        sims = []
        for _ in range(runs):
            sample = [float(vals[int(rng.integers(0, len(vals)))]) for vals in match_sets]
            if sample:
                sims.append(float(np.mean(sample)))
        sims = np.asarray(sims)
        observed = float(part["fwd_ret_16"].mean())
        rows.append({
            "symbol": symbol,
            "event_count": int(len(part)),
            "observed_mean": observed,
            "random_mean": float(np.mean(sims)) if len(sims) else np.nan,
            "random_p05": float(np.percentile(sims, 5)) if len(sims) else np.nan,
            "random_p50": float(np.percentile(sims, 50)) if len(sims) else np.nan,
            "random_p95": float(np.percentile(sims, 95)) if len(sims) else np.nan,
            "percentile_vs_random_time": float((np.sum(sims <= observed) + 1) / (len(sims) + 1)) if len(sims) else np.nan,
            "matched_event_count": int(len(match_sets)),
            "fallback_match_rate": float(fallback_count / len(part)) if len(part) else np.nan,
            "random_runs": int(len(sims)),
        })
    return pd.DataFrame(rows)


def stress_summary(events: pd.DataFrame) -> pd.DataFrame:
    def stats(name: str, part: pd.DataFrame, hint: str | None = None) -> dict:
        yearly = part.groupby("year")["fwd_ret_16"].mean() if len(part) else pd.Series(dtype=float)
        quarterly = part.groupby("quarter")["fwd_ret_16"].mean() if len(part) else pd.Series(dtype=float)
        pos_sym = int((part.groupby("symbol")["fwd_ret_16"].mean() > 0).sum()) if len(part) else 0
        mean = part["fwd_ret_16"].mean() if len(part) else np.nan
        if len(part) < 100:
            status = "insufficient_sample"
        elif hint:
            status = hint
        elif mean >= 0 and pos_sym >= 3 and (yearly > 0).mean() >= 0.6:
            status = "stress_pass"
        else:
            status = "stress_fail"
        return {
            "stress_case": name,
            "event_count": int(len(part)),
            "mean_fwd_ret_16": mean,
            "positive_symbol_count": pos_sym,
            "positive_year_rate": float((yearly > 0).mean()) if len(yearly) else np.nan,
            "positive_quarter_rate": float((quarterly > 0).mean()) if len(quarterly) else np.nan,
            "stress_status": status,
        }

    rows = [stats("original", events)]
    ordered = events.sort_values("fwd_ret_16", ascending=False)
    rows.append(stats("remove_best_1_event", ordered.iloc[1:], "single_event_dependent" if ordered.iloc[1:]["fwd_ret_16"].mean() < 0 else None))
    rows.append(stats("remove_best_3_events", ordered.iloc[3:], "single_event_dependent" if ordered.iloc[3:]["fwd_ret_16"].mean() < 0 else None))
    rows.append(stats("remove_best_5_events", ordered.iloc[5:], "single_event_dependent" if ordered.iloc[5:]["fwd_ret_16"].mean() < 0 else None))
    for period_col, name, hint in [("month", "remove_best_1_month", "month_dependent"), ("quarter", "remove_best_quarter", "quarter_dependent"), ("year", "remove_best_year", "year_dependent")]:
        best = events.groupby(period_col)["fwd_ret_16"].mean().sort_values(ascending=False)
        if len(best):
            subset = events[events[period_col] != best.index[0]]
            rows.append(stats(name, subset, hint if subset["fwd_ret_16"].mean() < 0 else None))
    rows.append(stats("only_ETH_BTC", events[events["symbol"].isin(["ETHUSDT", "BTCUSDT"])], "symbol_dependent"))
    rows.append(stats("only_SOL_BNB", events[events["symbol"].isin(["SOLUSDT", "BNBUSDT"])], "symbol_dependent"))
    rows.append(stats("only_long", events[events["side"] == "long"], "direction_dependent"))
    rows.append(stats("only_short", events[events["side"] == "short"], "direction_dependent"))
    rows.append(stats("remove_2025", events[events["year"] != 2025], "cycle_dependent" if events[events["year"] != 2025]["fwd_ret_16"].mean() < 0 else None))
    rows.append(stats("remove_2021_bull", events[events["year"] != 2021], "cycle_dependent" if events[events["year"] != 2021]["fwd_ret_16"].mean() < 0 else None))
    rows.append(stats("remove_2022_bear", events[events["year"] != 2022], "cycle_dependent" if events[events["year"] != 2022]["fwd_ret_16"].mean() < 0 else None))
    return pd.DataFrame(rows)


def decision_summary(
    input_val: pd.DataFrame,
    events: pd.DataFrame,
    summary: pd.DataFrame,
    yearly: pd.DataFrame,
    quarterly: pd.DataFrame,
    random_time: pd.DataFrame,
    stress: pd.DataFrame,
    corr: pd.DataFrame,
    overlap: pd.DataFrame,
) -> pd.DataFrame:
    input_pass = input_val["input_validation_status"].iloc[0] == "pass"
    overall = float(events["fwd_ret_16"].mean()) if len(events) else np.nan
    positive_year_rate = float((yearly.groupby("year")["mean_fwd_ret_16"].mean() > 0).mean()) if not yearly.empty else np.nan
    positive_quarter_rate = float((quarterly.groupby("quarter")["mean_fwd_ret_16"].mean() > 0).mean()) if not quarterly.empty else np.nan
    pos_symbols = int((summary["mean_fwd_ret_16"] > 0).sum()) if not summary.empty else 0
    random_pct = float(random_time["percentile_vs_random_time"].mean()) if not random_time.empty else np.nan
    fallback = float(random_time["fallback_match_rate"].mean()) if not random_time.empty else np.nan
    top1 = top_positive_contribution(events["fwd_ret_16"], 1)
    remove_top3 = _remove_top_mean(events, 3)
    remove_best_year = stress[stress["stress_case"] == "remove_best_year"]
    remove_best_year_ok = (not remove_best_year.empty) and float(remove_best_year["mean_fwd_ret_16"].iloc[0]) >= 0
    high_corr = bool((corr["corr_status"] == "high_corr").any()) if not corr.empty else False
    neg_rate = overlap["s28_positive_in_p4_negative_month_rate"].dropna().mean() if not overlap.empty else np.nan
    weak_rate = overlap["s28_positive_in_p4_weak_month_rate"].dropna().mean() if not overlap.empty else np.nan
    pass_rules = [
        input_pass,
        overall > 0,
        positive_year_rate >= 0.60,
        positive_quarter_rate >= 0.55,
        pos_symbols >= 3,
        random_pct >= 0.75,
        fallback <= 0.20,
        top1 <= 0.20,
        remove_top3 >= 0,
        remove_best_year_ok,
        not high_corr,
        (np.isnan(neg_rate) or neg_rate >= 0.40),
        (np.isnan(weak_rate) or weak_rate >= 0.45),
    ]
    if all(pass_rules):
        letter = "A"
    elif not input_pass:
        letter = "E"
    elif overall <= 0 or random_pct < 0.50:
        letter = "D"
    elif pos_symbols < 3 or positive_year_rate < 0.50:
        letter = "C"
    else:
        letter = "B"
    return pd.DataFrame([{
        "input_validation_status": input_val["input_validation_status"].iloc[0],
        "overall_mean_fwd_ret_16": overall,
        "positive_year_rate": positive_year_rate,
        "positive_quarter_rate": positive_quarter_rate,
        "positive_symbol_count": pos_symbols,
        "random_time_percentile_mean": random_pct,
        "fallback_match_rate_mean": fallback,
        "top1_positive_contribution": top1,
        "remove_top3_mean_fwd_ret": remove_top3,
        "remove_best_year_ok": remove_best_year_ok,
        "has_high_p4_corr": high_corr,
        "p4_negative_month_positive_rate": neg_rate,
        "p4_weak_month_positive_rate": weak_rate,
        "decision_letter": letter,
        "decision_status": {
            "A": "candidate_for_S3_minimal_strategy_prototype",
            "B": "long_history_supports_but_stability_threshold_not_met",
            "C": "year_symbol_or_direction_dependent",
            "D": "long_history_or_random_baseline_rejects_candidate",
            "E": "input_or_implementation_problem",
        }[letter],
        "strategy_backtest_generated": False,
        "data_layer": "expanded_discovery_long_history",
        "oos_status": "not_oos",
    }])
