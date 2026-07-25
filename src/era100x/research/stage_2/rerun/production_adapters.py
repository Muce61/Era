"""Receipt-driven production adapters for the Plan v1.3 successor chain.

The adapter layer never fabricates a task handoff.  A separately approved
producer command must publish a self-hashed receipt after its own Verify.  The
adapter only validates that receipt and translates it into the supervisor's
strict ``TaskHandoff`` value.
"""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .orchestrator import (
    TASKS,
    RetryableInterruption,
    TaskAdapter,
    TaskHandoff,
    canonical_hash,
)

PLAN_SCHEMA = "stage2-plan-v13-production-adapter-plan-v2"
RECEIPT_SCHEMA = "stage2-plan-v13-production-task-receipt-v2"
RETRYABLE_RETURN_CODES = frozenset({75, 130, 143})
UPSTREAM_TASKS: dict[str, tuple[str, ...]] = {
    "S2P13-T11": (),
    "S2P13-T12": ("S2P13-T11",),
    "S2P13-T13": ("S2P13-T12",),
    "S2P13-T14": ("S2P13-T12",),
    "S2P13-T15": ("S2P13-T14",),
    "S2P13-T16": ("S2P13-T11", "S2P13-T13", "S2P13-T15"),
}
PREREGISTRATION_CONSUMERS = frozenset({"S2P13-T11", "S2P13-T16"})
VERIFIED_PREFIX_ADOPTION_SCHEMA = "stage2-verified-prefix-adoption-binding-v1"


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.parent.is_symlink():
        raise ValueError(f"unsafe or missing production evidence: {path}")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("production evidence root must be an object")
    return cast(dict[str, Any], value)


def _self_hash_valid(payload: Mapping[str, Any], field: str) -> bool:
    claimed = payload.get(field)
    body = {key: value for key, value in payload.items() if key != field}
    return isinstance(claimed, str) and claimed == canonical_hash(body)


def _validate_verified_prefix_adoption(payload: Mapping[str, Any]) -> None:
    adoption = payload.get("verified_prefix_adoption")
    if adoption is None:
        return
    if not isinstance(adoption, dict) or set(adoption) != {
        "schema_name",
        "mode",
        "source_chain_root",
        "source_code_commit",
        "source_receipt_path",
        "source_receipt_hash",
        "source_run_id",
        "source_task_id",
    }:
        raise ValueError("verified-prefix adoption binding is invalid")
    source_chain_root = Path(str(adoption.get("source_chain_root", "")))
    source_receipt_path = Path(str(adoption.get("source_receipt_path", "")))
    if (
        adoption.get("schema_name") != VERIFIED_PREFIX_ADOPTION_SCHEMA
        or adoption.get("mode") != "READ_ONLY"
        or adoption.get("source_task_id") != payload.get("task_id")
        or not source_chain_root.is_absolute()
        or source_chain_root.is_symlink()
        or not source_chain_root.is_dir()
        or not source_receipt_path.is_absolute()
        or source_receipt_path.is_symlink()
        or not source_receipt_path.is_file()
        or not source_receipt_path.resolve().is_relative_to(source_chain_root.resolve())
    ):
        raise ValueError("verified-prefix adoption binding is invalid")
    source = _safe_json(source_receipt_path)
    source_hash = adoption.get("source_receipt_hash")
    if (
        not _self_hash_valid(source, "receipt_hash")
        or source.get("receipt_hash") != source_hash
        or source.get("code_commit") != adoption.get("source_code_commit")
        or source.get("task_id") != adoption.get("source_task_id")
        or source.get("run_id") != adoption.get("source_run_id")
        or source.get("run_id") != payload.get("run_id")
        or source.get("output_hash") != payload.get("output_hash")
        or source.get("row_count") != payload.get("row_count")
        or source.get("manifest_hash") != payload.get("manifest_hash")
        or source.get("catalog_hash") != payload.get("catalog_hash")
        or source.get("consumer_readback") != "PASS"
        or source.get("reconciliation") != "PASS"
        or source.get("verify_status") != "PASS"
    ):
        raise ValueError("verified-prefix source receipt drift")


def _safe_absolute_child(path: Path, root: Path) -> None:
    if not path.is_absolute():
        raise ValueError("production evidence paths must be absolute")
    resolved_root = root.resolve()
    resolved_parent = path.parent.resolve()
    if not resolved_parent.is_relative_to(resolved_root) or path.is_symlink():
        raise ValueError(f"production evidence path escapes approved root: {path}")


def _command(value: object, *, field: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item and "\x00" not in item for item in value)
    ):
        raise ValueError(f"{field} must be a non-empty argv array")
    command = tuple(cast(list[str], value))
    if command[0] in {"sh", "bash", "zsh", "/bin/sh", "/bin/bash", "/bin/zsh"}:
        raise ValueError(f"{field} cannot invoke a shell")
    return command


