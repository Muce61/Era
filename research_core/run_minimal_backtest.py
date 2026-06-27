"""Run Research Core R8 minimal prototype backtest."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from research_core.common import (
    DISCOVERY_DATA_PATH,
    RANDOM_SEED,
    RESEARCH_ROOT,
    append_run_log,
    current_git_commit,
    ensure_research_dirs,
    file_sha256,
    stable_hash,
)
from research_core.minimal_backtest_analysis import (
    R8_PROTOTYPES,
    SIZING_MODES,
    event_to_trade_consistency,
    enrich_events_with_exit_info,
    load_params,
    period_trade_summary,
    plot_drawdown_curves,
    plot_equity_curves,
    prepare_market_data,
    prototype_event_frames,
    r8_decision_summary,
    run_prototype_backtest,
    summarize_backtest,
    trade_stability_summary,
    trade_tail_dependence,
    walk_forward_backtest,
)


REQUIRED_INPUTS = [
    RESEARCH_ROOT / "events" / "event_candidates.parquet",
    RESEARCH_ROOT / "family_validation" / "family_scores.parquet",
    RESEARCH_ROOT / "family_validation" / "family_score_metadata.csv",
    RESEARCH_ROOT / "prototypes" / "prototype_decision_summary.csv",
    RESEARCH_ROOT / "prototypes" / "prototype_event_summary.csv",
    RESEARCH_ROOT / "prototypes" / "prototype_incremental_attribution.csv",
    RESEARCH_ROOT / "prototypes" / "prototype_tail_dependence.csv",
    RESEARCH_ROOT / "logs" / "run_log.csv",
]
CONFIG_INPUTS = [
    "configs/stage2_b1_frozen.json",
    "configs/stage2_b2_frozen.json",
    "configs/stage2_b3_frozen.json",
    "configs/stage4_c1_frozen.json",
]


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_inputs():
    missing = [str(path) for path in REQUIRED_INPUTS if not path.exists()]
    missing += [path for path in CONFIG_INPUTS if not (RESEARCH_ROOT.parent / path).exists()]
    if missing:
        raise FileNotFoundError("Missing R8 inputs: " + ", ".join(missing))
    events = pd.read_parquet(RESEARCH_ROOT / "events" / "event_candidates.parquet")
    scores = pd.read_parquet(RESEARCH_ROOT / "family_validation" / "family_scores.parquet")
    metadata = pd.read_csv(RESEARCH_ROOT / "family_validation" / "family_score_metadata.csv")
    r7_event = pd.read_csv(RESEARCH_ROOT / "prototypes" / "prototype_event_summary.csv")
    r7_decision = pd.read_csv(RESEARCH_ROOT / "prototypes" / "prototype_decision_summary.csv")
    c1_config = load_json(RESEARCH_ROOT.parent / "configs" / "stage4_c1_frozen.json")
    events["signal_time"] = pd.to_datetime(events["signal_time"], utc=True)
    events["execution_time"] = pd.to_datetime(events["execution_time"], utc=True)
    scores["signal_time"] = pd.to_datetime(scores["signal_time"], utc=True)
    if len(events) != len(scores):
        raise ValueError(f"event/scores row mismatch: {len(events)} != {len(scores)}")
    return events.reset_index(drop=True), scores.reset_index(drop=True), metadata, r7_event, r7_decision, c1_config


def write_report(summary, consistency, stability, tail, wf_summary, decision):
    fixed = summary[summary["sizing_mode"] == "fixed_2x"].set_index("prototype")
    decisions = decision.set_index("prototype")
    lines = [
        "# R8 Minimal Backtest Report",
        "",
        "data_layer: discovery",
        "data_coverage: 2024-01-01 00:00 UTC to 2026-06-24 12:05 UTC",
        "oos_status: not_oos",
        "simulation_approval: not_allowed",
        "",
        "R8 runs minimal trade accounting for fixed prototypes. It does not optimize thresholds and does not create deployable strategy rules.",
        "",
        "## Fixed 2x Summary",
        "",
        summary[summary["sizing_mode"] == "fixed_2x"].to_markdown(index=False),
        "",
        "## Event To Trade Consistency",
        "",
        consistency.to_markdown(index=False),
        "",
        "## R8 Decisions",
        "",
        decision.to_markdown(index=False),
        "",
        "## Required Answers",
        "",
    ]

    def better(test, base):
        return fixed.loc[test, "profit_factor"] > fixed.loc[base, "profit_factor"] and fixed.loc[test, "total_return"] > fixed.loc[base, "total_return"]

    lines.extend([
        f"1. P3 是否在真实交易后仍优于 P0：{better('P3_MOMENTUM_TOP20', 'P0_ALL_TREND_CONTEXT')}。",
        f"2. P4 是否在真实交易后仍优于 P0：{better('P4_BREAKOUT_TOP20', 'P0_ALL_TREND_CONTEXT')}。",
        f"3. P5 是否在真实交易后优于 P3/P4 单因子：{better('P5_MOMENTUM_AND_BREAKOUT_TOP40', 'P3_MOMENTUM_TOP20') and better('P5_MOMENTUM_AND_BREAKOUT_TOP40', 'P4_BREAKOUT_TOP20')}。",
        f"4. P6 是否更稳健：P6 决策 `{decisions.loc['P6_MOMENTUM_OR_BREAKOUT_TOP20', 'decision_status']}`，需要结合 walk-forward 与尾部依赖判断。",
        f"5. P3/P4/P5/P6 是否优于 C1/P1：{[p for p in ['P3_MOMENTUM_TOP20','P4_BREAKOUT_TOP20','P5_MOMENTUM_AND_BREAKOUT_TOP40','P6_MOMENTUM_OR_BREAKOUT_TOP20'] if better(p, 'P1_C1_FIRST_BREAKOUT')]}。",
        f"6. 执行层削弱：{consistency[['prototype', 'consistency_status']].to_dict(orient='records')}。",
        f"7. 少数交易或月份依赖：{tail[tail['sizing_mode']=='fixed_2x'][['prototype', 'tail_dependence_status']].to_dict(orient='records')}。",
        "8. 固定风险后最大回撤是否下降：见 `prototype_backtest_summary.csv` 中 fixed_2x 与 fixed_risk_0_5pct 的 max_drawdown 对照。",
        f"9. 可进入 R9 新数据验证：{decision[decision['decision_status']=='candidate_for_R9_oos_validation']['prototype'].tolist()}。",
        "10. 是否仍然禁止称为 OOS / 模拟盘：是。R8 仍然只使用 discovery 数据。",
        "",
    ])
    (RESEARCH_ROOT / "reports" / "R8_minimal_backtest_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ensure_research_dirs()
    out = RESEARCH_ROOT / "minimal_backtest"
    trades_dir = out / "prototype_trades"
    equity_dir = out / "equity_curves"
    trades_dir.mkdir(parents=True, exist_ok=True)
    equity_dir.mkdir(parents=True, exist_ok=True)

    events, scores, metadata, r7_event, r7_decision, config = load_inputs()
    params = load_params(config)
    data_1m, data_15m = prepare_market_data(DISCOVERY_DATA_PATH)
    events = enrich_events_with_exit_info(events, data_1m, data_15m, params)
    event_frames = prototype_event_frames(events, scores)

    summary_rows = []
    all_trades = []
    equity_frames = []
    start = data_1m.index[0]
    end = data_1m.index[-1]
    for prototype in R8_PROTOTYPES:
        for sizing_mode in SIZING_MODES:
            trades, equity = run_prototype_backtest(event_frames[prototype], data_1m, data_15m, params, prototype, sizing_mode)
            summary_rows.append(summarize_backtest(prototype, sizing_mode, trades, equity, params.initial_balance, start, end))
            trades.to_csv(trades_dir / f"{prototype}_{sizing_mode}_trades.csv", index=False)
            equity.to_csv(equity_dir / f"{prototype}_{sizing_mode}_equity.csv", index=False)
            if not trades.empty:
                all_trades.append(trades)
            equity_frames.append(equity)

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(out / "prototype_backtest_summary.csv", index=False)
    trades_all = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    monthly = period_trade_summary(trades_all, "month", params.initial_balance)
    quarterly = period_trade_summary(trades_all, "quarter", params.initial_balance)
    stability = trade_stability_summary(monthly, quarterly)
    tail = trade_tail_dependence(trades_all, params.initial_balance)
    consistency = event_to_trade_consistency(r7_event, summary, monthly, r7_decision)
    wf_windows, wf_summary = walk_forward_backtest(events, metadata, data_1m, data_15m, params)
    decision = r8_decision_summary(summary, wf_summary, tail)

    consistency.to_csv(out / "event_to_trade_consistency.csv", index=False)
    monthly.to_csv(out / "prototype_monthly_trade_summary.csv", index=False)
    quarterly.to_csv(out / "prototype_quarterly_trade_summary.csv", index=False)
    stability.to_csv(out / "prototype_trade_stability_summary.csv", index=False)
    tail.to_csv(out / "prototype_trade_tail_dependence.csv", index=False)
    wf_windows.to_csv(out / "walk_forward_backtest_windows.csv", index=False)
    wf_summary.to_csv(out / "walk_forward_backtest_summary.csv", index=False)
    decision.to_csv(out / "r8_decision_summary.csv", index=False)
    plot_equity_curves(equity_frames, out / "prototype_equity_comparison.png")
    plot_drawdown_curves(equity_frames, out / "prototype_drawdown_comparison.png")
    write_report(summary, consistency, stability, tail, wf_summary, decision)

    config_hash = stable_hash({
        "stage": "R8",
        "prototypes": R8_PROTOTYPES,
        "sizing_modes": SIZING_MODES,
        "config_hashes": {path: file_sha256(RESEARCH_ROOT.parent / path) for path in CONFIG_INPUTS},
        "event_hash": file_sha256(RESEARCH_ROOT / "events" / "event_candidates.parquet"),
        "score_hash": file_sha256(RESEARCH_ROOT / "family_validation" / "family_scores.parquet"),
    })
    append_run_log({
        "run_id": "R8_MINIMAL_BACKTEST",
        "stage": "R8",
        "script": "research_core/run_minimal_backtest.py",
        "config_hash": config_hash,
        "data_hash": file_sha256(DISCOVERY_DATA_PATH),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "discovery",
        "status": "success",
        "notes": "R8 minimal prototype backtest; discovery only; no deployable strategy rule generated.",
    })


if __name__ == "__main__":
    main()
