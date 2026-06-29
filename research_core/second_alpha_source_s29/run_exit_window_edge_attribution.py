"""Run S2.9 exit-window edge attribution."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from research_core.common import append_run_log, current_git_commit, stable_hash
from research_core.second_alpha_source_s29.exit_window_edge_attribution import (
    EVENTS_PATH,
    S29_DIR,
    case_samples,
    decision_summary,
    edge_explainability_summary,
    input_validation,
    load_s28_inputs,
    p4_exit_context_attribution,
    period_failure_attribution,
    reversion_vs_continuation_diagnostics,
    side_failure_attribution,
    symbol_failure_attribution,
)


RANDOM_SEED = 20260624


def write_report(
    input_val: pd.DataFrame,
    symbol_attr: pd.DataFrame,
    year_attr: pd.DataFrame,
    side_attr: pd.DataFrame,
    context: pd.DataFrame,
    rev_diag: pd.DataFrame,
    explain: pd.DataFrame,
    decision: pd.DataFrame,
) -> None:
    letter = decision["decision_letter"].iloc[0] if not decision.empty else "E"
    decision_text = {
        "A": "A. edge 可解释且弱点可控，可进入 S3 最小策略原型",
        "B": "B. edge 有解释力，但应先做 S2.10 状态分类验证",
        "C": "C. edge 主要依赖 SOL/BNB 或特定方向，应降级为局部研究",
        "D": "D. edge 无法稳定解释，应停止该候选",
        "E": "E. 输入或实现问题导致无法判断",
    }[letter]
    btc_reason = symbol_attr.set_index("symbol")["failure_reason"].to_dict().get("BTCUSDT", "NA") if not symbol_attr.empty else "NA"
    eth_reason = symbol_attr.set_index("symbol")["failure_reason"].to_dict().get("ETHUSDT", "NA") if not symbol_attr.empty else "NA"
    sol_reason = symbol_attr.set_index("symbol")["failure_reason"].to_dict().get("SOLUSDT", "NA") if not symbol_attr.empty else "NA"
    bnb_reason = symbol_attr.set_index("symbol")["failure_reason"].to_dict().get("BNBUSDT", "NA") if not symbol_attr.empty else "NA"
    dominant_diag = rev_diag["diagnosis"].mode().iloc[0] if not rev_diag.empty else "NA"
    lines = [
        "# S2.9 Exit-Window Edge 失效来源拆解报告",
        "",
        "data_layer: expanded_discovery_long_history",
        "oos_status: not_oos",
        "strategy_backtest_generated: false",
        "",
        "## 输入验收",
        "",
        input_val.to_markdown(index=False),
        "",
        "## 归因摘要",
        "",
        f"- BTC failure_reason: {btc_reason}",
        f"- ETH failure_reason: {eth_reason}",
        f"- SOL failure_reason: {sol_reason}",
        f"- BNB failure_reason: {bnb_reason}",
        f"- dominant reversion/continuation diagnosis: {dominant_diag}",
        f"- decision: {decision_text}",
        "",
        "## 必答问题",
        "",
        f"1. BTC 为什么拖累：见 `symbol_failure_attribution.csv`，当前分类为 `{btc_reason}`。",
        f"2. ETH 为什么不稳：见 `symbol_failure_attribution.csv`，当前分类为 `{eth_reason}`。",
        f"3. SOL/BNB 为什么更强：见 `symbol_failure_attribution.csv`，SOL=`{sol_reason}`，BNB=`{bnb_reason}`。",
        "4. 失败年份/季度共同特征：见 `year_failure_attribution.csv` 与 `quarter_failure_attribution.csv`。",
        f"5. 这是均值回归还是状态效应：主诊断 `{dominant_diag}`，见 `reversion_vs_continuation_diagnostics.csv`。",
        "6. continuation breakout 风险：见 `reversion_vs_continuation_diagnostics.csv` 和失败案例样本。",
        "7. 与 P4 的互补性：沿用 S2.8 `s28_p4_weak_month_overlap.csv`，并在 explainability 中汇总。",
        "8. 是否进入 S3/S2.10/停止：见 `s29_decision_summary.csv`。",
        "9. 当前仍然不是 OOS：是，长历史只标记 expanded_discovery_long_history。",
        "10. 下一阶段：若结论为 B，进入 S2.10 做 P4 exit 后状态分类验证；若 A 才能进入 S3。",
        "",
        "## Explainability",
        "",
        explain.to_markdown(index=False) if not explain.empty else "No explainability rows.",
        "",
        "## 最终结论",
        "",
        decision_text,
        "",
        "本阶段没有生成策略回测，没有修改 P4 或 IDLE_MR1，也没有把长历史称为 OOS。",
    ]
    (S29_DIR / "second_alpha_s29_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_blocked(input_val: pd.DataFrame) -> None:
    empty = pd.DataFrame()
    for name in [
        "symbol_failure_attribution.csv",
        "year_failure_attribution.csv",
        "quarter_failure_attribution.csv",
        "side_failure_attribution.csv",
        "p4_exit_context_attribution.csv",
        "reversion_vs_continuation_diagnostics.csv",
        "btc_eth_failure_case_sample.csv",
        "sol_bnb_success_case_sample.csv",
        "edge_explainability_summary.csv",
    ]:
        empty.to_csv(S29_DIR / name, index=False)
    decision = pd.DataFrame([{
        "input_validation_status": input_val["input_validation_status"].iloc[0],
        "decision_letter": "E",
        "decision_status": "input_or_implementation_problem",
        "strategy_backtest_generated": False,
        "data_layer": "expanded_discovery_long_history",
        "oos_status": "not_oos",
    }])
    decision.to_csv(S29_DIR / "s29_decision_summary.csv", index=False)
    write_report(input_val, empty, empty, empty, empty, empty, empty, decision)


def main() -> None:
    S29_DIR.mkdir(parents=True, exist_ok=True)
    input_val = input_validation()
    input_val.to_csv(S29_DIR / "s29_input_validation.csv", index=False)
    status = "success"
    if input_val["input_validation_status"].iloc[0] != "pass":
        _write_blocked(input_val)
        status = "blocked"
    else:
        inputs = load_s28_inputs()
        events = pd.read_parquet(EVENTS_PATH)
        symbol_attr = symbol_failure_attribution(events, inputs["random"], inputs["overlap"])
        symbol_attr.to_csv(S29_DIR / "symbol_failure_attribution.csv", index=False)
        year_attr = period_failure_attribution(events, inputs["p4_proxy"], "year")
        year_attr.to_csv(S29_DIR / "year_failure_attribution.csv", index=False)
        quarter_attr = period_failure_attribution(events, inputs["p4_proxy"], "quarter")
        quarter_attr.to_csv(S29_DIR / "quarter_failure_attribution.csv", index=False)
        side_attr = side_failure_attribution(events)
        side_attr.to_csv(S29_DIR / "side_failure_attribution.csv", index=False)
        context = p4_exit_context_attribution(events)
        context.to_csv(S29_DIR / "p4_exit_context_attribution.csv", index=False)
        rev_diag = reversion_vs_continuation_diagnostics(events)
        rev_diag.to_csv(S29_DIR / "reversion_vs_continuation_diagnostics.csv", index=False)
        failures, successes = case_samples(events)
        failures.to_csv(S29_DIR / "btc_eth_failure_case_sample.csv", index=False)
        successes.to_csv(S29_DIR / "sol_bnb_success_case_sample.csv", index=False)
        decision_pre = decision_summary(input_val, symbol_attr, year_attr, rev_diag, inputs["overlap"])
        explain = edge_explainability_summary(
            symbol_attr,
            year_attr,
            rev_diag,
            inputs["overlap"],
            decision_pre["decision_status"].iloc[0],
        )
        explain.to_csv(S29_DIR / "edge_explainability_summary.csv", index=False)
        decision = decision_summary(input_val, symbol_attr, year_attr, rev_diag, inputs["overlap"], explain)
        decision.to_csv(S29_DIR / "s29_decision_summary.csv", index=False)
        write_report(input_val, symbol_attr, year_attr, side_attr, context, rev_diag, explain, decision)
    metadata = pd.DataFrame([{
        "run_id": "S2_9_EXIT_WINDOW_EDGE_ATTRIBUTION",
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "config_hash": stable_hash({"exit_bucket": "after_p4_exit_5_16_bars", "random_seed": RANDOM_SEED}),
        "data_hash": stable_hash({"source": str(EVENTS_PATH)}),
        "git_commit": current_git_commit(),
        "data_layer": "expanded_discovery_long_history",
        "oos_status": "not_oos",
        "status": status,
    }])
    metadata.to_csv(S29_DIR / "s29_run_metadata.csv", index=False)
    append_run_log({
        "run_id": "S2_9_EXIT_WINDOW_EDGE_ATTRIBUTION",
        "stage": "S2.9",
        "script": "research_core/second_alpha_source_s29/run_exit_window_edge_attribution.py",
        "config_hash": stable_hash({"exit_bucket": "after_p4_exit_5_16_bars", "random_seed": RANDOM_SEED}),
        "data_hash": stable_hash({"source": str(EVENTS_PATH)}),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "expanded_discovery_long_history",
        "status": status,
        "notes": "edge attribution only; not OOS; no strategy backtest",
    })


if __name__ == "__main__":
    main()