@dataclass(frozen=True, slots=True)
class ProductionTaskSpec:
    task_id: str
    required_upstream_tasks: tuple[str, ...]
    static_preflight_command: tuple[str, ...]
    input_preflight_command: tuple[str, ...]
    run_command: tuple[str, ...]
    resume_command: tuple[str, ...]
    allowed_artifact_root: Path
    checkpoint_path: Path
    receipt_path: Path


@dataclass(frozen=True, slots=True)
class ProductionAdapterPlan:
    path: Path
    plan_hash: str
    code_commit: str
    evidence_root: Path
    preregistration_path: Path
    preregistration_hash: str
    tasks: dict[str, ProductionTaskSpec]


def load_adapter_plan(path: Path, *, code_commit: str) -> ProductionAdapterPlan:
    payload = _safe_json(path)
    if not _self_hash_valid(payload, "adapter_plan_hash"):
        raise ValueError("production adapter plan hash mismatch")
    if (
        payload.get("schema_name") != PLAN_SCHEMA
        or payload.get("status") != "APPROVED"
        or payload.get("code_commit") != code_commit
        or payload.get("stage_plan_version") != "1.3"
        or payload.get("formal_run_created") is not False
    ):
        raise ValueError("production adapter plan contract is not approved for this commit")
    evidence_root = Path(str(payload.get("evidence_root", "")))
    if not evidence_root.is_absolute() or evidence_root.is_symlink() or not evidence_root.is_dir():
        raise ValueError("production adapter evidence root is unsafe or missing")
    preregistration_path = Path(str(payload.get("preregistration_path", "")))
    preregistration_hash = str(payload.get("preregistration_hash", ""))
    if (
        not preregistration_path.is_absolute()
        or preregistration_path.is_symlink()
        or not preregistration_path.is_file()
        or len(preregistration_hash) != 64
        or _file_hash(preregistration_path) != preregistration_hash
    ):
        raise ValueError("production preregistration binding is unsafe or drifted")
    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, dict) or set(raw_tasks) != set(TASKS):
        raise ValueError("production adapter plan requires six exact task specs")
    tasks: dict[str, ProductionTaskSpec] = {}
    for task_id in TASKS:
        raw = raw_tasks[task_id]
        if not isinstance(raw, dict):
            raise ValueError(f"invalid production task spec: {task_id}")
        upstream = tuple(raw.get("required_upstream_tasks", ()))
        if upstream != UPSTREAM_TASKS[task_id]:
            raise ValueError(f"production upstream DAG drift: {task_id}")
        checkpoint_path = Path(str(raw.get("checkpoint_path", "")))
        receipt_path = Path(str(raw.get("receipt_path", "")))
        allowed_artifact_root = Path(str(raw.get("allowed_artifact_root", "")))
        _safe_absolute_child(checkpoint_path, evidence_root)
        _safe_absolute_child(receipt_path, evidence_root)
        if (
            not allowed_artifact_root.is_absolute()
            or allowed_artifact_root.is_symlink()
            or not allowed_artifact_root.is_dir()
        ):
            raise ValueError(f"unsafe or missing allowed artifact root: {task_id}")
        if checkpoint_path == receipt_path:
            raise ValueError("checkpoint and final receipt must be separate paths")
        tasks[task_id] = ProductionTaskSpec(
            task_id=task_id,
            required_upstream_tasks=upstream,
            static_preflight_command=_command(
                raw.get("static_preflight_command"),
                field=f"{task_id}.static_preflight_command",
            ),
            input_preflight_command=_command(
                raw.get("input_preflight_command"),
                field=f"{task_id}.input_preflight_command",
            ),
            run_command=_command(raw.get("run_command"), field=f"{task_id}.run_command"),
            resume_command=_command(raw.get("resume_command"), field=f"{task_id}.resume_command"),
            allowed_artifact_root=allowed_artifact_root,
            checkpoint_path=checkpoint_path,
            receipt_path=receipt_path,
        )
    evidence_paths = [
        path for spec in tasks.values() for path in (spec.checkpoint_path, spec.receipt_path)
    ]
    if len(evidence_paths) != len(set(evidence_paths)):
        raise ValueError("production task checkpoint and receipt paths must be unique")
    return ProductionAdapterPlan(
        path=path,
        plan_hash=str(payload["adapter_plan_hash"]),
        code_commit=code_commit,
        evidence_root=evidence_root,
        preregistration_path=preregistration_path,
        preregistration_hash=preregistration_hash,
        tasks=tasks,
    )


