"""Strict Plan v1.3 producer context and upstream artifact bindings."""

from __future__ import annotations

import json
import os
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .orchestrator import TASKS, canonical_hash, current_commit
from .production_adapters import PREREGISTRATION_CONSUMERS, UPSTREAM_TASKS

LEGACY_TASK_IDS = frozenset({"S2-T11", "S2-T12", "S2-T13", "S2-T14", "S2-T15"})
EXECUTION_MODES = frozenset({"REHEARSAL", "FORMAL"})
SCOPE_MODES = frozenset({"SEVEN_DAY", "FULL_HISTORY"})


def _safe_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.parent.is_symlink():
        raise ValueError(f"unsafe or missing producer evidence: {path}")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("producer evidence root must be an object")
    return cast(dict[str, Any], value)


def _self_hash_valid(payload: dict[str, Any], field: str) -> bool:
    claimed = payload.get(field)
    body = {key: value for key, value in payload.items() if key != field}
    return isinstance(claimed, str) and claimed == canonical_hash(body)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ExecutionScope:
    mode: str
    start_date: str
    end_date_exclusive: str
    execution_scope_hash: str

    @classmethod
    def seal(cls, *, mode: str, start_date: str, end_date_exclusive: str) -> ExecutionScope:
        payload = {
            "mode": mode,
            "start_date": start_date,
            "end_date_exclusive": end_date_exclusive,
        }
        return cls(**payload, execution_scope_hash=canonical_hash(payload))

    @classmethod
    def from_payload(cls, payload: object) -> ExecutionScope:
        if not isinstance(payload, dict):
            raise ValueError("execution scope must be an object")
        value = cast(dict[str, Any], payload)
        if set(value) != {
            "mode",
            "start_date",
            "end_date_exclusive",
            "execution_scope_hash",
        }:
            raise ValueError("execution scope fields drift")
        result = cls(
            mode=str(value["mode"]),
            start_date=str(value["start_date"]),
            end_date_exclusive=str(value["end_date_exclusive"]),
            execution_scope_hash=str(value["execution_scope_hash"]),
        )
        if result.mode not in SCOPE_MODES:
            raise ValueError("unsupported execution scope mode")
        if result.execution_scope_hash != canonical_hash(
            {
                "mode": result.mode,
                "start_date": result.start_date,
                "end_date_exclusive": result.end_date_exclusive,
            }
        ):
            raise ValueError("execution scope hash mismatch")
        if result.mode == "SEVEN_DAY" and (
            result.start_date != "2020-01-01" or result.end_date_exclusive != "2020-01-08"
        ):
            raise ValueError("seven-day rehearsal scope drift")
        if result.mode == "FULL_HISTORY" and (
            result.start_date != "2020-01-01" or result.end_date_exclusive != "2026-07-04"
        ):
            raise ValueError("full-history successor scope drift")
        if result.start_date >= result.end_date_exclusive:
            raise ValueError("execution scope is empty or reversed")
        return result

    def payload(self) -> dict[str, str]:
        return {
            "mode": self.mode,
            "start_date": self.start_date,
            "end_date_exclusive": self.end_date_exclusive,
            "execution_scope_hash": self.execution_scope_hash,
        }


