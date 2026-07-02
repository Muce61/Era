"""S2.6 P4-exit window validation helpers."""

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
    build_market_state_pool_s2,
    top_positive_contribution,
)
from research_core.second_alpha_source_s2.matched_random_baseline_s2 import matched_random_summary_s2


S2_DIR = RESEARCH_ROOT / "second_alpha_source_s2"
S26_DIR = RESEARCH_ROOT / "second_alpha_source_s26"
DATA_ROOT = Path("/Users/muce/1m_data/new_backtest_data_1year_1m")
START_UTC = pd.Timestamp("2024-12-01 00:00:00+00:00")
END_UTC = pd.Timestamp("2026-06-28 01:05:00+00:00")
EXIT_BUCKET = "after_p4_exit_5_16_bars"
RANDOM_SEED = 20260624
HORIZON = 16


def load_canonical_s2_events(path: Path = S2_DIR) -> pd.DataFrame:
    event_path = path / "candidate_event_table.parquet"
    if not event_path.exists():
        return pd.DataFrame()
    events = pd.read_parquet(event_path)
    for col in ["signal_time", "execution_time"]:
        if col in events.columns:
            events[col] = pd.to_datetime(events[col], utc=True)
    return events


def canonical_s2_validation(events: pd.DataFrame, path: Path = S2_DIR) -> pd.DataFrame:
    if events.empty:
        status = "blocked"
        idle_count = held_count = idle_held = after_count = 0
    else:
        idle = events[events["candidate"] == IDLE_CANDIDATE]
        idle_count = int(len(idle))
        held_count = int((events.get("p4_state_bucket", pd.Series(dtype=str)) == "p4_held").sum())
        idle_held = int((idle.get("p4_state_bucket", pd.Series(dtype=str)) == "p4_held").sum())
        after_count = int((idle.get("p4_state_bucket", pd.Series(dtype=str)) == EXIT_BUCKET).sum())
        status = "pass" if idle_count > 0 and idle_held == 0 and after_count > 0 else "blocked"
    return pd.DataFrame([{
        "s2_source_path": str(path),
        "source_status": "canonical" if path == S2_DIR else "non_canonical",
        "event_count_total": int(len(events)),
        "idle_mr1_event_count": idle_count,
        "p4_held_event_count": held_count,
        "idle_mr1_p4_held_count": idle_held,
        "after_exit_5_16_count": after_count,
        "canonical_validation_status": status,
    }])


