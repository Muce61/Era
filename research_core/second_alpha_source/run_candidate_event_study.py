"""Run second-alpha source candidate event studies.

This stage is event research only. It does not create a deployable strategy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from research_core.common import RESEARCH_ROOT, append_run_log, current_git_commit, file_sha256, stable_hash
from research_core.event_table import load_ohlcv_1m
from research_core.run_long_history_10_symbol_review import DATA_ROOT, END_UTC, START_UTC
from research_core.second_alpha_source.candidate_event_study import (
    CANDIDATES,
    SYMBOLS,
    build_candidate_events,
    regime_summary,
    summarize_events,
    top_trade_dependency,
)
from research_core.second_alpha_source.matched_random_baseline import matched_random_summary


OUT = RESEARCH_ROOT / "second_alpha_source"
HORIZON = 16


def bootstrap_summary(events: pd.DataFrame, runs: int = 1000, seed: int = 20260624) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    col = f"fwd_ret_{HORIZON}"
    for keys, part in events.groupby(["candidate", "symbol"]):
        vals = part[col].dropna().to_numpy(float)
        if len(vals) < 30:
            rows.append({"candidate": keys[0], "symbol": keys[1], "event_count": len(vals), "bootstrap_status": "invalid_or_sparse"})
            continue
        means = np.array([rng.choice(vals, size=len(vals), replace=True).mean() for _ in range(runs)])
        rows.append({
            "candidate": keys[0],
            "symbol": keys[1],
            "event_count": len(vals),
            "original_mean": float(vals.mean()),
            "bootstrap_p05": float(np.percentile(means, 5)),
            "bootstrap_p50": float(np.percentile(means, 50)),
            "bootstrap_p95": float(np.percentile(means, 95)),
            "positive_rate": float((means > 0).mean()),
            "bootstrap_status": "robust_candidate" if (means > 0).mean() >= 0.7 else "fragile_or_weak",
        })
    return pd.DataFrame(rows)


def stability_summary(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    work = events.copy()
    work["year"] = pd.to_datetime(work["signal_time"], utc=True).dt.year
    work["quarter"] = pd.to_datetime(work["signal_time"], utc=True).dt.to_period("Q").astype(str)
    col = f"fwd_ret_{HORIZON}"
    for keys, part in work.groupby(["candidate", "symbol"]):
        yearly = part.groupby("year")[col].mean()
        quarterly = part.groupby("quarter")[col].mean()
        rows.append({
            "candidate": keys[0],
            "symbol": keys[1],
            "event_count": int(len(part)),
            "positive_year_rate": float((yearly > 0).mean()) if len(yearly) else np.nan,
            "positive_quarter_rate": float((quarterly > 0).mean()) if len(quarterly) else np.nan,
            "worst_year_mean": float(yearly.min()) if len(yearly) else np.nan,
            "worst_quarter_mean": float(quarterly.min()) if len(quarterly) else np.nan,
            "stability_status": "stable_candidate" if len(yearly) >= 3 and (yearly > 0).mean() >= 0.6 else "unstable_or_sparse",
        })
    return pd.DataFrame(rows)


def parameter_neighborhood_summary(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    # First RB pass uses one frozen definition. The neighborhood table records
    # blocking status instead of retrofitting parameters on the same run.
    for candidate in CANDIDATES:
        rows.append({
            "candidate": candidate,
            "tested_neighborhoods": "not_run_in_v1",
            "status": "blocked_until_base_event_edge_is_positive",
            "reason": "avoid parameter search before candidate shows robust event edge",
        })
    return pd.DataFrame(rows)


def write_report(events: pd.DataFrame, summary: pd.DataFrame, random: pd.DataFrame, bootstrap: pd.DataFrame, stability: pd.DataFrame) -> None:
    decisions = []
    for candidate in CANDIDATES:
        rand = random[random["candidate"] == candidate]
        boot = bootstrap[bootstrap["candidate"] == candidate]
        stable = stability[stability["candidate"] == candidate]
        robust = (
            not rand.empty
            and float(rand["observed_mean"].mean()) > 0
            and float(rand["percentile_vs_random"].mean()) >= 0.7
            and (boot["positive_rate"].fillna(0) >= 0.7).mean() >= 0.5
            and (stable["positive_year_rate"].fillna(0) >= 0.6).mean() >= 0.5
        )
        decisions.append({
            "candidate": candidate,
            "decision": "candidate_for_minimal_backtest" if robust else "event_research_only",
        })
    decision_df = pd.DataFrame(decisions)
    decision_df.to_csv(OUT / "candidate_decision_summary.csv", index=False)
    if (decision_df["decision"] == "candidate_for_minimal_backtest").any():
        conclusion = "At least one candidate has enough event-study evidence for a minimal backtest."
    else:
        conclusion = "No validated second alpha source found"
    lines = [
        "# Second Alpha Source Research Report",
        "",
        "data_layer: expanded_discovery",
        "oos_status: not_oos",
        "deployable_strategy_generated: false",
        "",
        "## Conclusion",
        "",
        conclusion,
        "",
        "## Candidate Summary",
        "",
        summary.to_markdown(index=False),
        "",
        "## Matched Random Baseline",
        "",
        random.to_markdown(index=False),
        "",
        "## Bootstrap",
        "",
        bootstrap.to_markdown(index=False),
        "",
        "## Stability",
        "",
        stability.to_markdown(index=False),
        "",
        "## Required Answers",
        "",
        "1. 第二类收益来源是否真实存在？本阶段只做事件研究；只有 candidate_decision_summary 标记通过时才进入最小回测。",
        "2. 它赚的具体是什么钱？FB1 研究失败突破回归，MR1 研究短期偏离均值回归。",
        "3. 它在哪些市场状态有效？见 candidate_regime_summary.csv。",
        "4. 在哪些状态会失效？见按趋势/波动分组与最差窗口。",
        "5. 收益是否依赖少数极端交易？见 candidate_top_trade_dependency.csv。",
        "6. 交易频率是否明显高于 P4？事件数见 candidate_event_summary.csv。",
        "7. 与 P4 的相关性有多高？本阶段尚未建立策略收益序列，组合相关性延后到 minimal backtest。",
        "8. 组合后是否缩短最长回撤？未进入策略组合前不回答。",
        "9. 是否改善弱趋势和震荡年份？见 candidate_stability_summary.csv。",
        "10. 哪个候选应该停止，哪个值得继续？见 candidate_decision_summary.csv。",
        "11. 是否具备进入严格 OOS 的资格？否，本阶段不是 OOS。",
    ]
    (OUT / "second_alpha_research_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "candidate_equity_curves").mkdir(parents=True, exist_ok=True)
    all_events = []
    data_hashes = []
    for symbol in SYMBOLS:
        path = DATA_ROOT / f"{symbol}.csv"
        print(f"building second-alpha events for {symbol}", flush=True)
        data_hashes.append(file_sha256(path))
        data = load_ohlcv_1m(path)
        data = data[(data.index >= START_UTC) & (data.index <= END_UTC)].copy()
        events, _ = build_candidate_events(data, symbol)
        print(f"{symbol}: {len(events)} candidate events", flush=True)
        all_events.append(events)
    events = pd.concat(all_events, ignore_index=True)
    events.to_parquet(OUT / "candidate_event_table.parquet", index=False)
    events.head(500).to_csv(OUT / "candidate_event_table_sample.csv", index=False)
    summary = summarize_events(events)
    regimes = regime_summary(events)
    random = matched_random_summary(events, runs=500, horizon=HORIZON)
    bootstrap = bootstrap_summary(events)
    stability = stability_summary(events)
    dependency = top_trade_dependency(events, horizon=HORIZON)
    neighborhood = parameter_neighborhood_summary(events)

    summary.to_csv(OUT / "candidate_event_summary.csv", index=False)
    regimes.to_csv(OUT / "candidate_regime_summary.csv", index=False)
    random.to_csv(OUT / "candidate_random_baseline_summary.csv", index=False)
    bootstrap.to_csv(OUT / "candidate_bootstrap_summary.csv", index=False)
    stability.to_csv(OUT / "candidate_stability_summary.csv", index=False)
    dependency.to_csv(OUT / "candidate_top_trade_dependency.csv", index=False)
    neighborhood.to_csv(OUT / "candidate_parameter_neighborhood_summary.csv", index=False)
    pd.DataFrame([{
        "status": "blocked_event_research_first",
        "reason": "minimal strategy backtest is only allowed after event study shows robust edge",
    }]).to_csv(OUT / "candidate_backtest_summary.csv", index=False)
    pd.DataFrame([{
        "status": "not_run",
        "reason": "no independent candidate strategy portfolio exists at event-study stage",
    }]).to_csv(OUT / "p4_candidate_portfolio_comparison.csv", index=False)
    write_report(events, summary, random, bootstrap, stability)

    append_run_log({
        "run_id": "SECOND_ALPHA_EVENT_STUDY",
        "stage": "SECOND_ALPHA",
        "script": "research_core.second_alpha_source.run_candidate_event_study",
        "config_hash": stable_hash({
            "symbols": SYMBOLS,
            "candidates": CANDIDATES,
            "horizon": HORIZON,
            "time_alignment": "candle_close_time",
        }),
        "data_hash": stable_hash(data_hashes),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": 20260624,
        "data_layer": "expanded_discovery",
        "status": "success",
        "notes": "second alpha source event study only; no P4 rule changed; not OOS; no deployable strategy generated",
    })


if __name__ == "__main__":
    run()
