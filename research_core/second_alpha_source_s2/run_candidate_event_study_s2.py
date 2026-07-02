"""Run canonical Second Alpha Source S2 event study."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from research_core.common import RESEARCH_ROOT, append_run_log, current_git_commit, file_sha256, stable_hash
from research_core.event_table import load_ohlcv_1m
from research_core.second_alpha_source_s2.candidate_event_study_s2 import (
    CANDIDATES,
    SYMBOLS,
    EventConfigS2,
    build_candidate_events_s2,
    build_rv1_lite_events,
    stability_summary_s2,
    summarize_events_s2,
    top_trade_dependency_s2,
)
from research_core.second_alpha_source_s2.matched_random_baseline_s2 import matched_random_summary_s2


OUT = RESEARCH_ROOT / "second_alpha_source_s2"
DATA_ROOT = Path("/Users/muce/1m_data/new_backtest_data_1year_1m")
START_UTC = pd.Timestamp("2024-12-01 00:00:00+00:00")
END_UTC = pd.Timestamp("2026-06-28 01:05:00+00:00")
RANDOM_SEED = 20260624
HORIZON = 16


def _load_symbol(symbol: str) -> pd.DataFrame:
    path = DATA_ROOT / f"{symbol}.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    data = load_ohlcv_1m(path)
    return data[(data.index >= START_UTC) & (data.index <= END_UTC)].copy()


def bootstrap_summary(events: pd.DataFrame, runs: int = 1000, seed: int = RANDOM_SEED, horizon: int = HORIZON) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    col = f"fwd_ret_{horizon}"
    for candidate, part in events.groupby("candidate", dropna=False):
        vals = part[col].dropna().to_numpy(float)
        if len(vals) < 30:
            rows.append({"candidate": candidate, "event_count": len(vals), "positive_rate": np.nan, "bootstrap_status": "invalid_or_sparse"})
            continue
        sims = np.array([rng.choice(vals, len(vals), replace=True).mean() for _ in range(runs)])
        rows.append({
            "candidate": candidate,
            "event_count": int(len(vals)),
            "original_mean": float(vals.mean()),
            "p05": float(np.percentile(sims, 5)),
            "p50": float(np.percentile(sims, 50)),
            "p95": float(np.percentile(sims, 95)),
            "positive_rate": float((sims > 0).mean()),
            "bootstrap_status": "robust_candidate" if (sims > 0).mean() >= 0.7 else "fragile_or_weak",
        })
    return pd.DataFrame(rows)


def block_bootstrap_summary(events: pd.DataFrame, runs: int = 1000, seed: int = RANDOM_SEED, horizon: int = HORIZON) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    work = events.copy()
    work["month"] = pd.to_datetime(work["signal_time"], utc=True).dt.to_period("M").astype(str)
    col = f"fwd_ret_{horizon}"
    rows = []
    for candidate, part in work.groupby("candidate", dropna=False):
        blocks = {month: g[col].dropna().to_numpy(float) for month, g in part.groupby("month")}
        months = list(blocks)
        if len(months) < 3:
            rows.append({"candidate": candidate, "event_count": int(len(part)), "block_type": "month", "positive_rate": np.nan, "bootstrap_status": "invalid_or_sparse"})
            continue
        sims = []
        for _ in range(runs):
            chosen = rng.choice(months, size=len(months), replace=True)
            vals = np.concatenate([blocks[m] for m in chosen if len(blocks[m])])
            if len(vals):
                sims.append(float(vals.mean()))
        sims = np.asarray(sims)
        rows.append({
            "candidate": candidate,
            "event_count": int(len(part)),
            "block_type": "month",
            "p05": float(np.percentile(sims, 5)) if len(sims) else np.nan,
            "p50": float(np.percentile(sims, 50)) if len(sims) else np.nan,
            "p95": float(np.percentile(sims, 95)) if len(sims) else np.nan,
            "positive_rate": float((sims > 0).mean()) if len(sims) else np.nan,
            "bootstrap_status": "robust" if len(sims) and (sims > 0).mean() >= 0.7 else "fragile",
        })
    return pd.DataFrame(rows)


def decision_summary(events: pd.DataFrame, random: pd.DataFrame, boot: pd.DataFrame, stability: pd.DataFrame, dep: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for candidate in CANDIDATES:
        part = events[events["candidate"] == candidate]
        rand = random[random["candidate"] == candidate]
        b = boot[boot["candidate"] == candidate]
        stab = stability[stability["candidate"] == candidate]
        d = dep[dep["candidate"] == candidate]
        mean_16 = float(part["fwd_ret_16"].mean()) if len(part) else np.nan
        positive_symbols = int((part.groupby("symbol")["fwd_ret_16"].mean() > 0).sum()) if len(part) else 0
        remove_top3 = d["remove_top3_mean_fwd_ret"].dropna().mean() if not d.empty else np.nan
        top1 = d["top1_positive_contribution"].dropna().mean() if not d.empty else np.nan
        passed = (
            len(part) >= 300
            and mean_16 > 0
            and not rand.empty
            and float(rand["percentile_vs_random"].mean()) >= 0.70
            and not b.empty
            and float(b["positive_rate"].fillna(0).mean()) >= 0.70
            and positive_symbols >= 2
            and (np.isnan(top1) or top1 <= 0.20)
            and (np.isnan(remove_top3) or remove_top3 >= 0)
        )
        rows.append({
            "candidate": candidate,
            "event_count": int(len(part)),
            "mean_fwd_16": mean_16,
            "positive_symbol_count": positive_symbols,
            "percentile_vs_random": float(rand["percentile_vs_random"].mean()) if not rand.empty else np.nan,
            "bootstrap_positive_rate": float(b["positive_rate"].mean()) if not b.empty else np.nan,
            "positive_year_rate": float(stab["positive_year_rate"].mean()) if not stab.empty else np.nan,
            "top1_positive_contribution": top1,
            "remove_top3_mean_fwd_ret": remove_top3,
            "decision": "candidate_for_s3_minimal_backtest" if passed else "event_research_only",
        })
    return pd.DataFrame(rows)


def write_report(events: pd.DataFrame, decisions: pd.DataFrame) -> None:
    idle = events[events["candidate"] == "IDLE_MR1_P4_IDLE_REVERSION"]
    idle_held = int((idle["p4_state_bucket"] == "p4_held").sum()) if not idle.empty else 0
    after = int((idle["p4_state_bucket"] == "after_p4_exit_5_16_bars").sum()) if not idle.empty else 0
    lines = [
        "# Canonical S2 第二类 Alpha 事件研究报告",
        "",
        "data_layer: expanded_discovery / internal_validation",
        "oos_status: not_oos",
        "strategy_backtest_generated: false",
        "",
        "## Canonical Checks",
        "",
        f"- event_count_total: {len(events)}",
        f"- idle_mr1_event_count: {len(idle)}",
        f"- idle_mr1_p4_held_count: {idle_held}",
        f"- after_p4_exit_5_16_count: {after}",
        "",
        "## Decisions",
        "",
        decisions.to_markdown(index=False),
        "",
        "本阶段只提供 canonical S2 事件研究输入，不允许直接策略化。",
    ]
    (OUT / "second_alpha_s2_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    config = EventConfigS2()
    events_by_symbol = []
    frames = {}
    data_by_symbol = {}
    hashes = {}
    for symbol in SYMBOLS:
        data = _load_symbol(symbol)
        data_by_symbol[symbol] = data
        hashes[symbol] = file_sha256(DATA_ROOT / f"{symbol}.csv")
        ev, frame = build_candidate_events_s2(data, symbol, config)
        events_by_symbol.append(ev)
        frames[symbol] = frame
    rv = build_rv1_lite_events(frames, data_by_symbol)
    if not rv.empty:
        events_by_symbol.append(rv)
    events = pd.concat([e for e in events_by_symbol if not e.empty], ignore_index=True) if events_by_symbol else pd.DataFrame()
    if not events.empty:
        events = events.sort_values(["candidate", "symbol", "signal_time", "side"]).reset_index(drop=True)
        events.to_parquet(OUT / "candidate_event_table.parquet", index=False)
        events.head(2000).to_csv(OUT / "candidate_event_table_sample.csv", index=False)
    summary = summarize_events_s2(events)
    summary.to_csv(OUT / "candidate_event_summary.csv", index=False)
    random = matched_random_summary_s2(events, runs=500, seed=RANDOM_SEED)
    random.to_csv(OUT / "candidate_random_baseline_summary.csv", index=False)
    boot = bootstrap_summary(events)
    boot.to_csv(OUT / "candidate_bootstrap_summary.csv", index=False)
    block = block_bootstrap_summary(events)
    block.to_csv(OUT / "candidate_block_bootstrap_summary.csv", index=False)
    stability = stability_summary_s2(events)
    stability.to_csv(OUT / "candidate_stability_summary.csv", index=False)
    dep = top_trade_dependency_s2(events)
    dep.to_csv(OUT / "candidate_top_trade_dependency.csv", index=False)
    decisions = decision_summary(events, random, boot, stability, dep)
    decisions.to_csv(OUT / "candidate_decision_summary.csv", index=False)
    write_report(events, decisions)
    metadata = pd.DataFrame([{
        "run_id": "S2_CANONICAL_EVENT_STUDY",
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "data_start": START_UTC.isoformat(),
        "data_end": END_UTC.isoformat(),
        "symbol_count": len(SYMBOLS),
        "event_count": len(events),
        "config_hash": stable_hash(config.__dict__),
        "data_hash": stable_hash(hashes),
        "git_commit": current_git_commit(),
        "data_layer": "expanded_discovery",
        "oos_status": "not_oos",
    }])
    metadata.to_csv(OUT / "s2_run_metadata.csv", index=False)
    append_run_log({
        "run_id": "S2_CANONICAL_EVENT_STUDY",
        "stage": "S2",
        "script": "research_core/second_alpha_source_s2/run_candidate_event_study_s2.py",
        "config_hash": stable_hash(config.__dict__),
        "data_hash": stable_hash(hashes),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "expanded_discovery",
        "status": "success",
        "notes": "canonical S2 event study; no strategy backtest; not OOS",
    })


if __name__ == "__main__":
    main()