def exit_window_events(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    out = events[
        (events["candidate"] == IDLE_CANDIDATE)
        & (events["p4_state_bucket"] == EXIT_BUCKET)
    ].copy()
    out["month"] = out["signal_time"].dt.to_period("M").astype(str)
    out["quarter"] = out["signal_time"].dt.to_period("Q").astype(str)
    if "trend_strength_bucket" not in out.columns:
        out["trend_strength_bucket"] = pd.cut(
            out["trend_strength_atr"],
            [-np.inf, 0.5, 1.0, 1.5, 2.5, np.inf],
            labels=["0_0.5", "0.5_1.0", "1.0_1.5", "1.5_2.5", "gt_2.5"],
        ).astype("object").fillna("unknown")
    return out


def _summary_row(part: pd.DataFrame, extra: dict | None = None) -> dict:
    extra = extra or {}
    row = {**extra, "event_count": int(len(part))}
    for horizon in HORIZONS:
        row[f"mean_fwd_ret_{horizon}"] = part[f"fwd_ret_{horizon}"].mean()
    row.update({
        "median_fwd_ret_16": part["fwd_ret_16"].median(),
        "plus_1atr_first_rate_16": part["plus_1atr_first_16"].mean(),
        "minus_1atr_first_rate_16": part["minus_1atr_first_16"].mean(),
        "ambiguous_rate_16": part["ambiguous_touch_16"].mean(),
        "mean_mae_16": part["fwd_mae_16"].mean(),
        "mean_mfe_16": part["fwd_mfe_16"].mean(),
        "mean_reversion_rate_32": part["mean_reversion_bars"].notna().mean(),
        "top1_positive_contribution": top_positive_contribution(part["fwd_ret_16"], 1),
        "top3_positive_contribution": top_positive_contribution(part["fwd_ret_16"], 3),
        "remove_top3_mean_fwd_ret": part["fwd_ret_16"].dropna().sort_values(ascending=False).iloc[3:].mean() if len(part) > 3 else np.nan,
    })
    return row


def event_summary(events: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([_summary_row(events, {"candidate": IDLE_CANDIDATE, "p4_state_bucket": EXIT_BUCKET})]) if not events.empty else pd.DataFrame()


def grouped_breakdown(events: pd.DataFrame, group_col: str) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    rows = []
    for key, part in events.groupby(group_col, dropna=False):
        rows.append(_summary_row(part, {group_col: key}))
    return pd.DataFrame(rows)


def build_full_market_state_pool(symbols: list[str] | None = None, config: EventConfigS2 = EventConfigS2()) -> pd.DataFrame:
    symbols = symbols or SYMBOLS
    pools = []
    for symbol in symbols:
        path = DATA_ROOT / f"{symbol}.csv"
        if not path.exists():
            continue
        data = load_ohlcv_1m(path)
        data = data[(data.index >= START_UTC) & (data.index <= END_UTC)].copy()
        pool = build_market_state_pool_s2(data, symbol, config, horizon=HORIZON)
        if not pool.empty:
            pool["month"] = pd.to_datetime(pool["signal_time"], utc=True).dt.to_period("M").astype(str)
            pools.append(pool)
    return pd.concat(pools, ignore_index=True) if pools else pd.DataFrame()


def random_baseline(events: pd.DataFrame, pool: pd.DataFrame, runs: int = 1000, seed: int = RANDOM_SEED) -> pd.DataFrame:
    if events.empty or pool.empty:
        return pd.DataFrame([{
            "candidate": IDLE_CANDIDATE,
            "event_count": int(len(events)),
            "observed_mean": np.nan,
            "random_mean": np.nan,
            "percentile_vs_random": np.nan,
            "matched_event_count": 0,
            "fallback_match_rate": np.nan,
            "random_runs": 0,
            "pool_source": "full_market_state_pool",
        }])
    work = events.copy()
    work["candidate"] = IDLE_CANDIDATE
    base = matched_random_summary_s2(work, pool=pool, runs=runs, seed=seed, horizon=HORIZON)
    return base


def ordinary_bootstrap(events: pd.DataFrame, runs: int = 1000, seed: int = RANDOM_SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    vals = events["fwd_ret_16"].dropna().to_numpy(float)
    if len(vals) < 30:
        return pd.DataFrame([{"bootstrap_type": "ordinary", "positive_rate": np.nan, "bootstrap_status": "invalid_or_sparse"}])
    sims = np.array([rng.choice(vals, size=len(vals), replace=True).mean() for _ in range(runs)])
    return pd.DataFrame([{
        "bootstrap_type": "ordinary",
        "event_count": int(len(vals)),
        "p05": float(np.percentile(sims, 5)),
        "p50": float(np.percentile(sims, 50)),
        "p95": float(np.percentile(sims, 95)),
        "positive_rate": float((sims > 0).mean()),
        "bootstrap_status": "robust" if (sims > 0).mean() >= 0.70 else "fragile",
    }])


def block_bootstrap(events: pd.DataFrame, block_col: str, runs: int = 1000, seed: int = RANDOM_SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    if events.empty or block_col not in events.columns:
        return pd.DataFrame([{"block_type": block_col, "positive_rate": np.nan, "bootstrap_status": "invalid_or_sparse"}])
    blocks = {key: g["fwd_ret_16"].dropna().to_numpy(float) for key, g in events.groupby(block_col, dropna=False)}
    keys = list(blocks)
    if len(keys) < 2:
        return pd.DataFrame([{"block_type": block_col, "event_count": int(len(events)), "positive_rate": np.nan, "bootstrap_status": "invalid_or_sparse"}])
    sims = []
    for _ in range(runs):
        chosen = rng.choice(keys, size=len(keys), replace=True)
        vals = np.concatenate([blocks[k] for k in chosen if len(blocks[k])])
        if len(vals):
            sims.append(float(vals.mean()))
    sims = np.asarray(sims)
    return pd.DataFrame([{
        "block_type": block_col,
        "event_count": int(len(events)),
        "p05": float(np.percentile(sims, 5)) if len(sims) else np.nan,
        "p50": float(np.percentile(sims, 50)) if len(sims) else np.nan,
        "p95": float(np.percentile(sims, 95)) if len(sims) else np.nan,
        "positive_rate": float((sims > 0).mean()) if len(sims) else np.nan,
        "bootstrap_status": "robust" if len(sims) and (sims > 0).mean() >= 0.60 else "fragile",
    }])


def top_trade_dependency(events: pd.DataFrame) -> pd.DataFrame:
    vals = events["fwd_ret_16"].dropna().sort_values(ascending=False)
    return pd.DataFrame([{
        "event_count": int(len(events)),
        "top1_positive_contribution": top_positive_contribution(vals, 1),
        "top3_positive_contribution": top_positive_contribution(vals, 3),
        "top5_positive_contribution": top_positive_contribution(vals, 5),
        "remove_top1_mean_fwd_ret": vals.iloc[1:].mean() if len(vals) > 1 else np.nan,
        "remove_top3_mean_fwd_ret": vals.iloc[3:].mean() if len(vals) > 3 else np.nan,
        "remove_top5_mean_fwd_ret": vals.iloc[5:].mean() if len(vals) > 5 else np.nan,
    }])


def failure_cases(events: pd.DataFrame, seed: int = RANDOM_SEED) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    worst_ret = events.nsmallest(20, "fwd_ret_16").assign(sample_reason="worst_return")
    worst_mae = events.nsmallest(20, "fwd_mae_16").assign(sample_reason="worst_mae")
    minus = events[events["minus_1atr_first_16"] == True]  # noqa: E712
    minus_sample = minus.sample(n=min(50, len(minus)), random_state=seed).assign(sample_reason="minus_1atr_random")
    sample = pd.concat([worst_ret, worst_mae, minus_sample], ignore_index=True)
    cols = [
        "sample_reason", "event_id", "symbol", "side", "signal_time", "execution_time",
        "execution_open", "p4_state_bucket", "trend_strength_atr", "volatility_regime",
        "deviation_ema20_atr", "fwd_ret_16", "fwd_mae_16", "fwd_mfe_16",
        "plus_1atr_first_16", "minus_1atr_first_16", "subsequent_trend_breakout",
    ]
    return sample[[c for c in cols if c in sample.columns]].reset_index(drop=True)


def decision_summary(
    validation: pd.DataFrame,
    events: pd.DataFrame,
    random: pd.DataFrame,
    boot: pd.DataFrame,
    block: pd.DataFrame,
    dep: pd.DataFrame,
    vol_breakdown: pd.DataFrame,
) -> pd.DataFrame:
    canonical_pass = validation["canonical_validation_status"].iloc[0] == "pass"
    mean_16 = float(events["fwd_ret_16"].mean()) if len(events) else np.nan
    percentile = float(random["percentile_vs_random"].iloc[0]) if not random.empty else np.nan
    ordinary_pos = float(boot["positive_rate"].iloc[0]) if not boot.empty else np.nan
    month_row = block[block["block_type"] == "month"] if not block.empty else pd.DataFrame()
    monthly_pos = float(month_row["positive_rate"].iloc[0]) if not month_row.empty else np.nan
    symbol_positive = int((events.groupby("symbol")["fwd_ret_16"].mean() > 0).sum()) if len(events) else 0
    top1 = float(dep["top1_positive_contribution"].iloc[0]) if not dep.empty else np.nan
    remove_top3 = float(dep["remove_top3_mean_fwd_ret"].iloc[0]) if not dep.empty else np.nan
    high_vol_only = False
    if not vol_breakdown.empty:
        by_vol = dict(zip(vol_breakdown["volatility_regime"], vol_breakdown["mean_fwd_ret_16"]))
        high_vol_only = by_vol.get("high_vol", -1) > 0 and all(v <= 0 for k, v in by_vol.items() if k != "high_vol")
    pass_rules = [
        canonical_pass,
        len(events) >= 300,
        mean_16 > 0,
        percentile >= 0.70,
        ordinary_pos >= 0.70,
        monthly_pos >= 0.60,
        symbol_positive >= 2,
        top1 <= 0.20,
        remove_top3 >= 0,
        not high_vol_only,
    ]
    if all(pass_rules):
        conclusion = "A"
        next_step = "S2.7_event_validation"
    elif not canonical_pass:
        conclusion = "E"
        next_step = "blocked"
    elif len(events) and (symbol_positive < 2):
        conclusion = "C"
        next_step = "needs_more_data"
    elif len(events) and mean_16 <= 0:
        conclusion = "D"
        next_step = "stop_exit_window"
    else:
        conclusion = "B"
        next_step = "needs_more_history_or_definition"
    return pd.DataFrame([{
        "candidate": IDLE_CANDIDATE,
        "p4_state_bucket": EXIT_BUCKET,
        "event_count": int(len(events)),
        "mean_fwd_ret_16": mean_16,
        "percentile_vs_random": percentile,
        "ordinary_bootstrap_positive_rate": ordinary_pos,
        "monthly_block_positive_rate": monthly_pos,
        "positive_symbol_count": symbol_positive,
        "top1_positive_contribution": top1,
        "remove_top3_mean_fwd_ret": remove_top3,
        "high_vol_only": high_vol_only,
        "canonical_pass": canonical_pass,
        "decision_letter": conclusion,
        "decision_status": {
            "A": "clear_local_edge_for_S2.7",
            "B": "weak_lead_needs_more_validation",
            "C": "single_asset_or_month_dependency",
            "D": "sample_noise_not_worth_continuing",
            "E": "canonical_or_implementation_problem",
        }[conclusion],
        "allowed_next_step": next_step,
        "strategy_backtest_generated": False,
        "data_layer": "expanded_discovery",
        "oos_status": "not_oos",
    }])

