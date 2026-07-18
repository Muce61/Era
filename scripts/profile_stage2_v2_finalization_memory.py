#!/usr/bin/env python3
"""Profile real packed-object scanning and Foundation evidence sealing for CR-2026-012."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.research.stage_2.manifests.models import canonical_json
from era100x.research.stage_2.runtime_v2.foundation_pipeline import (
    FoundationShardCheckpoint,
)
from era100x.research.stage_2.runtime_v2.memory import ProcessMemoryBudget
from era100x.research.stage_2.runtime_v2.models import (
    MAX_PROCESS_CURRENT_RSS_BYTES,
    MAX_PROCESS_RSS_DELTA_BYTES,
)
from era100x.research.stage_2.runtime_v2.production_backend import (
    PipelineTaskResult,
    TaskAggregateEvidence,
)

EXPECTED_FAILED_RUN = "stage2-g1-v2-b-20260718T105814Z-cb5c25abd485"
EXPECTED_MONTHLY = 316
EXPECTED_PACKED = 82
EXPECTED_RECEIPTS = 9_504
MAX_ARROW_BYTES = 1_073_741_824


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--failed-run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _write_once(path: Path, payload: dict[str, Any]) -> str:
    encoded = canonical_json(payload).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise FileExistsError(f"write-once evidence conflict: {path}")
        return digest
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(path)
    return digest


def _release(table: pa.Table | None = None) -> None:
    del table
    gc.collect()
    pa.default_memory_pool().release_unused()


def main() -> int:
    args = _arguments()
    run_root = args.failed_run_root.resolve()
    if run_root.name != EXPECTED_FAILED_RUN:
        raise ValueError("CR-2026-012 profile is bound to the approved failed Run B")
    checkpoint_path = run_root / "checkpoint-v2.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if checkpoint.get("status") != "FAILED_UNPUBLISHED":
        raise ValueError("failed Run B terminal status changed")
    published = run_root / "published"
    if published.exists() and any(
        item.is_file() and not item.name.startswith("._") for item in published.rglob("*")
    ):
        raise ValueError("failed Run B unexpectedly contains published data")

    monthly_paths = tuple(
        sorted(
            item
            for item in (run_root / "staging/foundation/checkpoints").rglob("*.json")
            if not item.name.startswith("._")
        )
    )
    packed_paths = tuple(
        sorted(
            item
            for item in (run_root / "staging/foundation/packed-checkpoints").rglob("*.json")
            if not item.name.startswith("._")
        )
    )
    if len(monthly_paths) != EXPECTED_MONTHLY or len(packed_paths) != EXPECTED_PACKED:
        raise ValueError("failed Run B Foundation checkpoint matrix is incomplete")

    budget = ProcessMemoryBudget(
        current_limit_bytes=MAX_PROCESS_CURRENT_RSS_BYTES,
        delta_limit_bytes=MAX_PROCESS_RSS_DELTA_BYTES,
    )
    max_arrow_bytes = 0
    scanned_rows = 0
    scanned_row_groups = 0
    checkpoints: list[FoundationShardCheckpoint] = []

    with budget.monitor_phase("PACKED_OBJECT_ROW_GROUP_SCAN"):
        for path in packed_paths:
            checkpoint_model = FoundationShardCheckpoint.model_validate_json(path.read_bytes())
            if checkpoint_model.storage_role != "PACKED_FINAL":
                raise ValueError("profile received a non-final Foundation checkpoint")
            checkpoints.append(checkpoint_model)
            if checkpoint_model.artifact is None:
                continue
            object_path = run_root / "staging/snapshot" / checkpoint_model.artifact.relative_path
            parquet = pq.ParquetFile(object_path)
            for ordinal in range(parquet.metadata.num_row_groups):
                table = parquet.read_row_group(ordinal)
                max_arrow_bytes = max(max_arrow_bytes, table.nbytes)
                scanned_rows += table.num_rows
                scanned_row_groups += 1
                budget.check("PACKED_OBJECT_ROW_GROUP", arrow_inflight_bytes=table.nbytes)
                del table
                _release()

    with budget.monitor_phase("FOUNDATION_TASK_SEAL"):
        artifacts_by_hash = {
            item.artifact.object_sha256: item.artifact
            for item in checkpoints
            if item.artifact is not None
        }
        result = PipelineTaskResult(
            artifacts=tuple(artifacts_by_hash[key] for key in sorted(artifacts_by_hash)),
            receipts=tuple(receipt for item in checkpoints for receipt in item.receipts),
            fragments=tuple(fragment for item in checkpoints for fragment in item.fragments),
            seals=tuple(item.seal for item in checkpoints),
            max_inflight_bytes_observed=max_arrow_bytes,
        )
        if len(result.receipts) != EXPECTED_RECEIPTS:
            raise ValueError("packed Foundation receipt count changed")
        evidence = TaskAggregateEvidence.seal(
            {
                "task_id": "FOUNDATION:BTCUSDT",
                "snapshot_id": checkpoint["snapshot_id"],
                "manifest_hash": checkpoint["manifest_hash"],
                "artifacts": tuple(sorted(result.artifacts, key=lambda item: item.object_sha256)),
                "receipts": tuple(
                    sorted(result.receipts, key=lambda item: item.partition.semantic_order_key())
                ),
                "fragments": tuple(sorted(result.fragments, key=lambda item: item.fragment_hash)),
                "seals": tuple(sorted(result.seals, key=lambda item: item.seal_hash)),
                "supporting_evidence": (),
                "global_distributions": (),
                "max_inflight_bytes_observed": max_arrow_bytes,
                "peak_process_rss_bytes": budget.max_peak_rss_bytes_observed,
                "quality_status": "PASS",
            }
        )
        evidence_hash = evidence.semantic_sha256
        budget.check("FOUNDATION_TASK_SEAL_COMPLETE")

    samples = [
        {
            "phase": item.phase,
            "baseline_current_rss_bytes": item.baseline_current_rss_bytes,
            "baseline_peak_rss_bytes": item.baseline_peak_rss_bytes,
            "current_rss_bytes": item.current_rss_bytes,
            "peak_rss_bytes": item.peak_rss_bytes,
            "current_rss_delta_bytes": item.current_rss_delta_bytes,
            "peak_rss_delta_bytes_audit_only": item.peak_rss_delta_bytes,
            "arrow_inflight_bytes": item.arrow_inflight_bytes,
        }
        for item in budget.samples
    ]
    payload = {
        "schema_name": "stage2-v2-finalization-memory-profile",
        "schema_version": "1.0",
        "change_request": "CR-2026-012",
        "read_only_source": True,
        "failed_run_id": EXPECTED_FAILED_RUN,
        "failed_checkpoint_sha256": hashlib.sha256(checkpoint_path.read_bytes()).hexdigest(),
        "monthly_checkpoint_count": len(monthly_paths),
        "packed_checkpoint_count": len(packed_paths),
        "receipt_count": EXPECTED_RECEIPTS,
        "packed_row_group_count": scanned_row_groups,
        "packed_row_count": scanned_rows,
        "max_arrow_bytes": max_arrow_bytes,
        "max_current_rss_bytes": budget.max_current_rss_bytes_observed,
        "max_phase_current_rss_delta_bytes": budget.max_current_rss_delta_bytes_observed,
        "lifetime_peak_rss_bytes_audit_only": budget.max_peak_rss_bytes_observed,
        "lifetime_peak_delta_bytes_audit_only": budget.max_peak_rss_delta_bytes_observed,
        "task_evidence_semantic_sha256": evidence_hash,
        "samples": samples,
        "limits": {
            "arrow_inflight_bytes": MAX_ARROW_BYTES,
            "current_rss_bytes": MAX_PROCESS_CURRENT_RSS_BYTES,
            "phase_current_rss_delta_bytes": MAX_PROCESS_RSS_DELTA_BYTES,
            "lifetime_peak_policy": "AUDIT_ONLY",
        },
        "result": "PASS",
    }
    digest = _write_once(args.output, payload)
    print(canonical_json({"output": args.output.as_posix(), "sha256": digest, **payload}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
