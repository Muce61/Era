"""Run S2.6 exit-window validation."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from research_core.common import RESEARCH_ROOT, append_run_log, current_git_commit, file_sha256, stable_hash
from research_core.second_alpha_source_s26.exit_window_validation import (
    DATA_ROOT,
    EXIT_BUCKET,
    S2_DIR,
    S26_DIR,
    block_bootstrap,
    build_full_market_state_pool,
    canonical_s2_validation,
    decision_summary,
    event_summary,
    exit_window_events,
    failure_cases,
    grouped_breakdown,
    load_canonical_s2_events,
    ordinary_bootstrap,
    random_baseline,
    top_trade_dependency,
)


RANDOM_SEED = 20260624


def write_report(validation, events, random, boot, block, dep, decision) -> None:
    conclusion = decision["decision_letter"].iloc[0] if not decision.empty else "E"
    lines = [
        "# S2.6 P4 Exit 后 5-16 根回归窗口验证报告",
        "",
        "data_layer: expanded_discovery / internal_validation",
        "oos_status: not_oos",
        "strategy_backtest_generated: false",
        "",
        "## Canonical S2 验收",
        "",
        validation.to_markdown(index=False),
        "",
        "## 核心结果",
        "",
        f"- 事件数: {len(events)}",
        f"- mean_fwd_ret_16: {events['fwd_ret_16'].mean() if len(events) else 'NA'}",
        f"- percentile_vs_random: {random['percentile_vs_random'].iloc[0] if not random.empty else 'NA'}",
        f"- ordinary_bootstrap_positive_rate: {boot['positive_rate'].iloc[0] if not boot.empty else 'NA'}",
        f"- monthly_block_positive_rate: {block[block['block_type'] == 'month']['positive_rate'].iloc[0] if not block[block['block_type'] == 'month'].empty else 'NA'}",
        f"- top1_positive_contribution: {dep['top1_positive_contribution'].iloc[0] if not dep.empty else 'NA'}",
        "",
        "## 必答问题",
        "",
        "1. canonical S2 是否合格：见 canonical_s2_validation.csv。",
        "2. IDLE_MR1 是否还混入 p4_held：canonical 验收要求 idle_mr1_p4_held_count = 0。",
        "3. after_p4_exit_5_16 是否仍为正：见 exit_window_event_summary.csv。",
        "4. 是否优于 full market-state random baseline：见 exit_window_random_baseline_summary.csv。",
        "5. 是否跨至少 2 个标的有效：见 exit_window_symbol_breakdown.csv。",
        "6. 是否依赖少数月份：见 monthly/quarterly breakdown。",
        "7. 是否依赖少数事件：见 exit_window_top_trade_dependency.csv。",
        "8. high_vol 是否危险：见 exit_window_volatility_breakdown.csv。",
        "9. 是否值得进入 S2.7：见 exit_window_decision_summary.csv。",
        "10. 当前仍然不是 OOS：是，不能称为 OOS 或策略结论。",
        "",
        "## 最终结论",
        "",
        {
            "A": "A. after_p4_exit_5_16 存在明确局部 edge，可进入 S2.7",
            "B": "B. 存在弱线索，但仍需更长历史或重新定义事件",
            "C": "C. edge 主要来自单一标的或单一月份",
            "D": "D. after_p4_exit_5_16 只是样本噪声，不值得继续",
            "E": "E. canonical S2 或实现问题导致无法判断",
        }[conclusion],
        "",
        "本阶段没有生成策略回测，也没有改变 P4 或 IDLE_MR1 规则。",
    ]
    (S26_DIR / "second_alpha_s26_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    S26_DIR.mkdir(parents=True, exist_ok=True)
    events_all = load_canonical_s2_events(S2_DIR)
    validation = canonical_s2_validation(events_all, S2_DIR)
    validation.to_csv(S26_DIR / "canonical_s2_validation.csv", index=False)
    if validation["canonical_validation_status"].iloc[0] != "pass":
        empty = pd.DataFrame()
        empty.to_csv(S26_DIR / "exit_window_event_summary.csv", index=False)
        decision = decision_summary(validation, empty, empty, empty, empty, empty, empty)
        decision.to_csv(S26_DIR / "exit_window_decision_summary.csv", index=False)
        write_report(validation, empty, empty, empty, empty, empty, decision)
        status = "blocked"
    else:
        events = exit_window_events(events_all)
        event_summary(events).to_csv(S26_DIR / "exit_window_event_summary.csv", index=False)
        grouped_breakdown(events, "side").to_csv(S26_DIR / "exit_window_direction_breakdown.csv", index=False)
        grouped_breakdown(events, "symbol").to_csv(S26_DIR / "exit_window_symbol_breakdown.csv", index=False)
        grouped_breakdown(events, "month").to_csv(S26_DIR / "exit_window_monthly_breakdown.csv", index=False)
        grouped_breakdown(events, "quarter").to_csv(S26_DIR / "exit_window_quarterly_breakdown.csv", index=False)
        vol = grouped_breakdown(events, "volatility_regime")
        vol.to_csv(S26_DIR / "exit_window_volatility_breakdown.csv", index=False)
        grouped_breakdown(events, "trend_strength_bucket").to_csv(S26_DIR / "exit_window_trend_strength_breakdown.csv", index=False)
        pool = build_full_market_state_pool()
        rand = random_baseline(events, pool, runs=1000, seed=RANDOM_SEED)
        rand.to_csv(S26_DIR / "exit_window_random_baseline_summary.csv", index=False)
        boot = ordinary_bootstrap(events, runs=1000, seed=RANDOM_SEED)
        boot.to_csv(S26_DIR / "exit_window_bootstrap_summary.csv", index=False)
        block = pd.concat([
            block_bootstrap(events, "month", runs=1000, seed=RANDOM_SEED),
            block_bootstrap(events, "symbol", runs=1000, seed=RANDOM_SEED),
        ], ignore_index=True)
        block.to_csv(S26_DIR / "exit_window_block_bootstrap_summary.csv", index=False)
        dep = top_trade_dependency(events)
        dep.to_csv(S26_DIR / "exit_window_top_trade_dependency.csv", index=False)
        failure_cases(events).to_csv(S26_DIR / "exit_window_failure_cases.csv", index=False)
        decision = decision_summary(validation, events, rand, boot, block, dep, vol)
        decision.to_csv(S26_DIR / "exit_window_decision_summary.csv", index=False)
        write_report(validation, events, rand, boot, block, dep, decision)
        status = "success"
    data_hashes = {}
    for path in DATA_ROOT.glob("*.csv"):
        if path.name.replace(".csv", "") in {"ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT"}:
            data_hashes[path.name] = file_sha256(path)
    pd.DataFrame([{
        "run_id": "S2_6_EXIT_WINDOW_VALIDATION",
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "s2_source": str(S2_DIR),
        "exit_bucket": EXIT_BUCKET,
        "status": status,
        "data_layer": "expanded_discovery",
        "oos_status": "not_oos",
        "config_hash": stable_hash({"exit_bucket": EXIT_BUCKET, "random_seed": RANDOM_SEED}),
        "data_hash": stable_hash(data_hashes),
        "git_commit": current_git_commit(),
    }]).to_csv(S26_DIR / "s26_run_metadata.csv", index=False)
    append_run_log({
        "run_id": "S2_6_EXIT_WINDOW_VALIDATION",
        "stage": "S2.6",
        "script": "research_core/second_alpha_source_s26/run_exit_window_validation.py",
        "config_hash": stable_hash({"exit_bucket": EXIT_BUCKET, "random_seed": RANDOM_SEED}),
        "data_hash": stable_hash(data_hashes),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "expanded_discovery",
        "status": status,
        "notes": "canonical S2 exit-window event validation only; not OOS; no strategy backtest",
    })


if __name__ == "__main__":
    main()

