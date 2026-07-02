"""Run H2 path-safety factor validation."""

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
from research_core.path_safety_factor_validation_analysis import (
    BOOTSTRAP_ITERATIONS,
    H2_FACTORS,
    H2_WINDOWS,
    add_time_columns,
    factor_role_decomposition,
    failure_case_explainability,
    h2_decision_summary,
    horizon_consistency,
    path_safety_bootstrap,
    path_safety_stress,
)


def final_decision(decision: pd.DataFrame, role: pd.DataFrame, boot: pd.DataFrame) -> tuple[str, str]:
    if not decision.empty and (decision["decision_status"] == "candidate_for_H3_prototype").any():
        return "A", "存在稳定 path-safety 因子，可进入 H3 最小准入原型"
    if (role["factor_role"].isin(["path_safety_only", "dual_use_candidate"])).any():
        return "B", "存在弱路径安全证据，但需要更细数据或更多样本"
    if (role["factor_role"] == "alpha_only").sum() > (role["factor_role"].isin(["path_safety_only", "dual_use_candidate"])).sum():
        return "C", "因子主要解释 MFE，不足以解释高杠杆路径安全"
    if (boot["bootstrap_status"] == "robust_path_safety_candidate").sum() == 0:
        return "D", "高杠杆失败不可由当前因子稳定解释，应停止 10x-20x"
    return "E", "当前实现或数据不足，无法判断"


def write_report(
    role: pd.DataFrame,
    boot: pd.DataFrame,
    stress: pd.DataFrame,
    horizon: pd.DataFrame,
    failure: pd.DataFrame,
    decision: pd.DataFrame,
    final_code: str,
    final_text: str,
) -> str:
    role_counts = role["factor_role"].value_counts().reset_index()
    boot_counts = boot["bootstrap_status"].value_counts().reset_index()
    stress_counts = stress["stress_status"].value_counts().reset_index()
    best = decision.sort_values(["decision_status", "bootstrap_ok", "stress_ok"], ascending=[True, False, False]).head(20)
    lines = [
        "# H2 Path Safety Factor Validation Report",
        "",
        "branch: codex/adaptive-leverage-10x-20x",
        "data_layer: high_leverage_research",
        "oos_status: not_oos",
        "simulation_approval: not_allowed",
        "",
        "This stage validates path-safety evidence only. No alpha rule or trading filter is changed.",
        "",
        "## Role Counts",
        "",
        role_counts.to_markdown(index=False),
        "",
        "## Bootstrap Counts",
        "",
        boot_counts.to_markdown(index=False),
        "",
        "## Stress Counts",
        "",
        stress_counts.to_markdown(index=False),
        "",
        "## H3 Candidate Check",
        "",
        best.to_markdown(index=False) if not best.empty else "No candidate rows.",
        "",
        "## Horizon Roles",
        "",
        horizon.head(40).to_markdown(index=False),
        "",
        "## Failure Explainability",
        "",
        failure.sort_values("lift", ascending=False).head(40).to_markdown(index=False),
        "",
        "## Required Answers",
        "",
        "1. 哪些因子是真正的 path safety 因子：见 factor_role_decomposition 中 path_safety_only / dual_use_candidate。",
        "2. 哪些因子只是 alpha / MFE 因子：见 factor_role_decomposition 中 alpha_only。",
        "3. 哪些因子只适合做 risk monitor：见 factor_role_decomposition 中 risk_monitor。",
        "4. 哪些因子只适合 execution 层：见 horizon_consistency_summary 中 execution_risk_short_window。",
        "5. 哪些因子跨 symbol 稳定：见 path_safety_bootstrap_summary 的 symbol_positive_rate 与 bootstrap_status。",
        "6. 哪些因子依赖某个月份或某个 symbol：见 path_safety_stress_summary。",
        "7. 哪些因子能解释 L1/L2 失败案例：见 failure_case_explainability.csv。",
        f"8. 是否可以进入 H3 做最小高杠杆准入原型：{final_code == 'A'}。",
        "9. 是否仍禁止形成策略规则：是。H2 不是策略化阶段。",
        "10. 是否需要 1s 或盘口数据：若继续研究 10x-20x 强平边界，需要 1s/盘口数据验证执行风险。",
        "",
        f"## Final Decision\n\n{final_code}. {final_text}",
        "",
        "## Guardrails",
        "",
        "- no alpha rule changed",
        "- factor validation only",
        "- not OOS",
        "- no deployable strategy rule generated",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ensure_research_dirs()
    out = RESEARCH_ROOT / "high_leverage_path_safety_h2"
    out.mkdir(parents=True, exist_ok=True)

    labels = add_time_columns(pd.read_csv(RESEARCH_ROOT / "high_leverage_path_safety" / "path_safety_labels.csv"))
    failures = pd.read_csv(RESEARCH_ROOT / "high_leverage_path_safety" / "high_leverage_failure_cases.csv")
    role = factor_role_decomposition(labels)
    boot = path_safety_bootstrap(labels, seed=RANDOM_SEED)
    stress = path_safety_stress(labels)
    horizon = horizon_consistency(role)
    failure = failure_case_explainability(labels, failures)
    decision = h2_decision_summary(role, boot, stress, horizon, failure)
    final_code, final_text = final_decision(decision, role, boot)

    role.to_csv(out / "factor_role_decomposition.csv", index=False)
    boot.to_csv(out / "path_safety_bootstrap_summary.csv", index=False)
    stress.to_csv(out / "path_safety_stress_summary.csv", index=False)
    horizon.to_csv(out / "horizon_consistency_summary.csv", index=False)
    failure.to_csv(out / "failure_case_explainability.csv", index=False)
    decision.to_csv(out / "h2_decision_summary.csv", index=False)
    (RESEARCH_ROOT / "reports" / "H2_path_safety_factor_validation_report.md").write_text(
        write_report(role, boot, stress, horizon, failure, decision, final_code, final_text),
        encoding="utf-8",
    )

    append_run_log({
        "run_id": "H2_PATH_SAFETY_FACTOR_VALIDATION",
        "stage": "H2",
        "script": "research_core/run_path_safety_factor_validation.py",
        "config_hash": stable_hash({
            "factors": H2_FACTORS,
            "windows": H2_WINDOWS,
            "bootstrap_iterations": BOOTSTRAP_ITERATIONS,
            "labels": ["safe_for_20x", "mae_pct", "mfe_pct", "hit_liquidation_20x"],
        }),
        "data_hash": stable_hash({
            "path_safety_labels": file_sha256(RESEARCH_ROOT / "high_leverage_path_safety" / "path_safety_labels.csv"),
            "path_safety_factor_summary": file_sha256(RESEARCH_ROOT / "high_leverage_path_safety" / "path_safety_factor_summary.csv"),
            "failure_cases": file_sha256(RESEARCH_ROOT / "high_leverage_path_safety" / "high_leverage_failure_cases.csv"),
        }),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "high_leverage_research",
        "status": "success",
        "notes": "H2 path safety factor validation; no alpha rule changed; factor validation only; not OOS; no deployable strategy rule generated.",
    })


if __name__ == "__main__":
    main()
