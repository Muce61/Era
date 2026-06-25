"""R2: Factor quintile and monotonicity analysis."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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
from research_core.event_table import FACTOR_COLUMNS, FACTOR_COMMON, HORIZONS
from research_core.factor_analysis import summarize_factor


def load_events() -> pd.DataFrame:
    parquet_path = RESEARCH_ROOT / "events" / "event_candidates.parquet"
    fallback_path = RESEARCH_ROOT / "events" / "event_candidates.pkl"
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)
    if fallback_path.exists():
        return pd.read_pickle(fallback_path)
    raise FileNotFoundError("Run R1 first: missing event_candidates.parquet/pkl")


def main() -> None:
    ensure_research_dirs()
    events = load_events()
    rows = []
    meta_rows = []
    for factor in FACTOR_COLUMNS:
        if factor not in events.columns:
            continue
        for horizon in HORIZONS:
            summary, meta = summarize_factor(events, factor, horizon)
            if not summary.empty:
                rows.append(summary)
            meta_rows.append(meta)
    detail = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    meta_df = pd.DataFrame(meta_rows)
    if not detail.empty:
        detail.insert(1, "common", detail["factor"].map(FACTOR_COMMON).fillna(""))
    if not meta_df.empty:
        meta_df.insert(1, "common", meta_df["factor"].map(FACTOR_COMMON).fillna(""))
    detail.to_csv(RESEARCH_ROOT / "factor_analysis" / "factor_quintile_summary.csv", index=False)
    meta_df.to_csv(RESEARCH_ROOT / "factor_analysis" / "factor_monotonicity_summary.csv", index=False)

    data_hash = file_sha256(DISCOVERY_DATA_PATH) if DISCOVERY_DATA_PATH.exists() else ""
    config_hash = stable_hash({
        "factors": FACTOR_COLUMNS,
        "factor_common": FACTOR_COMMON,
        "horizons": HORIZONS,
        "method": "quintile_monotonicity_v1",
    })
    append_run_log({
        "run_id": "R2_FACTOR_QUINTILE_ANALYSIS",
        "stage": "R2",
        "script": "research_core/run_factor_quintile_analysis.py",
        "config_hash": config_hash,
        "data_hash": data_hash,
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "discovery",
        "status": "success",
        "notes": f"Analyzed {len(FACTOR_COLUMNS)} factors across {len(HORIZONS)} horizons.",
    })

    counts = meta_df["candidate_status"].value_counts().to_dict() if not meta_df.empty else {}
    report = [
        "# R2 Factor Monotonicity Report",
        "",
        f"event_count: {len(events)}",
        f"factor_count: {len(FACTOR_COLUMNS)}",
        f"horizons: {HORIZONS}",
        "",
        "## Candidate Status Counts",
        "",
        pd.DataFrame([counts]).to_markdown(index=False) if counts else "No factor rows.",
        "",
        "## Blocking Rules For Next Stages",
        "",
        "- R3 stability must pass before any factor can enter strategy composition.",
        "- R4 random baseline must use `(1+count)/(N+1)` percentile formulas.",
        "- R5-R7 must standardize Bootstrap, risk sizing, and manual audit before any OOS claim.",
        "- Without new unseen data, R8 cannot return an A-type OOS-ready conclusion.",
    ]
    (RESEARCH_ROOT / "reports" / "R2_factor_monotonicity_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
