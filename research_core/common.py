"""Shared helpers for Research Core scripts."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = REPO_ROOT / "research_core"
DISCOVERY_DATA_PATH = Path("/Users/muce/PycharmProjects/20260621/eth/backtest_results/stage2/data_audit/merged_ethusdt_1m.csv")
START_UTC = "2024-01-01 00:00:00+00:00"
END_UTC = "2026-06-24 12:05:00+00:00"
RANDOM_SEED = 20260624


def ensure_research_dirs() -> None:
    for name in [
        "manifests",
        "schemas",
        "events",
        "factor_analysis/plots",
        "stability",
        "random_baseline",
        "bootstrap",
        "reports",
        "logs",
    ]:
        (RESEARCH_ROOT / name).mkdir(parents=True, exist_ok=True)


def file_sha256(path: Path | str) -> str:
    path = Path(path)
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def current_git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_simple_yaml(path: Path, payload: dict[str, Any]) -> None:
    """Write simple YAML without adding a dependency."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key, value in payload.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                if isinstance(item, dict):
                    lines.append("  -")
                    for k, v in item.items():
                        lines.append(f"      {k}: {json.dumps(v, ensure_ascii=False) if isinstance(v, str) else v}")
                else:
                    lines.append(f"  - {item}")
        elif isinstance(value, dict):
            lines.append(f"{key}:")
            for k, v in value.items():
                lines.append(f"  {k}: {json.dumps(v, ensure_ascii=False) if isinstance(v, str) else v}")
        else:
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False) if isinstance(value, str) else str(value).lower() if isinstance(value, bool) else value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_run_log(row: dict[str, Any]) -> None:
    path = RESEARCH_ROOT / "logs" / "run_log.csv"
    required = [
        "run_id",
        "stage",
        "script",
        "config_hash",
        "data_hash",
        "git_commit",
        "run_timestamp",
        "random_seed",
        "data_layer",
        "status",
        "notes",
    ]
    frame = pd.DataFrame([{k: row.get(k, "") for k in required}])
    if path.exists():
        old = pd.read_csv(path)
        frame = pd.concat([old, frame], ignore_index=True)
    frame.to_csv(path, index=False)


def validate_run_log_row(row: dict[str, Any]) -> bool:
    required = ["config_hash", "data_hash", "git_commit", "run_timestamp", "random_seed", "data_layer"]
    return all(bool(row.get(k)) for k in required)


def validate_data_manifest_record(record: dict[str, Any]) -> bool:
    required = ["dataset_name", "symbol", "timeframe", "path", "start_utc", "end_utc", "row_count", "sha256", "data_layer", "notes"]
    if not all(k in record for k in required):
        return False
    if record.get("data_layer") == "discovery" and record.get("oos_eligible") is True:
        return False
    return True
