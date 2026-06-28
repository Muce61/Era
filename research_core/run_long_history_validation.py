"""Run LH1 ETH long-history validation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from research_core.common import RESEARCH_ROOT, append_run_log, current_git_commit, file_sha256, stable_hash
from research_core.long_history_validation_analysis import (
    build_gate_events,
    build_lh1_scores,
    event_summary,
    gate_assignments,
    load_or_build_long_events,
    plot_lh1_drawdown,
    plot_lh1_equity,
    prototype_frames,
    regime_event_summary,
    run_minimal_backtests,
    run_strict_lh1,
    walk_forward_strict_lh1,
    year_quarter_trade_summary,
    yearly_event_summary,
)
from research_core.minimal_backtest_analysis import load_params


LONG_DATA = Path("/Users/muce/1m_data/long_history_1m/merged/ETHUSDT.csv")
OUT = RESEARCH_ROOT / "long_history_validation"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_report(
    event_sum: pd.DataFrame,
    backtest: pd.DataFrame,
    yearly: pd.DataFrame,
    strict: pd.DataFrame,
    wf: pd.DataFrame,
    final_code: str,
    final_text: str,
) -> None:
    fixed = backtest[backtest["sizing_mode"] == "fixed_2x"].copy()
    strict_focus = strict[strict["leverage_mode"].isin(["fixed_20x", "adaptive_3x_8x_v1"])].copy()
    lines = [
        "# LH1 ETH Long History Validation Report",
        "",
        "data_layer: expanded_discovery",
        "oos_status: not_oos",
        "deployable_strategy_generated: false",
        "data_range: 2020-01-01 00:00 UTC to 2026-06-28 01:05 UTC",
        "",
        "This stage reuses fixed discovery score thresholds and fixed H3 gate thresholds. It does not optimize alpha, gates, leverage, Donchian, EMA, or ATR parameters.",
        "",
        "## Event Summary",
        "",
        event_sum.to_markdown(index=False),
        "",
        "## Fixed 2x Backtest Summary",
        "",
        fixed.to_markdown(index=False),
        "",
        "## Yearly Backtest Summary",
        "",
        yearly.to_markdown(index=False),
        "",
        "## Strict Replay Focus",
        "",
        strict_focus.to_markdown(index=False),
        "",
        "## Walk Forward Summary",
        "",
        wf.to_markdown(index=False),
        "",
        "## Required Answers",
        "",
        "1. P4/P6 在 6.5 年 ETH 长历史中是否仍有效：见 fixed_2x summary 的 total_return、PF、DD。",
        "2. P4/P6 是否优于 P1/P2：比较 fixed_2x summary。",
        "3. 2020-2023 是否支持 2024-2026 的结论：见 yearly summary。",
        "4. 2022 熊市是否失效：见 2022 yearly rows。",
        "5. 是否存在连续失效年份：见 yearly PF 和 return。",
        "6. 收益是否过度集中：见 top1/top3/top5/top10 contribution。",
        "7. fixed_10x / fixed_20x 是否仍不可接受：见 strict replay liquidation_count 和 max_drawdown。",
        "8. adaptive_3x_8x 是否仍最稳：见 strict replay 和 walk-forward。",
        "9. G1/G4 path gate 是否继续有效：比较 G0/G1/G4 strict replay。",
        "10. 是否允许进入下一步：只允许进入 OOS / 模拟盘前准备，不允许实盘结论。",
        "",
        f"## Final Decision\n\n{final_code}. {final_text}",
        "",
        "## Guardrails",
        "",
        "- ETH long history validation",
        "- no alpha rule changed",
        "- fixed discovery thresholds",
        "- not OOS",
        "- no deployable strategy rule generated",
    ]
    (RESEARCH_ROOT / "reports" / "LH1_eth_long_history_validation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def decide(backtest: pd.DataFrame, strict: pd.DataFrame, wf: pd.DataFrame) -> tuple[str, str]:
    fixed = backtest[backtest["sizing_mode"] == "fixed_2x"].set_index("prototype")
    p4_ok = "P4_BREAKOUT_TOP20" in fixed.index and fixed.loc["P4_BREAKOUT_TOP20", "profit_factor"] > 1.1 and fixed.loc["P4_BREAKOUT_TOP20", "total_return"] > 0
    p6_ok = "P6_MOMENTUM_OR_BREAKOUT_TOP20" in fixed.index and fixed.loc["P6_MOMENTUM_OR_BREAKOUT_TOP20", "profit_factor"] > 1.1 and fixed.loc["P6_MOMENTUM_OR_BREAKOUT_TOP20", "total_return"] > 0
    adaptive = strict[strict["leverage_mode"] == "adaptive_3x_8x_v1"]
    fixed20 = strict[strict["leverage_mode"] == "fixed_20x"]
    adaptive_no_liq = not adaptive.empty and int(adaptive["liquidation_count"].sum()) == 0
    fixed20_bad = not fixed20.empty and int(fixed20["liquidation_count"].sum()) > 0
    wf_adaptive = wf[(wf["leverage_mode"] == "adaptive_3x_8x_v1") & (wf["gate"].isin(["G1_SINGLE_BEST_PATH_SAFETY", "G4_RISK_MONITOR_DOWNSHIFT"]))]
    wf_ok = not wf_adaptive.empty and (wf_adaptive["walk_forward_status"].isin(["wf_pass", "wf_weak"])).any()
    if (p4_ok or p6_ok) and adaptive_no_liq and wf_ok:
        return "A", "长历史支持 P4/P6 + path gate，可进入 OOS / 模拟盘前准备"
    if (p4_ok or p6_ok) and adaptive_no_liq:
        return "B", "长历史部分支持，但仍有年份/周期脆弱性"
    if p4_ok or p6_ok:
        return "C", "长历史显示收益主要来自特定周期，需要降级"
    if fixed20_bad:
        return "D", "长历史显示高杠杆风险不可控，应停止高杠杆策略化"
    return "E", "数据或实现问题导致无法判断"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "lh1_trades").mkdir(exist_ok=True)
    (OUT / "lh1_equity_curves").mkdir(exist_ok=True)
    (OUT / "lh1_strict_trades").mkdir(exist_ok=True)
    (OUT / "lh1_strict_equity_curves").mkdir(exist_ok=True)
    (RESEARCH_ROOT / "reports").mkdir(exist_ok=True)

    if not LONG_DATA.exists():
        raise FileNotFoundError(f"Missing ETH long history data: {LONG_DATA}")

    metadata = pd.read_csv(RESEARCH_ROOT / "family_validation" / "family_score_metadata.csv")
    discovery_scores = pd.read_parquet(RESEARCH_ROOT / "family_validation" / "family_scores.parquet")
    gate_factors = pd.read_csv(RESEARCH_ROOT / "high_leverage_gate" / "h3_gate_factors.csv")
    gate_thresholds = pd.read_csv(RESEARCH_ROOT / "high_leverage_h4_validation" / "h4_gate_fixed_thresholds.csv")
    config = load_json(RESEARCH_ROOT.parent / "configs" / "stage4_c1_frozen.json")
    params = load_params(config)

    data_1m, data_15m, events = load_or_build_long_events(
        LONG_DATA,
        RESEARCH_ROOT / "long_history_data" / "ETHUSDT_long_history_event_candidates.parquet",
    )
    scores, score_check = build_lh1_scores(events, metadata, discovery_scores)
    frames, score_thresholds = prototype_frames(events, scores, discovery_scores)
    gate_events = build_gate_events(events, scores, discovery_scores)
    assignments = gate_assignments(gate_events, gate_factors, gate_thresholds)

    events.to_parquet(OUT / "lh1_events.parquet", index=False)
    scores.to_parquet(OUT / "lh1_scores.parquet", index=False)
    assignments.to_csv(OUT / "lh1_gate_assignments.csv", index=False)
    pd.concat([
        score_thresholds.assign(threshold_type="prototype_score"),
        gate_thresholds.assign(threshold_type="path_gate"),
    ], ignore_index=True, sort=False).to_csv(OUT / "lh1_thresholds_used.csv", index=False)
    score_check.to_csv(OUT / "lh1_score_distribution_check.csv", index=False)

    ev_summary = event_summary(frames)
    ev_yearly = yearly_event_summary(frames)
    ev_regime = regime_event_summary(frames)
    ev_summary.to_csv(OUT / "lh1_event_summary.csv", index=False)
    ev_yearly.to_csv(OUT / "lh1_yearly_event_summary.csv", index=False)
    ev_regime.to_csv(OUT / "lh1_regime_event_summary.csv", index=False)

    backtest_summary, trades_all, equity_frames = run_minimal_backtests(frames, data_1m, data_15m, params, OUT)
    yearly_bt, quarterly_bt = year_quarter_trade_summary(trades_all, params.initial_balance)
    backtest_summary.to_csv(OUT / "lh1_backtest_summary.csv", index=False)
    yearly_bt.to_csv(OUT / "lh1_yearly_backtest_summary.csv", index=False)
    quarterly_bt.to_csv(OUT / "lh1_quarterly_backtest_summary.csv", index=False)
    plot_lh1_equity(equity_frames, OUT / "lh1_equity_comparison.png")
    plot_lh1_drawdown(equity_frames, OUT / "lh1_drawdown_comparison.png")

    strict_summary, strict_liq, strict_proxy = run_strict_lh1(gate_events, gate_factors, gate_thresholds, data_1m, data_15m, OUT)
    strict_summary.to_csv(OUT / "lh1_strict_replay_summary.csv", index=False)
    strict_liq.to_csv(OUT / "lh1_strict_liquidation_events.csv", index=False)
    strict_proxy.to_csv(OUT / "lh1_strict_vs_proxy_comparison.csv", index=False)

    wf_windows, wf_summary = walk_forward_strict_lh1(gate_events, gate_factors, gate_thresholds, data_1m, data_15m)
    wf_windows.to_csv(OUT / "lh1_walk_forward_windows.csv", index=False)
    wf_summary.to_csv(OUT / "lh1_walk_forward_summary.csv", index=False)

    final_code, final_text = decide(backtest_summary, strict_summary, wf_summary)
    write_report(ev_summary, backtest_summary, yearly_bt, strict_summary, wf_summary, final_code, final_text)

    run_ts = datetime.now(timezone.utc).isoformat()
    append_run_log({
        "run_id": "LH1_ETH_LONG_HISTORY_VALIDATION",
        "stage": "LH1",
        "script": "research_core.run_long_history_validation",
        "config_hash": stable_hash({
            "prototypes": list(frames),
            "gates": ["G0_NO_PATH_GATE", "G1_SINGLE_BEST_PATH_SAFETY", "G4_RISK_MONITOR_DOWNSHIFT"],
            "fixed_thresholds": True,
        }),
        "data_hash": file_sha256(LONG_DATA),
        "git_commit": current_git_commit(),
        "run_timestamp": run_ts,
        "random_seed": 20260624,
        "data_layer": "expanded_discovery",
        "status": "success",
        "notes": "ETH long history validation; no alpha rule changed; fixed discovery thresholds; not OOS; no deployable strategy rule generated",
    })


if __name__ == "__main__":
    main()
