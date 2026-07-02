"""Run S2.7 strict exit-window event validation."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from research_core.common import append_run_log, current_git_commit, stable_hash
from research_core.second_alpha_source_s27.strict_exit_window_validation import (
    EXIT_BUCKET,
    RANDOM_SEED,
    S27_DIR,
    build_strict_market_pool,
    decision_summary,
    direction_symbol_matrix,
    input_validation,
    load_events,
    long_history_check,
    neighbor_comparison,
    p4_correlation,
    period_stability,
    random_direction_baseline,
    random_time_baseline,
    stress_summary,
    top_trade_dependency,
)


def write_report(input_val, neighbor, random_dir, random_time, monthly, quarterly, matrix, dep, stress, corr, overlap, long_hist, decision) -> None:
    letter = decision["decision_letter"].iloc[0] if not decision.empty else "E"
    by_bucket = neighbor.set_index("p4_state_bucket")["mean_fwd_ret_16"].to_dict() if not neighbor.empty else {}
    lines = [
        "# S2.7 严格 Exit Window 事件验证报告",
        "",
        "data_layer: expanded_discovery / internal_validation",
        "oos_status: not_oos",
        "strategy_backtest_generated: false",
        "",
        "## 输入验收",
        "",
        input_val.to_markdown(index=False),
        "",
        "## 核心对照",
        "",
        f"- after_p4_exit_5_16 mean_fwd_ret_16: {by_bucket.get(EXIT_BUCKET)}",
        f"- after_p4_exit_0_4 mean_fwd_ret_16: {by_bucket.get('after_p4_exit_0_4_bars')}",
        f"- deep_idle mean_fwd_ret_16: {by_bucket.get('deep_idle')}",
        f"- random_direction_percentile: {random_dir.get('percentile_vs_random_direction', pd.Series([None])).iloc[0] if not random_dir.empty else 'NA'}",
        f"- random_time_percentile: {random_time.get('percentile_vs_random_time', pd.Series([None])).iloc[0] if not random_time.empty else 'NA'}",
        f"- positive_month_rate: {(monthly['positive_period'].mean() if not monthly.empty else 'NA')}",
        f"- positive_quarter_rate: {(quarterly['positive_period'].mean() if not quarterly.empty else 'NA')}",
        f"- top1_positive_contribution: {dep.get('top1_positive_contribution', pd.Series([None])).iloc[0] if not dep.empty else 'NA'}",
        "",
        "## 必答问题",
        "",
        "1. S2.7 输入是否合格：见 s27_input_validation.csv。",
        "2. 5-16 窗口是否优于相邻窗口：见 exit_window_neighbor_comparison.csv。",
        "3. edge 是否来自方向判断：见 exit_window_random_direction_baseline.csv。",
        "4. edge 是否优于更严格随机时间基线：见 exit_window_random_time_baseline.csv。",
        "5. 是否跨 symbol 和 side 稳定：见 exit_window_direction_symbol_matrix.csv。",
        "6. 是否多数月份/季度为正：见 monthly/quarterly stability。",
        "7. 是否依赖少数事件、月份或季度：见 stress summary 和 top dependency。",
        "8. 与 P4 是否低相关：见 exit_window_p4_correlation.csv。",
        "9. 是否能改善 P4 弱月份：见 exit_window_drawdown_overlap_proxy.csv。",
        "10. 是否允许进入 S3：见 exit_window_decision_summary.csv。",
        "",
        "## 最终结论",
        "",
        {
            "A": "A. exit-window IDLE_MR1 通过严格事件验证，可进入 S3 最小策略原型",
            "B": "B. 有弱 edge，但仍需更长历史或更严格随机基线",
            "C": "C. edge 依赖窗口、月份、方向或标的，不适合策略化",
            "D": "D. edge 不显著优于随机状态，停止该候选",
            "E": "E. 输入或实现问题导致无法判断",
        }[letter],
        "",
        "本阶段没有生成策略回测，不是 OOS，也没有改变 P4 或 IDLE_MR1 规则。",
    ]
    (S27_DIR / "second_alpha_s27_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    S27_DIR.mkdir(parents=True, exist_ok=True)
    events = load_events()
    input_val = input_validation()
    input_val.to_csv(S27_DIR / "s27_input_validation.csv", index=False)
    if input_val["input_validation_status"].iloc[0] != "pass" or events.empty:
        empty = pd.DataFrame()
        for name in [
            "exit_window_neighbor_comparison.csv",
            "exit_window_direction_symbol_matrix.csv",
            "exit_window_monthly_stability.csv",
            "exit_window_quarterly_stability.csv",
            "exit_window_random_direction_baseline.csv",
            "exit_window_random_time_baseline.csv",
            "exit_window_long_history_check.csv",
            "exit_window_p4_correlation.csv",
            "exit_window_drawdown_overlap_proxy.csv",
            "exit_window_stress_summary.csv",
        ]:
            empty.to_csv(S27_DIR / name, index=False)
        decision = pd.DataFrame([{
            "decision_letter": "E",
            "decision_status": "input_or_implementation_problem",
            "strategy_backtest_generated": False,
            "data_layer": "expanded_discovery",
            "oos_status": "not_oos",
        }])
        decision.to_csv(S27_DIR / "exit_window_decision_summary.csv", index=False)
        write_report(input_val, empty, empty, empty, empty, empty, empty, empty, empty, empty, empty, empty, decision)
        status = "blocked"
    else:
        neighbor = neighbor_comparison(events)
        neighbor.to_csv(S27_DIR / "exit_window_neighbor_comparison.csv", index=False)
        matrix = direction_symbol_matrix(events)
        matrix.to_csv(S27_DIR / "exit_window_direction_symbol_matrix.csv", index=False)
        monthly, monthly_stats = period_stability(events, "month")
        monthly.to_csv(S27_DIR / "exit_window_monthly_stability.csv", index=False)
        quarterly, quarterly_stats = period_stability(events, "quarter")
        quarterly.to_csv(S27_DIR / "exit_window_quarterly_stability.csv", index=False)
        random_dir = random_direction_baseline(events, runs=1000, seed=RANDOM_SEED)
        random_dir.to_csv(S27_DIR / "exit_window_random_direction_baseline.csv", index=False)
        pool = build_strict_market_pool()
        random_time = random_time_baseline(events, pool, runs=3000, seed=RANDOM_SEED)
        random_time.to_csv(S27_DIR / "exit_window_random_time_baseline.csv", index=False)
        long_hist = long_history_check()
        long_hist.to_csv(S27_DIR / "exit_window_long_history_check.csv", index=False)
        corr, overlap = p4_correlation(events)
        corr.to_csv(S27_DIR / "exit_window_p4_correlation.csv", index=False)
        overlap.to_csv(S27_DIR / "exit_window_drawdown_overlap_proxy.csv", index=False)
        stress = stress_summary(events)
        stress.to_csv(S27_DIR / "exit_window_stress_summary.csv", index=False)
        dep = top_trade_dependency(events)
        dep.to_csv(S27_DIR / "exit_window_top_trade_dependency.csv", index=False)
        stability = pd.DataFrame([{**monthly_stats, **quarterly_stats}])
        stability.to_csv(S27_DIR / "exit_window_stability_summary.csv", index=False)
        decision = decision_summary(input_val, neighbor, random_dir, random_time, monthly, quarterly, matrix, dep, stress, corr, overlap, long_hist)
        decision.to_csv(S27_DIR / "exit_window_decision_summary.csv", index=False)
        write_report(input_val, neighbor, random_dir, random_time, monthly, quarterly, matrix, dep, stress, corr, overlap, long_hist, decision)
        status = "success"
    metadata = pd.DataFrame([{
        "run_id": "S2_7_STRICT_EXIT_WINDOW_VALIDATION",
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "config_hash": stable_hash({"exit_bucket": EXIT_BUCKET, "random_seed": RANDOM_SEED}),
        "data_hash": stable_hash({"source": "canonical_s2_event_table"}),
        "git_commit": current_git_commit(),
        "data_layer": "expanded_discovery",
        "oos_status": "not_oos",
        "status": status,
    }])
    metadata.to_csv(S27_DIR / "s27_run_metadata.csv", index=False)
    append_run_log({
        "run_id": "S2_7_STRICT_EXIT_WINDOW_VALIDATION",
        "stage": "S2.7",
        "script": "research_core/second_alpha_source_s27/run_strict_exit_window_validation.py",
        "config_hash": stable_hash({"exit_bucket": EXIT_BUCKET, "random_seed": RANDOM_SEED}),
        "data_hash": stable_hash({"source": "canonical_s2_event_table"}),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "expanded_discovery",
        "status": status,
        "notes": "strict event validation only; not OOS; no strategy backtest",
    })


if __name__ == "__main__":
    main()