@dataclass(frozen=True, slots=True)
class UpstreamArtifact:
    task_id: str
    execution_mode: str
    chain_id: str
    run_id: str | None
    evidence_id: str
    artifact_root: Path
    snapshot_id: str
    manifest_path: Path
    manifest_hash: str
    catalog_path: Path
    catalog_hash: str
    output_hash: str
    row_count: int
    execution_scope_hash: str
    producer_receipt_hash: str

    @classmethod
    def from_payload(cls, task_id: str, payload: object) -> UpstreamArtifact:
        if task_id not in TASKS or task_id in LEGACY_TASK_IDS or not isinstance(payload, dict):
            raise ValueError("successor upstream task identity is invalid")
        value = cast(dict[str, Any], payload)
        if value.get("task_id") != task_id:
            raise ValueError("successor upstream task identity mismatch")
        result = cls(
            task_id=task_id,
            execution_mode=str(value.get("execution_mode", "")),
            chain_id=str(value.get("chain_id", "")),
            run_id=cast(str | None, value.get("run_id")),
            evidence_id=str(value.get("evidence_id", "")),
            artifact_root=Path(str(value.get("artifact_root", ""))),
            snapshot_id=str(value.get("snapshot_id", "")),
            manifest_path=Path(str(value.get("manifest_path", ""))),
            manifest_hash=str(value.get("manifest_hash", "")),
            catalog_path=Path(str(value.get("catalog_path", ""))),
            catalog_hash=str(value.get("catalog_hash", "")),
            output_hash=str(value.get("output_hash", "")),
            row_count=int(value.get("row_count", -1)),
            execution_scope_hash=str(value.get("execution_scope_hash", "")),
            producer_receipt_hash=str(value.get("producer_receipt_hash", "")),
        )
        result.verify()
        return result

    def verify(self) -> None:
        if self.execution_mode not in EXECUTION_MODES or not self.chain_id or not self.evidence_id:
            raise ValueError("upstream execution identity is incomplete")
        if self.execution_mode == "FORMAL" and not self.run_id:
            raise ValueError("formal upstream lacks Run ID")
        if self.execution_mode == "REHEARSAL" and self.run_id is not None:
            raise ValueError("rehearsal upstream claims a formal Run ID")
        paths = (self.artifact_root, self.manifest_path, self.catalog_path)
        if any(not path.is_absolute() or path.is_symlink() for path in paths):
            raise ValueError("upstream artifact path is unsafe")
        if not self.manifest_path.resolve().is_relative_to(self.artifact_root.resolve()) or not (
            self.catalog_path.resolve().is_relative_to(self.artifact_root.resolve())
        ):
            raise ValueError("upstream artifact path escapes its root")
        manifest = _safe_json(self.manifest_path)
        catalog = _safe_json(self.catalog_path)
        if (
            not _self_hash_valid(manifest, "manifest_hash")
            or manifest.get("manifest_hash") != self.manifest_hash
            or not _self_hash_valid(catalog, "catalog_hash")
            or catalog.get("catalog_hash") != self.catalog_hash
        ):
            raise ValueError("upstream Manifest or Catalog hash drift")
        hashes = (
            self.output_hash,
            self.execution_scope_hash,
            self.producer_receipt_hash,
        )
        if any(len(value) != 64 for value in hashes) or self.row_count < 0:
            raise ValueError("upstream output binding is incomplete")

    def payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "execution_mode": self.execution_mode,
            "chain_id": self.chain_id,
            "run_id": self.run_id,
            "evidence_id": self.evidence_id,
            "artifact_root": str(self.artifact_root),
            "snapshot_id": self.snapshot_id,
            "manifest_path": str(self.manifest_path),
            "manifest_hash": self.manifest_hash,
            "catalog_path": str(self.catalog_path),
            "catalog_hash": self.catalog_hash,
            "output_hash": self.output_hash,
            "row_count": self.row_count,
            "execution_scope_hash": self.execution_scope_hash,
            "producer_receipt_hash": self.producer_receipt_hash,
        }


