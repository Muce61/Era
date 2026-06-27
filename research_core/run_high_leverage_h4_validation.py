"""Run H4 OOS-first, holdout cross-asset, or finer-path validation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from research_core.common import (
    RANDOM_SEED,
    RESEARCH_ROOT,
    append_run_log,
    current_git_commit,
    ensure_research_dirs,
    file_sha256,
    stable_hash,
)
from research_core.cross_asset_validation_analysis import run_cross_asset_symbol
from research_core.high_leverage_h4_validation_analysis import (
    DISCOVERY_END,
    HOLDOUT_PRIORITY_SYMBOLS,
    H4_GATES,
    H4_LEVERAGE_MODES,
    audit_holdout_symbol,
    build_holdout_gate_events,
    choose_holdout_symbols,
    discover_symbol_files,
    final_h4_decision,
    gate_assignments_for_symbol,
    h3_vs_h4_comparison,
    h4_gate_backtest_symbol,
    holdout_asset_decision,
)
from research_core.high_leverage_gate_analysis import build_fixed_gate_thresholds, unique_event_labels
from research_core.leverage_research_analysis import plot_leverage_equity
from research_core.minimal_backtest_analysis import load_params
from research_core.oos_validation_analysis import build_data_inventory, candidate_csv_paths, coverage_decision


SEARCH_ROOTS = [
    Path("/Users/muce/1m_data"),
    Path("/Users/muce/PycharmProjects/20260621/eth"),
    Path("/Users/muce/PycharmProjects/20260625/Era"),
    Path("/Users/muce/Downloads"),
]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_data_decision(oos_decision: dict, inventory: pd.DataFrame, holdout_symbols: list[str], finer_available: bool) -> str:
    lines = [
        "# H4 Data Decision",
        "",
        f"discovery_end: {DISCOVERY_END.isoformat()}",
        f"time_oos_status: {oos_decision.get('status', 'blocked')}",
        f"time_oos_reason: {oos_decision.get('reason', '')}",
        f"time_oos_best_path: {oos_decision.get('best_path', '')}",
        f"time_oos_coverage_days: {oos_decision.get('coverage_days', 0.0):.4f}",
        f"holdout_symbols: {holdout_symbols}",
        f"holdout_symbol_count: {len(holdout_symbols)}",
        f"finer_data_available: {finer_available}",
        "",
        "H4 uses time OOS first. If time OOS is insufficient, it uses cross_asset_holdout, which is not time OOS.",
        "",
        "## Inventory",
        "",
        inventory.head(50).to_markdown(index=False) if not inventory.empty else "No inventory rows.",
    ]
    return "\n".join(lines) + "\n"


def write_report(
    oos_decision: dict,
    holdout_quality: pd.DataFrame,
    holdout_asset_summary: pd.DataFrame,
    holdout_status: str,
    summary: pd.DataFrame,
    stress: pd.DataFrame,
    comparison: pd.DataFrame,
    final_code: str,
    final_text: str,
) -> str:
    stress_counts = stress.groupby(["data_layer", "gate", "leverage_mode", "stress_status"]).size().reset_index(name="count") if not stress.empty else pd.DataFrame()
    best = summary.sort_values(["validation_status", "profit_factor"], ascending=[False, False]).head(30) if not summary.empty else pd.DataFrame()
    lines = [
        "# H4 OOS Cross-Asset Or Finer Validation Report",
        "",
        "data_layer: high_leverage_validation",
        "oos_status: not_time_oos" if oos_decision.get("status") != "success" else "time_oos_available",
        "simulation_approval: not_allowed",
        "",
        "H4 does not change P4/P6 alpha, H3 gate factors, gate thresholds, leverage rules, or liquidation model.",
        "",
        "## Data Availability",
        "",
        f"- time_oos_status: {oos_decision.get('status')}",
        f"- time_oos_coverage_days: {oos_decision.get('coverage_days', 0.0):.4f}",
        f"- holdout_status: {holdout_status}",
        f"- holdout_symbols: {holdout_quality['symbol'].tolist() if not holdout_quality.empty else []}",
        "- finer_path_data: unavailable",
        "",
        "## Holdout Data Quality",
        "",
        holdout_quality.to_markdown(index=False) if not holdout_quality.empty else "unavailable",
        "",
        "## Holdout Asset Decision",
        "",
        holdout_asset_summary.to_markdown(index=False) if not holdout_asset_summary.empty else "unavailable",
        "",
        "## H4 Leverage Summary",
        "",
        best.to_markdown(index=False) if not best.empty else "unavailable",
        "",
        "## Stress Counts",
        "",
        stress_counts.to_markdown(index=False) if not stress_counts.empty else "unavailable",
        "",
        "## H3 vs H4",
        "",
        comparison.head(80).to_markdown(index=False) if not comparison.empty else "unavailable",
        "",
        "## Required Answers",
        "",
        f"1. 是否存在合格 time OOS 数据：{'是' if oos_decision.get('status') == 'success' else '否'}。",
        f"2. 如果没有 OOS，是否存在至少 3 个新增 holdout 币种：{'是' if len(holdout_quality) >= 3 else '否'}。",
        "3. 是否存在更细粒度路径数据：否，本轮未发现可用 finer path 数据。",
        f"4. H3 gate 是否在新验证层仍有效：{holdout_status}。",
        "5. G1 是否继续降低风险：见 h4_leverage_summary.csv 与 h3_vs_h4_summary.csv。",
        "6. G4 是否比直接过滤更稳：见 G4_RISK_MONITOR_DOWNSHIFT 的 validation_status 与 stress_status。",
        "7. G2 是否值得保留：仅 P6 作为对照输出，是否保留看 trade_count/PF/DD/liq。",
        "8. adaptive_3x_8x / 4x_10x / 5x_12x 哪个最稳：按 liquidation_count、max_drawdown、stress_liquidation_cases 排序。",
        "9. 1m 是否低估强平风险：无法判断，未发现 finer path 数据。",
        f"10. 是否允许进入 H5 模拟盘观察准备：{final_code in ['A', 'B']}，但 cross_asset_holdout 通过不等于 time OOS。",
        "",
        f"## Final Decision\n\n{final_code}. {final_text}",
        "",
        "## Guardrails",
        "",
        "- cross_asset_holdout != time_oos",
        "- no alpha rule changed",
        "- no H2/H3 factor reselection",
        "- no deployable strategy rule generated",
    ]
    return "\n".join(lines) + "\n"


def plot_h4_equity(equity_frames: list[pd.DataFrame], validation_dir: Path) -> None:
    frames: list[pd.DataFrame] = []
    for frame in equity_frames:
        if frame.empty:
            continue
        for _, part in frame.groupby(["symbol", "prototype", "gate", "leverage_mode"], dropna=False):
            plot_part = part.sort_values("time").copy()
            plot_part["leverage_mode"] = plot_part["gate"].astype(str) + "_" + plot_part["leverage_mode"].astype(str)
            frames.append(plot_part)
    if not frames:
        pd.DataFrame().to_csv(validation_dir / "h4_equity_plot_unavailable.csv", index=False)
        return
    plot_leverage_equity(frames, validation_dir / "h4_equity_comparison.png")
    plot_leverage_equity(frames, validation_dir / "h4_drawdown_comparison.png", kind="drawdown")


def main() -> None:
    ensure_research_dirs()
    audit_dir = RESEARCH_ROOT / "high_leverage_h4_data_audit"
    validation_dir = RESEARCH_ROOT / "high_leverage_h4_validation"
    cross_dir = RESEARCH_ROOT / "high_leverage_h4_cross_asset"
    finer_dir = RESEARCH_ROOT / "high_leverage_h4_finer_path"
    comparison_dir = RESEARCH_ROOT / "high_leverage_h4_comparison"
    for path in [audit_dir, validation_dir, cross_dir, finer_dir, comparison_dir, validation_dir / "h4_leverage_trades", validation_dir / "h4_equity_curves"]:
        path.mkdir(parents=True, exist_ok=True)

    oos_paths = candidate_csv_paths(SEARCH_ROOTS)
    oos_inventory = build_data_inventory(oos_paths)
    oos_decision = coverage_decision(oos_inventory)
    oos_inventory.to_csv(audit_dir / "h4_data_inventory.csv", index=False)
    pd.DataFrame([oos_decision]).to_csv(audit_dir / "h4_oos_quality_report.csv", index=False)
    pd.DataFrame().to_csv(audit_dir / "h4_finer_data_quality_report.csv", index=False)
    pd.DataFrame().to_csv(audit_dir / "h4_missing_ranges.csv", index=False)
    pd.DataFrame().to_csv(audit_dir / "h4_duplicate_rows.csv", index=False)
    pd.DataFrame().to_csv(audit_dir / "h4_invalid_ohlc_rows.csv", index=False)
    pd.DataFrame().to_csv(audit_dir / "h4_outlier_rows.csv", index=False)

    symbol_inventory = discover_symbol_files(HOLDOUT_PRIORITY_SYMBOLS)
    holdout_symbols = choose_holdout_symbols(symbol_inventory, max_symbols=5)
    finer_available = False
    (audit_dir / "h4_data_decision.md").write_text(write_data_decision(oos_decision, symbol_inventory, holdout_symbols, finer_available), encoding="utf-8")

    if oos_decision.get("status") != "success" and len(holdout_symbols) < 3 and not finer_available:
        pd.DataFrame().to_csv(validation_dir / "h4_leverage_summary.csv", index=False)
        pd.DataFrame().to_csv(validation_dir / "h4_stress_summary.csv", index=False)
        pd.DataFrame().to_csv(validation_dir / "h4_decision_summary.csv", index=False)
        report = write_report(oos_decision, pd.DataFrame(), pd.DataFrame(), "cross_asset_holdout_fail", pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "E", "数据不足，无法判断")
        (RESEARCH_ROOT / "reports" / "H4_oos_cross_asset_or_finer_validation_report.md").write_text(report, encoding="utf-8")
        status = "blocked"
    else:
        metadata = pd.read_csv(RESEARCH_ROOT / "family_validation" / "family_score_metadata.csv")
        discovery_scores = pd.read_parquet(RESEARCH_ROOT / "family_validation" / "family_scores.parquet")
        params = load_params(load_json(RESEARCH_ROOT.parent / "configs" / "stage4_c1_frozen.json"))
        gate_factors = pd.read_csv(RESEARCH_ROOT / "high_leverage_gate" / "h3_gate_factors.csv")
        discovery_gate_events = unique_event_labels(pd.read_csv(RESEARCH_ROOT / "high_leverage_path_safety" / "path_safety_labels.csv"))
        gate_thresholds = build_fixed_gate_thresholds(discovery_gate_events, gate_factors)

        quality_rows = []
        events_frames = []
        scores_frames = []
        assignment_frames = []
        summary_frames = []
        stress_frames = []
        liquidation_frames = []
        audit_frames = []
        equity_frames = []
        threshold_frames = []
        data_hash_payload = {}

        from research_core.cross_asset_validation_analysis import merge_symbol_1m
        from research_core.oos_validation_analysis import discovery_score_thresholds, oos_prototype_masks

        for symbol in holdout_symbols:
            paths = [Path(p) for p in symbol_inventory[symbol_inventory["symbol"] == symbol]["paths"].iloc[0].split("|") if p]
            data_hash_payload[symbol] = [file_sha256(p) for p in paths if p.exists()]
            data = merge_symbol_1m(paths)
            quality_rows.append(audit_holdout_symbol(symbol, data))
            result = run_cross_asset_symbol(symbol, paths, metadata, discovery_scores, params)
            events = result["events"].copy()
            scores = result["scores"].copy()
            thresholds = result["thresholds"].copy()
            thresholds["data_layer"] = "cross_asset_holdout"
            threshold_frames.append(thresholds)

            masks = oos_prototype_masks(scores, events, discovery_score_thresholds(discovery_scores))
            proto_events = []
            for prototype in ["P4_BREAKOUT_TOP20", "P6_MOMENTUM_OR_BREAKOUT_TOP20"]:
                part = events[masks[prototype]].copy()
                part["prototype"] = prototype
                proto_events.append(part)
            proto_events_df = pd.concat(proto_events, ignore_index=True) if proto_events else pd.DataFrame()
            proto_events_df["data_layer"] = "cross_asset_holdout"
            gate_events = build_holdout_gate_events(proto_events_df, scores, gate_factors, discovery_scores)
            assignments = gate_assignments_for_symbol(gate_events, gate_factors, gate_thresholds)

            summary, stress, liquidations, gate_audit, equity = h4_gate_backtest_symbol(
                "cross_asset_holdout",
                symbol,
                result["trades"],
                gate_events,
                gate_factors,
                gate_thresholds,
            )
            events_frames.append(gate_events)
            scores_frames.append(scores.assign(symbol=symbol, data_layer="cross_asset_holdout"))
            assignment_frames.append(assignments)
            summary_frames.append(summary)
            stress_frames.append(stress)
            if not liquidations.empty:
                liquidation_frames.append(liquidations)
            if not gate_audit.empty:
                audit_frames.append(gate_audit)
            if not equity.empty:
                equity_frames.append(equity)
            result["trades"].to_csv(validation_dir / "h4_leverage_trades" / f"{symbol}_base_prototype_trades.csv", index=False)
            equity.to_csv(validation_dir / "h4_equity_curves" / f"{symbol}_h4_equity.csv", index=False)

        quality = pd.DataFrame(quality_rows)
        events_all = pd.concat(events_frames, ignore_index=True) if events_frames else pd.DataFrame()
        scores_all = pd.concat(scores_frames, ignore_index=True) if scores_frames else pd.DataFrame()
        assignments_all = pd.concat(assignment_frames, ignore_index=True) if assignment_frames else pd.DataFrame()
        summary_all = pd.concat(summary_frames, ignore_index=True) if summary_frames else pd.DataFrame()
        stress_all = pd.concat(stress_frames, ignore_index=True) if stress_frames else pd.DataFrame()
        liquidations_all = pd.concat(liquidation_frames, ignore_index=True) if liquidation_frames else pd.DataFrame()
        audit_all = pd.concat(audit_frames, ignore_index=True) if audit_frames else pd.DataFrame()
        thresholds_all = pd.concat(threshold_frames, ignore_index=True) if threshold_frames else pd.DataFrame()

        holdout_asset_summary, holdout_status = holdout_asset_decision(summary_all)
        h3_summary = pd.read_csv(RESEARCH_ROOT / "high_leverage_gate" / "gate_leverage_summary.csv")
        comparison = h3_vs_h4_comparison(h3_summary, summary_all)
        final_code, final_text = final_h4_decision(False, holdout_status, finer_available, summary_all)

        quality.to_csv(audit_dir / "h4_cross_asset_holdout_quality_report.csv", index=False)
        events_all.to_parquet(validation_dir / "h4_validation_events.parquet", index=False)
        scores_all.to_parquet(validation_dir / "h4_validation_scores.parquet", index=False)
        assignments_all.to_csv(validation_dir / "h4_gate_assignments.csv", index=False)
        thresholds_all.to_csv(validation_dir / "h4_thresholds_used.csv", index=False)
        gate_thresholds.to_csv(validation_dir / "h4_gate_fixed_thresholds.csv", index=False)
        summary_all.to_csv(validation_dir / "h4_leverage_summary.csv", index=False)
        stress_all.to_csv(validation_dir / "h4_stress_summary.csv", index=False)
        liquidations_all.to_csv(validation_dir / "h4_liquidation_events.csv", index=False)
        audit_all.to_csv(validation_dir / "h4_gate_audit.csv", index=False)
        summary_all.to_csv(validation_dir / "h4_decision_summary.csv", index=False)
        plot_h4_equity(equity_frames, validation_dir)
        holdout_asset_summary.to_csv(cross_dir / "holdout_asset_summary.csv", index=False)
        pd.DataFrame([{"holdout_status": holdout_status, "holdout_symbol_count": len(holdout_symbols)}]).to_csv(cross_dir / "holdout_asset_decision.csv", index=False)
        pd.DataFrame().to_csv(finer_dir / "finer_path_trade_audit.csv", index=False)
        pd.DataFrame().to_csv(finer_dir / "finer_vs_1m_liquidation_diff.csv", index=False)
        pd.DataFrame([{"finer_data_available": False, "summary": "finer_path_data_unavailable"}]).to_csv(finer_dir / "finer_path_summary.csv", index=False)
        comparison.to_csv(comparison_dir / "h3_vs_h4_summary.csv", index=False)
        report = write_report(oos_decision, quality, holdout_asset_summary, holdout_status, summary_all, stress_all, comparison, final_code, final_text)
        (RESEARCH_ROOT / "reports" / "H4_oos_cross_asset_or_finer_validation_report.md").write_text(report, encoding="utf-8")
        status = "success"

    append_run_log({
        "run_id": "H4_OOS_CROSS_ASSET_OR_FINER_VALIDATION",
        "stage": "H4",
        "script": "research_core/run_high_leverage_h4_validation.py",
        "config_hash": stable_hash({
            "holdout_priority_symbols": HOLDOUT_PRIORITY_SYMBOLS,
            "h4_gates": H4_GATES,
            "h4_leverage_modes": H4_LEVERAGE_MODES,
            "time_oos_min_days": 90,
            "rules": "no alpha rule changed; cross_asset_holdout is not time OOS",
        }),
        "data_hash": stable_hash({
            "h3_gate_factors": file_sha256(RESEARCH_ROOT / "high_leverage_gate" / "h3_gate_factors.csv"),
            "h3_decision": file_sha256(RESEARCH_ROOT / "high_leverage_gate" / "h3_decision_summary.csv"),
            "holdout_symbols": holdout_symbols,
        }),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "high_leverage_validation",
        "status": status,
        "notes": "H4 OOS-first validation; uses cross_asset_holdout if time OOS unavailable; not OOS when holdout-only; no deployable strategy rule generated.",
    })


if __name__ == "__main__":
    main()
