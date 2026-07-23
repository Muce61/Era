"""Append-only execution and verification for one successor producer."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any, cast

from era100x.foundation.governance import require_operation_allowed

from .orchestrator import canonical_hash
from .producer_contracts import ProducerContext
from .production_adapters import RECEIPT_SCHEMA
from .scoped_producers import (
    produce_scoped_ambiguity,
    produce_scoped_first_passage,
    produce_scoped_metrics,
    produce_scoped_paths,
)


def _write_exclusive(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    with path.open("xb") as handle:
        handle.write(encoded)


def _read(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"unsafe or missing producer JSON: {path}")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("producer JSON root must be an object")
    return cast(dict[str, Any], value)


def _seal(value: dict[str, Any], field: str) -> dict[str, Any]:
    result = dict(value)
    result[field] = canonical_hash(value)
    return result


def _artifact_data_root(context: ProducerContext) -> Path:
    return (
        context.receipt_path.parent
        / "artifacts"
        / (f"{context.execution_mode.lower()}-{context.scope.execution_scope_hash[:12]}")
    )


def _bound_data_root(source_root: Path) -> Path:
    output = _read(source_root / "output.json")
    data_root = Path(str(output.get("artifact_data_root", "")))
    if (
        not data_root.is_absolute()
        or data_root.is_symlink()
        or not data_root.is_dir()
        or not data_root.resolve().is_relative_to(source_root.resolve())
    ):
        raise ValueError("upstream producer data-root binding is unsafe")
    return data_root


def _producer_payload(context: ProducerContext, data_root: Path) -> dict[str, Any]:
    start = date.fromisoformat(context.scope.start_date)
    end = date.fromisoformat(context.scope.end_date_exclusive)
    if context.task_id == "S2P13-T11":
        from .seven_day_rehearsal import produce_scoped_lifecycle

        return produce_scoped_lifecycle(
            start_date=start,
            end_date_exclusive=end,
        )
    if context.task_id == "S2P13-T12":
        return produce_scoped_paths(
            output_root=data_root,
            start_date=start,
            end_date_exclusive=end,
        )
    if context.task_id in {"S2P13-T13", "S2P13-T14"}:
        source = context.upstream["S2P13-T12"]
        source_root = _bound_data_root(source.artifact_root)
        if context.task_id == "S2P13-T13":
            return produce_scoped_metrics(
                output_root=data_root,
                source_paths_root=source_root,
                source_snapshot_id=source.snapshot_id,
                source_manifest_hash=source.manifest_hash,
                source_catalog_hash=source.catalog_hash,
            )
        return produce_scoped_first_passage(
            output_root=data_root,
            source_paths_root=source_root,
            source_snapshot_id=source.snapshot_id,
            source_manifest_hash=source.manifest_hash,
            source_catalog_hash=source.catalog_hash,
        )
    if context.task_id == "S2P13-T15":
        source = context.upstream["S2P13-T14"]
        result = produce_scoped_ambiguity(
            output_root=data_root,
            source_first_passage_root=_bound_data_root(source.artifact_root),
        )
        result["source_first_passage_root"] = str(source.artifact_root / "data")
        return result
    if context.task_id == "S2P13-T16":
        if context.execution_mode == "FORMAL":
            raise ValueError(
                "formal T16 requires a frozen successor binning handoff; "
                "rehearsal bins cannot authorize a formal Run"
            )
        from .seven_day_rehearsal import produce_scoped_conditional_baseline

        t15_output = _read(context.upstream["S2P13-T15"].artifact_root / "output.json")
        source_root = Path(str(t15_output.get("source_first_passage_root", "")))
        if not source_root.is_absolute() or source_root.is_symlink() or not source_root.is_dir():
            raise ValueError("T16 cannot resolve the current T14 First Passage binding")
        return produce_scoped_conditional_baseline(source_first_passage_root=source_root)
    raise ValueError(f"unsupported successor producer: {context.task_id}")


def execute_producer(context: ProducerContext, *, resume: bool = False) -> dict[str, Any]:
    """Execute once and publish a strict v2 receipt."""

    context.input_preflight()
    if context.execution_mode == "FORMAL":
        require_operation_allowed("RESUME" if resume else "RUN")
    if context.receipt_path.exists():
        return verify_producer(context)
    artifact_root = _artifact_data_root(context)
    if artifact_root.is_symlink():
        raise ValueError("producer artifact root is a symlink")
    artifact_root.mkdir(parents=True, exist_ok=True)
    checkpoint = _read(context.checkpoint_path) if context.checkpoint_path.exists() else {}
    attempt = int(checkpoint.get("attempt", 0)) + 1
    data_root = artifact_root / f"attempt-{attempt}" / "data"
    if data_root.parent.exists():
        raise ValueError("producer attempt identity already exists")
    data_root.parent.mkdir(parents=True)
    checkpoint_payload = _seal(
        {
            "schema_name": "stage2-plan-v13-producer-checkpoint-v1",
            "status": "IN_PROGRESS",
            "task_id": context.task_id,
            "execution_mode": context.execution_mode,
            "attempt": attempt,
            "code_commit": context.code_commit,
            "adapter_plan_hash": context.adapter_plan_hash,
            "execution_scope_hash": context.scope.execution_scope_hash,
        },
        "checkpoint_hash",
    )
    temporary_checkpoint = context.checkpoint_path.with_suffix(".tmp")
    temporary_checkpoint.write_text(
        json.dumps(checkpoint_payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_checkpoint, context.checkpoint_path)
    payload = _producer_payload(context, data_root)
    payload["artifact_data_root"] = str(data_root)
    output_path = artifact_root / "output.json"
    _write_exclusive(output_path, payload)
    output_hash = canonical_hash(payload)
    row_count = int(payload.get("row_count", -1))
    if row_count < 0:
        raise ValueError("producer did not reconcile a primary row count")
    chain_id = f"stage2-s2p13-successor-{context.adapter_plan_hash[:12]}"
    run_id = (
        f"stage2-{context.task_id.lower()}-{context.adapter_plan_hash[:12]}"
        if context.execution_mode == "FORMAL"
        else None
    )
    evidence_id = run_id or f"rehearsal-{context.code_commit[:12]}-{context.task_id.lower()}"
    manifest = _seal(
        {
            "schema_name": "stage2-plan-v13-producer-manifest-v2",
            "stage_plan_version": "1.3",
            "task_id": context.task_id,
            "execution_mode": context.execution_mode,
            "chain_id": chain_id,
            "run_id": run_id,
            "evidence_id": evidence_id,
            "code_commit": context.code_commit,
            "adapter_plan_hash": context.adapter_plan_hash,
            "execution_scope": context.scope.payload(),
            "upstream_handoffs": {name: item.payload() for name, item in context.upstream.items()},
            "preregistration_hash": context.preregistration_hash,
            "output_hash": output_hash,
            "row_count": row_count,
        },
        "manifest_hash",
    )
    manifest_path = artifact_root / "manifest.json"
    _write_exclusive(manifest_path, manifest)
    catalog = _seal(
        {
            "schema_name": "stage2-plan-v13-producer-catalog-v2",
            "task_id": context.task_id,
            "manifest_hash": manifest["manifest_hash"],
            "files": [
                {
                    "relative_path": "output.json",
                    "content_hash": output_hash,
                }
            ],
        },
        "catalog_hash",
    )
    catalog_path = artifact_root / "catalog.json"
    _write_exclusive(catalog_path, catalog)
    receipt = _seal(
        {
            "schema_name": RECEIPT_SCHEMA,
            "status": "PASS",
            "stage_plan_version": "1.3",
            "execution_mode": context.execution_mode,
            "task_id": context.task_id,
            "code_commit": context.code_commit,
            "chain_id": chain_id,
            "run_id": run_id,
            "evidence_id": evidence_id,
            "artifact_root": str(artifact_root),
            "snapshot_id": str(manifest["manifest_hash"]),
            "manifest_path": str(manifest_path),
            "manifest_hash": str(manifest["manifest_hash"]),
            "catalog_path": str(catalog_path),
            "catalog_hash": str(catalog["catalog_hash"]),
            "adapter_plan_hash": context.adapter_plan_hash,
            "upstream_handoffs": {name: item.payload() for name, item in context.upstream.items()},
            "execution_scope": context.scope.payload(),
            "output_hash": output_hash,
            "row_count": row_count,
            "consumer_readback": "PASS",
            "reconciliation": "PASS",
            "verify_status": "PASS",
        },
        "receipt_hash",
    )
    _write_exclusive(context.receipt_path, receipt)
    completed_checkpoint = _seal(
        {
            **{key: value for key, value in checkpoint_payload.items() if key != "checkpoint_hash"},
            "status": "PASS",
            "receipt_hash": receipt["receipt_hash"],
        },
        "checkpoint_hash",
    )
    temporary_checkpoint.write_text(
        json.dumps(completed_checkpoint, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_checkpoint, context.checkpoint_path)
    return verify_producer(context)


def verify_producer(context: ProducerContext) -> dict[str, Any]:
    """Strictly verify the task receipt and its exact output."""

    receipt = _read(context.receipt_path)
    claimed = receipt.pop("receipt_hash", None)
    if claimed != canonical_hash(receipt):
        raise ValueError("producer receipt hash mismatch")
    receipt["receipt_hash"] = claimed
    if (
        receipt.get("schema_name") != RECEIPT_SCHEMA
        or receipt.get("status") != "PASS"
        or receipt.get("task_id") != context.task_id
        or receipt.get("execution_mode") != context.execution_mode
        or receipt.get("code_commit") != context.code_commit
        or receipt.get("adapter_plan_hash") != context.adapter_plan_hash
        or receipt.get("execution_scope") != context.scope.payload()
        or receipt.get("upstream_handoffs")
        != {name: item.payload() for name, item in context.upstream.items()}
    ):
        raise ValueError("producer receipt binding mismatch")
    artifact_root = Path(str(receipt["artifact_root"]))
    output = _read(artifact_root / "output.json")
    if canonical_hash(output) != receipt.get("output_hash") or int(
        output.get("row_count", -1)
    ) != int(receipt.get("row_count", -2)):
        raise ValueError("producer output read-back or reconciliation mismatch")
    return receipt
