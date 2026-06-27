"""Run L2 conservative adaptive leverage research."""

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
    L2_LEVERAGE_MODES,
    STRESS_CASES,
    TARGET_PROTOTYPES,
    attach_metadata,
    load_event_metadata,
    load_trade_inputs,
    plot_leverage_equity,
    simulate_leverage_path,
    stress_status,
    summarize_leverage,
)


def l2_decision(summary: pd.DataFrame, stress: pd.DataFrame) -> tuple[str, str]:
    adaptive_modes = ["adaptive_3x_8x_v1", "adaptive_4x_10x_v1", "adaptive_5x_12x_v1"]
    baseline_eth = summary[(summary["symbol"] == "ETHUSDT") & (summary["leverage_mode"] == "baseline_fixed_2x")]
    baseline_final = baseline_eth["final_equity"].max()
    critical_stress = stress[stress["stress_case"].isin(["fee_2x", "slippage_2x", "liquidation_price_up_10pct"])]
    passed_modes = []
    partial_modes = []

    for mode in adaptive_modes:
        mode_summary = summary[summary["leverage_mode"] == mode]
        eth = mode_summary[mode_summary["symbol"] == "ETHUSDT"]
        eth_ok = (
            (eth["final_equity"] > baseline_final)
            & (eth["max_drawdown"] >= -0.30)
            & (eth["liquidation_count"] == 0)
            & (eth["profit_factor"] > 1.3)
        ).any()
        cross = mode_summary[mode_summary["symbol"].isin(["BTCUSDT", "SOLUSDT", "BNBUSDT"])]
        cross_ok = (
            int((cross["liquidation_count"] == 0).sum()) >= 2
            and int((cross["profit_factor"] > 1.2).sum()) >= 2
            and (cross["max_drawdown"] >= -0.40).all()
        )
        critical = critical_stress[critical_stress["leverage_mode"] == mode]
        stress_ok = critical["liquidation_count"].sum() == 0 if not critical.empty else False
        has_liq = mode_summary["liquidation_count"].sum() > 0
        if eth_ok and cross_ok and stress_ok and not has_liq:
            passed_modes.append(mode)
        elif eth_ok and not has_liq:
            partial_modes.append(mode)

    if passed_modes:
        return "A", f"{', '.join(passed_modes)} 通过风险约束，可进入 L3"
    if partial_modes:
        return "B", f"{', '.join(partial_modes)} 有一定价值，但还需进一步降杠杆或补充验证"

    fixed = summary[summary["leverage_mode"].isin(["fixed_3x", "fixed_5x"])]
    fixed_ok = (
        (fixed["liquidation_count"] == 0).all()
        and (fixed["profit_factor"] > 1.2).any()
        and (fixed["max_drawdown"] >= -0.40).all()
    )
    if fixed_ok:
        return "C", "只有 fixed_3x / fixed_5x 具备研究价值"
    return "D", "所有高杠杆方案风险调整后都不如 2x"


