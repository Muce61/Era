"""R3: Validate factor stability across time and available regimes."""

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
from research_core.event_table import FACTOR_COMMON
from research_core.stability_analysis import summarize_stability


def load_events() -> pd.DataFrame:
    parquet_path = RESEARCH_ROOT / "events" / "event_candidates.parquet"
    fallback_path = RESEARCH_ROOT / "events" / "event_candidates.pkl"
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)
    if fallback_path.exists():
        return pd.read_pickle(fallback_path)
    raise FileNotFoundError("Run R1 first: missing event_candidates.parquet/pkl")


def load_r2_meta() -> pd.DataFrame:
    path = RESEARCH_ROOT / "factor_analysis" / "factor_monotonicity_summary.csv"
    if not path.exists():
        raise FileNotFoundError("Run R2 first: missing factor_monotonicity_summary.csv")
    return pd.read_csv(path)


def main() -> None:
    ensure_research_dirs()
    events = load_events()
    r2_meta = load_r2_meta()
    detail, summary = summarize_stability(events, r2_meta)
    detail.to_csv(RESEARCH_ROOT / "stability" / "factor_stability_by_group.csv", index=False)
    summary.to_csv(RESEARCH_ROOT / "stability" / "factor_stability_summary.csv", index=False)

    status_counts = summary["stability_status"].value_counts().to_dict() if not summary.empty else {}
    pass_count = int(status_counts.get("candidate_for_random_baseline", 0))
    config_hash = stable_hash({
        "method": "factor_stability_v1",
        "r2_rows": len(r2_meta),
        "factor_common": FACTOR_COMMON,
        "group_columns": ["year_group", "quarter_group", "trend_regime", "volatility_regime"],
        "gate": {
            "candidate_status": "candidate_for_validation",
            "min_valid_years": 2,
            "min_valid_quarters": 4,
            "year_same_direction_rate": 0.60,
            "quarter_same_direction_rate": 0.55,
        },
    })
    data_hash = file_sha256(DISCOVERY_DATA_PATH) if DISCOVERY_DATA_PATH.exists() else ""
    append_run_log({
        "run_id": "R3_FACTOR_STABILITY",
        "stage": "R3",
        "script": "research_core/run_factor_stability_analysis.py",
        "config_hash": config_hash,
        "data_hash": data_hash,
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "discovery",
        "status": "success",
        "notes": f"Validated {len(summary)} factor-horizon rows; {pass_count} passed to random baseline candidacy.",
    })

    top = summary.sort_values(
        ["stability_status", "quarter_same_direction_rate", "year_same_direction_rate"],
        ascending=[True, False, False],
    ).head(20)
    report = [
        "# R3 Factor Stability Report",
        "",
        f"event_count: {len(events)}",
        f"factor_horizon_rows: {len(summary)}",
        f"data_layer: discovery",
        "data_coverage_note: current 2024-01-01 to 2026-06-24 data is not final OOS.",
        "",
        "## Stability Gate",
        "",
        "- R2 status must be `candidate_for_validation`.",
        "- At least 2 yearly groups and 4 quarterly groups must be sample-sufficient.",
        "- Year same-direction rate must be >= 60%.",
        "- Quarter same-direction rate must be >= 55%.",
        "- Passing R3 only means eligible for R4 random-baseline testing, not strategy approval.",
        "",
        "## Status Counts",
        "",
        pd.DataFrame([status_counts]).to_markdown(index=False) if status_counts else "No stability rows.",
        "",
        "## Top Rows",
        "",
        top.to_markdown(index=False) if not top.empty else "No stability summary.",
        "",
        "## Regime Limitation",
        "",
        "Current R1 event table stores `trend_regime` and `volatility_regime` as `unavailable`; R3 therefore treats state-regime stability as unavailable rather than evidence.",
    ]
    (RESEARCH_ROOT / "reports" / "R3_factor_stability_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
