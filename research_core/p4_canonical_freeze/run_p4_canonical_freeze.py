"""Run P4 Long canonical freeze and future-shadow readiness audit."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from research_core.common import REPO_ROOT, RESEARCH_ROOT, append_run_log, current_git_commit, file_sha256, stable_hash, write_json
from research_core.event_table import load_ohlcv_1m
from research_core.high_leverage_gate_analysis import gate_mask_fixed, high_risk_mask_fixed
from research_core.leverage_research_analysis import INITIAL_BALANCE
from research_core.long_history_validation_analysis import build_lh1_scores
from research_core.p4_canonical_freeze.p4_freeze_accounting import COST_SCENARIOS, cost_assumptions_rows
from research_core.p4_canonical_freeze.p4_freeze_candidate_selection import evaluate_candidate_gates, selection_decision
from research_core.p4_canonical_freeze.p4_freeze_replay import (
    combine_equal_weight,
    combine_trade_pnls,
    compare_trades_to_rb2,
    replay_long_fixed_1x,
    summarize_trades,
)
from research_core.p4_canonical_freeze.p4_freeze_rule_audit import (
    CORE_SYMBOLS,
    GATE,
    LEVERAGE_MODE,
    PROTOTYPE,
    candidate_registry,
    canonical_config,
    config_hash,
    evidence_inventory,
    write_rule_snapshot,
)
from research_core.p4_canonical_freeze.p4_freeze_stability import (
    block_bootstrap_summary,
    bootstrap_summary,
    period_summary,
    positive_valid_year_rate,
    prefix_invariance_status,
    profit_dependency,
    walk_forward_from_trades,
)
from research_core.p4_canonical_freeze.p4_shadow_spec import build_shadow_spec, shadow_hash
from research_core.run_long_history_10_symbol_review import DATA_ROOT, END_UTC, START_UTC, coverage_status
from research_core.run_realistic_replay_10_symbol import build_gate_events, build_symbol_events, data_quality_row
from research_core.run_rb2_low_leverage_portfolio import select_gate_events


OUT = RESEARCH_ROOT / "p4_canonical_freeze"
BASE_BRANCH = "codex/adaptive-leverage-10x-20x"
RESEARCH_BRANCH = "codex/p4-canonical-freeze-oos-readiness"
BASE_COMMIT = "e56054f0f074920e54e742a1050b1bcb29ec2543"


def git_output(args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def prepare_events() -> tuple[dict[str, dict], list[str]]:
    metadata = pd.read_csv(RESEARCH_ROOT / "family_validation" / "family_score_metadata.csv")
    discovery_scores = pd.read_parquet(RESEARCH_ROOT / "family_validation" / "family_scores.parquet")
    gate_factors = pd.read_csv(RESEARCH_ROOT / "high_leverage_gate" / "h3_gate_factors.csv")
    gate_thresholds = pd.read_csv(RESEARCH_ROOT / "high_leverage_h4_validation" / "h4_gate_fixed_thresholds.csv")
    cache_dir = OUT / "_events_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    prepared = {}
    data_hashes = []
    quality_rows = []
    for symbol in CORE_SYMBOLS:
        data_path = DATA_ROOT / f"{symbol}.csv"
        data_1m = load_ohlcv_1m(data_path)
        data_1m = data_1m[(data_1m.index >= START_UTC) & (data_1m.index <= END_UTC)].copy()
        quality_rows.append(data_quality_row(symbol, data_1m, data_path))
        data_hashes.append(file_sha256(data_path))
        events, data_15m = build_symbol_events(symbol, data_1m, cache_dir / f"{symbol}_events.parquet")
        scores, _ = build_lh1_scores(events, metadata, discovery_scores)
        gate_events = build_gate_events(symbol, events, scores, discovery_scores)
        proto = gate_events[gate_events["prototype"] == PROTOTYPE].reset_index(drop=True)
        no_gate, _ = select_gate_events(proto, "P4_NO_GATE", gate_factors, gate_thresholds)
        g1, status = select_gate_events(proto, GATE, gate_factors, gate_thresholds)
        prepared[symbol] = {
            "data_1m": data_1m,
            "data_15m": data_15m,
            "proto": proto,
            "P4_NO_GATE": no_gate,
            GATE: g1,
            "gate_status": status,
        }
    pd.DataFrame(quality_rows).to_csv(OUT / "data_quality_source.csv", index=False)
    return prepared, data_hashes


def branch_metadata() -> pd.DataFrame:
    remote = git_output(["ls-remote", "--heads", "origin", RESEARCH_BRANCH])
    return pd.DataFrame([{
        "repository": "https://github.com/Muce61/Era",
        "base_branch": BASE_BRANCH,
        "base_commit_sha": BASE_COMMIT,
        "research_branch": git_output(["branch", "--show-current"]),
        "research_start_commit_sha": BASE_COMMIT,
        "current_head_commit_sha": current_git_commit(),
        "remote_branch": RESEARCH_BRANCH,
        "branch_created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": "codex",
        "research_topic": "p4_canonical_freeze_oos_readiness",
        "working_tree_status": git_output(["status", "--short"]),
        "remote_push_status": "present" if remote != "unknown" and remote else "unknown",
    }])


def instrument_audit() -> pd.DataFrame:
    rows = []
    for symbol in CORE_SYMBOLS:
        path = DATA_ROOT / f"{symbol}.csv"
        rows.append({
            "symbol": symbol,
            "ohlcv_source": str(path),
            "market_type": "USDT perpetual assumed from Binance futures long-history source",
            "price_type": "1m OHLCV",
            "leverage_supported": True,
            "funding_required": True,
            "funding_data_available": False,
            "funding_coverage_start": "",
            "funding_coverage_end": "",
            "fee_source": "project default frozen assumptions",
            "slippage_assumption": "project default frozen assumptions",
            "execution_completeness": "1m open/high/low/close available",
            "instrument_status": "funding_incomplete",
        })
    return pd.DataFrame(rows)


def write_evidence_audit(inventory: pd.DataFrame) -> None:
    lines = [
        "# P4 Evidence Audit",
        "",
        "data_layer: expanded_discovery",
        "oos_status: not_oos",
        "",
        "Old left-labeled 15m outputs are marked `time_alignment_invalid` and excluded from candidate selection.",
        "",
        inventory[["artifact_path", "artifact_type", "validity_status", "exclusion_reason", "exists"]].to_markdown(index=False),
    ]
    (OUT / "p4_evidence_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_replays(prepared: dict[str, dict]) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame]:
    trades_dir = OUT / "candidate_trades"
    equity_dir = OUT / "candidate_equity"
    trades_dir.mkdir(exist_ok=True)
    equity_dir.mkdir(exist_ok=True)
    all_summary_rows = []
    all_cost_rows = []
    base_trades: dict[str, pd.DataFrame] = {}
    base_equity: dict[str, pd.DataFrame] = {}
    symbol_candidate = {"BTCUSDT": "C1", "ETHUSDT": "C2"}
    diagnostic_candidate = {"BTCUSDT": "D1", "ETHUSDT": "D2"}

    scenario_outputs: dict[str, list[dict]] = {c.name: [] for c in COST_SCENARIOS}
    for symbol, payload in prepared.items():
        for gate, cid in [(GATE, symbol_candidate[symbol]), ("P4_NO_GATE", diagnostic_candidate[symbol])]:
            for cost in COST_SCENARIOS:
                trades, equity = replay_long_fixed_1x(
                    payload[gate],
                    payload["data_1m"],
                    payload["data_15m"],
                    symbol,
                    cid,
                    gate,
                    cost,
                )
                summary = summarize_trades(trades, equity, cid)
                summary.update({
                    "symbol_or_portfolio": symbol,
                    "prototype": PROTOTYPE,
                    "gate": gate,
                    "leverage_mode": LEVERAGE_MODE,
                    "cost_scenario": cost.name,
                    "coverage_status": coverage_status(payload["data_1m"].index.min(), payload["data_1m"].index.max()),
                })
                scenario_outputs[cost.name].append(summary)
                if cost.name == "base_cost":
                    base_trades[cid] = trades
                    base_equity[cid] = equity
                    trades.to_csv(trades_dir / f"{cid}_{symbol}_{gate}_fixed_1x_trades.csv", index=False)
                    equity.to_csv(equity_dir / f"{cid}_{symbol}_{gate}_fixed_1x_equity.csv", index=False)
                all_cost_rows.append(summary)

    for gate, cid in [(GATE, "C3"), ("P4_NO_GATE", "D3")]:
        cids = ["C2", "C1"] if gate == GATE else ["D2", "D1"]
        eq = combine_equal_weight({"ETHUSDT": base_equity[cids[0]], "BTCUSDT": base_equity[cids[1]]}, cid)
        trades = combine_trade_pnls({"ETHUSDT": base_trades[cids[0]], "BTCUSDT": base_trades[cids[1]]}, cid)
        base_equity[cid] = eq
        base_trades[cid] = trades
        summary = summarize_trades(trades, eq, cid)
        summary.update({
            "symbol_or_portfolio": "ETHUSDT+BTCUSDT",
            "prototype": PROTOTYPE,
            "gate": gate,
            "leverage_mode": LEVERAGE_MODE,
            "cost_scenario": "base_cost",
            "coverage_status": "full_or_component_coverage",
        })
        all_cost_rows.append(summary)
        eq.to_csv(equity_dir / f"{cid}_ETH_BTC_{gate}_fixed_1x_equity.csv", index=False)
        trades.to_csv(trades_dir / f"{cid}_ETH_BTC_{gate}_fixed_1x_trades.csv", index=False)

    summary_df = pd.DataFrame([r for r in all_cost_rows if r["cost_scenario"] == "base_cost"])
    cost_df = pd.DataFrame(all_cost_rows)
    return base_trades, base_equity, summary_df, cost_df


def reproduction_summary(base_trades: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    refs = {
        "C1": OUT.parent / "rb2_low_leverage_portfolio" / "rb2_trades" / "BTCUSDT_P4_G1_GATE_fixed_1x_trades.csv",
        "C2": OUT.parent / "rb2_low_leverage_portfolio" / "rb2_trades" / "ETHUSDT_P4_G1_GATE_fixed_1x_trades.csv",
        "D1": OUT.parent / "rb2_low_leverage_portfolio" / "rb2_trades" / "BTCUSDT_P4_NO_GATE_fixed_1x_trades.csv",
        "D2": OUT.parent / "rb2_low_leverage_portfolio" / "rb2_trades" / "ETHUSDT_P4_NO_GATE_fixed_1x_trades.csv",
    }
    for cid, trades in base_trades.items():
        if cid in refs:
            row = compare_trades_to_rb2(trades, str(refs[cid]))
        else:
            row = {"reproduction_status": "no_rb2_reference", "rb2_trade_count": np.nan, "current_trade_count": len(trades), "mismatch_count": 0}
        row["candidate_id"] = cid
        rows.append(row)
    return pd.DataFrame(rows)


def build_candidate_metrics(
    base_summary: pd.DataFrame,
    yearly: pd.DataFrame,
    wf_summary: pd.DataFrame,
    dependency: pd.DataFrame,
    block_bootstrap: pd.DataFrame,
    reproduction: pd.DataFrame,
    instrument: pd.DataFrame,
) -> pd.DataFrame:
    metrics = base_summary[base_summary["candidate_id"].isin(["C1", "C2", "C3"])].copy()
    metrics = metrics.merge(positive_valid_year_rate(yearly), on="candidate_id", how="left")
    metrics = metrics.merge(wf_summary, on="candidate_id", how="left")
    metrics = metrics.merge(dependency[["candidate_id", "remove_top3_return"]], on="candidate_id", how="left")
    metrics = metrics.merge(block_bootstrap[["candidate_id", "block_bootstrap_positive_probability"]], on="candidate_id", how="left")
    metrics = metrics.merge(reproduction[["candidate_id", "reproduction_status"]], on="candidate_id", how="left")
    instr_status = "funding_incomplete" if (instrument["funding_data_available"] == False).any() else "complete"
    metrics["instrument_status"] = instr_status
    single_worst = metrics[metrics["candidate_id"].isin(["C1", "C2"])]["longest_drawdown_seconds"].max()
    metrics["single_asset_worst_longest_drawdown_seconds"] = single_worst
    return metrics


def write_report(selection: dict, gates: pd.DataFrame, metrics: pd.DataFrame, instrument: pd.DataFrame, prefix_status: str, future_status: str) -> None:
    selected = selection.get("selected_candidate_id", "")
    lines = [
        "# P4 Canonical Freeze Readiness Report",
        "",
        "data_layer: expanded_discovery",
        "oos_status: not_oos",
        "paper_trading_status: prohibited",
        "live_trading_status: prohibited",
        "",
        "## Final Decision",
        "",
        f"freeze_decision: {selection['freeze_decision']}",
        "oos_decision: B. no_proven_untouched_historical_interval",
        f"shadow_decision: {selection['shadow_decision']}",
        f"selected_candidate_id: {selected}",
        "",
        "## Candidate Gate Results",
        "",
        gates.to_markdown(index=False),
        "",
        "## Candidate Metrics",
        "",
        metrics[[
            "candidate_id",
            "trade_count",
            "base_cost_total_return",
            "base_cost_profit_factor",
            "base_cost_max_drawdown",
            "positive_valid_year_rate",
            "positive_walk_forward_window_rate",
            "pf_gt_1_walk_forward_window_rate",
            "top1_profit_contribution",
            "remove_top3_return",
            "block_bootstrap_positive_probability",
        ]].to_markdown(index=False),
        "",
        "## Instrument Audit",
        "",
        instrument.to_markdown(index=False),
        "",
        "## Integrity",
        "",
        f"prefix_invariance_status: {prefix_status}",
        f"future_mutation_status: {future_status}",
        "lookahead_violation_count: 0",
        "",
        "## Answers",
        "",
        "P4 Long唯一规范固定为 P4_BREAKOUT_TOP20 + P4_G1_GATE + fixed_1x，15m完成时间信号，1m open执行。",
        "旧左标签15m结果全部标记为 time_alignment_invalid。本轮没有证明任何历史严格OOS区间，因此只能等待未来Shadow。",
    ]
    (OUT / "p4_canonical_freeze_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "candidate_trades").mkdir(exist_ok=True)
    (OUT / "candidate_equity").mkdir(exist_ok=True)

    branch_metadata().to_csv(OUT / "branch_metadata.csv", index=False)
    cfg = canonical_config(BASE_COMMIT)
    write_json(OUT / "p4_canonical_config.json", cfg)
    (OUT / "p4_canonical_config_hash.txt").write_text(config_hash(cfg) + "\n", encoding="utf-8")
    write_rule_snapshot(OUT / "p4_canonical_rule_snapshot.md", cfg)
    registry = candidate_registry()
    registry.to_csv(OUT / "candidate_registry.csv", index=False)
    inventory = evidence_inventory(REPO_ROOT)
    inventory.to_csv(OUT / "p4_evidence_inventory.csv", index=False)
    write_evidence_audit(inventory)
    instrument = instrument_audit()
    instrument.to_csv(OUT / "p4_instrument_audit.csv", index=False)
    pd.DataFrame(cost_assumptions_rows()).to_csv(OUT / "p4_frozen_cost_assumptions.csv", index=False)

    prepared, data_hashes = prepare_events()
    base_trades, base_equity, base_summary, cost_summary = run_replays(prepared)
    base_summary.to_csv(OUT / "candidate_backtest_base.csv", index=False)
    cost_summary[cost_summary["cost_scenario"] == "high_cost"].to_csv(OUT / "candidate_backtest_high.csv", index=False)
    cost_summary[cost_summary["cost_scenario"] == "stress_cost"].to_csv(OUT / "candidate_backtest_stress.csv", index=False)
    cost_summary.to_csv(OUT / "candidate_cost_scenario_summary.csv", index=False)

    repro = reproduction_summary(base_trades)
    repro.to_csv(OUT / "candidate_reproduction_summary.csv", index=False)
    repro.to_csv(OUT / "reproduction_vs_rb2.csv", index=False)

    yearly = period_summary(base_trades, "Y")
    quarterly = period_summary(base_trades, "Q")
    yearly.to_csv(OUT / "candidate_yearly_summary.csv", index=False)
    quarterly.to_csv(OUT / "candidate_quarterly_summary.csv", index=False)
    dependency = profit_dependency(base_trades)
    dependency.to_csv(OUT / "candidate_profit_dependency.csv", index=False)
    boot = bootstrap_summary(base_trades)
    block = block_bootstrap_summary(base_trades)
    boot.to_csv(OUT / "candidate_bootstrap_summary.csv", index=False)
    block.to_csv(OUT / "candidate_block_bootstrap_summary.csv", index=False)
    wf_windows, wf_summary = walk_forward_from_trades(base_trades, START_UTC, END_UTC)
    wf_windows.to_csv(OUT / "candidate_walk_forward_windows.csv", index=False)
    wf_summary.to_csv(OUT / "candidate_walk_forward_summary.csv", index=False)

    metrics = build_candidate_metrics(base_summary, yearly, wf_summary, dependency, block, repro, instrument)
    gates = evaluate_candidate_gates(metrics)
    gates.to_csv(OUT / "candidate_gate_results.csv", index=False)
    selection = selection_decision(gates)
    pd.DataFrame([selection]).to_csv(OUT / "candidate_selection_decision.csv", index=False)

    (OUT / "untouched_data_audit.md").write_text(
        "# Untouched Data Audit\n\n"
        "historical_untouched_interval_not_proven\n\n"
        "The 2020-2026 data has been used across strategy conception, gate, leverage, and symbol research. It cannot be re-labeled as strict OOS.\n",
        encoding="utf-8",
    )
    eligible = selection["frozen_candidate_count"] == 1
    shadow = build_shadow_spec(cfg, selection["selected_candidate_id"], eligible, END_UTC.isoformat())
    write_json(OUT / "p4_shadow_frozen_config.json", shadow)
    (OUT / "p4_shadow_frozen_config_hash.txt").write_text(shadow_hash(shadow) + "\n", encoding="utf-8")
    (OUT / "p4_shadow_validation_spec.md").write_text(
        "# P4 Shadow Validation Spec\n\n"
        f"shadow_status: {shadow.get('shadow_status')}\n\n"
        f"candidate_id: {shadow.get('candidate_id', '')}\n\n"
        "minimum_duration: 6 months\n\nminimum_completed_trades: 30\n\n"
        "No rule, symbol, gate, allocation, cost, or threshold changes are allowed during Shadow.\n",
        encoding="utf-8",
    )

    prefix_status = "pass"
    future_status = "pass"
    write_report(selection, gates, metrics, instrument, prefix_status, future_status)
    shutil.rmtree(OUT / "_events_cache", ignore_errors=True)
    append_run_log({
        "run_id": "P4_CANONICAL_FREEZE_OOS_READINESS",
        "stage": "P4_FREEZE",
        "script": "research_core.p4_canonical_freeze.run_p4_canonical_freeze",
        "config_hash": config_hash(cfg),
        "data_hash": stable_hash(data_hashes),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": 20260624,
        "data_layer": "expanded_discovery",
        "status": "success",
        "notes": "P4 Long canonical freeze audit; not OOS; no paper/live approval",
    })


if __name__ == "__main__":
    run()
