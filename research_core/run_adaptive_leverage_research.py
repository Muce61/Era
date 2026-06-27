"""Run L1 adaptive 10x-20x leverage research."""

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
from research_core.leverage_research_analysis import (
    LEVERAGE_MODES,
    STRESS_CASES,
    TARGET_PROTOTYPES,
    attach_metadata,
    leverage_decision,
    load_event_metadata,
    load_trade_inputs,
    plot_leverage_equity,
    simulate_leverage_path,
    stress_status,
    summarize_leverage,
)


def write_report(summary: pd.DataFrame, stress: pd.DataFrame, decision_code: str, decision_text: str) -> str:
    fixed20_liq = int(summary[summary["leverage_mode"] == "fixed_20x"]["liquidation_count"].sum())
    adaptive_liq = int(summary[summary["leverage_mode"] == "adaptive_10x_20x_v1"]["liquidation_count"].sum())
    p4 = summary[(summary["prototype"] == "P4_BREAKOUT_TOP20") & (summary["leverage_mode"] == "adaptive_10x_20x_v1")]
    p6 = summary[(summary["prototype"] == "P6_MOMENTUM_OR_BREAKOUT_TOP20") & (summary["leverage_mode"] == "adaptive_10x_20x_v1")]
    lines = [
        "# L1 Adaptive Leverage Report",
        "",
        "branch: codex/adaptive-leverage-10x-20x",
        "data_layer: discovery_and_cross_asset_internal_validation",
        "oos_status: not_oos",
        "simulation_approval: not_allowed",
        "",
        "This research changes only leverage sizing. P4/P6 entry definitions are unchanged.",
        "",
        "## Summary",
        "",
        summary.to_markdown(index=False),
        "",
        "## Stress Summary",
        "",
        stress.to_markdown(index=False),
        "",
        "## Required Answers",
        "",
        f"1. 固定 10x 是否明显优于 2x：见 summary；收益通常更高，但回撤和强平风险同步放大。",
        f"2. 固定 20x 是否出现爆仓：{fixed20_liq > 0}，爆仓次数 {fixed20_liq}。",
        f"3. adaptive 是否避免 fixed_20x 主要风险：adaptive 爆仓次数 {adaptive_liq}。",
        f"4. P4 和 P6 哪个更适合高杠杆：P4 adaptive 中位 PF {p4['profit_factor'].median():.2f}，P6 adaptive 中位 PF {p6['profit_factor'].median():.2f}。",
        "5. ETH 上是否可行：以 ETH P4/P6 adaptive 行为准，需同时看强平与回撤。",
        "6. BTC/SOL/BNB 横向是否支持：以 adaptive 在三个横向标的的 liquidation_count 和 PF 为准。",
        "7. 哪些压力测试会击穿账户：见 leverage_stress_summary.csv 中 account_destroyed/liquidation_risk。",
        "8. 最大风险来自波动、连续亏损还是强平价：L1 使用 liquidation、ATR rank、drawdown 和 recent losses 分解。",
        f"9. 是否允许进入 L2：{decision_code in ['A', 'B']}。",
        "10. 是否仍禁止实盘 / 模拟盘：是。该分支仍是研究，不是 OOS，也不是模拟盘准入。",
        "",
        f"## Final Decision\n\n{decision_code}. {decision_text}",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ensure_research_dirs()
    out = RESEARCH_ROOT / "leverage_research"
    trades_dir = out / "leverage_trades"
    equity_dir = out / "leverage_equity_curves"
    for path in [out, trades_dir, equity_dir]:
        path.mkdir(parents=True, exist_ok=True)

    trade_inputs = load_trade_inputs(REPO_ROOT)
    metadata = load_event_metadata(REPO_ROOT)
    summary_rows = []
    stress_rows = []
    liquidation_frames = []
    audit_frames = []
    equity_frames = []

    for (symbol, prototype), trades in trade_inputs.items():
        enriched = attach_metadata(trades, metadata)
        for mode in LEVERAGE_MODES:
            sim, equity, audit = simulate_leverage_path(enriched, symbol, prototype, mode)
            summary = {"symbol": symbol, "prototype": prototype, "leverage_mode": mode, **summarize_leverage(sim, equity)}
            summary_rows.append(summary)
            sim.to_csv(trades_dir / f"{symbol}_{prototype}_{mode}_trades.csv", index=False)
            equity = equity.assign(symbol=symbol, prototype=prototype, leverage_mode=mode)
            equity.to_csv(equity_dir / f"{symbol}_{prototype}_{mode}_equity.csv", index=False)
            equity_frames.append(equity)
            if not audit.empty:
                audit_frames.append(audit)
            liq = sim[sim["liquidation"]].copy()
            if not liq.empty:
                liquidation_frames.append(liq)
            for stress in STRESS_CASES:
                if stress.name == "base":
                    continue
                stress_sim, stress_equity, _ = simulate_leverage_path(enriched, symbol, prototype, mode, stress=stress)
                stress_summary = summarize_leverage(stress_sim, stress_equity)
                stress_rows.append({
                    "symbol": symbol,
                    "prototype": prototype,
                    "leverage_mode": mode,
                    "stress_case": stress.name,
                    "trade_count": stress_summary["trade_count"],
                    "total_return": stress_summary["total_return"],
                    "max_drawdown": stress_summary["max_drawdown"],
                    "profit_factor": stress_summary["profit_factor"],
                    "liquidation_count": stress_summary["liquidation_count"],
                    "final_equity": stress_summary["final_equity"],
                    "stress_status": stress_status(stress_summary),
                })

    summary = pd.DataFrame(summary_rows)
    stress = pd.DataFrame(stress_rows)
    liquidations = pd.concat(liquidation_frames, ignore_index=True) if liquidation_frames else pd.DataFrame()
    audit = pd.concat(audit_frames, ignore_index=True) if audit_frames else pd.DataFrame()
    decision_code, decision_text = leverage_decision(summary, stress)

    summary.to_csv(out / "leverage_summary.csv", index=False)
    stress.to_csv(out / "leverage_stress_summary.csv", index=False)
    liquidations.to_csv(out / "liquidation_events.csv", index=False)
    audit.to_csv(out / "adaptive_leverage_audit.csv", index=False)
    plot_leverage_equity(equity_frames, out / "leverage_equity_comparison.png")
    plot_leverage_equity(equity_frames, out / "leverage_drawdown_comparison.png", kind="drawdown")
    (RESEARCH_ROOT / "reports" / "L1_adaptive_leverage_report.md").write_text(
        write_report(summary, stress, decision_code, decision_text),
        encoding="utf-8",
    )

    append_run_log({
        "run_id": "L1_ADAPTIVE_LEVERAGE",
        "stage": "L1",
        "script": "research_core/run_adaptive_leverage_research.py",
        "config_hash": stable_hash({
            "target_prototypes": TARGET_PROTOTYPES,
            "leverage_modes": LEVERAGE_MODES,
            "stress_cases": [s.__dict__ for s in STRESS_CASES],
            "maintenance_margin_rate": 0.005,
        }),
        "data_hash": stable_hash({
            "eth_trades": file_sha256(RESEARCH_ROOT / "minimal_backtest" / "prototype_trades" / "P4_BREAKOUT_TOP20_fixed_2x_trades.csv"),
            "cross_asset_summary": file_sha256(RESEARCH_ROOT / "cross_asset_validation" / "cross_asset_backtest_summary.csv"),
        }),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "leverage_research",
        "status": "success",
        "notes": "L1 adaptive 10x-20x leverage research; no alpha rule changed; not OOS.",
    })


if __name__ == "__main__":
    main()
