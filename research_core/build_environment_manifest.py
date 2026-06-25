"""R0: Freeze research environment and data layer metadata."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from research_core.common import (
    DISCOVERY_DATA_PATH,
    RANDOM_SEED,
    REPO_ROOT,
    RESEARCH_ROOT,
    append_run_log,
    current_git_commit,
    ensure_research_dirs,
    file_sha256,
    stable_hash,
    validate_data_manifest_record,
    write_json,
    write_simple_yaml,
)


def main() -> None:
    ensure_research_dirs()
    status = "success"
    notes = []
    if not DISCOVERY_DATA_PATH.exists():
        status = "missing_discovery_dataset"
        data_hash = ""
        row_count = 0
        start = ""
        end = ""
        notes.append(f"Missing discovery dataset: {DISCOVERY_DATA_PATH}")
    else:
        data_hash = file_sha256(DISCOVERY_DATA_PATH)
        ts = pd.read_csv(DISCOVERY_DATA_PATH, usecols=["timestamp"], parse_dates=["timestamp"])["timestamp"]
        ts = pd.to_datetime(ts, utc=True)
        row_count = int(len(ts))
        start = str(ts.iloc[0])
        end = str(ts.iloc[-1])

    record = {
        "dataset_name": "ethusdt_stage2_merged_1m",
        "symbol": "ETHUSDT",
        "timeframe": "1m",
        "path": str(DISCOVERY_DATA_PATH),
        "start_utc": start,
        "end_utc": end,
        "row_count": row_count,
        "sha256": data_hash,
        "data_layer": "discovery",
        "oos_eligible": False,
        "notes": "Observed repeatedly in Stage1-Stage4; not eligible for final OOS.",
    }
    write_json(RESEARCH_ROOT / "manifests" / "data_manifest.json", {"datasets": [record]})

    policy = {
        "no_parameter_optimization": True,
        "current_data_is_discovery_only": True,
        "require_next_1m_open_execution": True,
        "require_config_hash": True,
        "require_data_hash": True,
        "require_run_log": True,
        "allowed_current_conclusion": "research_only_no_oos_no_paper_approval",
    }
    write_simple_yaml(RESEARCH_ROOT / "manifests" / "research_policy.yaml", policy)

    frozen_configs = sorted(str(p.relative_to(REPO_ROOT)) for p in (REPO_ROOT / "configs").glob("*.json"))
    config_payload = {}
    for rel in frozen_configs:
        path = REPO_ROOT / rel
        config_payload[rel] = json.loads(path.read_text(encoding="utf-8"))
    config_hash = stable_hash(config_payload)

    append_run_log({
        "run_id": "R0_ENVIRONMENT_FREEZE",
        "stage": "R0",
        "script": "research_core/build_environment_manifest.py",
        "config_hash": config_hash,
        "data_hash": data_hash,
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "discovery",
        "status": status,
        "notes": "; ".join(notes) if notes else "Environment frozen for Research Core R0-R2.",
    })

    existing = {
        "stage1_conclusion": (REPO_ROOT / "backtest_results/stage1/stage1_conclusion.md").exists(),
        "stage2_conclusion": (REPO_ROOT / "backtest_results/stage2/stage2_conclusion.md").exists(),
        "stage3_conclusion": (REPO_ROOT / "backtest_results/stage3/stage3_conclusion.md").exists(),
        "stage4_conclusion": (REPO_ROOT / "backtest_results/stage4/stage4_conclusion.md").exists(),
    }
    report = [
        "# R0 Environment Freeze",
        "",
        f"status: {status}",
        f"discovery_dataset: `{DISCOVERY_DATA_PATH}`",
        f"data_hash: `{data_hash}`",
        f"row_count: {row_count}",
        f"start_utc: {start}",
        f"end_utc: {end}",
        "",
        "## Stage Summary Availability",
        "",
        pd.DataFrame([existing]).to_markdown(index=False),
        "",
        "## Decisions",
        "",
        "- Current data is discovery only and not final OOS.",
        "- Strategy optimization is not allowed in Research Core R0-R2.",
        "- Next required infrastructure: event table, factor catalog, factor monotonicity report.",
    ]
    (RESEARCH_ROOT / "reports" / "R0_environment_freeze.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    if not validate_data_manifest_record(record):
        raise ValueError("Invalid data manifest record")


if __name__ == "__main__":
    main()

