"""Run S2.8 long-history complement validation."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from research_core.common import append_run_log, current_git_commit, stable_hash
from research_core.second_alpha_source_s28.long_history_complement_validation import (
    S28_DIR,
    build_long_history_exit_events,
    decision_summary,
    input_validation,
    long_history_summary,
    p4_correlation,
    p4_monthly_proxy,
    period_summary,
    random_time_baseline_long_history,
    regime_summary,
    stress_summary,
    symbol_side_matrix,
    weak_month_overlap,
)


RANDOM_SEED = 20260624


def write_report(input_val, summary, yearly, quarterly, matrix, regime, random_time, corr, overlap, stress, decision) -> None:
    letter = decision["decision_letter"].iloc[0] if not decision.empty else "E"
    lines = [
        "# S2.8 长历史稳定性与 P4 弱期互补性补证报告",
        "",
        "data_layer: expanded_discovery_long_history",
        "oos_status: not_oos",
        "strategy_backtest_generated: false",
        "",
        "## 输入验收",
        "",
        input_val.to_markdown(index=False),
        "",
        "## 核心指标",
        "",
        f"- overall_mean_fwd_ret_16: {decision.get('overall_mean_fwd_ret_16', pd.Series([None])).iloc[0] if not decision.empty else 'NA'}",
        f"- positive_year_rate: {decision.get('positive_year_rate', pd.Series([None])).iloc[0] if not decision.empty else 'NA'}",
        f"- positive_quarter_rate: {decision.get('positive_quarter_rate', pd.Series([None])).iloc[0] if not decision.empty else 'NA'}",
        f"- positive_symbol_count: {decision.get('positive_symbol_count', pd.Series([None])).iloc[0] if not decision.empty else 'NA'}",
        f"- random_time_percentile_mean: {decision.get('random_time_percentile_mean', pd.Series([None])).iloc[0] if not decision.empty else 'NA'}",
        f"- fallback_match_rate_mean: {decision.get('fallback_match_rate_mean', pd.Series([None])).iloc[0] if not decision.empty else 'NA'}",
        f"- p4_negative_month_positive_rate: {decision.get('p4_negative_month_positive_rate', pd.Series([None])).iloc[0] if not decision.empty else 'NA'}",
        f"- p4_weak_month_positive_rate: {decision.get('p4_weak_month_positive_rate', pd.Series([None])).iloc[0] if not decision.empty else 'NA'}",
        "",
        "## 必答问题",
        "",
        "1. 长历史是否支持 after_p4_exit_5_16：见 long_history_exit_window_summary.csv 和 decision。",
        "2. 是否多数年份和季度为正：见 yearly/quarterly summary。",
        "3. 是否跨 ETH/BTC/SOL/BNB 有效：见 long_history_exit_window_summary.csv。",
        "4. long/short 是否都有效：见 long_history_symbol_side_matrix.csv。",
        "5. high_vol 是否危险：见 long_history_regime_summary.csv。",
        "6. 是否优于长历史 full market-state random baseline：见 s28_random_time_baseline_long_history.csv。",
        "7. 是否与 P4 低相关：见 s28_p4_correlation.csv。",
        "8. 是否能补 P4 亏损或弱收益月份：见 s28_p4_weak_month_overlap.csv。",
        "9. 是否依赖少数年份、月份、事件或标的：见 s28_stress_summary.csv。",
        "10. 是否允许进入 S3：见 s28_decision_summary.csv。",
        "",
        "## 最终结论",
        "",
        {
            "A": "A. 长历史与 P4 互补性均支持，可进入 S3 最小策略原型",
            "B": "B. 长历史支持但 P4 互补性证据不足",
            "C": "C. 存在 edge，但依赖年份 / 标的 / 方向，不适合策略化",
            "D": "D. 长历史或随机基线推翻 S2.7，应停止该候选",
            "E": "E. 输入或实现问题导致无法判断",
        }[letter],
        "",
        "本阶段没有生成策略回测，不能称为 OOS，也没有改变 P4 或 IDLE_MR1 定义。",
    ]
    (S28_DIR / "second_alpha_s28_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    S28_DIR.mkdir(parents=True, exist_ok=True)
    input_val = input_validation()
    input_val.to_csv(S28_DIR / "s28_input_validation.csv", index=False)
    if input_val["input_validation_status"].iloc[0] != "pass":
        empty = pd.DataFrame()
        for name in [
            "long_history_exit_window_summary.csv",
            "long_history_yearly_summary.csv",
            "long_history_quarterly_summary.csv",
            "long_history_symbol_side_matrix.csv",
            "long_history_regime_summary.csv",
            "p4_monthly_proxy.csv",
            "s28_p4_correlation.csv",
            "s28_p4_weak_month_overlap.csv",
            "s28_random_time_baseline_long_history.csv",
            "s28_stress_summary.csv",
        ]:
            empty.to_csv(S28_DIR / name, index=False)
        decision = pd.DataFrame([{
            "decision_letter": "E",
            "decision_status": "input_or_implementation_problem",
            "strategy_backtest_generated": False,
            "data_layer": "expanded_discovery_long_history",
            "oos_status": "not_oos",
        }])
        decision.to_csv(S28_DIR / "s28_decision_summary.csv", index=False)
        write_report(input_val, empty, empty, empty, empty, empty, empty, empty, empty, empty, decision)
        status = "blocked"
    else:
        events, data_by_symbol = build_long_history_exit_events()
        events.to_parquet(S28_DIR / "long_history_exit_window_events.parquet", index=False)
        summary = long_history_summary(events)
        summary.to_csv(S28_DIR / "long_history_exit_window_summary.csv", index=False)
        yearly = period_summary(events, "year")
        yearly.to_csv(S28_DIR / "long_history_yearly_summary.csv", index=False)
        quarterly = period_summary(events, "quarter")
        quarterly.to_csv(S28_DIR / "long_history_quarterly_summary.csv", index=False)
        matrix = symbol_side_matrix(events)
        matrix.to_csv(S28_DIR / "long_history_symbol_side_matrix.csv", index=False)
        regime = regime_summary(events)
        regime.to_csv(S28_DIR / "long_history_regime_summary.csv", index=False)
        p4_proxy = p4_monthly_proxy(data_by_symbol)
        p4_proxy.to_csv(S28_DIR / "p4_monthly_proxy.csv", index=False)
        corr = p4_correlation(events, p4_proxy)
        corr.to_csv(S28_DIR / "s28_p4_correlation.csv", index=False)
        overlap = weak_month_overlap(events, p4_proxy)
        overlap.to_csv(S28_DIR / "s28_p4_weak_month_overlap.csv", index=False)
        random_time = random_time_baseline_long_history(events, data_by_symbol, runs=3000, seed=RANDOM_SEED)
        random_time.to_csv(S28_DIR / "s28_random_time_baseline_long_history.csv", index=False)
        stress = stress_summary(events)
        stress.to_csv(S28_DIR / "s28_stress_summary.csv", index=False)
        decision = decision_summary(input_val, events, summary, yearly, quarterly, random_time, stress, corr, overlap)
        decision.to_csv(S28_DIR / "s28_decision_summary.csv", index=False)
        write_report(input_val, summary, yearly, quarterly, matrix, regime, random_time, corr, overlap, stress, decision)
        status = "success"
    metadata = pd.DataFrame([{
        "run_id": "S2_8_LONG_HISTORY_COMPLEMENT_VALIDATION",
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "config_hash": stable_hash({"exit_bucket": "after_p4_exit_5_16_bars", "random_seed": RANDOM_SEED}),
        "data_hash": stable_hash({"source": "long_history_1m_merged"}),
        "git_commit": current_git_commit(),
        "data_layer": "expanded_discovery_long_history",
        "oos_status": "not_oos",
        "status": status,
    }])
    metadata.to_csv(S28_DIR / "s28_run_metadata.csv", index=False)
    append_run_log({
        "run_id": "S2_8_LONG_HISTORY_COMPLEMENT_VALIDATION",
        "stage": "S2.8",
        "script": "research_core/second_alpha_source_s28/run_long_history_complement_validation.py",
        "config_hash": stable_hash({"exit_bucket": "after_p4_exit_5_16_bars", "random_seed": RANDOM_SEED}),
        "data_hash": stable_hash({"source": "long_history_1m_merged"}),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "expanded_discovery_long_history",
        "status": status,
        "notes": "long-history event validation only; not OOS; no strategy backtest",
    })


if __name__ == "__main__":
    main()

