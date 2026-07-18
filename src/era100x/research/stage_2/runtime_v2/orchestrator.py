"""Fixed full-matrix orchestration for the S2-T10 v1.8 Runtime V2 path.

The orchestrator is intentionally ignorant of event formulas.  It accepts only
the immutable V2 Manifest, explicit snapshot, Run-A protection authority and
migration authority; it then schedules the approved matrix in a fixed order.
Concrete Foundation and Group-1 builders are statically injected by repository
code.  Missing builder registration fails closed.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from era100x.research.stage_2.manifests.models import (
    Stage2ExecutionManifest,
    Stage2ReleaseSupplementManifest,
    canonical_json,
)
from era100x.research.stage_2.runtime_v2.checkpoint import (
    FOUNDATION_TASKS,
    FULL_TASK_MATRIX,
    GROUP1_TASKS,
    BackendTaskReceipt,
    CheckpointStore,
    CompletedTask,
    FailureRecord,
    RuntimeV2Checkpoint,
    read_backend_receipt,
    task_receipt_relative_path,
    write_once_model,
)
from era100x.research.stage_2.runtime_v2.models import ManifestV2
from era100x.research.stage_2.runtime_v2.source_authority import (
    CONTRACT_PRICE_MANIFEST_AUTHORITY,
    TRADES_RESOLVED_INDEX_AUTHORITY,
)
from era100x.research.stage_2.runtime_v2.transition import (
    RunAPublishedSourceProtectionManifest,
    V2MigrationManifest,
    sha256_file,
    verify_run_a_protection,
)

STAGE2_ROOT = Path("/Volumes/FuckingLife/era100x_stage2")
APPROVED_VOLUME = Path("/Volumes/FuckingLife")
REPO_ROOT = Path(__file__).resolve().parents[5]
APPROVED_BRANCH = "stage/2-multi-event-runtime-v2"
RUN_A_ID = "stage2-g1-full-a-20260716T144233Z-366a541b7956"
STAGE1_DATA_RUN_ID = "stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682"
STAGE1_MANIFEST_SHA256 = "436ffbe36e310dd015a962a29593360729d06db25ff96eddf12644c62d76e94f"
PREREGISTRATION_SHA256 = "6b0f66e4007b86e08b58a9b366170eeee952199baa203d7f174b2ca69478c1f9"
CONFIG_SHA256 = "adb6295e210de66d1e69aa008e6161e8fef1e1fd72001ff812b68597f8c72e3f"
STAGE1_LOGICAL_HASHES = {
    "BTCUSDT": "03d437ed9a6c19d92162e5c9dd115df4988e8accce3c8180b749f15cfdcc36a8",
    "ETHUSDT": "6db4d5e411edae3838b352944b83c38ba68915841a1f9c9de8f16ef44c3b8332",
}
MINIMUM_V2_FREE_BYTES = 1_345_364_951_040
FORMAL_GROUP1_PARTITION_COUNT = 61_776

_CODE_SURFACES = (
    "scripts/run_stage2_research.py",
    "src/era100x/data/schema/models.py",
    "src/era100x/research/stage_2/contracts",
    "src/era100x/research/stage_2/episodes",
    "src/era100x/research/stage_2/features/foundation",
    "src/era100x/research/stage_2/gates",
    "src/era100x/research/stage_2/key_levels",
    "src/era100x/research/stage_2/manifests/configuration.py",
    "src/era100x/research/stage_2/manifests/models.py",
    "src/era100x/research/stage_2/pipelines/candidates",
    "src/era100x/research/stage_2/pipelines/v2",
    "src/era100x/research/stage_2/runtime_v2",
)
_FORBIDDEN_DATASET_TOKENS = (
    "bootstrap",
    "entry_intent",
    "first_passage",
    "mfe",
    "mae",
    "pnl",
    "stop_first",
    "target_first",
)


class RuntimeV2OrchestrationError(RuntimeError):
    """The locked V2 run cannot safely advance."""


class RuntimeV2BackendUnavailable(RuntimeV2OrchestrationError):
    """No approved static build backend is wired into the CLI."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RuntimeVerification(_FrozenModel):
    schema_name: Literal["stage2-v2-runtime-verification"] = "stage2-v2-runtime-verification"
    status: Literal["PASS"] = "PASS"
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    publication_state: Literal["PUBLISHED"] = "PUBLISHED"
    checked_task_count: int = Field(ge=0)
    checked_partition_count: int = Field(ge=0)
    unknown_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def full_and_clean(self) -> Self:
        if self.checked_task_count != len(FULL_TASK_MATRIX):
            raise ValueError("verification did not cover the fixed task matrix")
        if self.unknown_count or self.error_count:
            raise ValueError("verification contains UNKNOWN or error facts")
        return self