def write_report(summary: pd.DataFrame, stress: pd.DataFrame, decision_code: str, decision_text: str) -> str:
    adaptive = summary[summary["leverage_mode"].str.startswith("adaptive_")]
    fixed = summary[summary["leverage_mode"].str.startswith("fixed_")]
    stress_counts = stress.groupby(["leverage_mode", "stress_status"]).size().reset_index(name="count")
    liq_by_mode = summary.groupby("leverage_mode")["liquidation_count"].sum().reset_index()
    fixed_best = fixed.sort_values(["liquidation_count", "max_drawdown", "profit_factor"], ascending=[True, False, False]).head(1)
    p4 = adaptive[adaptive["prototype"] == "P4_BREAKOUT_TOP20"]
    p6 = adaptive[adaptive["prototype"] == "P6_MOMENTUM_OR_BREAKOUT_TOP20"]
    weakest = stress[stress["stress_status"].isin(["stress_fragile", "liquidation_risk", "account_destroyed"])]
    weakest_counts = weakest.groupby("stress_case").size().sort_values(ascending=False).reset_index(name="count")
    lines = [
        "# L2 Conservative Adaptive Leverage Report",
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
        "## Liquidation By Mode",
        "",
        liq_by_mode.to_markdown(index=False),
        "",
        "## Stress Status Counts",
        "",
        stress_counts.to_markdown(index=False),
        "",
        "## Required Answers",
        "",
        f"1. 降低杠杆上限后，爆仓是否消失：总爆仓/强风险次数见 Liquidation By Mode；adaptive 合计 {int(adaptive['liquidation_count'].sum())}。",
        f"2. fixed_3x / fixed_5x / fixed_8x / fixed_10x 哪个风险收益最好：按无强平、回撤、PF 排序，当前首位是 {fixed_best['leverage_mode'].iloc[0] if not fixed_best.empty else 'unavailable'}。",
        "3. adaptive_3x_8x 是否明显优于 fixed_2x：见 summary 中 ETH 与横向标的对比。",
        "4. adaptive_4x_10x 是否还能保持无爆仓：见 Liquidation By Mode。",
        "5. adaptive_5x_12x 是否仍然过激：见 max_drawdown、liquidation_count 和压力测试。",
        f"6. P4 和 P6 哪个更适合保守高杠杆：P4 adaptive 中位 PF {p4['profit_factor'].median():.2f}，P6 adaptive 中位 PF {p6['profit_factor'].median():.2f}。",
        "7. ETH 上是否可行：以 ETH P4/P6 各 adaptive 的回撤、PF、liquidation_count 为准。",
        "8. BTC/SOL/BNB 横向是否支持：以三标的 adaptive liquidation_count、PF、max_drawdown 为准。",
        f"9. 压力测试中最脆弱的是：{weakest_counts.to_dict(orient='records') if not weakest_counts.empty else 'none'}。",
        f"10. 是否允许进入 L3：{decision_code == 'A'}。",
        "",
        f"## Final Decision\n\n{decision_code}. {decision_text}",
        "",
        "## Guardrails",
        "",
        "- no alpha rule changed",
        "- not OOS",
        "- no deployable strategy rule generated",
    ]
    return "\n".join(lines)


def main() -> None:
    ensure_research_dirs()
    out = RESEARCH_ROOT / "leverage_research_l2"
    trades_dir = out / "leverage_l2_trades"
    equity_dir = out / "leverage_l2_equity_curves"
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
        for mode in L2_LEVERAGE_MODES:
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
    decision_code, decision_text = l2_decision(summary, stress)

    summary.to_csv(out / "leverage_l2_summary.csv", index=False)
    stress.to_csv(out / "leverage_l2_stress_summary.csv", index=False)
    liquidations.to_csv(out / "liquidation_events_l2.csv", index=False)
    audit.to_csv(out / "adaptive_leverage_l2_audit.csv", index=False)
    plot_leverage_equity(equity_frames, out / "leverage_l2_equity_comparison.png")
    plot_leverage_equity(equity_frames, out / "leverage_l2_drawdown_comparison.png", kind="drawdown")
    (RESEARCH_ROOT / "reports" / "L2_conservative_adaptive_leverage_report.md").write_text(
        write_report(summary, stress, decision_code, decision_text),
        encoding="utf-8",
    )

    append_run_log({
        "run_id": "L2_CONSERVATIVE_ADAPTIVE_LEVERAGE",
        "stage": "L2",
        "script": "research_core/run_conservative_adaptive_leverage.py",
        "config_hash": stable_hash({
            "target_prototypes": TARGET_PROTOTYPES,
            "leverage_modes": L2_LEVERAGE_MODES,
            "stress_cases": [s.__dict__ for s in STRESS_CASES],
            "maintenance_margin_rate": 0.005,
        }),
        "data_hash": stable_hash({
            "l1_summary": file_sha256(RESEARCH_ROOT / "leverage_research" / "leverage_summary.csv"),
            "l1_stress": file_sha256(RESEARCH_ROOT / "leverage_research" / "leverage_stress_summary.csv"),
            "eth_trades": file_sha256(RESEARCH_ROOT / "minimal_backtest" / "prototype_trades" / "P4_BREAKOUT_TOP20_fixed_2x_trades.csv"),
            "cross_asset_summary": file_sha256(RESEARCH_ROOT / "cross_asset_validation" / "cross_asset_backtest_summary.csv"),
        }),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "leverage_research",
        "status": "success",
        "notes": "L2 conservative adaptive leverage research; no alpha rule changed; not OOS; no deployable strategy rule generated.",
    })


if __name__ == "__main__":
    main()
