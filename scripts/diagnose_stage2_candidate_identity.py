"""Create append-only CR-2026-004 evidence from the retained failed PRICE staging."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import polars as pl

from era100x.research.stage_2.manifests.configuration import parameter_sets
from era100x.research.stage_2.pipelines.candidates.candidate_diagnostics import (
    classify_legacy_price_records,
)

FAILED_RUN_ID = "stage2-g1-full-a-20260716-4c15e46"


def load_records(failed_run_root: Path, days: int) -> list[dict[str, object]]:
    if failed_run_root.name != FAILED_RUN_ID:
        raise ValueError("diagnosis must use the retained CR-2026-004 failed run")
    checkpoint = json.loads((failed_run_root / "checkpoint.json").read_text())
    if checkpoint.get("status") != "FAILED" or (failed_run_root / "published/data").exists():
        raise ValueError("failed-run protection check failed")
    root = failed_run_root / "staging/data/instrument=BTCUSDT/variant=V1_PRICE/market_episodes"
    files = sorted(
        (path for path in root.rglob("part-*.parquet") if not path.name.startswith("._")),
        key=lambda path: path.parent.name,
    )[:days]
    if len(files) != days:
        raise ValueError(f"expected {days} retained PRICE partitions, found {len(files)}")
    records: list[dict[str, object]] = []
    for path in files:
        frame = pl.read_parquet(path)
        if "empty_partition" in frame.columns:
            continue
        processing = path.parent.name.removeprefix("date=")
        relative = path.relative_to(root).as_posix()
        for ordinal, row in enumerate(frame.to_dicts()):
            records.append(
                {
                    **row,
                    "source_processing_partition": processing,
                    "source_row_ordinal": ordinal,
                    "source_file_logical_path": relative,
                }
            )
    return records


def publish_evidence(
    *, failed_run_root: Path, output_root: Path, days: int, code_commit: str
) -> dict[str, object]:
    if output_root.exists():
        raise FileExistsError(f"append-only diagnostic evidence exists: {output_root}")
    for name in ("staging", "published", "manifests", "reports", "logs", "tmp"):
        (output_root / name).mkdir(parents=True, exist_ok=False)
    records = load_records(failed_run_root, days)
    timing = {item.parameter_set_id: item.timing_id for item in parameter_sets()}
    first = classify_legacy_price_records(records, timing)
    second = classify_legacy_price_records(list(reversed(records)), timing)
    if first != second:
        raise ValueError("candidate diagnosis is input-order dependent")
    report_path = output_root / "reports" / "candidate-classification.parquet"
    pl.DataFrame(first.classifications, strict=False).write_parquet(report_path, compression="zstd")
    report_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
    summary = {
        "schema": "cr-2026-004-candidate-diagnosis-v1",
        "audit_of_run_id": FAILED_RUN_ID,
        "code_commit": code_commit,
        "days": days,
        "classification_parquet_sha256": report_hash,
        **first.summary,
    }
    summary_path = output_root / "reports" / "summary.json"
    summary_path.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema": "cr-2026-004-diagnostic-manifest-v1",
        "audit_of_run_id": FAILED_RUN_ID,
        "code_commit": code_commit,
        "summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        "classification_parquet_sha256": report_hash,
    }
    manifest["manifest_hash"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (output_root / "manifests" / f"{manifest['manifest_hash']}.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--failed-run-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--days", type=int, default=50)
    parser.add_argument("--code-commit", required=True)
    args = parser.parse_args()
    summary = publish_evidence(
        failed_run_root=args.failed_run_root,
        output_root=args.output_root,
        days=args.days,
        code_commit=args.code_commit,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