class RuntimeComparison(_FrozenModel):
    schema_name: Literal["stage2-v2-run-a-comparison"] = "stage2-v2-run-a-comparison"
    status: Literal["PASS"] = "PASS"
    source_run_a_id: Literal["stage2-g1-full-a-20260716T144233Z-366a541b7956"] = (
        "stage2-g1-full-a-20260716T144233Z-366a541b7956"
    )
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    matched_partition_count: int = Field(ge=0)
    difference_count: int = Field(ge=0)
    comparison_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def full_and_equal(self) -> Self:
        if self.matched_partition_count != FORMAL_GROUP1_PARTITION_COUNT:
            raise ValueError("comparison did not cover all 61,776 Group-1 owner-day partitions")
        if self.difference_count:
            raise ValueError("Run A/V2 comparison contains semantic differences")
        return self


class RuntimeFailureEvidence(_FrozenModel):
    schema_name: Literal["stage2-v2-runtime-failure"] = "stage2-v2-runtime-failure"
    failure_version: Literal["1.0"] = "1.0"
    run_id: str
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_id: str
    error_type: str
    reason: str
    publication_status: Literal["FAILED_UNPUBLISHED"] = "FAILED_UNPUBLISHED"


@dataclass(frozen=True, slots=True)
class RuntimeV2Context:
    run_id: str
    run_root: Path
    manifest: ManifestV2
    protection: RunAPublishedSourceProtectionManifest
    migration: V2MigrationManifest


class RuntimeV2Backend(Protocol):
    """Static backend boundary; implementations cannot alter the run matrix."""

    def validate_preflight(self, context: RuntimeV2Context) -> None: ...

    def execute_task(
        self,
        context: RuntimeV2Context,
        task_id: str,
    ) -> BackendTaskReceipt: ...

    def verify_completed_task(
        self,
        context: RuntimeV2Context,
        receipt: BackendTaskReceipt,
    ) -> None: ...

    def release_run(self, context: RuntimeV2Context) -> None: ...

    def verify_run(self, context: RuntimeV2Context) -> RuntimeVerification: ...

    def compare_run_a(
        self,
        context: RuntimeV2Context,
    ) -> RuntimeComparison: ...


class FailClosedRuntimeV2Backend:
    """Safe default until the approved builders are wired by repository code."""

    @staticmethod
    def _unavailable() -> RuntimeV2BackendUnavailable:
        return RuntimeV2BackendUnavailable(
            "approved Runtime V2 build backend is not statically registered"
        )

    def execute_task(
        self,
        context: RuntimeV2Context,
        task_id: str,
    ) -> BackendTaskReceipt:
        del context, task_id
        raise self._unavailable()

    def validate_preflight(self, context: RuntimeV2Context) -> None:
        del context
        raise self._unavailable()

    def verify_completed_task(
        self,
        context: RuntimeV2Context,
        receipt: BackendTaskReceipt,
    ) -> None:
        del context, receipt
        raise self._unavailable()

    def verify_run(self, context: RuntimeV2Context) -> RuntimeVerification:
        del context
        raise self._unavailable()

    def release_run(self, context: RuntimeV2Context) -> None:
        del context
        raise self._unavailable()

    def compare_run_a(self, context: RuntimeV2Context) -> RuntimeComparison:
        del context
        raise self._unavailable()


@dataclass(frozen=True, slots=True)
class _LoadedAuthorities:
    manifest: ManifestV2
    protection: RunAPublishedSourceProtectionManifest
    migration: V2MigrationManifest
    manifest_source_sha256: str
    protection_source_sha256: str
    migration_source_sha256: str


