"""Run S2.5 IDLE_MR1 state breakdown.

This script is descriptive event analysis only. It must not create a strategy
backtest or alter P4 rules.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from research_core.common import RESEARCH_ROOT, append_run_log, current_git_commit, file_sha256, stable_hash
from research_core.second_alpha_source_s25.idle_mr1_state_breakdown import (
    RANDOM_SEED,
    add_time_buckets,
    add_trend_strength_bucket,
    attach_p4_phase,
    blocked_strategy_summary,
    breakdown,
    failure_case_sample,
    hypothesis_summary,
    load_idle_events,
    random_baseline_diagnostics,
    resolve_s2_source,
)


OUT = RESEARCH_ROOT / "second_alpha_source_s25"


def write_report(
    source_status: str,
    events: pd.DataFrame,
    direction: pd.DataFrame,
    symbol: pd.DataFrame,
    monthly: pd.DataFrame,
    phase: pd.DataFrame,
    vol: pd.DataFrame,
    trend: pd.DataFrame,
    diagnostics: pd.DataFrame,
    hypotheses: pd.DataFrame,
) -> str:
    conclusion = "B. IDLE_MR1 has weak local clues but needs canonical S2 and deeper validation"
    if source_status != "canonical":
        conclusion = "E. 当前 S2 来源不是 canonical，无法形成正式判断"
    elif events["fwd_ret_16"].mean() < 0 and (hypotheses["hypothesis_status"] == "weak_positive_bucket").sum() == 0:
        conclusion = "C. IDLE_MR1 只是比随机少亏，没有明确正期望"

    long_mean = direction.loc[direction["side"] == "long", "mean_fwd_ret_16"].mean() if "side" in direction else float("nan")
    short_mean = direction.loc[direction["side"] == "short", "mean_fwd_ret_16"].mean() if "side" in direction else float("nan")
    worst_symbol = symbol.sort_values("mean_fwd_ret_16").head(1)["symbol"].iloc[0] if not symbol.empty else "unknown"
    best_months = monthly.sort_values("mean_fwd_ret_16", ascending=False).head(5) if not monthly.empty else pd.DataFrame()
    phase_best = phase.sort_values("mean_fwd_ret_16", ascending=False).head(1) if not phase.empty else pd.DataFrame()
    high_vol = vol[vol["volatility_regime"] == "high_vol"]["mean_fwd_ret_16"].mean() if not vol.empty else float("nan")
    trend_worst = trend.sort_values("mean_fwd_ret_16").head(1)["trend_strength_bucket"].iloc[0] if not trend.empty else "unknown"
    true_breakout_rate = float(events["subsequent_trend_breakout"].mean()) if len(events) else float("nan")

    lines = [
        "# S2.5 IDLE_MR1 State Breakdown Report",
        "",
        f"source_status: {source_status}",
        "data_layer: expanded_discovery",
        "oos_status: not_oos",
        "strategy_backtest_generated: false",
        "",
        "## Final Decision",
        "",
        conclusion,
        "",
        "## Summary",
        "",
        f"- IDLE_MR1 events analyzed: {len(events)}",
        f"- Overall mean_fwd_ret_16: {events['fwd_ret_16'].mean():.8f}" if len(events) else "- Overall mean_fwd_ret_16: n/a",
        f"- Subsequent trend breakout rate: {true_breakout_rate:.4f}" if len(events) else "- Subsequent trend breakout rate: n/a",
        "",
        "## Direction Breakdown",
        "",
        direction.to_markdown(index=False) if not direction.empty else "No data",
        "",
        "## Symbol Breakdown",
        "",
        symbol.to_markdown(index=False) if not symbol.empty else "No data",
        "",
        "## P4 Phase Breakdown",
        "",
        phase.to_markdown(index=False) if not phase.empty else "No data",
        "",
        "## Volatility Breakdown",
        "",
        vol.to_markdown(index=False) if not vol.empty else "No data",
        "",
        "## Trend Strength Breakdown",
        "",
        trend.to_markdown(index=False) if not trend.empty else "No data",
        "",
        "## Random Baseline Diagnostics",
        "",
        diagnostics.to_markdown(index=False) if not diagnostics.empty else "No data",
        "",
        "## Edge Hypotheses",
        "",
        hypotheses.to_markdown(index=False) if not hypotheses.empty else "No data",
        "",
        "## Required Answers",
        "",
        f"1. IDLE_MR1 的 long 和 short 哪个更差？long mean={long_mean:.8f}, short mean={short_mean:.8f}，较低者更差。",
        f"2. 哪个币种拖累最大？当前最差 symbol={worst_symbol}。",
        "3. 是否存在有效月份或有效季度？见 idle_mr1_monthly_breakdown.csv，最好的 5 个月如下：",
        best_months.to_markdown(index=False) if not best_months.empty else "No monthly data",
        f"4. 是否在 P4 刚退出后更有效？见 p4_phase breakdown；当前最佳 phase={phase_best['p4_phase'].iloc[0] if not phase_best.empty else 'unknown'}。",
        "5. deep_idle 是否有效？见 idle_mr1_p4_phase_breakdown.csv 的 deep_idle 行。",
        f"6. 高波动是否导致失败？high_vol mean_fwd_ret_16={high_vol:.8f}。",
        f"7. 趋势强度是否解释失败？最差 trend bucket={trend_worst}。",
        f"8. 失败案例是否经常演变为真趋势突破？整体 subsequent_trend_breakout_rate={true_breakout_rate:.4f}。",
        "9. percentile 高但 mean return 负的原因是什么？S2.5 诊断倾向于：IDLE_MR1 可能比匹配事件少亏，但自身 16-bar forward mean 仍未转正；还需要 full market-state random baseline 才能最终解释。",
        "10. 是否值得进入 S2.6？只有 canonical S2 且出现明确正收益局部状态时才进入；当前若 source_status 非 canonical，则不能进入正式 S2.6。",
    ]
    (OUT / "second_alpha_s25_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return conclusion


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    source = resolve_s2_source()
    events = load_idle_events(source)
    events = attach_p4_phase(events)
    events = add_time_buckets(events)
    events = add_trend_strength_bucket(events)

    direction = breakdown(events, ["side"])
    symbol = breakdown(events, ["symbol"])
    monthly = breakdown(events, ["month"])
    quarterly = breakdown(events, ["quarter"])
    phase = breakdown(events, ["p4_phase"])
    vol = breakdown(events, ["volatility_regime"])
    trend = breakdown(events, ["trend_strength_bucket"])
    state = breakdown(events, ["symbol", "side", "p4_phase", "volatility_regime", "trend_strength_bucket"])
    failures = failure_case_sample(events)
    diagnostics = random_baseline_diagnostics(events)
    hypotheses = hypothesis_summary(direction, symbol, phase, vol, trend)
    blocked = blocked_strategy_summary()

    events.to_parquet(OUT / "idle_mr1_enriched_events.parquet", index=False)
    events.head(1000).to_csv(OUT / "idle_mr1_enriched_events_sample.csv", index=False)
    direction.to_csv(OUT / "idle_mr1_direction_breakdown.csv", index=False)
    symbol.to_csv(OUT / "idle_mr1_symbol_breakdown.csv", index=False)
    monthly.to_csv(OUT / "idle_mr1_monthly_breakdown.csv", index=False)
    quarterly.to_csv(OUT / "idle_mr1_quarterly_breakdown.csv", index=False)
    phase.to_csv(OUT / "idle_mr1_p4_phase_breakdown.csv", index=False)
    vol.to_csv(OUT / "idle_mr1_volatility_breakdown.csv", index=False)
    trend.to_csv(OUT / "idle_mr1_trend_strength_breakdown.csv", index=False)
    state.to_csv(OUT / "idle_mr1_state_breakdown.csv", index=False)
    failures.to_csv(OUT / "idle_mr1_failure_case_sample.csv", index=False)
    diagnostics.to_csv(OUT / "idle_mr1_random_baseline_diagnostics.csv", index=False)
    hypotheses.to_csv(OUT / "idle_mr1_edge_hypothesis_summary.csv", index=False)
    blocked.to_csv(OUT / "idle_mr1_strategy_backtest_blocked.csv", index=False)
    pd.DataFrame([{
        "source_path": str(source.path),
        "source_status": source.source_status,
        "event_count": len(events),
        "data_layer": "expanded_discovery",
        "oos_status": "not_oos",
    }]).to_csv(OUT / "s25_run_metadata.csv", index=False)

    conclusion = write_report(source.source_status, events, direction, symbol, monthly, phase, vol, trend, diagnostics, hypotheses)
    append_run_log({
        "run_id": "SECOND_ALPHA_S25_IDLE_MR1_BREAKDOWN",
        "stage": "SECOND_ALPHA_S25",
        "script": "research_core.second_alpha_source_s25.run_idle_mr1_state_breakdown",
        "config_hash": stable_hash({
            "candidate": "IDLE_MR1_P4_IDLE_REVERSION",
            "source_status": source.source_status,
            "p4_phase": "past_only_position_simulation",
        }),
        "data_hash": file_sha256(source.path / "candidate_event_table.parquet"),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "expanded_discovery",
        "status": "success" if source.source_status == "canonical" else "blocked",
        "notes": f"S2.5 IDLE_MR1 state breakdown only; {conclusion}; no strategy backtest; not OOS",
    })


if __name__ == "__main__":
    run()
