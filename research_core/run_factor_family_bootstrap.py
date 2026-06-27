"""R5: Factor-family bootstrap and stress tests."""

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
from research_core.family_bootstrap_analysis import (
    attach_family,
    factor_bootstrap_summary,
    family_bootstrap_summary,
    horizon_decay_summary,
    month_stress_summary,
    role_classification,
)


N_BOOTSTRAP_RUNS = 5000


def load_events() -> pd.DataFrame:
    parquet_path = RESEARCH_ROOT / "events" / "event_candidates.parquet"
    fallback_path = RESEARCH_ROOT / "events" / "event_candidates.pkl"
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)
    if fallback_path.exists():
        return pd.read_pickle(fallback_path)
    raise FileNotFoundError("Run R1 first: missing event_candidates.parquet/pkl")


def load_r4_candidates() -> pd.DataFrame:
    path = RESEARCH_ROOT / "random_baseline" / "factor_random_baseline_summary.csv"
    if not path.exists():
        raise FileNotFoundError("Run R4 first: missing factor_random_baseline_summary.csv")
    df = pd.read_csv(path)
    return df[df["random_baseline_status"] == "passes_random_baseline"].copy()


def load_literature_queue() -> pd.DataFrame:
    path = RESEARCH_ROOT / "literature" / "literature_research_queue.csv"
    if not path.exists():
        raise FileNotFoundError("Missing literature_research_queue.csv")
    return pd.read_csv(path)


def main() -> None:
    ensure_research_dirs()
    events = load_events()
    queue = load_literature_queue()
    candidates = attach_family(load_r4_candidates(), queue)

    factor_summary = factor_bootstrap_summary(events, candidates, N_BOOTSTRAP_RUNS, RANDOM_SEED)
    family_summary = family_bootstrap_summary(factor_summary, queue)
    stress = month_stress_summary(events, candidates)
    decay = horizon_decay_summary(factor_summary, queue)
    roles = role_classification(family_summary, decay, queue)

    out_dir = RESEARCH_ROOT / "bootstrap"
    factor_summary.to_csv(out_dir / "factor_bootstrap_summary.csv", index=False)
    family_summary.to_csv(out_dir / "family_bootstrap_summary.csv", index=False)
    stress.to_csv(out_dir / "month_stress_summary.csv", index=False)
    decay.to_csv(out_dir / "horizon_decay_summary.csv", index=False)
    roles.to_csv(out_dir / "role_classification.csv", index=False)

    config_hash = stable_hash({
        "method": "factor_family_bootstrap_v1",
        "n_bootstrap_runs": N_BOOTSTRAP_RUNS,
        "candidate_count": len(candidates),
        "family_count": len(queue),
        "random_seed": RANDOM_SEED,
        "data_layer": "discovery",
    })
    data_hash = file_sha256(DISCOVERY_DATA_PATH) if DISCOVERY_DATA_PATH.exists() else ""
    robust_families = int((family_summary["family_bootstrap_status"] == "family_robust_candidate").sum())
    r6_eligible = int((roles["allowed_next_step"] == "eligible_for_R6_validation").sum())
    append_run_log({
        "run_id": "R5_FACTOR_FAMILY_BOOTSTRAP",
        "stage": "R5",
        "script": "research_core/run_factor_family_bootstrap.py",
        "config_hash": config_hash,
        "data_hash": data_hash,
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "discovery",
        "status": "success",
        "notes": f"Tested {len(candidates)} factor-horizon rows across {len(queue)} families; {robust_families} robust families; {r6_eligible} eligible for R6.",
    })

    report = [
        "# R5 Factor Family Bootstrap Report",
        "",
        f"event_count: {len(events)}",
        f"r4_candidate_count: {len(candidates)}",
        f"family_count: {len(queue)}",
        f"bootstrap_runs_per_test: {N_BOOTSTRAP_RUNS}",
        "data_layer: discovery",
        "data_coverage_note: current 2024-01-01 to 2026-06-24 data is not final OOS.",
        "",
        "## Status Counts",
        "",
        "### Factor Bootstrap",
        factor_summary["bootstrap_status"].value_counts().to_frame("count").to_markdown() if not factor_summary.empty else "No factor rows.",
        "",
        "### Family Bootstrap",
        family_summary["family_bootstrap_status"].value_counts().to_frame("count").to_markdown() if not family_summary.empty else "No family rows.",
        "",
        "### Stress",
        stress["stress_status"].value_counts().to_frame("count").to_markdown() if not stress.empty else "No stress rows.",
        "",
        "### Role Classification",
        roles["allowed_next_step"].value_counts().to_frame("count").to_markdown() if not roles.empty else "No role rows.",
        "",
        "## Family Summary",
        "",
        family_summary.to_markdown(index=False),
        "",
        "## Horizon Decay",
        "",
        decay.to_markdown(index=False),
        "",
        "## Role Classification",
        "",
        roles.to_markdown(index=False),
        "",
        "## Required Answers",
        "",
        "1. Family bootstrap pass/fail is reported in `family_bootstrap_summary.csv`.",
        "2. Monthly and quarterly fragility is captured by `monthly_same_direction_rate`, `quarterly_same_direction_rate`, and `family_bootstrap_status`.",
        "3. Best-month and best-quarter dependence is reported in `month_stress_summary.csv`.",
        "4. Single-horizon dependence is reported in `horizon_decay_summary.csv`.",
        "5. Direction consistency across horizons is reported in `horizon_decay_summary.csv`.",
        "6. Alpha/avoid/risk/execution roles are reported in `role_classification.csv`.",
        "7. Selection-on-discovery bias still exists because R2-R5 use the same discovery event table.",
        "8. No family is allowed to become a strategy filter after R5.",
        "9. R6 should only validate families marked `eligible_for_R6_validation`; blocked families need data before validation.",
        "10. R5 is a pressure-test gate, not OOS evidence or simulation approval.",
    ]
    (RESEARCH_ROOT / "reports" / "R5_factor_family_bootstrap_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
