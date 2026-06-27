"""Run Research Core R9 OOS validation gate."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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
from research_core.oos_validation_analysis import (
    DISCOVERY_END,
    candidate_csv_paths,
    audit_ohlcv,
    build_data_inventory,
    coverage_decision,
)


SEARCH_ROOTS = [
    Path("/Users/muce/1m_data"),
    Path("/Users/muce/PycharmProjects/20260621/eth"),
    Path("/Users/muce/PycharmProjects/20260625/Era"),
]


def write_coverage_report(decision: dict, inventory: pd.DataFrame, quality: pd.DataFrame) -> str:
    lines = [
        "# R9 OOS Coverage Decision",
        "",
        f"discovery_end: {DISCOVERY_END.isoformat()}",
        f"status: {decision['status']}",
        f"reason: {decision['reason']}",
        f"best_path: {decision.get('best_path', '')}",
        f"coverage_days: {decision.get('coverage_days', 0.0):.4f}",
        f"conclusion: {decision['conclusion']}",
        "",
        "R9 requires at least 90 days of ETHUSDT 1m data strictly after the discovery end.",
        "",
        "## Inventory Summary",
        "",
        f"- candidate_files: {len(inventory)}",
        f"- files_with_oos_rows: {int(inventory['has_rows_after_discovery_end'].sum()) if not inventory.empty else 0}",
        "",
        "## Quality Summary",
        "",
        quality.to_markdown(index=False) if not quality.empty else "No readable OOS OHLCV candidate was available.",
        "",
    ]
    return "\n".join(lines)


def write_r9_report(decision: dict, quality: pd.DataFrame) -> str:
    best = quality.iloc[0].to_dict() if not quality.empty else {}
    lines = [
        "# R9 OOS Validation Report",
        "",
        "data_layer: oos",
        f"status: {decision['status']}",
        f"reason: {decision['reason']}",
        "final_conclusion: E. OOS 数据不足，无法判断",
        "",
        "当前本地新增 ETHUSDT 1m 数据不足 3 个月，因此 R9 按规则停止，不生成策略性 OOS 结论。",
        "",
        "## Required Answers",
        "",
        f"1. 是否存在合格 OOS 数据：否，覆盖不足。最佳候选 `{decision.get('best_path', '')}`。",
        f"2. OOS 数据覆盖多久：约 {decision.get('coverage_days', 0.0):.4f} 天。",
        "3. OOS 事件数量是否足够：未构建 OOS 事件表，因为数据覆盖不足。",
        "4. P4 是否仍优于 P1/C1：无法判断。",
        "5. P6 是否仍优于 P1/C1：无法判断。",
        "6. P3 是否仍值得保留：无法判断，等待新增数据。",
        "7. P5 是否仍值得保留：无法判断，等待新增数据。",
        "8. discovery 到 OOS 是否明显衰减：无法判断。",
        "9. 是否存在 selection-on-discovery 偏差：仍然存在该风险，因为没有足够 OOS。",
        "10. 是否允许进入 R10 模拟盘观察准备：不允许。",
        "",
        "## Best Candidate Quality",
        "",
        pd.DataFrame([best]).to_markdown(index=False) if best else "No quality row.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ensure_research_dirs()
    audit_dir = RESEARCH_ROOT / "oos_data_audit"
    events_dir = RESEARCH_ROOT / "oos_events"
    validation_dir = RESEARCH_ROOT / "oos_validation"
    for path in [audit_dir, events_dir, validation_dir]:
        path.mkdir(parents=True, exist_ok=True)

    paths = candidate_csv_paths(SEARCH_ROOTS)
    inventory = build_data_inventory(paths)
    inventory.to_csv(audit_dir / "oos_data_inventory.csv", index=False)
    decision = coverage_decision(inventory)

    quality_rows = []
    missing_frames = []
    duplicate_frames = []
    invalid_frames = []
    outlier_frames = []
    candidates = inventory[inventory["has_rows_after_discovery_end"]].sort_values("oos_coverage_days", ascending=False)
    for _, row in candidates.head(3).iterrows():
        path = Path(row["path"])
        try:
            report, missing, duplicates, invalid, outliers = audit_ohlcv(path)
            quality_rows.append(report)
            for frame, target in [
                (missing, missing_frames),
                (duplicates, duplicate_frames),
                (invalid, invalid_frames),
                (outliers, outlier_frames),
            ]:
                if not frame.empty:
                    copied = frame.copy()
                    copied["source_path"] = str(path)
                    target.append(copied)
        except Exception as exc:
            quality_rows.append({"path": str(path), "coverage_status": "unreadable", "error": str(exc)})
    quality = pd.DataFrame(quality_rows)
    quality.to_csv(audit_dir / "oos_data_quality_report.csv", index=False)
    pd.concat(missing_frames, ignore_index=True).to_csv(audit_dir / "oos_missing_ranges.csv", index=False) if missing_frames else pd.DataFrame(columns=["missing_start", "missing_end", "missing_minutes", "source_path"]).to_csv(audit_dir / "oos_missing_ranges.csv", index=False)
    pd.concat(duplicate_frames, ignore_index=True).to_csv(audit_dir / "oos_duplicate_rows.csv", index=False) if duplicate_frames else pd.DataFrame().to_csv(audit_dir / "oos_duplicate_rows.csv", index=False)
    pd.concat(invalid_frames, ignore_index=True).to_csv(audit_dir / "oos_invalid_ohlc_rows.csv", index=False) if invalid_frames else pd.DataFrame().to_csv(audit_dir / "oos_invalid_ohlc_rows.csv", index=False)
    pd.concat(outlier_frames, ignore_index=True).to_csv(audit_dir / "oos_outlier_rows.csv", index=False) if outlier_frames else pd.DataFrame().to_csv(audit_dir / "oos_outlier_rows.csv", index=False)

    (audit_dir / "oos_coverage_decision.md").write_text(write_coverage_report(decision, inventory, quality), encoding="utf-8")
    if decision["status"] == "blocked":
        (RESEARCH_ROOT / "reports" / "R9_oos_validation_report.md").write_text(write_r9_report(decision, quality), encoding="utf-8")
        config_hash = stable_hash({
            "stage": "R9",
            "discovery_end": DISCOVERY_END.isoformat(),
            "min_oos_days": 90,
            "search_roots": [str(p) for p in SEARCH_ROOTS],
            "decision": decision,
        })
        data_hash = stable_hash(inventory.to_dict(orient="records"))
        append_run_log({
            "run_id": "R9_OOS_VALIDATION",
            "stage": "R9",
            "script": "research_core/run_oos_validation.py",
            "config_hash": config_hash,
            "data_hash": data_hash,
            "git_commit": current_git_commit(),
            "run_timestamp": datetime.now(timezone.utc).isoformat(),
            "random_seed": RANDOM_SEED,
            "data_layer": "oos",
            "status": "blocked",
            "notes": "oos_data_unavailable_or_insufficient",
        })
        return

    raise NotImplementedError("Sufficient OOS data path is intentionally gated for a later extension.")


if __name__ == "__main__":
    main()