class Stage2V2Orchestrator:
    """Run the approved S2-T10 v1.8 matrix without any runtime override."""

    def __init__(self, backend: RuntimeV2Backend | None = None) -> None:
        self.backend = backend or FailClosedRuntimeV2Backend()

    def preflight(
        self,
        *,
        run_id: str,
        manifest_path: Path,
        snapshot_id: str,
        protection_path: Path,
        migration_path: Path,
    ) -> RuntimeV2Checkpoint:
        run_root = _run_root(run_id)
        authorities = self._load_authorities(
            run_id=run_id,
            run_root=run_root,
            manifest_path=manifest_path,
            snapshot_id=snapshot_id,
            protection_path=protection_path,
            migration_path=migration_path,
        )
        self._assert_repository_authority(authorities)
        self._assert_external_root(run_id=run_id, write_probe=True, require_space=True)
        self._verify_protected_run_a(authorities.protection)
        if run_root.exists():
            raise FileExistsError("append-only Runtime V2 run_id already exists")
        # Source authority, capacity, and protected comparison inputs are
        # validated read-only before this append-only run_id is consumed.
        self.backend.validate_preflight(
            RuntimeV2Context(
                run_id,
                run_root,
                authorities.manifest,
                authorities.protection,
                authorities.migration,
            )
        )
        run_root.mkdir(parents=True, exist_ok=False)
        for name in ("staging", "published", "manifests", "reports", "logs", "tmp"):
            (run_root / name).mkdir(exist_ok=False)
        write_once_model(
            run_root / "manifests" / f"runtime-{authorities.manifest.manifest_hash}.json",
            authorities.manifest,
        )
        write_once_model(
            run_root
            / "manifests"
            / f"run-a-protection-{authorities.protection.manifest_hash}.json",
            authorities.protection,
        )
        write_once_model(
            run_root / "manifests" / f"migration-{authorities.migration.manifest_hash}.json",
            authorities.migration,
        )
        checkpoint = RuntimeV2Checkpoint.seal(
            {
                "run_id": run_id,
                "snapshot_id": snapshot_id,
                "manifest_hash": authorities.manifest.manifest_hash,
                "manifest_source_sha256": authorities.manifest_source_sha256,
                "run_a_protection_manifest_hash": authorities.protection.manifest_hash,
                "run_a_protection_source_sha256": authorities.protection_source_sha256,
                "migration_manifest_hash": authorities.migration.manifest_hash,
                "migration_manifest_source_sha256": authorities.migration_source_sha256,
                "code_tree_sha256": authorities.manifest.code_tree_sha256,
                "stage1_data_run_id": authorities.manifest.stage1_data_run_id,
                "preregistration_manifest_sha256": (
                    authorities.manifest.preregistration_manifest_sha256
                ),
                "config_sha256": authorities.manifest.config_sha256,
                "planned_tasks": FULL_TASK_MATRIX,
                "completed_tasks": (),
                "phase": "PREFLIGHT",
                "status": "PREFLIGHT_PASSED",
                "active_task": None,
                "failure": None,
                "revision": 0,
            }
        )
        CheckpointStore(run_root).create(checkpoint)
        return checkpoint

    def build_foundation(
        self,
        *,
        run_id: str,
        manifest_path: Path,
        snapshot_id: str,
        protection_path: Path,
        migration_path: Path,
    ) -> RuntimeV2Checkpoint:
        context, checkpoint = self._load_run(
            run_id, manifest_path, snapshot_id, protection_path, migration_path, mutating=True
        )
        if checkpoint.status != "PREFLIGHT_PASSED":
            raise RuntimeV2OrchestrationError(
                "build-foundation requires PREFLIGHT_PASSED; interrupted work uses resume"
            )
        with self._run_lock(context.run_root):
            return self._execute_phase(context, checkpoint, "FOUNDATION", FOUNDATION_TASKS)

    def run_group1(
        self,
        *,
        run_id: str,
        manifest_path: Path,
        snapshot_id: str,
        protection_path: Path,
        migration_path: Path,
    ) -> RuntimeV2Checkpoint:
        context, checkpoint = self._load_run(
            run_id, manifest_path, snapshot_id, protection_path, migration_path, mutating=True
        )
        if checkpoint.status != "FOUNDATION_COMPLETE":
            raise RuntimeV2OrchestrationError("run-group1 requires complete Foundation receipts")
        with self._run_lock(context.run_root):
            return self._execute_phase(context, checkpoint, "GROUP1", GROUP1_TASKS)

    def resume(
        self,
        *,
        run_id: str,
        manifest_path: Path,
        snapshot_id: str,
        protection_path: Path,
        migration_path: Path,
    ) -> RuntimeV2Checkpoint:
        context, checkpoint = self._load_run(
            run_id, manifest_path, snapshot_id, protection_path, migration_path, mutating=True
        )
        if checkpoint.status not in {"IN_PROGRESS", "INTERRUPTED_RECOVERABLE"}:
            raise RuntimeV2OrchestrationError("resume requires a recoverable interrupted state")
        with self._run_lock(context.run_root):
            self._verify_completed(context, checkpoint)
            if checkpoint.phase == "FOUNDATION":
                return self._execute_phase(context, checkpoint, "FOUNDATION", FOUNDATION_TASKS)
            if checkpoint.phase == "GROUP1":
                return self._execute_phase(context, checkpoint, "GROUP1", GROUP1_TASKS)
            raise RuntimeV2OrchestrationError("preflight has no resumable build phase")

    def verify(
        self,
        *,
        run_id: str,
        manifest_path: Path,
        snapshot_id: str,
        protection_path: Path,
        migration_path: Path,
    ) -> RuntimeVerification:
        context, checkpoint = self._load_run(
            run_id, manifest_path, snapshot_id, protection_path, migration_path, mutating=False
        )
        if checkpoint.status != "GROUP1_COMPLETE":
            raise RuntimeV2OrchestrationError("verify requires the complete fixed Group-1 matrix")
        self._verify_completed(context, checkpoint)
        result = self.backend.verify_run(context)
        self._assert_result_binding(result.snapshot_id, result.manifest_hash, context)
        return result

    def release(
        self,
        *,
        run_id: str,
        manifest_path: Path,
        snapshot_id: str,
        protection_path: Path,
        migration_path: Path,
    ) -> RuntimeV2Checkpoint:
        """Publish in its own process after all build metadata is released."""

        context, checkpoint = self._load_run(
            run_id, manifest_path, snapshot_id, protection_path, migration_path, mutating=True
        )
        if checkpoint.status != "GROUP1_COMPLETE":
            raise RuntimeV2OrchestrationError("release requires the complete fixed Group-1 matrix")
        with self._run_lock(context.run_root):
            self._verify_completed(context, checkpoint)
            self.backend.release_run(context)
        return checkpoint

    def compare(
        self,
        *,
        run_id: str,
        manifest_path: Path,
        snapshot_id: str,
        protection_path: Path,
        migration_path: Path,
    ) -> RuntimeComparison:
        context, checkpoint = self._load_run(
            run_id,
            manifest_path,
            snapshot_id,
            protection_path,
            migration_path,
            mutating=True,
            require_space=False,
        )
        if checkpoint.status != "GROUP1_COMPLETE":
            raise RuntimeV2OrchestrationError("compare requires the complete fixed Group-1 matrix")
        # CR-2026-009 classifies compare as a narrowly mutating command: it may
        # write exactly one append-only evidence report.  It therefore needs
        # the same single-writer exclusion as build/release, but not the full
        # build space gate after publication has already consumed capacity.
        with self._run_lock(context.run_root):
            self._verify_completed(context, checkpoint)
            result = self.backend.compare_run_a(context)
            self._assert_result_binding(result.snapshot_id, result.manifest_hash, context)
            if result.source_run_a_id != context.protection.source_run_id:
                raise RuntimeV2OrchestrationError("comparison used a different Run A authority")
            return result

    def _execute_phase(
        self,
        context: RuntimeV2Context,
        checkpoint: RuntimeV2Checkpoint,
        phase: Literal["FOUNDATION", "GROUP1"],
        phase_tasks: tuple[str, ...],
    ) -> RuntimeV2Checkpoint:
        store = CheckpointStore(context.run_root)
        pending = [task for task in phase_tasks if task not in _completed_ids(checkpoint)]
        if not pending:
            raise RuntimeV2OrchestrationError(f"{phase} has no pending task")
        current = checkpoint
        for task_id in pending:
            if task_id != FULL_TASK_MATRIX[len(current.completed_tasks)]:
                raise RuntimeV2OrchestrationError("runtime matrix order changed")
            active = current.advance(
                phase=phase,
                status="IN_PROGRESS",
                active_task=task_id,
                failure=None,
            )
            store.replace(active, expected_hash=current.checkpoint_hash)
            current = active
            try:
                receipt = self.backend.execute_task(context, task_id)
                self._validate_backend_receipt(context, task_id, receipt)
                receipt_path = context.run_root / task_receipt_relative_path(task_id)
                receipt_file_hash = write_once_model(receipt_path, receipt)
                self.backend.verify_completed_task(context, receipt)
                completion = CompletedTask(
                    task_id=task_id,
                    receipt_relative_path=task_receipt_relative_path(task_id),
                    receipt_file_sha256=receipt_file_hash,
                    receipt_hash=receipt.receipt_hash,
                    semantic_sha256=receipt.semantic_sha256,
                )
            except InterruptedError:
                interrupted = current.advance(
                    status="INTERRUPTED_RECOVERABLE",
                    active_task=task_id,
                )
                store.replace(interrupted, expected_hash=current.checkpoint_hash)
                raise
            except Exception as exc:
                failed = self._terminal_failure(context, current, task_id, exc)
                store.replace(failed, expected_hash=current.checkpoint_hash)
                raise
            completions = (*current.completed_tasks, completion)
            phase_complete = task_id == phase_tasks[-1]
            if phase_complete:
                status = "FOUNDATION_COMPLETE" if phase == "FOUNDATION" else "GROUP1_COMPLETE"
                next_task = None
            else:
                status = "INTERRUPTED_RECOVERABLE"
                next_task = FULL_TASK_MATRIX[len(completions)]
            completed = current.advance(
                completed_tasks=completions,
                status=status,
                active_task=next_task,
                failure=None,
            )
            store.replace(completed, expected_hash=current.checkpoint_hash)
            current = completed
        return current

    def _load_run(
        self,
        run_id: str,
        manifest_path: Path,
        snapshot_id: str,
        protection_path: Path,
        migration_path: Path,
        *,
        mutating: bool,
        require_space: bool | None = None,
    ) -> tuple[RuntimeV2Context, RuntimeV2Checkpoint]:
        run_root = _run_root(run_id)
        authorities = self._load_authorities(
            run_id=run_id,
            run_root=run_root,
            manifest_path=manifest_path,
            snapshot_id=snapshot_id,
            protection_path=protection_path,
            migration_path=migration_path,
        )
        self._assert_repository_authority(authorities)
        self._assert_external_root(
            run_id=run_id,
            write_probe=mutating,
            require_space=mutating if require_space is None else require_space,
        )
        self._verify_protected_run_a(authorities.protection)
        checkpoint = CheckpointStore(run_root).read()
        expected = {
            "run_id": run_id,
            "snapshot_id": snapshot_id,
            "manifest_hash": authorities.manifest.manifest_hash,
            "manifest_source_sha256": authorities.manifest_source_sha256,
            "run_a_protection_manifest_hash": authorities.protection.manifest_hash,
            "run_a_protection_source_sha256": authorities.protection_source_sha256,
            "migration_manifest_hash": authorities.migration.manifest_hash,
            "migration_manifest_source_sha256": authorities.migration_source_sha256,
            "code_tree_sha256": authorities.manifest.code_tree_sha256,
        }
        actual = checkpoint.model_dump(mode="python", include=set(expected))
        if actual != expected:
            raise RuntimeV2OrchestrationError("checkpoint authority differs from explicit inputs")
        self._verify_manifest_copies(run_root, authorities)
        return (
            RuntimeV2Context(
                run_id,
                run_root,
                authorities.manifest,
                authorities.protection,
                authorities.migration,
            ),
            checkpoint,
        )

    def _load_authorities(
        self,
        *,
        run_id: str,
        run_root: Path,
        manifest_path: Path,
        snapshot_id: str,
        protection_path: Path,
        migration_path: Path,
    ) -> _LoadedAuthorities:
        if not _is_sha256(snapshot_id):
            raise ValueError("snapshot_id must be a lowercase SHA-256")
        manifest_source = _authority_file(manifest_path)
        protection_source = _authority_file(protection_path)
        migration_source = _authority_file(migration_path)
        manifest = ManifestV2.model_validate_json(manifest_source.read_bytes())
        protection = RunAPublishedSourceProtectionManifest.model_validate_json(
            protection_source.read_bytes()
        )
        migration = V2MigrationManifest.model_validate_json(migration_source.read_bytes())
        if manifest.manifest_hash != manifest.computed_hash():
            raise ValueError("Runtime V2 Manifest is not sealed")
        if protection.manifest_hash != protection.computed_hash():
            raise ValueError("Run A protection Manifest is not sealed")
        if migration.manifest_hash != migration.computed_hash():
            raise ValueError("V2 migration Manifest is not sealed")
        transition_manifest_root = migration_source.parent.resolve()
        if any(
            Path(value).resolve().parent != transition_manifest_root
            for value in (
                migration.contract_price_inventory_manifest_path,
                migration.stage1_resolved_source_index_path,
            )
        ):
            raise ValueError("resolved source authority is outside transition evidence")
        if manifest.snapshot_id != snapshot_id:
            raise ValueError("explicit snapshot_id differs from the locked Manifest")
        if manifest.stage1_data_run_id != STAGE1_DATA_RUN_ID:
            raise ValueError("Runtime V2 Manifest changed the frozen Stage 1 Data Run")
        if manifest.preregistration_manifest_sha256 != PREREGISTRATION_SHA256:
            raise ValueError("Runtime V2 Manifest changed the preregistration authority")
        if manifest.config_sha256 != CONFIG_SHA256:
            raise ValueError("Runtime V2 Manifest changed the preregistered config")
        required_hashes = {
            STAGE1_MANIFEST_SHA256,
            *STAGE1_LOGICAL_HASHES.values(),
        }
        actual_authorities = {item.name: item.sha256 for item in manifest.stage1_authorities}
        actual_hashes = set(actual_authorities.values())
        if not required_hashes.issubset(actual_hashes):
            raise ValueError("Runtime V2 Manifest omits a frozen Stage 1 authority")
        expected_resolved_authorities = {
            CONTRACT_PRICE_MANIFEST_AUTHORITY: (migration.contract_price_inventory_manifest_hash),
            TRADES_RESOLVED_INDEX_AUTHORITY: (migration.stage1_resolved_source_index_manifest_hash),
        }
        if any(
            actual_authorities.get(name) != digest
            for name, digest in expected_resolved_authorities.items()
        ):
            raise ValueError("Runtime V2 Manifest omits a sealed resolved source authority")
        if protection.source_run_id != RUN_A_ID:
            raise ValueError("V2 migration is not bound to the formal Run A")
        if protection.preregistration_manifest_hash != PREREGISTRATION_SHA256:
            raise ValueError("Run A protection preregistration hash changed")
        if protection.config_hash != CONFIG_SHA256:
            raise ValueError("Run A protection config hash changed")
        if protection.stage1_data_run_id != STAGE1_DATA_RUN_ID:
            raise ValueError("Run A protection Stage 1 Data Run changed")
        if protection.stage1_logical_hashes != STAGE1_LOGICAL_HASHES:
            raise ValueError("Run A protection Stage 1 logical hashes changed")
        if migration.source_protection_manifest_hash != protection.manifest_hash:
            raise ValueError("migration Manifest references another Run A protection authority")
        if migration.source_run_id != protection.source_run_id:
            raise ValueError("migration Manifest references another Run A")
        if migration.destination_run_id != run_id:
            raise ValueError("migration Manifest destination run_id mismatch")
        if Path(migration.destination_root) != run_root:
            raise ValueError("migration Manifest destination root mismatch")
        if migration.v2_code_tree_hash != manifest.code_tree_sha256:
            raise ValueError("Manifest and migration code-tree hashes differ")
        for spec in manifest.dataset_specs:
            lowered = {spec.dataset_name.lower(), *(field.name.lower() for field in spec.fields)}
            if any(token in value for token in _FORBIDDEN_DATASET_TOKENS for value in lowered):
                raise ValueError("Runtime V2 Manifest contains a forbidden later-stage dataset")
        return _LoadedAuthorities(
            manifest=manifest,
            protection=protection,
            migration=migration,
            manifest_source_sha256=sha256_file(manifest_source),
            protection_source_sha256=sha256_file(protection_source),
            migration_source_sha256=sha256_file(migration_source),
        )

    def _assert_repository_authority(self, authorities: _LoadedAuthorities) -> None:
        branch = _git("branch", "--show-current")
        if branch != APPROVED_BRANCH:
            raise RuntimeV2OrchestrationError(
                f"Runtime V2 execution requires {APPROVED_BRANCH}, found {branch}"
            )
        if _git("status", "--porcelain", "--untracked-files=all"):
            raise RuntimeV2OrchestrationError("Runtime V2 execution requires a clean worktree")
        commit = _git("rev-parse", "HEAD")
        if commit != authorities.migration.v2_code_commit:
            raise RuntimeV2OrchestrationError("migration Manifest code commit differs from HEAD")
        actual_tree = compute_v2_code_tree_sha256(REPO_ROOT)
        if actual_tree != authorities.manifest.code_tree_sha256:
            raise RuntimeV2OrchestrationError("Runtime V2 code tree differs from the Manifest")

    def _assert_external_root(
        self,
        *,
        run_id: str,
        write_probe: bool,
        require_space: bool,
    ) -> None:
        if STAGE2_ROOT != Path("/Volumes/FuckingLife/era100x_stage2"):
            raise RuntimeV2OrchestrationError("Runtime V2 root override is forbidden")
        if not APPROVED_VOLUME.is_mount():
            raise RuntimeV2OrchestrationError("approved external volume is not mounted")
        if not STAGE2_ROOT.is_dir() or STAGE2_ROOT.is_symlink():
            raise RuntimeV2OrchestrationError("approved Stage 2 root is unavailable")
        runs = STAGE2_ROOT / "runs"
        if not runs.is_dir() or runs.is_symlink():
            raise RuntimeV2OrchestrationError("approved Stage 2 runs root is unavailable")
        if require_space and shutil.disk_usage(STAGE2_ROOT).free < MINIMUM_V2_FREE_BYTES:
            raise RuntimeV2OrchestrationError("Runtime V2 full-build space gate failed")
        if write_probe:
            probe = runs / f".{run_id}.v2-write-probe"
            descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(descriptor, b"stage2-runtime-v2\n")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
                probe.unlink()

    def _verify_protected_run_a(
        self,
        protection: RunAPublishedSourceProtectionManifest,
    ) -> None:
        run_a_root = STAGE2_ROOT / "runs" / protection.source_run_id
        execution_path, supplement_path = _protected_run_a_manifest_paths(run_a_root, protection)
        verify_run_a_protection(
            protection=protection,
            run_a_root=run_a_root,
            execution_manifest_path=execution_path,
            release_supplement_path=supplement_path,
        )

    def _verify_manifest_copies(
        self,
        run_root: Path,
        authorities: _LoadedAuthorities,
    ) -> None:
        expected: tuple[tuple[Path, BaseModel], ...] = (
            (
                run_root / "manifests" / f"runtime-{authorities.manifest.manifest_hash}.json",
                authorities.manifest,
            ),
            (
                run_root
                / "manifests"
                / f"run-a-protection-{authorities.protection.manifest_hash}.json",
                authorities.protection,
            ),
            (
                run_root / "manifests" / f"migration-{authorities.migration.manifest_hash}.json",
                authorities.migration,
            ),
        )
        for path, model in expected:
            payload = (canonical_json(model.model_dump(mode="json")) + "\n").encode("utf-8")
            if not path.is_file() or path.is_symlink() or path.read_bytes() != payload:
                raise RuntimeV2OrchestrationError(f"immutable run authority changed: {path}")

    def _verify_completed(
        self,
        context: RuntimeV2Context,
        checkpoint: RuntimeV2Checkpoint,
    ) -> None:
        for completion in checkpoint.completed_tasks:
            receipt = read_backend_receipt(context.run_root, completion)
            self._validate_backend_receipt(context, completion.task_id, receipt)
            self.backend.verify_completed_task(context, receipt)

    @staticmethod
    def _validate_backend_receipt(
        context: RuntimeV2Context,
        task_id: str,
        receipt: BackendTaskReceipt,
    ) -> None:
        if receipt.task_id != task_id:
            raise RuntimeV2OrchestrationError("backend returned a receipt for another task")
        if receipt.snapshot_id != context.manifest.snapshot_id:
            raise RuntimeV2OrchestrationError("backend receipt changed the snapshot")
        if receipt.manifest_hash != context.manifest.manifest_hash:
            raise RuntimeV2OrchestrationError("backend receipt changed the Manifest")
        if receipt.receipt_hash != receipt.computed_hash():
            raise RuntimeV2OrchestrationError("backend receipt is not sealed")

    @staticmethod
    def _assert_result_binding(
        snapshot_id: str,
        manifest_hash: str,
        context: RuntimeV2Context,
    ) -> None:
        if snapshot_id != context.manifest.snapshot_id:
            raise RuntimeV2OrchestrationError("read-only result changed the snapshot")
        if manifest_hash != context.manifest.manifest_hash:
            raise RuntimeV2OrchestrationError("read-only result changed the Manifest")

    @staticmethod
    def _terminal_failure(
        context: RuntimeV2Context,
        checkpoint: RuntimeV2Checkpoint,
        task_id: str,
        error: Exception,
    ) -> RuntimeV2Checkpoint:
        reason = str(error).strip() or type(error).__name__
        reason = reason[:2048]
        evidence = RuntimeFailureEvidence(
            run_id=context.run_id,
            snapshot_id=context.manifest.snapshot_id,
            manifest_hash=context.manifest.manifest_hash,
            task_id=task_id,
            error_type=type(error).__name__,
            reason=reason,
        )
        safe_task = task_id.lower().replace(":", "-")
        relative_path = f"reports/failure-{safe_task}-r{checkpoint.revision + 1}.json"
        report_hash = write_once_model(context.run_root / relative_path, evidence)
        failure = FailureRecord(
            task_id=task_id,
            error_type=type(error).__name__,
            reason=reason,
            report_relative_path=relative_path,
            report_sha256=report_hash,
        )
        return checkpoint.advance(
            status="FAILED_UNPUBLISHED",
            active_task=None,
            failure=failure,
        )

    @staticmethod
    @contextmanager
    def _run_lock(run_root: Path) -> Iterator[None]:
        path = run_root / "orchestration-v2.lock"
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeV2OrchestrationError(
                    "another Runtime V2 orchestration command is active"
                ) from exc
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def compute_v2_code_tree_sha256(repo_root: Path = REPO_ROOT) -> str:
    """Hash the explicit tracked Runtime V2 code surface without filesystem discovery."""

    command = ["git", "-C", str(repo_root), "ls-files", "-z", "--", *_CODE_SURFACES]
    output = subprocess.check_output(command)
    relative_paths = tuple(item.decode("utf-8") for item in output.split(b"\0") if item)
    if "scripts/run_stage2_research.py" not in relative_paths:
        raise RuntimeV2OrchestrationError("fixed Runtime V2 CLI is not tracked")
    digest = hashlib.sha256(b"stage2-runtime-v2-code-tree-v1\0")
    for relative in sorted(relative_paths):
        path = repo_root / relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeV2OrchestrationError(f"tracked Runtime V2 code is unavailable: {relative}")
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _run_root(run_id: str) -> Path:
    from era100x.research.stage_2.runtime_v2.checkpoint import SAFE_RUN_ID

    if SAFE_RUN_ID.fullmatch(run_id) is None:
        raise ValueError("Runtime V2 run_id is not in the approved Run-B namespace")
    return STAGE2_ROOT / "runs" / run_id


