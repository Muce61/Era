"""Run H3 high-leverage path-safety gate research."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from research_core.common import (
    RANDOM_SEED,
    REPO_ROOT,
    RESEARCH_ROOT,
    append_run_log,
    current_git_commit,
    ensure_research_dirs,
    file_sha256,
    stable_hash,
)
from research_core.high_leverage_gate_analysis import (
    H3_GATES,
    H3_LEVERAGE_MODES,
    build_incremental,
    coverage_status,
    eligible_factors,
    enrich_trades_with_gate_metadata,
    factor_ranks,
    gate_mask,
    h3_decision_status,
    high_risk_mask,
    load_h3_trade_inputs,
    plot_leverage_equity,
    simulate_gate_leverage_path,
    unique_event_labels,
    write_h3_report,
)
from research_core.leverage_research_analysis import STRESS_CASES, stress_status, summarize_leverage


def blocked_outputs(out, reason: str) -> None:
    empty_coverage = pd.DataFrame(columns=[
        "symbol",
        "prototype",
        "gate",
        "original_event_count",
        "accepted_event_count",
        "rejected_event_count",
        "acceptance_rate",
        "rejected_failure_case_count",
        "failure_case_rejection_rate",
        "avg_breakout_score_accepted",
        "avg_momentum_score_accepted",
        "avg_atr_pct_accepted",
        "coverage_status",
    ])
    empty_summary = pd.DataFrame(columns=[
        "symbol",
        "prototype",
        "gate",
        "leverage_mode",
        "trade_count",
        "total_return",
        "annualized_return",
        "max_drawdown",
        "profit_factor",
        "liquidation_count",
        "final_equity",
    ])
    empty_coverage.to_csv(out / "gate_coverage_summary.csv", index=False)
    empty_summary.to_csv(out / "gate_leverage_summary.csv", index=False)
    pd.DataFrame().to_csv(out / "gate_incremental_risk_reduction.csv", index=False)
    pd.DataFrame().to_csv(out / "gate_leverage_stress_summary.csv", index=False)
    pd.DataFrame([{
        "symbol": "",
        "prototype": "",
        "gate": "",
        "leverage_mode": "",
        "decision_status": "gate_unavailable",
        "allowed_next_step": "discard",
        "notes": reason,
    }]).to_csv(out / "h3_decision_summary.csv", index=False)
    pd.DataFrame().to_csv(out / "gate_liquidation_events.csv", index=False)
    pd.DataFrame().to_csv(out / "gate_adaptive_audit.csv", index=False)
    (RESEARCH_ROOT / "reports" / "H3_high_leverage_gate_report.md").write_text(
        "# H3 High Leverage Gate Report\n\n"
        "data_layer: high_leverage_research\n"
        "oos_status: not_oos\n"
        "simulation_approval: not_allowed\n\n"
        f"## Final Decision\n\nE. {reason}\n\n"
        "No deployable strategy rule generated.\n",
        encoding="utf-8",
    )


def final_decision(decision: pd.DataFrame, incremental: pd.DataFrame) -> tuple[str, str]:
    if decision.empty:
        return "E", "当前实现或数据不足，无法判断"
    if (decision["decision_status"] == "candidate_for_H4_oos_or_finer_data_validation").any():
        return "A", "路径安全 gate 显著降低高杠杆风险，可进入 H4"
    if (decision["decision_status"] == "risk_monitor_only").any():
        return "B", "gate 有风险控制价值，但更适合作为降杠杆 risk monitor"
    if (incremental["risk_reduction_status"] == "return_too_damaged").any():
        return "C", "gate 过度损伤收益，不适合作为准入条件"
    if (decision["decision_status"] == "unsafe_high_leverage").any():
        return "D", "当前因子仍无法控制 10x-20x 风险，应停止高杠杆策略化"
    return "E", "当前实现或数据不足，无法判断"


def main() -> None:
    ensure_research_dirs()
    out = RESEARCH_ROOT / "high_leverage_gate"
    trades_dir = out / "gate_leverage_trades"
    equity_dir = out / "gate_equity_curves"
    for path in [out, trades_dir, equity_dir]:
        path.mkdir(parents=True, exist_ok=True)

    decision_h2 = pd.read_csv(RESEARCH_ROOT / "high_leverage_path_safety_h2" / "h2_decision_summary.csv")
    role = pd.read_csv(RESEARCH_ROOT / "high_leverage_path_safety_h2" / "factor_role_decomposition.csv")
    boot = pd.read_csv(RESEARCH_ROOT / "high_leverage_path_safety_h2" / "path_safety_bootstrap_summary.csv")
    stress_h2 = pd.read_csv(RESEARCH_ROOT / "high_leverage_path_safety_h2" / "path_safety_stress_summary.csv")
    horizon = pd.read_csv(RESEARCH_ROOT / "high_leverage_path_safety_h2" / "horizon_consistency_summary.csv")
    failure_explain = pd.read_csv(RESEARCH_ROOT / "high_leverage_path_safety_h2" / "failure_case_explainability.csv")
    factors = eligible_factors(decision_h2, role, boot, stress_h2, horizon, failure_explain)

    if factors.empty:
        blocked_outputs(out, "没有稳定路径安全因子，不能构建高杠杆准入原型")
        status = "blocked"
    else:
        labels = unique_event_labels(pd.read_csv(RESEARCH_ROOT / "high_leverage_path_safety" / "path_safety_labels.csv"))
        labels = factor_ranks(labels, factors["factor"].unique().tolist())
        failures = pd.read_csv(RESEARCH_ROOT / "high_leverage_path_safety" / "high_leverage_failure_cases.csv")
        trade_inputs = load_h3_trade_inputs(REPO_ROOT)

        coverage_rows = []
        summary_rows = []
        stress_rows = []
        decision_rows = []
        liquidation_frames = []
        audit_frames = []
        equity_frames = []

        for (symbol, prototype), trades in trade_inputs.items():
            event_part = labels[(labels["symbol"] == symbol) & (labels["prototype"] == prototype)].copy()
            if event_part.empty:
                continue
            event_part = event_part.reset_index(drop=True)
            failure_keys = set(
                failures[(failures["symbol"] == symbol) & (failures["prototype"] == prototype)]["event_id"].dropna().astype(str)
            )
            for gate in H3_GATES:
                mask, availability = gate_mask(event_part, factors, prototype, gate)
                accepted_events = event_part.loc[mask, "event_id"].astype(str).tolist()
                high_risk = high_risk_mask(event_part, factors, prototype)
                event_with_risk = event_part.assign(gate_high_risk=high_risk)
                accepted_set = set(accepted_events)
                rejected_failure_count = len(failure_keys - accepted_set) if gate != "G4_RISK_MONITOR_DOWNSHIFT" else 0
                failure_case_count = len(failure_keys)
                acceptance_rate = float(mask.mean()) if len(mask) else 0.0
                status = coverage_status(gate, availability, acceptance_rate)
                accepted_frame = event_part.loc[mask]
                coverage_rows.append({
                    "symbol": symbol,
                    "prototype": prototype,
                    "gate": gate,
                    "original_event_count": int(len(event_part)),
                    "accepted_event_count": int(mask.sum()) if availability != "gate_unavailable" else 0,
                    "rejected_event_count": int((~mask).sum()) if availability != "gate_unavailable" else int(len(event_part)),
                    "acceptance_rate": acceptance_rate if availability != "gate_unavailable" else 0.0,
                    "rejected_failure_case_count": int(rejected_failure_count),
                    "failure_case_rejection_rate": float(rejected_failure_count / failure_case_count) if failure_case_count else 0.0,
                    "avg_breakout_score_accepted": float(accepted_frame["breakout_score_quantile"].mean()) if not accepted_frame.empty else float("nan"),
                    "avg_momentum_score_accepted": float(accepted_frame["momentum_score_quantile"].mean()) if not accepted_frame.empty else float("nan"),
                    "avg_atr_pct_accepted": float(accepted_frame["atr_pct"].mean()) if not accepted_frame.empty else float("nan"),
                    "coverage_status": status,
                })
                enriched = enrich_trades_with_gate_metadata(trades.copy(), event_with_risk)
                if gate != "G4_RISK_MONITOR_DOWNSHIFT":
                    enriched = enriched[enriched["event_id"].astype(str).isin(accepted_set)].copy()
                else:
                    risk_map = event_with_risk.set_index("event_id")["gate_high_risk"].to_dict()
                    enriched["gate_high_risk"] = enriched["event_id"].map(risk_map).fillna(False)

                for mode in H3_LEVERAGE_MODES:
                    if availability == "gate_unavailable":
                        sim = pd.DataFrame()
                        equity = pd.DataFrame([{"time": "", "equity": 1000.0}])
                        audit = pd.DataFrame()
                    else:
                        sim, equity, audit = simulate_gate_leverage_path(enriched, symbol, prototype, gate, mode)
                    summary = {
                        "symbol": symbol,
                        "prototype": prototype,
                        "gate": gate,
                        "leverage_mode": mode,
                        **summarize_leverage(sim, equity),
                        "coverage_status": status,
                    }
                    summary_rows.append(summary)
                    sim.to_csv(trades_dir / f"{symbol}_{prototype}_{gate}_{mode}_trades.csv", index=False)
                    equity = equity.assign(symbol=symbol, prototype=prototype, gate=gate, leverage_mode=mode)
                    equity.to_csv(equity_dir / f"{symbol}_{prototype}_{gate}_{mode}_equity.csv", index=False)
                    equity_frames.append(equity)
                    if not sim.empty and "liquidation" in sim:
                        liq = sim[sim["liquidation"]].copy()
                        if not liq.empty:
                            liquidation_frames.append(liq)
                    if not audit.empty:
                        audit_frames.append(audit)

                    for stress in STRESS_CASES:
                        if stress.name == "base":
                            continue
                        if availability == "gate_unavailable":
                            stress_summary = {"trade_count": 0, "total_return": 0.0, "max_drawdown": 0.0, "profit_factor": float("nan"), "liquidation_count": 0, "final_equity": 1000.0}
                            stress_case_status = "gate_unavailable"
                        else:
                            stress_sim, stress_equity, _ = simulate_gate_leverage_path(enriched, symbol, prototype, gate, mode, stress=stress)
                            stress_summary = summarize_leverage(stress_sim, stress_equity)
                            stress_case_status = stress_status(stress_summary)
                        stress_rows.append({
                            "symbol": symbol,
                            "prototype": prototype,
                            "gate": gate,
                            "leverage_mode": mode,
                            "stress_case": stress.name,
                            "trade_count": stress_summary["trade_count"],
                            "total_return": stress_summary["total_return"],
                            "max_drawdown": stress_summary["max_drawdown"],
                            "profit_factor": stress_summary["profit_factor"],
                            "liquidation_count": stress_summary["liquidation_count"],
                            "final_equity": stress_summary["final_equity"],
                            "stress_status": stress_case_status,
                        })

        coverage = pd.DataFrame(coverage_rows)
        summary = pd.DataFrame(summary_rows)
        stress = pd.DataFrame(stress_rows)
        incremental = build_incremental(summary)
        liquidations = pd.concat(liquidation_frames, ignore_index=True) if liquidation_frames else pd.DataFrame()
        audit = pd.concat(audit_frames, ignore_index=True) if audit_frames else pd.DataFrame()

        for _, row in summary.iterrows():
            gate = row["gate"]
            cov = coverage[
                (coverage["symbol"] == row["symbol"])
                & (coverage["prototype"] == row["prototype"])
                & (coverage["gate"] == gate)
            ]
            acceptance = float(cov.iloc[0]["acceptance_rate"]) if not cov.empty else 0.0
            critical = stress[
                (stress["symbol"] == row["symbol"])
                & (stress["prototype"] == row["prototype"])
                & (stress["gate"] == gate)
                & (stress["leverage_mode"] == row["leverage_mode"])
                & (stress["stress_case"].isin(["fee_2x", "slippage_2x", "liquidation_price_up_10pct"]))
            ]
            stress_liq = int(critical["liquidation_count"].sum()) if not critical.empty else 0
            cross = summary[
                (summary["prototype"] == row["prototype"])
                & (summary["gate"] == gate)
                & (summary["leverage_mode"] == row["leverage_mode"])
                & (summary["symbol"].isin(["BTCUSDT", "SOLUSDT", "BNBUSDT"]))
            ]
            cross_ok = (
                int((cross["liquidation_count"] == 0).sum()) >= 2
                and int((cross["profit_factor"] > 1.2).sum()) >= 2
                and (cross["max_drawdown"] >= -0.45).all()
            )
            decision_status, next_step = h3_decision_status(row, stress_liq, acceptance, cross_ok)
            decision_rows.append({
                "symbol": row["symbol"],
                "prototype": row["prototype"],
                "gate": gate,
                "leverage_mode": row["leverage_mode"],
                "trade_count": row["trade_count"],
                "total_return": row["total_return"],
                "max_drawdown": row["max_drawdown"],
                "profit_factor": row["profit_factor"],
                "liquidation_count": row["liquidation_count"],
                "stress_liquidation_cases": stress_liq,
                "final_equity": row["final_equity"],
                "decision_status": decision_status,
                "allowed_next_step": next_step,
            })
        decision = pd.DataFrame(decision_rows)
        final_code, final_text = final_decision(decision, incremental)

        factors.to_csv(out / "h3_gate_factors.csv", index=False)
        coverage.to_csv(out / "gate_coverage_summary.csv", index=False)
        summary.to_csv(out / "gate_leverage_summary.csv", index=False)
        incremental.to_csv(out / "gate_incremental_risk_reduction.csv", index=False)
        stress.to_csv(out / "gate_leverage_stress_summary.csv", index=False)
        decision.to_csv(out / "h3_decision_summary.csv", index=False)
        liquidations.to_csv(out / "gate_liquidation_events.csv", index=False)
        audit.to_csv(out / "gate_adaptive_audit.csv", index=False)
        plottable_equity = [
            frame for frame in equity_frames
            if not frame.empty and pd.to_datetime(frame["time"], utc=True, errors="coerce").notna().any()
        ]
        plot_leverage_equity(plottable_equity, out / "gate_equity_comparison.png")
        plot_leverage_equity(plottable_equity, out / "gate_drawdown_comparison.png", kind="drawdown")
        (RESEARCH_ROOT / "reports" / "H3_high_leverage_gate_report.md").write_text(
            write_h3_report(factors, coverage, summary, incremental, stress, decision, final_code, final_text),
            encoding="utf-8",
        )
        status = "success"

    append_run_log({
        "run_id": "H3_HIGH_LEVERAGE_GATE",
        "stage": "H3",
        "script": "research_core/run_high_leverage_gate.py",
        "config_hash": stable_hash({
            "gates": H3_GATES,
            "leverage_modes": H3_LEVERAGE_MODES,
            "stress_cases": [s.__dict__ for s in STRESS_CASES],
            "candidate_rule": "H2 eligible path-safety factors only",
        }),
        "data_hash": stable_hash({
            "h2_decision": file_sha256(RESEARCH_ROOT / "high_leverage_path_safety_h2" / "h2_decision_summary.csv"),
            "path_safety_labels": file_sha256(RESEARCH_ROOT / "high_leverage_path_safety" / "path_safety_labels.csv"),
            "l2_summary": file_sha256(RESEARCH_ROOT / "leverage_research_l2" / "leverage_l2_summary.csv"),
        }),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "high_leverage_research",
        "status": status,
        "notes": "H3 high leverage path safety gate; no alpha rule changed; path safety gate research only; not OOS; no deployable strategy rule generated.",
    })


if __name__ == "__main__":
    main()
