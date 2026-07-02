"""Run H1 high-leverage path safety research."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from research_core.common import (
    RANDOM_SEED,
    RESEARCH_ROOT,
    append_run_log,
    current_git_commit,
    ensure_research_dirs,
    file_sha256,
    stable_hash,
)
from research_core.high_leverage_path_safety_analysis import (
    PATH_FACTOR_COLUMNS,
    PATH_LABELS,
    TARGET_PROTOTYPES,
    WINDOWS_MINUTES,
    build_failure_cases,
    build_path_safety_labels,
    factor_safety_analysis,
    failure_review_markdown,
)


def h1_decision(summary: pd.DataFrame, failures: pd.DataFrame) -> tuple[str, str]:
    candidates = summary[summary["status"] == "path_safety_candidate"]
    score_candidates = candidates[candidates["factor"].isin(["momentum_score_quantile", "breakout_score_quantile"])]
    new_candidates = candidates[~candidates["factor"].isin(["momentum_score_quantile", "breakout_score_quantile"])]
    if score_candidates["label"].isin(["safe_for_20x", "hit_liquidation_20x", "mae_pct"]).any() and len(new_candidates) == 0:
        return "A", "原有 P4/P6 因子足以解释高杠杆路径安全，可进入 H2 验证"
    if len(new_candidates) > 0:
        return "B", "需要新增路径安全 / execution-risk 因子，P4/P6 只能作为趋势背景"
    if not failures.empty and failures["symbol"].nunique() <= 1:
        return "C", "高杠杆失败主要来自特定 symbol 或极端行情，需要分资产处理"
    return "B", "需要新增路径安全 / execution-risk 因子，P4/P6 只能作为趋势背景"


def write_report(labels: pd.DataFrame, summary: pd.DataFrame, failures: pd.DataFrame, decision_code: str, decision_text: str) -> str:
    label_overview = labels.groupby(["symbol", "prototype", "forward_window"]).agg(
        event_count=("event_id", "count"),
        safe_for_10x_rate=("safe_for_10x", "mean"),
        safe_for_20x_rate=("safe_for_20x", "mean"),
        fast_follow_through_rate=("fast_follow_through", "mean"),
        hit_liq_10x_rate=("hit_liquidation_10x", "mean"),
        hit_liq_20x_rate=("hit_liquidation_20x", "mean"),
        mean_mae_pct=("mae_pct", "mean"),
        mean_mfe_pct=("mfe_pct", "mean"),
    ).reset_index()
    candidates = summary[summary["status"].isin(["path_safety_candidate", "weak_path_safety_candidate"])]
    top_candidates = candidates.sort_values(["status", "cross_symbol_positive_count", "monthly_positive_rate"], ascending=[True, False, False]).head(20)
    score_rows = summary[
        summary["factor"].isin(["momentum_score_quantile", "breakout_score_quantile"])
        & summary["label"].isin(["safe_for_20x", "hit_liquidation_20x", "mae_pct"])
    ]
    lines = [
        "# H1 High Leverage Path Safety Report",
        "",
        "branch: codex/adaptive-leverage-10x-20x",
        "data_layer: discovery_and_cross_asset_internal_validation",
        "oos_status: not_oos",
        "simulation_approval: not_allowed",
        "",
        "This research changes no alpha rule. It only studies short-path safety labels for high leverage.",
        "",
        "## Path Label Overview",
        "",
        label_overview.to_markdown(index=False),
        "",
        "## Original Score Evidence",
        "",
        score_rows.to_markdown(index=False) if not score_rows.empty else "unavailable",
        "",
        "## Top Path-Safety Candidates",
        "",
        top_candidates.to_markdown(index=False) if not top_candidates.empty else "none",
        "",
        "## Failure Cases",
        "",
        failures.head(50).to_markdown(index=False) if not failures.empty else "No failure cases found in L1 liquidation or L2 extreme-loss inputs.",
        "",
        "## Required Answers",
        "",
        "1. P4/P6 为什么适合 2x，但不一定适合 10x-20x：趋势延续 alpha 可以提高方向胜率和趋势捕捉，但高杠杆还要求入场后短路径 MAE 很小、不能先触及强平距离。",
        "2. 哪些路径标签最能解释高杠杆失败：重点看 safe_for_20x、hit_liquidation_20x、mae_pct 和 fast_follow_through。",
        "3. 原有 momentum/breakout score 是否能解释路径安全：见 Original Score Evidence。",
        "4. 是否需要新的路径安全因子：见 Final Decision。",
        "5. 哪些候选因子值得进入 H2：见 Top Path-Safety Candidates。",
        "6. 是否可以直接形成高杠杆策略：不可以。H1 是解释性研究，不是策略化。",
        "7. 是否需要 1m 更细颗粒度数据：H1 已使用本地 1m；若继续研究强平边界，1s 聚合数据更合适。",
        "8. 横向 BTC/SOL/BNB 是否支持同样结论：见 Path Label Overview 和 cross_symbol_positive_count。",
        "9. 当前是否仍存在 discovery bias：存在。discovery + cross_asset_internal_validation 不是 OOS。",
        "10. 下一阶段应该研究 alpha、risk 还是 execution：risk / execution path-safety，而不是新 alpha。",
        "",
        f"## Final Decision\n\n{decision_code}. {decision_text}",
        "",
        "## Guardrails",
        "",
        "- no alpha rule changed",
        "- path safety research only",
        "- not OOS",
        "- no deployable strategy rule generated",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ensure_research_dirs()
    out = RESEARCH_ROOT / "high_leverage_path_safety"
    out.mkdir(parents=True, exist_ok=True)

    labels = build_path_safety_labels()
    summary, quintile, symbol_summary, monthly = factor_safety_analysis(labels)
    failures = build_failure_cases(labels)
    decision_code, decision_text = h1_decision(summary, failures)

    labels.to_csv(out / "path_safety_labels.csv", index=False)
    summary.to_csv(out / "path_safety_factor_summary.csv", index=False)
    quintile.to_csv(out / "path_safety_quintile_summary.csv", index=False)
    symbol_summary.to_csv(out / "path_safety_symbol_summary.csv", index=False)
    monthly.to_csv(out / "path_safety_monthly_summary.csv", index=False)
    failures.to_csv(out / "high_leverage_failure_cases.csv", index=False)
    (out / "high_leverage_failure_review.md").write_text(failure_review_markdown(failures), encoding="utf-8")
    (RESEARCH_ROOT / "reports" / "H1_high_leverage_path_safety_report.md").write_text(
        write_report(labels, summary, failures, decision_code, decision_text),
        encoding="utf-8",
    )

    append_run_log({
        "run_id": "H1_HIGH_LEVERAGE_PATH_SAFETY",
        "stage": "H1",
        "script": "research_core/run_high_leverage_path_safety.py",
        "config_hash": stable_hash({
            "target_prototypes": TARGET_PROTOTYPES,
            "windows_minutes": WINDOWS_MINUTES,
            "path_labels": PATH_LABELS,
            "factor_columns": PATH_FACTOR_COLUMNS,
            "liquidation_model": "L1 simplified long liquidation",
        }),
        "data_hash": stable_hash({
            "eth_events": file_sha256(RESEARCH_ROOT / "events" / "event_candidates.parquet"),
            "eth_scores": file_sha256(RESEARCH_ROOT / "family_validation" / "family_scores.parquet"),
            "l1_summary": file_sha256(RESEARCH_ROOT / "leverage_research" / "leverage_summary.csv"),
            "l2_summary": file_sha256(RESEARCH_ROOT / "leverage_research_l2" / "leverage_l2_summary.csv"),
        }),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "high_leverage_research",
        "status": "success",
        "notes": "H1 high leverage path safety; no alpha rule changed; path safety research only; not OOS; no deployable strategy rule generated.",
    })


if __name__ == "__main__":
    main()