@dataclass(frozen=True, slots=True)
class ProducerContext:
    task_id: str
    execution_mode: str
    code_commit: str
    adapter_plan_hash: str
    receipt_path: Path
    checkpoint_path: Path
    scope: ExecutionScope
    upstream: dict[str, UpstreamArtifact]
    preregistration_path: Path
    preregistration_hash: str

    @classmethod
    def from_environment(
        cls,
        *,
        task_id: str,
        execution_mode: str,
        scope: ExecutionScope,
        repository_root: Path,
        require_upstream: bool = True,
    ) -> ProducerContext:
        if task_id not in TASKS or task_id in LEGACY_TASK_IDS:
            raise ValueError("producer requires a fully qualified Plan v1.3 Task ID")
        if execution_mode not in EXECUTION_MODES:
            raise ValueError("producer execution mode is invalid")
        environment_task = os.environ.get("ERA_S2P13_TASK_ID")
        if environment_task != task_id:
            raise ValueError("producer task does not match the approved adapter")
        commit = os.environ.get("ERA_S2P13_CODE_COMMIT", "")
        if commit != current_commit(repository_root):
            raise ValueError("producer code commit binding drift")
        adapter_plan_hash = os.environ.get("ERA_S2P13_ADAPTER_PLAN_HASH", "")
        if len(adapter_plan_hash) != 64:
            raise ValueError("producer adapter plan hash is missing")
        receipt_path = Path(os.environ.get("ERA_S2P13_TASK_RECEIPT_PATH", ""))
        checkpoint_path = Path(os.environ.get("ERA_S2P13_TASK_CHECKPOINT_PATH", ""))
        if any(
            not path.is_absolute() or path.is_symlink() for path in (receipt_path, checkpoint_path)
        ):
            raise ValueError("producer receipt/checkpoint path is unsafe")
        raw = json.loads(os.environ.get("ERA_S2P13_EXPECTED_UPSTREAM_HANDOFFS", "{}"))
        expected_upstream = set(UPSTREAM_TASKS[task_id]) if require_upstream else set()
        if not isinstance(raw, dict) or set(raw) != expected_upstream:
            raise ValueError("producer upstream DAG binding drift")
        upstream = {
            name: UpstreamArtifact.from_payload(name, payload)
            for name, payload in cast(dict[str, object], raw).items()
        }
        if any(
            item.execution_scope_hash != scope.execution_scope_hash for item in upstream.values()
        ):
            raise ValueError("producer upstream execution scope drift")
        if any(item.execution_mode != execution_mode for item in upstream.values()):
            raise ValueError("producer upstream execution mode drift")
        preregistration_path = Path(os.environ.get("ERA_S2P13_PREREGISTRATION_PATH", ""))
        preregistration_hash = os.environ.get("ERA_S2P13_PREREGISTRATION_HASH", "")
        if task_id in PREREGISTRATION_CONSUMERS and (
            not preregistration_path.is_absolute()
            or preregistration_path.is_symlink()
            or not preregistration_path.is_file()
            or len(preregistration_hash) != 64
            or _file_hash(preregistration_path) != preregistration_hash
        ):
            raise ValueError("producer preregistration binding drift")
        return cls(
            task_id=task_id,
            execution_mode=execution_mode,
            code_commit=commit,
            adapter_plan_hash=adapter_plan_hash,
            receipt_path=receipt_path,
            checkpoint_path=checkpoint_path,
            scope=scope,
            upstream=upstream,
            preregistration_path=preregistration_path,
            preregistration_hash=preregistration_hash,
        )

    def static_preflight(self) -> dict[str, object]:
        if self.receipt_path.parent.is_symlink() or not self.receipt_path.parent.is_dir():
            raise ValueError("producer evidence directory is unsafe or missing")
        return {
            "status": "PASS",
            "task_id": self.task_id,
            "execution_mode": self.execution_mode,
            "code_commit": self.code_commit,
            "adapter_plan_hash": self.adapter_plan_hash,
            "execution_scope_hash": self.scope.execution_scope_hash,
            "run_id_created": False,
            "preregistration_hash": (
                self.preregistration_hash if self.task_id in PREREGISTRATION_CONSUMERS else None
            ),
        }

    def input_preflight(self) -> dict[str, object]:
        for artifact in self.upstream.values():
            artifact.verify()
        return {
            "status": "PASS",
            "task_id": self.task_id,
            "upstream_tasks": list(self.upstream),
            "upstream_output_hashes": {
                task_id: artifact.output_hash for task_id, artifact in self.upstream.items()
            },
            "run_id_created": False,
        }
