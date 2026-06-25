"""R4: Random baseline test for R3-passed factor-horizon rows."""

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
from research_core.random_baseline_analysis import summarize_random_baseline


N_RANDOM_RUNS = 5000


def load_events() -> pd.DataFrame:
    parquet_path = RESEARCH_ROOT / "events" / "event_candidates.parquet"
    fallback_path = RESEARCH_ROOT / "events" / "event_candidates.pkl"
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)
    if fallback_path.exists():
        return pd.read_pickle(fallback_path)
    raise FileNotFoundError("Run R1 first: missing event_candidates.parquet/pkl")


def load_r3_candidates() -> pd.DataFrame:
    path = RESEARCH_ROOT / "stability" / "factor_stability_summary.csv"
    if not path.exists():
        raise FileNotFoundError("Run R3 first: missing factor_stability_summary.csv")
    df = pd.read_csv(path)
    return df[df["stability_status"] == "candidate_for_random_baseline"].copy()


def main() -> None:
    ensure_research_dirs()
    events = load_events()
    candidates = load_r3_candidates()
    summary, runs = summarize_random_baseline(events, candidates, n_runs=N_RANDOM_RUNS, random_seed=RANDOM_SEED)
    summary_path = RESEARCH_ROOT / "random_baseline" / "factor_random_baseline_summary.csv"
    runs_path = RESEARCH_ROOT / "random_baseline" / "factor_random_baseline_runs.csv"
    summary.to_csv(summary_path, index=False)
    runs.to_csv(runs_path, index=False)

    status_counts = summary["random_baseline_status"].value_counts().to_dict() if not summary.empty else {}
    pass_count = int(status_counts.get("passes_random_baseline", 0))
    weak_count = int(status_counts.get("weak_random_evidence", 0))
    fdr_pass_count = int(summary["passes_after_fdr_5pct"].sum()) if "passes_after_fdr_5pct" in summary else 0
    config_hash = stable_hash({
        "method": "factor_random_baseline_v1",
        "n_random_runs": N_RANDOM_RUNS,
        "percentile_formula": "(1+count)/(N+1)",
        "candidate_count": len(candidates),
        "random_seed": RANDOM_SEED,
        "baseline": "random_q1_q5_assignment_same_counts_same_event_pool",
    })
    data_hash = file_sha256(DISCOVERY_DATA_PATH) if DISCOVERY_DATA_PATH.exists() else ""
    append_run_log({
        "run_id": "R4_FACTOR_RANDOM_BASELINE",
        "stage": "R4",
        "script": "research_core/run_factor_random_baseline.py",
        "config_hash": config_hash,
        "data_hash": data_hash,
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "discovery",
        "status": "success",
        "notes": f"Tested {len(summary)} factor-horizon candidates; {pass_count} passed, {weak_count} were weak, {fdr_pass_count} passed BH-FDR 5%.",
    })

    top = summary.sort_values(
        ["random_baseline_status", "directional_percentile"],
        ascending=[True, False],
    ).head(25)
    report = [
        "# R4 Factor Random Baseline Report",
        "",
        f"event_count: {len(events)}",
        f"r3_candidate_count: {len(candidates)}",
        f"random_runs_per_candidate: {N_RANDOM_RUNS}",
        "percentile_formula: `(1+count)/(N+1)`",
        f"bh_fdr_5pct_pass_count: {fdr_pass_count}",
        "data_layer: discovery",
        "data_coverage_note: current 2024-01-01 to 2026-06-24 data is not final OOS.",
        "",
        "## Method",
        "",
        "- For each R3-passed factor-horizon row, compute observed `Q5 mean forward return - Q1 mean forward return`.",
        "- Preserve the observed Q1 and Q5 event counts.",
        "- Randomly sample disjoint Q1/Q5 groups from the same event pool without replacement.",
        "- Convert negative factors into directional edge by multiplying by the R3 full-sample direction.",
        "- Use `(1+count)/(N+1)` for both directional percentile and one-sided p value.",
        "- Apply Benjamini-Hochberg FDR across the tested factor-horizon rows as an additional descriptive guardrail.",
        "- Passing R4 only permits deeper validation; it is not a strategy rule or OOS claim.",
        "",
        "## Status Counts",
        "",
        pd.DataFrame([status_counts]).to_markdown(index=False) if status_counts else "No random baseline rows.",
        "",
        "## Top Rows",
        "",
        top.to_markdown(index=False) if not top.empty else "No random baseline summary.",
        "",
        "## Next Gate",
        "",
        "All R4 results remain selected-on-discovery evidence because R2/R3/R4 use the same data layer. The correct next step is stress testing and then genuinely new data, not immediate strategy filtering.",
        "",
        "R5 must stress surviving factor evidence with bootstrap/block bootstrap and must still avoid turning these descriptive factors into filters before validation is complete.",
    ]
    (RESEARCH_ROOT / "reports" / "R4_factor_random_baseline_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
