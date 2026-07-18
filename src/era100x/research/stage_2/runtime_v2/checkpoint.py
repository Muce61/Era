"""Atomic, fail-closed checkpoints for the Stage 2 Runtime V2 orchestrator.

The checkpoint contains execution metadata only.  It never changes the locked
Manifest, snapshot, research matrix, or semantic receipts produced by a build
backend.  A single deterministic writer advances the checkpoint through an
exclusive lock and an atomic same-directory replace.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from era100x.research.stage_2.manifests.models import canonical_json

SHA256_PATTERN = r"^[0-9a-f]{64}$"
ZERO_SHA256 = "0" * 64
SAFE_RUN_ID = re.compile(r"^stage2-g1-v2-b-[A-Za-z0-9][A-Za-z0-9.-]{0,95}$")

FOUNDATION_TASKS = (
    "FOUNDATION:BTCUSDT",
    "FOUNDATION:ETHUSDT",
)
GROUP1_TASKS = (
    "GROUP1:BTCUSDT:V1_PRICE",
    "GROUP1:BTCUSDT:V1_FLOW",
    "GROUP1:ETHUSDT:V1_PRICE",
    "GROUP1:ETHUSDT:V1_FLOW",
)
FULL_TASK_MATRIX = FOUNDATION_TASKS + GROUP1_TASKS

RuntimePhase = Literal["PREFLIGHT", "FOUNDATION", "GROUP1"]
RuntimeStatus = Literal[
    "PREFLIGHT_PASSED",
    "IN_PROGRESS",
    "INTERRUPTED_RECOVERABLE",
    "RUNNING_WITH_ANOMALIES",
    "PAUSED_RESOURCE_PRESSURE",
    "PAUSED_STORAGE_UNAVAILABLE",
    "FOUNDATION_COMPLETE",
    "GROUP1_COMPLETE",
    "FAILED_UNPUBLISHED",
    "FAILED_INTEGRITY",
]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _metadata_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _safe_relative_path(value: str, *, required_prefix: str | None = None) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError("checkpoint path must be a safe relative POSIX path")
    if required_prefix is not None and path.parts[0] != required_prefix:
        raise ValueError(f"checkpoint path must remain under {required_prefix}/")


def task_receipt_relative_path(task_id: str) -> str:
    if task_id not in FULL_TASK_MATRIX:
        raise ValueError(f"unapproved Runtime V2 task: {task_id}")
    parts = task_id.split(":")
    if parts[0] == "FOUNDATION":
        return f"staging/receipts/foundation/{parts[1]}.json"
    return f"staging/receipts/group1/{parts[1]}/{parts[2]}.json"


class BackendTaskReceipt(_FrozenModel):
    """Semantic completion returned by one statically registered build backend."""

    schema_name: Literal["stage2-v2-backend-task-receipt"] = "stage2-v2-backend-task-receipt"
    receipt_version: Literal["1.0"] = "1.0"
    task_id: str
    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    manifest_hash: str = Field(pattern=SHA256_PATTERN)
    semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    quality_status: Literal["PASS"] = "PASS"
    resource_anomaly_count: int = Field(ge=0, default=0)
    receipt_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return _metadata_sha256(self.model_dump(mode="json", exclude={"receipt_hash"}))

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        if self.task_id not in FULL_TASK_MATRIX:
            raise ValueError("backend receipt task is outside the frozen full matrix")
        if self.receipt_hash != ZERO_SHA256 and self.receipt_hash != self.computed_hash():
            raise ValueError("backend task receipt hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "receipt_hash": ZERO_SHA256})
        return provisional.model_copy(update={"receipt_hash": provisional.computed_hash()})


class CompletedTask(_FrozenModel):
    task_id: str
    receipt_relative_path: str
    receipt_file_sha256: str = Field(pattern=SHA256_PATTERN)
    receipt_hash: str = Field(pattern=SHA256_PATTERN)
    semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    resource_anomaly_count: int = Field(ge=0, default=0)

    @model_validator(mode="after")
    def validate_completion(self) -> Self:
        if self.task_id not in FULL_TASK_MATRIX:
            raise ValueError("completed task is outside the frozen full matrix")
        if self.receipt_relative_path != task_receipt_relative_path(self.task_id):
            raise ValueError("completed task receipt path is not deterministic")
        _safe_relative_path(self.receipt_relative_path, required_prefix="staging")
        return self


class FailureRecord(_FrozenModel):
    task_id: str
    error_type: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2048)
    report_relative_path: str
    report_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_failure(self) -> Self:
        if self.task_id not in FULL_TASK_MATRIX:
            raise ValueError("failure task is outside the frozen full matrix")
        _safe_relative_path(self.report_relative_path, required_prefix="reports")
        return self


class ResourcePauseRecord(_FrozenModel):
    task_id: str
    reason: str = Field(min_length=1, max_length=2048)
    report_relative_path: str
    report_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_pause(self) -> Self:
        if self.task_id not in FULL_TASK_MATRIX:
            raise ValueError("resource pause task is outside the frozen full matrix")
        _safe_relative_path(self.report_relative_path, required_prefix="reports")
        return self


class RuntimeV2Checkpoint(_FrozenModel):
    """Complete monotonic state for one immutable full-matrix V2 run."""

    schema_name: Literal["stage2-v2-runtime-checkpoint"] = "stage2-v2-runtime-checkpoint"
    checkpoint_version: Literal["1.0"] = "1.0"
    run_id: str
    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    manifest_hash: str = Field(pattern=SHA256_PATTERN)
    manifest_source_sha256: str = Field(pattern=SHA256_PATTERN)
    run_a_protection_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    run_a_protection_source_sha256: str = Field(pattern=SHA256_PATTERN)
    migration_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    migration_manifest_source_sha256: str = Field(pattern=SHA256_PATTERN)
    code_tree_sha256: str = Field(pattern=SHA256_PATTERN)
    stage1_data_run_id: str = Field(min_length=1)
    preregistration_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    config_sha256: str = Field(pattern=SHA256_PATTERN)
    planned_tasks: tuple[str, ...]
    completed_tasks: tuple[CompletedTask, ...]
    phase: RuntimePhase
    status: RuntimeStatus
    active_task: str | None
    failure: FailureRecord | None
    resource_pause: ResourcePauseRecord | None = None
    revision: int = Field(ge=0)
    checkpoint_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return _metadata_sha256(self.model_dump(mode="json", exclude={"checkpoint_hash"}))

    def computed_legacy_v1_hash(self) -> str:
        """Recompute pre-CR-2026-013 v1.0 bytes without the optional pause field."""

        payload = self.model_dump(mode="json", exclude={"checkpoint_hash"})
        if self.resource_pause is None:
            payload.pop("resource_pause", None)
        return _metadata_sha256(payload)

    @model_validator(mode="after")
    def validate_checkpoint(self) -> Self:
        if SAFE_RUN_ID.fullmatch(self.run_id) is None:
            raise ValueError("Runtime V2 run_id is not in the approved Run-B namespace")
        if self.planned_tasks != FULL_TASK_MATRIX:
            raise ValueError("checkpoint plan is not the frozen full matrix")
        completed_ids = tuple(item.task_id for item in self.completed_tasks)
        if completed_ids != FULL_TASK_MATRIX[: len(completed_ids)]:
            raise ValueError("completed tasks must be the deterministic matrix prefix")
        next_task = (
            None
            if len(completed_ids) == len(FULL_TASK_MATRIX)
            else FULL_TASK_MATRIX[len(completed_ids)]
        )
        if self.status in {
            "IN_PROGRESS",
            "INTERRUPTED_RECOVERABLE",
            "RUNNING_WITH_ANOMALIES",
        }:
            if (
                self.active_task != next_task
                or self.failure is not None
                or self.resource_pause is not None
            ):
                raise ValueError("active checkpoint must bind the next deterministic task")
        elif self.status in {"PAUSED_RESOURCE_PRESSURE", "PAUSED_STORAGE_UNAVAILABLE"}:
            if (
                self.active_task != next_task
                or self.failure is not None
                or self.resource_pause is None
            ):
                raise ValueError("resource-paused checkpoint must bind resumable evidence")
        elif self.active_task is not None:
            raise ValueError("non-active checkpoint cannot retain an active task")
        if self.status == "PREFLIGHT_PASSED":
            if self.phase != "PREFLIGHT" or completed_ids or self.failure is not None:
                raise ValueError("invalid preflight checkpoint state")
        elif self.status == "FOUNDATION_COMPLETE":
            if (
                self.phase != "FOUNDATION"
                or completed_ids != FOUNDATION_TASKS
                or self.failure is not None
            ):
                raise ValueError("invalid Foundation completion state")
        elif self.status == "GROUP1_COMPLETE":
            if (
                self.phase != "GROUP1"
                or completed_ids != FULL_TASK_MATRIX
                or self.failure is not None
            ):
                raise ValueError("invalid Group-1 completion state")
        elif self.status in {"FAILED_UNPUBLISHED", "FAILED_INTEGRITY"}:
            if self.failure is None:
                raise ValueError("terminal failure requires an append-only failure record")
        if self.phase == "PREFLIGHT" and self.status not in {
            "PREFLIGHT_PASSED",
            "FAILED_UNPUBLISHED",
            "FAILED_INTEGRITY",
        }:
            raise ValueError("preflight phase has an invalid status")
        if self.phase == "FOUNDATION" and any(item.startswith("GROUP1:") for item in completed_ids):
            raise ValueError("Foundation phase cannot contain Group-1 completion")
        if self.checkpoint_hash != ZERO_SHA256:
            accepted_hashes = {self.computed_hash()}
            if self.resource_pause is None:
                accepted_hashes.add(self.computed_legacy_v1_hash())
            if self.checkpoint_hash not in accepted_hashes:
                raise ValueError("checkpoint hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "checkpoint_hash": ZERO_SHA256})
        return provisional.model_copy(update={"checkpoint_hash": provisional.computed_hash()})

    def advance(self, **updates: Any) -> RuntimeV2Checkpoint:
        payload = self.model_dump(mode="python", exclude={"checkpoint_hash"})
        payload.update(updates)
        payload["revision"] = self.revision + 1
        return type(self).seal(payload)


class CheckpointConflict(RuntimeError):
    """Another writer or a changed checkpoint prevents deterministic resume."""


class CheckpointStore:
    """Exclusive single-writer store using fsync and same-directory replace."""

    def __init__(self, run_root: Path) -> None:
        self.run_root = run_root
        self.path = run_root / "checkpoint-v2.json"
        self.lock_path = run_root / "checkpoint-v2.lock"

    def read(self) -> RuntimeV2Checkpoint:
        if not self.path.is_file() or self.path.is_symlink():
            raise FileNotFoundError(f"Runtime V2 checkpoint is missing: {self.path}")
        return RuntimeV2Checkpoint.model_validate_json(self.path.read_bytes())

    def create(self, checkpoint: RuntimeV2Checkpoint) -> None:
        if checkpoint.revision != 0:
            raise ValueError("initial checkpoint revision must be zero")
        self._replace(checkpoint, expected_hash=None, require_existing=False)

    def replace(
        self,
        checkpoint: RuntimeV2Checkpoint,
        *,
        expected_hash: str,
    ) -> None:
        self._replace(checkpoint, expected_hash=expected_hash, require_existing=True)

    def _replace(
        self,
        checkpoint: RuntimeV2Checkpoint,
        *,
        expected_hash: str | None,
        require_existing: bool,
    ) -> None:
        self.run_root.mkdir(parents=True, exist_ok=True)
        lock_fd: int | None = None
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            # The stable lock inode is intentional.  flock ownership belongs
            # to the open file description and is released by the kernel on
            # SIGKILL, so a hard-crashed writer cannot strand an O_EXCL marker
            # that permanently blocks resume.
            lock_fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise CheckpointConflict("another checkpoint writer is active") from exc
            if require_existing:
                current = self.read()
                if current.checkpoint_hash != expected_hash:
                    raise CheckpointConflict("checkpoint changed since it was read")
                if checkpoint.revision != current.revision + 1:
                    raise CheckpointConflict("checkpoint revision is not monotonic")
            elif self.path.exists():
                raise FileExistsError("append-only Runtime V2 checkpoint already exists")
            payload = canonical_json(checkpoint.model_dump(mode="json")) + "\n"
            with temporary.open("x", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            _fsync_directory(self.run_root)
        finally:
            if lock_fd is not None:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
            if temporary.exists():
                temporary.unlink()


def write_once_model(path: Path, model: BaseModel) -> str:
    """Write immutable canonical evidence and return its physical SHA-256."""

    _safe_relative_path(path.name)
    payload = (canonical_json(model.model_dump(mode="json")) + "\n").encode("utf-8")
    if path.exists():
        if path.is_symlink() or path.read_bytes() != payload:
            raise FileExistsError(f"append-only evidence differs: {path}")
        return hashlib.sha256(payload).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_directory(path.parent)
    return hashlib.sha256(payload).hexdigest()


def read_backend_receipt(run_root: Path, completion: CompletedTask) -> BackendTaskReceipt:
    path = run_root / completion.receipt_relative_path
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"completed task receipt is missing: {path}")
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != completion.receipt_file_sha256:
        raise CheckpointConflict("completed task receipt bytes changed")
    receipt = BackendTaskReceipt.model_validate_json(payload)
    if (
        receipt.task_id != completion.task_id
        or receipt.receipt_hash != completion.receipt_hash
        or receipt.semantic_sha256 != completion.semantic_sha256
    ):
        raise CheckpointConflict("completed task receipt no longer matches checkpoint")
    return receipt


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