class CommandTaskAdapter(TaskAdapter):
    """Execute one approved argv plan and accept only its verified receipt."""

    def __init__(
        self,
        *,
        spec: ProductionTaskSpec,
        code_commit: str,
        adapter_plan_hash: str,
        supervisor_checkpoint_path: Path,
        repository_root: Path,
        preregistration_path: Path,
        preregistration_hash: str,
    ) -> None:
        self.spec = spec
        self.code_commit = code_commit
        self.adapter_plan_hash = adapter_plan_hash
        self.supervisor_checkpoint_path = supervisor_checkpoint_path
        self.repository_root = repository_root
        self.preregistration_path = preregistration_path
        self.preregistration_hash = preregistration_hash

    def _upstream_handoffs(self) -> dict[str, dict[str, Any]]:
        if not self.spec.required_upstream_tasks:
            return {}
        checkpoint = _safe_json(self.supervisor_checkpoint_path)
        tasks = checkpoint.get("tasks")
        if not isinstance(tasks, dict):
            raise ValueError("successor checkpoint task map is missing")
        result: dict[str, dict[str, Any]] = {}
        for task_id in self.spec.required_upstream_tasks:
            state = tasks.get(task_id)
            if not isinstance(state, dict):
                raise ValueError(f"required upstream handoff is not PASS: {task_id}")
            handoff = state.get("handoff")
            if not isinstance(handoff, dict) or state.get("status") != "PASS":
                raise ValueError(f"required upstream handoff is not PASS: {task_id}")
            try:
                validated = TaskHandoff(**handoff)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"required upstream handoff is not PASS: {task_id}") from exc
            normalized = validated.payload()
            for status_field in ("consumer_readback", "reconciliation", "verify_status"):
                normalized.pop(status_field)
            result[task_id] = cast(dict[str, Any], normalized)
        return result

    def _environment(self, upstream_handoffs: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
        upstream_hashes = {
            task_id: str(handoff["output_hash"]) for task_id, handoff in upstream_handoffs.items()
        }
        return {
            **os.environ,
            "ERA_S2P13_TASK_ID": self.spec.task_id,
            "ERA_S2P13_CODE_COMMIT": self.code_commit,
            "ERA_S2P13_ADAPTER_PLAN_HASH": self.adapter_plan_hash,
            "ERA_S2P13_EXPECTED_UPSTREAM_HASHES": json.dumps(
                upstream_hashes, sort_keys=True, separators=(",", ":")
            ),
            "ERA_S2P13_EXPECTED_UPSTREAM_HANDOFFS": json.dumps(
                upstream_handoffs, sort_keys=True, separators=(",", ":")
            ),
            "ERA_S2P13_TASK_RECEIPT_PATH": str(self.spec.receipt_path),
            "ERA_S2P13_TASK_CHECKPOINT_PATH": str(self.spec.checkpoint_path),
            "ERA_S2P13_PREREGISTRATION_PATH": str(self.preregistration_path),
            "ERA_S2P13_PREREGISTRATION_HASH": self.preregistration_hash,
        }

    def _execute(
        self,
        command: Sequence[str],
        *,
        phase: str,
        upstream_handoffs: Mapping[str, Mapping[str, Any]],
    ) -> None:
        completed = subprocess.run(
            tuple(command),
            cwd=self.repository_root,
            env=self._environment(upstream_handoffs),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode == 0:
            return
        detail = (completed.stderr or completed.stdout).strip()[-2_000:]
        if completed.returncode in RETRYABLE_RETURN_CODES:
            raise RetryableInterruption(
                f"{self.spec.task_id} {phase} interrupted ({completed.returncode}): {detail}"
            )
        raise RuntimeError(f"{self.spec.task_id} {phase} failed ({completed.returncode}): {detail}")

    def static_preflight(self) -> None:
        if self.spec.receipt_path.exists():
            self._receipt(self._upstream_handoffs())
            return
        self._execute(
            self.spec.static_preflight_command,
            phase="static-preflight",
            upstream_handoffs={},
        )

    def input_preflight(self) -> None:
        upstream = self._upstream_handoffs()
        if self.spec.receipt_path.exists():
            self._receipt(upstream)
            return
        self._execute(
            self.spec.input_preflight_command,
            phase="input-preflight",
            upstream_handoffs=upstream,
        )

    def _receipt(self, upstream_handoffs: Mapping[str, Mapping[str, Any]]) -> TaskHandoff:
        payload = _safe_json(self.spec.receipt_path)
        if not _self_hash_valid(payload, "receipt_hash"):
            raise ValueError(f"{self.spec.task_id} production receipt hash mismatch")
        _validate_verified_prefix_adoption(payload)
        if (
            payload.get("schema_name") != RECEIPT_SCHEMA
            or payload.get("status") != "PASS"
            or payload.get("stage_plan_version") != "1.3"
            or payload.get("execution_mode") != "FORMAL"
            or payload.get("task_id") != self.spec.task_id
            or payload.get("code_commit") != self.code_commit
            or payload.get("adapter_plan_hash") != self.adapter_plan_hash
            or payload.get("upstream_handoffs") != dict(upstream_handoffs)
            or payload.get("consumer_readback") != "PASS"
            or payload.get("reconciliation") != "PASS"
            or payload.get("verify_status") != "PASS"
            or not isinstance(payload.get("chain_id"), str)
            or not payload.get("chain_id")
            or not isinstance(payload.get("run_id"), str)
            or not payload.get("run_id")
            or payload.get("evidence_id") != payload.get("run_id")
        ):
            raise ValueError(f"{self.spec.task_id} production receipt contract mismatch")
        artifact_root = Path(str(payload.get("artifact_root", "")))
        manifest_path = Path(str(payload.get("manifest_path", "")))
        catalog_path = Path(str(payload.get("catalog_path", "")))
        for path in (artifact_root, manifest_path, catalog_path):
            if not path.is_absolute() or path.is_symlink():
                raise ValueError(f"{self.spec.task_id} production artifact path is unsafe")
        if not artifact_root.resolve().is_relative_to(self.spec.allowed_artifact_root.resolve()):
            raise ValueError(f"{self.spec.task_id} production artifact root is not approved")
        if not manifest_path.resolve().is_relative_to(artifact_root.resolve()) or not (
            catalog_path.resolve().is_relative_to(artifact_root.resolve())
        ):
            raise ValueError(f"{self.spec.task_id} production artifact escapes its root")
        manifest = _safe_json(manifest_path)
        catalog = _safe_json(catalog_path)
        if not _self_hash_valid(manifest, "manifest_hash") or manifest.get(
            "manifest_hash"
        ) != payload.get("manifest_hash"):
            raise ValueError(f"{self.spec.task_id} Manifest binding mismatch")
        if (
            self.spec.task_id in PREREGISTRATION_CONSUMERS
            and manifest.get("preregistration_hash") != self.preregistration_hash
        ):
            raise ValueError(f"{self.spec.task_id} preregistration binding mismatch")
        if not _self_hash_valid(catalog, "catalog_hash") or catalog.get(
            "catalog_hash"
        ) != payload.get("catalog_hash"):
            raise ValueError(f"{self.spec.task_id} Catalog binding mismatch")
        scope = payload.get("execution_scope")
        if not isinstance(scope, dict) or not _self_hash_valid(scope, "execution_scope_hash"):
            raise ValueError(f"{self.spec.task_id} execution scope binding mismatch")
        return TaskHandoff(
            task_id=self.spec.task_id,
            execution_mode="FORMAL",
            chain_id=str(payload["chain_id"]),
            run_id=str(payload["run_id"]),
            evidence_id=str(payload["evidence_id"]),
            artifact_root=str(artifact_root),
            snapshot_id=str(payload.get("snapshot_id", "")),
            manifest_path=str(manifest_path),
            manifest_hash=str(payload.get("manifest_hash", "")),
            catalog_path=str(catalog_path),
            catalog_hash=str(payload.get("catalog_hash", "")),
            output_hash=str(payload.get("output_hash", "")),
            row_count=int(payload.get("row_count", -1)),
            execution_scope_hash=str(scope["execution_scope_hash"]),
            producer_receipt_hash=str(payload["receipt_hash"]),
            consumer_readback=str(payload.get("consumer_readback")),
            reconciliation=str(payload.get("reconciliation")),
            verify_status=str(payload.get("verify_status")),
        )

    def run_or_resume(self) -> TaskHandoff:
        upstream = self._upstream_handoffs()
        if self.spec.receipt_path.exists():
            return self._receipt(upstream)
        command = (
            self.spec.resume_command
            if self.spec.checkpoint_path.exists()
            else self.spec.run_command
        )
        phase = "resume" if command == self.spec.resume_command else "run"
        self._execute(command, phase=phase, upstream_handoffs=upstream)
        return self._receipt(upstream)


def build_production_adapters(
    plan: ProductionAdapterPlan,
    *,
    supervisor_root: Path,
    repository_root: Path,
) -> dict[str, TaskAdapter]:
    checkpoint_path = supervisor_root / "checkpoint.json"
    return {
        task_id: CommandTaskAdapter(
            spec=plan.tasks[task_id],
            code_commit=plan.code_commit,
            adapter_plan_hash=plan.plan_hash,
            supervisor_checkpoint_path=checkpoint_path,
            repository_root=repository_root,
            preregistration_path=plan.preregistration_path,
            preregistration_hash=plan.preregistration_hash,
        )
        for task_id in TASKS
    }