def _authority_file(path: Path) -> Path:
    source = Path(path)
    if not source.is_file() or source.is_symlink():
        raise FileNotFoundError(f"explicit Runtime V2 authority is unavailable: {source}")
    resolved = source.resolve(strict=True)
    root = STAGE2_ROOT.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError("Runtime V2 authority must live under the approved external root")
    return source


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(REPO_ROOT), *args],
        text=True,
    ).strip()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _completed_ids(checkpoint: RuntimeV2Checkpoint) -> set[str]:
    return {item.task_id for item in checkpoint.completed_tasks}


def _protected_run_a_manifest_paths(
    run_a_root: Path,
    protection: RunAPublishedSourceProtectionManifest,
) -> tuple[Path, Path]:
    execution: list[Path] = []
    supplement: list[Path] = []
    for relative in protection.protected_relative_paths:
        candidate = run_a_root / relative
        if candidate.parent != run_a_root / "manifests" or candidate.suffix != ".json":
            continue
        if not candidate.is_file() or candidate.is_symlink():
            continue
        payload = candidate.read_bytes()
        try:
            item = Stage2ExecutionManifest.model_validate_json(payload)
        except ValueError:
            item = None
        if item is not None and item.manifest_hash == protection.execution_manifest_hash:
            execution.append(candidate)
        try:
            release = Stage2ReleaseSupplementManifest.model_validate_json(payload)
        except ValueError:
            release = None
        if release is not None and release.manifest_hash == protection.release_supplement_hash:
            supplement.append(candidate)
    if len(execution) != 1:
        raise RuntimeV2OrchestrationError(
            "protected Run A execution Manifest match count differs: "
            f"expected=1 actual={len(execution)}"
        )
    if len(supplement) != 1:
        raise RuntimeV2OrchestrationError(
            "protected Run A release supplement match count differs: "
            f"expected=1 actual={len(supplement)}"
        )
    return execution[0], supplement[0]
