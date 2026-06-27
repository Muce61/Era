"""R6: Validate R5-eligible factor-family scores before strategy construction."""

from __future__ import annotations

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
from research_core.family_validation_analysis import (
    build_family_scores,
    c1_overlap,
    correlation_rows,
    decision_summary,
    group_summary,
    stress_summary,
    walk_forward_windows,
)


def load_events() -> pd.DataFrame:
    path = RESEARCH_ROOT / "events" / "event_candidates.parquet"
    if not path.exists():
        raise FileNotFoundError("Run R1 first: missing event_candidates.parquet")
    return pd.read_parquet(path)


def main() -> None:
    ensure_research_dirs()
    out_dir = RESEARCH_ROOT / "family_validation"
    out_dir.mkdir(parents=True, exist_ok=True)

    events = load_events()
    r4 = pd.read_csv(RESEARCH_ROOT / "random_baseline" / "factor_random_baseline_summary.csv")
    scores, metadata = build_family_scores(events, r4)
    scores.to_parquet(out_dir / "family_scores.parquet", index=False)
    metadata.to_csv(out_dir / "family_score_metadata.csv", index=False)

    corr = correlation_rows(scores, events)
    groups = group_summary(events, scores)
    wf_windows, wf_summary = walk_forward_windows(events, r4)
    overlap = c1_overlap(events, scores)
    stress = stress_summary(events, scores)
    decisions = decision_summary(wf_summary, corr, overlap, stress)

    corr.to_csv(out_dir / "family_score_correlation.csv", index=False)
    groups.to_csv(out_dir / "family_score_group_summary.csv", index=False)
    wf_windows.to_csv(out_dir / "walk_forward_family_windows.csv", index=False)
    wf_summary.to_csv(out_dir / "walk_forward_family_summary.csv", index=False)
    overlap.to_csv(out_dir / "c1_overlap_audit.csv", index=False)
    stress.to_csv(out_dir / "family_score_stress.csv", index=False)
    decisions.to_csv(out_dir / "r6_decision_summary.csv", index=False)

    config_hash = stable_hash({
        "method": "family_validation_v1",
        "families": ["momentum_continuation", "breakout_conviction"],
        "score": "winsor_1_99_zscore_equal_weight",
        "walk_forward": {"train_months": 12, "test_months": 3, "step_months": 3},
        "data_layer": "discovery",
    })
    data_hash = file_sha256(DISCOVERY_DATA_PATH) if DISCOVERY_DATA_PATH.exists() else ""
    eligible = int((decisions["r6_status"] == "eligible_for_R7_candidate_construction").sum())
    append_run_log({
        "run_id": "R6_FAMILY_VALIDATION",
        "stage": "R6",
        "script": "research_core/run_family_validation.py",
        "config_hash": config_hash,
        "data_hash": data_hash,
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "discovery",
        "status": "success",
        "notes": f"Validated 2 family scores; {eligible} eligible for R7 candidate construction.",
    })

    report = [
        "# R6 Family Validation Report",
        "",
        f"event_count: {len(events)}",
        "data_layer: discovery",
        "data_coverage_note: current 2024-01-01 to 2026-06-24 data is not final OOS.",
        "",
        "## Decisions",
        decisions.to_markdown(index=False),
        "",
        "## Score Correlation",
        corr.to_markdown(index=False),
        "",
        "## Walk-forward Summary",
        wf_summary.to_markdown(index=False),
        "",
        "## C1 Overlap",
        overlap.to_markdown(index=False),
        "",
        "## Stress Summary",
        stress.to_markdown(index=False),
        "",
        "## Required Answers",
        "",
        "1. Momentum and breakout decisions are in `r6_decision_summary.csv`.",
        "2. Correlation and redundancy are in `family_score_correlation.csv`.",
        "3. C1/FIRST_BREAKOUT overlap is in `c1_overlap_audit.csv`.",
        "4. R6 still has selection-on-discovery bias because it uses the same event table as R2-R5.",
        "5. R6 does not permit live strategy filters or simulation approval.",
        "6. New unseen data is still required before any OOS claim.",
    ]
    (RESEARCH_ROOT / "reports" / "R6_family_validation_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
