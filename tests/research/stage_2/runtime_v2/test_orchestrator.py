from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pytest

from era100x.research.stage_2.manifests.models import canonical_json
from era100x.research.stage_2.runtime_v2 import orchestrator as module
from era100x.research.stage_2.runtime_v2.checkpoint import (
    FOUNDATION_TASKS,
    FULL_TASK_MATRIX,
    GROUP1_TASKS,
    BackendTaskReceipt,
    CheckpointConflict,
    CheckpointStore,
    RuntimeV2Checkpoint,
)
from era100x.research.stage_2.runtime_v2.models import (
    ArrowFieldSpec,
    DatasetPlan,
    DatasetSpec,
    DigestBinding,
    LogicalPartitionKey,
    ManifestV2,
)
from era100x.research.stage_2.runtime_v2.orchestrator import (
    RuntimeComparison,
    RuntimeV2Context,
    RuntimeV2OrchestrationError,
    RuntimeVerification,
    Stage2V2Orchestrator,
    compute_v2_code_tree_sha256,
)
from era100x.research.stage_2.runtime_v2.resource_anomalies import ResourcePause
from era100x.research.stage_2.runtime_v2.source_authority import (
    CONTRACT_PRICE_MANIFEST_AUTHORITY,
    TRADES_RESOLVED_INDEX_AUTHORITY,
)
from era100x.research.stage_2.runtime_v2.transition import (
    RunAPublishedSourceProtectionManifest,
    V2MigrationManifest,
)

H = "a" * 64
S = "b" * 64
C = "c" * 64
COMMIT = "d" * 40
RUN_ID = "stage2-g1-v2-b-test"
FORMAL_RUN_A_ROOT = Path(
    "/Volumes/FuckingLife/era100x_stage2/runs/stage2-g1-full-a-20260716T144233Z-366a541b7956"
)
FORMAL_RUN_A_PROTECTION = Path(
    "/Volumes/FuckingLife/era100x_stage2/runs/"
    "stage2-g1-v2-authority-20260718T075348Z-e185e643051f/manifests/"
    "4f29785d5de16ecb8f17b7f45b86f7085d61fcbd63b23e3499d103445d249841.json"
)


class FakeBackend:
    def __init__(
        self,
        *,
        interrupt_once: str | None = None,
        fail_on: str | None = None,
        pause_on: str | None = None,
        preflight_error: Exception | None = None,
    ) -> None:
        self.executed: list[str] = []
        self.verified: list[str] = []
        self.interrupt_once = interrupt_once
        self.fail_on = fail_on
        self.pause_on = pause_on
        self.preflight_error = preflight_error
        self.released = False

    def validate_preflight(self, context: RuntimeV2Context) -> None:
        del context
        if self.preflight_error is not None:
            raise self.preflight_error

    def execute_task(
        self,
        context: RuntimeV2Context,
        task_id: str,
    ) -> BackendTaskReceipt:
        self.executed.append(task_id)
        if self.interrupt_once == task_id:
            self.interrupt_once = None
            raise InterruptedError("controlled test interruption")
        if self.fail_on == task_id:
            raise ValueError("controlled terminal failure")
        if self.pause_on == task_id:
            raise ResourcePause("controlled resource pressure")
        digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
        return BackendTaskReceipt.seal(
            {
                "task_id": task_id,
                "snapshot_id": context.manifest.snapshot_id,
                "manifest_hash": context.manifest.manifest_hash,
                "semantic_sha256": digest,
                "evidence_sha256": digest,
                "quality_status": "PASS",
            }
        )

    def verify_completed_task(
        self,
        context: RuntimeV2Context,
        receipt: BackendTaskReceipt,
    ) -> None:
        assert receipt.snapshot_id == context.manifest.snapshot_id
        self.verified.append(receipt.task_id)

    def release_run(self, context: RuntimeV2Context) -> None:
        del context
        self.released = True

    def verify_run(self, context: RuntimeV2Context) -> RuntimeVerification:
        return RuntimeVerification(
            snapshot_id=context.manifest.snapshot_id,
            manifest_hash=context.manifest.manifest_hash,
            checked_task_count=len(FULL_TASK_MATRIX),
            checked_partition_count=module.FORMAL_GROUP1_PARTITION_COUNT,
            unknown_count=0,
            error_count=0,
            semantic_sha256=H,
        )

    def compare_run_a(self, context: RuntimeV2Context) -> RuntimeComparison:
        return RuntimeComparison(
            snapshot_id=context.manifest.snapshot_id,
            manifest_hash=context.manifest.manifest_hash,
            matched_partition_count=module.FORMAL_GROUP1_PARTITION_COUNT,
            difference_count=0,
            comparison_sha256=S,
        )


class UserStopBackend(FakeBackend):
    def execute_task(
        self,
        context: RuntimeV2Context,
        task_id: str,
    ) -> BackendTaskReceipt:
        del context, task_id
        raise KeyboardInterrupt


def _manifest(snapshot_id: str = S) -> ManifestV2:
    spec = DatasetSpec.seal(
        {
            "dataset_name": "canonical_key_levels",
            "dataset_version": "1.0",
            "fields": (
                ArrowFieldSpec(name="key_level_id", data_type="utf8"),
                ArrowFieldSpec(name="available_at_ts", data_type="int64"),
            ),
            "stable_sort_keys": ("key_level_id",),
            "identity_fields": ("key_level_id",),
            "payload_association_fields": ("key_level_id", "available_at_ts"),
            "distribution_fields": (),
            "ownership_mode": "TIMESTAMP_NS_FIELD",
            "owner_timestamp_ns_field": "available_at_ts",
            "legacy_hash_algorithm": "ERA_CANONICAL_JSON_ROW_V1",
        }
    )
    partition = LogicalPartitionKey(
        snapshot_id=snapshot_id,
        dataset_name=spec.dataset_name,
        dataset_version=spec.dataset_version,
        dataset_spec_hash=spec.spec_hash,
        setup_id="KEY_LOW_SWEEP_RECLAIM_HOLD_V1",
        context_id="CAUSAL_EMA20_1H",
        instrument="BTCUSDT",
        variant="V1_PRICE",
        owner_date=date(2020, 1, 1),
    )
    authorities = tuple(
        sorted(
            (
                DigestBinding(name="btc_trades", sha256=module.STAGE1_LOGICAL_HASHES["BTCUSDT"]),
                DigestBinding(name="eth_trades", sha256=module.STAGE1_LOGICAL_HASHES["ETHUSDT"]),
                DigestBinding(name="stage1_manifest", sha256=module.STAGE1_MANIFEST_SHA256),
                DigestBinding(name=CONTRACT_PRICE_MANIFEST_AUTHORITY, sha256=H),
                DigestBinding(name=TRADES_RESOLVED_INDEX_AUTHORITY, sha256=S),
            ),
            key=lambda item: item.name,
        )
    )
    return ManifestV2.seal(
        {
            "snapshot_id": snapshot_id,
            "stage1_data_run_id": module.STAGE1_DATA_RUN_ID,
            "stage1_authorities": authorities,
            "preregistration_manifest_sha256": module.PREREGISTRATION_SHA256,
            "config_sha256": module.CONFIG_SHA256,
            "code_tree_sha256": C,
            "dataset_specs": (spec,),
            "dataset_plans": (
                DatasetPlan(
                    dataset_spec_hash=spec.spec_hash,
                    expected_partition_ids=(partition.partition_id,),
                ),
            ),
            "invalidation_conditions": ("HASH_CHANGED",),
        }
    )


def _protection() -> RunAPublishedSourceProtectionManifest:
    return RunAPublishedSourceProtectionManifest.seal(
        {
            "schema_name": "stage2-run-a-source-protection-v1",
            "manifest_version": "1.0",
            "role": "IMMUTABLE_V2_MIGRATION_SOURCE",
            "source_run_id": module.RUN_A_ID,
            "checkpoint_status": "PUBLISHED",
            "release_state": "PUBLISHED",
            "planned_count": 9508,
            "completed_count": 9508,
            "failed_count": 0,
            "catalog_entry_count": 61776,
            "execution_manifest_hash": H,
            "release_supplement_hash": S,
            "generator_commit": "e" * 40,
            "checkpoint_sha256": H,
            "catalog_sha256": H,
            "catalog_logical_hash": H,
            "catalog_physical_hash": H,
            "quality_report_sha256": H,
            "count_summary_sha256": H,
            "release_analysis_sha256": H,
            "preregistration_manifest_hash": module.PREREGISTRATION_SHA256,
            "config_hash": module.CONFIG_SHA256,
            "stage1_data_run_id": module.STAGE1_DATA_RUN_ID,
            "stage1_logical_hashes": module.STAGE1_LOGICAL_HASHES,
            "protected_relative_paths": (
                "manifests/execution.json",
                "manifests/release-supplement.json",
            ),
            "recorded_at": "2026-07-17T00:00:00+00:00",
        }
    )


def _migration(
    root: Path,
    protection: RunAPublishedSourceProtectionManifest,
) -> V2MigrationManifest:
    return V2MigrationManifest.seal(
        {
            "schema_name": "stage2-v2-migration-manifest-v1",
            "manifest_version": "1.0",
            "operation": "BUILD_V2_FOUNDATION_AND_RECONSTRUCT_GROUP1",
            "change_requests": ("CR-2026-007", "CR-2026-008"),
            "source_protection_manifest_hash": protection.manifest_hash,
            "source_run_id": protection.source_run_id,
            "destination_run_id": RUN_ID,
            "destination_root": str(root / "runs" / RUN_ID),
            "v2_code_commit": COMMIT,
            "v2_code_tree_hash": C,
            "catalog_schema_version": "2.0",
            "semantic_hash_algorithm": "era-canonical-binary-v2",
            "legacy_hash_algorithm": "era-canonical-json-row-v1",
            "snapshot_reader_mode": "EXPLICIT_SNAPSHOT_ID_ONLY",
            "source_delete_allowed": False,
            "run_a_artifact_reuse_allowed": False,
            "same_volume_atomic_publish": True,
            "contract_price_inventory_manifest_path": str(root / "authorities" / "prices.json"),
            "contract_price_inventory_manifest_hash": H,
            "contract_price_inventory_source_sha256": H,
            "stage1_resolved_source_index_path": str(root / "authorities" / "trades.json"),
            "stage1_resolved_source_index_manifest_hash": S,
            "stage1_resolved_source_index_source_sha256": S,
            "recorded_at": "2026-07-17T00:00:00+00:00",
        }
    )


def _write(path: Path, model: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assert hasattr(model, "model_dump")
    payload = model.model_dump(mode="json")  # type: ignore[union-attr]
    path.write_text(canonical_json(payload) + "\n", encoding="utf-8")


@pytest.fixture
def authority_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, object], Path]:
    root = tmp_path / "era100x_stage2"
    (root / "runs").mkdir(parents=True)
    monkeypatch.setattr(module, "STAGE2_ROOT", root)
    monkeypatch.setattr(Stage2V2Orchestrator, "_assert_external_root", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        Stage2V2Orchestrator, "_assert_repository_authority", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        Stage2V2Orchestrator, "_verify_protected_run_a", lambda *args, **kwargs: None
    )
    manifest = _manifest()
    protection = _protection()
    migration = _migration(root, protection)
    manifest_path = root / "authorities" / "runtime-manifest.json"
    protection_path = root / "authorities" / "run-a-protection.json"
    migration_path = root / "authorities" / "migration.json"
    _write(manifest_path, manifest)
    _write(protection_path, protection)
    _write(migration_path, migration)
    common: dict[str, object] = {
        "run_id": RUN_ID,
        "manifest_path": manifest_path,
        "snapshot_id": manifest.snapshot_id,
        "protection_path": protection_path,
        "migration_path": migration_path,
    }
    return common, root


def test_preflight_freezes_authorities_and_full_matrix(
    authority_paths: tuple[dict[str, object], Path],
) -> None:
    common, root = authority_paths
    orchestrator = Stage2V2Orchestrator(FakeBackend())
    checkpoint = orchestrator.preflight(**common)  # type: ignore[arg-type]
    assert checkpoint.planned_tasks == FULL_TASK_MATRIX
    assert checkpoint.status == "PREFLIGHT_PASSED"
    run_root = root / "runs" / RUN_ID
    assert CheckpointStore(run_root).read() == checkpoint
    assert {path.name for path in (run_root / "manifests").iterdir()} == {
        f"runtime-{checkpoint.manifest_hash}.json",
        f"run-a-protection-{checkpoint.run_a_protection_manifest_hash}.json",
        f"migration-{checkpoint.migration_manifest_hash}.json",
    }
    with pytest.raises(FileExistsError, match="append-only"):
        orchestrator.preflight(**common)  # type: ignore[arg-type]


def test_failed_backend_preflight_does_not_consume_run_id(
    authority_paths: tuple[dict[str, object], Path],
) -> None:
    common, root = authority_paths
    backend = FakeBackend(preflight_error=ValueError("bad Stage 1 authority"))

    with pytest.raises(ValueError, match="bad Stage 1 authority"):
        Stage2V2Orchestrator(backend).preflight(**common)  # type: ignore[arg-type]

    assert not (root / "runs" / RUN_ID).exists()


@pytest.mark.skipif(
    not FORMAL_RUN_A_ROOT.exists() or not FORMAL_RUN_A_PROTECTION.exists(),
    reason="formal Run A protection authority absent",
)
def test_formal_run_a_protection_resolves_exact_cr009_supplement() -> None:
    protection = RunAPublishedSourceProtectionManifest.model_validate_json(
        FORMAL_RUN_A_PROTECTION.read_bytes()
    )

    execution, supplement = module._protected_run_a_manifest_paths(FORMAL_RUN_A_ROOT, protection)

    assert execution.name == f"{protection.execution_manifest_hash}.json"
    assert supplement.name == f"{protection.release_supplement_hash}.json"


@pytest.mark.skipif(
    not FORMAL_RUN_A_ROOT.exists() or not FORMAL_RUN_A_PROTECTION.exists(),
    reason="formal Run A protection authority absent",
)
def test_run_a_protection_reports_missing_and_duplicate_supplements(
    tmp_path: Path,
) -> None:
    protection = RunAPublishedSourceProtectionManifest.model_validate_json(
        FORMAL_RUN_A_PROTECTION.read_bytes()
    )
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    execution_name = f"{protection.execution_manifest_hash}.json"
    supplement_name = f"{protection.release_supplement_hash}.json"
    (manifests / execution_name).write_bytes(
        (FORMAL_RUN_A_ROOT / "manifests" / execution_name).read_bytes()
    )

    with pytest.raises(
        RuntimeV2OrchestrationError,
        match="release supplement match count differs: expected=1 actual=0",
    ):
        module._protected_run_a_manifest_paths(tmp_path, protection)

    supplement_bytes = (FORMAL_RUN_A_ROOT / "manifests" / supplement_name).read_bytes()
    (manifests / supplement_name).write_bytes(supplement_bytes)
    duplicate_name = "duplicate-release-supplement.json"
    (manifests / duplicate_name).write_bytes(supplement_bytes)
    duplicate_protection = protection.model_copy(
        update={
            "protected_relative_paths": (
                *protection.protected_relative_paths,
                f"manifests/{duplicate_name}",
            )
        }
    )

    with pytest.raises(
        RuntimeV2OrchestrationError,
        match="release supplement match count differs: expected=1 actual=2",
    ):
        module._protected_run_a_manifest_paths(tmp_path, duplicate_protection)


def test_fixed_full_matrix_and_read_only_checks(
    authority_paths: tuple[dict[str, object], Path],
) -> None:
    common, root = authority_paths
    backend = FakeBackend()
    orchestrator = Stage2V2Orchestrator(backend)
    orchestrator.preflight(**common)  # type: ignore[arg-type]
    with pytest.raises(RuntimeV2OrchestrationError, match="complete Foundation"):
        orchestrator.run_group1(**common)  # type: ignore[arg-type]
    foundation = orchestrator.build_foundation(**common)  # type: ignore[arg-type]
    assert foundation.status == "FOUNDATION_COMPLETE"
    complete = orchestrator.run_group1(**common)  # type: ignore[arg-type]
    assert complete.status == "GROUP1_COMPLETE"
    assert backend.executed == list(FULL_TASK_MATRIX)
    assert not backend.released
    released = orchestrator.release(**common)  # type: ignore[arg-type]
    assert released == complete
    assert backend.released
    checkpoint_path = root / "runs" / RUN_ID / "checkpoint-v2.json"
    before = checkpoint_path.read_bytes()
    verification = orchestrator.verify(**common)  # type: ignore[arg-type]
    comparison = orchestrator.compare(**common)  # type: ignore[arg-type]
    assert verification.status == comparison.status == "PASS"
    assert checkpoint_path.read_bytes() == before


def test_compare_uses_write_probe_and_lock_without_requiring_build_space(
    authority_paths: tuple[dict[str, object], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, _root = authority_paths
    observed: list[dict[str, object]] = []

    def capture_external_root(*_args: object, **kwargs: object) -> None:
        observed.append(kwargs)

    monkeypatch.setattr(Stage2V2Orchestrator, "_assert_external_root", capture_external_root)
    orchestrator = Stage2V2Orchestrator(FakeBackend())
    orchestrator.preflight(**common)  # type: ignore[arg-type]
    orchestrator.build_foundation(**common)  # type: ignore[arg-type]
    orchestrator.run_group1(**common)  # type: ignore[arg-type]
    comparison = orchestrator.compare(**common)  # type: ignore[arg-type]

    assert comparison.status == "PASS"
    assert observed[-1]["write_probe"] is True
    assert observed[-1]["require_space"] is False


def test_interrupted_foundation_resumes_without_changing_completed_receipt(
    authority_paths: tuple[dict[str, object], Path],
) -> None:
    common, root = authority_paths
    backend = FakeBackend(interrupt_once=FOUNDATION_TASKS[1])
    orchestrator = Stage2V2Orchestrator(backend)
    orchestrator.preflight(**common)  # type: ignore[arg-type]
    with pytest.raises(InterruptedError, match="controlled"):
        orchestrator.build_foundation(**common)  # type: ignore[arg-type]
    store = CheckpointStore(root / "runs" / RUN_ID)
    interrupted = store.read()
    assert interrupted.status == "INTERRUPTED_RECOVERABLE"
    assert tuple(item.task_id for item in interrupted.completed_tasks) == FOUNDATION_TASKS[:1]
    first_receipt = (
        root / "runs" / RUN_ID / interrupted.completed_tasks[0].receipt_relative_path
    ).read_bytes()
    resumed = orchestrator.resume(**common)  # type: ignore[arg-type]
    assert resumed.status == "FOUNDATION_COMPLETE"
    assert (
        root / "runs" / RUN_ID / resumed.completed_tasks[0].receipt_relative_path
    ).read_bytes() == first_receipt
    assert backend.executed == [*FOUNDATION_TASKS, FOUNDATION_TASKS[1]]


def test_terminal_backend_failure_is_unpublished_and_not_resumable(
    authority_paths: tuple[dict[str, object], Path],
) -> None:
    common, root = authority_paths
    backend = FakeBackend(fail_on=FOUNDATION_TASKS[0])
    orchestrator = Stage2V2Orchestrator(backend)
    orchestrator.preflight(**common)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="controlled terminal"):
        orchestrator.build_foundation(**common)  # type: ignore[arg-type]
    failed = CheckpointStore(root / "runs" / RUN_ID).read()
    assert failed.status == "FAILED_INTEGRITY"
    assert failed.failure is not None
    assert (root / "runs" / RUN_ID / failed.failure.report_relative_path).is_file()
    with pytest.raises(RuntimeV2OrchestrationError, match="recoverable"):
        orchestrator.resume(**common)  # type: ignore[arg-type]
    assert not (root / "runs" / RUN_ID / "published" / "snapshots").exists()


def test_resource_pressure_is_checkpointed_and_resumable(
    authority_paths: tuple[dict[str, object], Path],
) -> None:
    common, root = authority_paths
    backend = FakeBackend(pause_on=FOUNDATION_TASKS[0])
    orchestrator = Stage2V2Orchestrator(backend)
    orchestrator.preflight(**common)  # type: ignore[arg-type]
    with pytest.raises(ResourcePause, match="controlled"):
        orchestrator.build_foundation(**common)  # type: ignore[arg-type]
    paused = CheckpointStore(root / "runs" / RUN_ID).read()
    assert paused.status == "PAUSED_RESOURCE_PRESSURE"
    assert paused.resource_pause is not None
    backend.pause_on = None
    resumed = orchestrator.resume(**common)  # type: ignore[arg-type]
    assert resumed.status == "FOUNDATION_COMPLETE"


def test_explicit_snapshot_or_manifest_drift_fails_before_mutation(
    authority_paths: tuple[dict[str, object], Path],
) -> None:
    common, root = authority_paths
    orchestrator = Stage2V2Orchestrator(FakeBackend())
    wrong_snapshot = {**common, "snapshot_id": H}
    with pytest.raises(ValueError, match="explicit snapshot_id"):
        orchestrator.preflight(**wrong_snapshot)  # type: ignore[arg-type]
    assert not (root / "runs" / RUN_ID).exists()
    orchestrator.preflight(**common)  # type: ignore[arg-type]
    manifest_path = Path(common["manifest_path"])
    original = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(f"  {original}", encoding="utf-8")
    with pytest.raises(RuntimeV2OrchestrationError, match="checkpoint authority differs"):
        orchestrator.build_foundation(**common)  # type: ignore[arg-type]


def test_checkpoint_compare_and_swap_rejects_a_stale_writer(
    authority_paths: tuple[dict[str, object], Path],
) -> None:
    common, root = authority_paths
    initial = Stage2V2Orchestrator(FakeBackend()).preflight(  # type: ignore[arg-type]
        **common
    )
    store = CheckpointStore(root / "runs" / RUN_ID)
    first = initial.advance(
        phase="FOUNDATION",
        status="IN_PROGRESS",
        active_task=FOUNDATION_TASKS[0],
    )
    second = initial.advance(
        phase="FOUNDATION",
        status="IN_PROGRESS",
        active_task=FOUNDATION_TASKS[0],
    )
    store.replace(first, expected_hash=initial.checkpoint_hash)
    with pytest.raises(CheckpointConflict, match="changed"):
        store.replace(second, expected_hash=initial.checkpoint_hash)


def test_checkpoint_v1_read_compatibility_excludes_absent_resource_pause(
    authority_paths: tuple[dict[str, object], Path],
) -> None:
    common, root = authority_paths
    initial = Stage2V2Orchestrator(FakeBackend()).preflight(  # type: ignore[arg-type]
        **common
    )
    legacy = initial.model_dump(mode="json", exclude={"checkpoint_hash", "resource_pause"})
    legacy["checkpoint_hash"] = initial.computed_legacy_v1_hash()
    checkpoint_path = root / "runs" / RUN_ID / "checkpoint-v2.json"
    checkpoint_path.write_text(json.dumps(legacy, sort_keys=True), encoding="utf-8")

    restored = CheckpointStore(checkpoint_path.parent).read()

    assert restored.checkpoint_hash == initial.computed_legacy_v1_hash()
    assert restored.resource_pause is None


def test_checkpoint_lock_is_released_by_kernel_after_sigkill(
    authority_paths: tuple[dict[str, object], Path],
) -> None:
    common, root = authority_paths
    initial = Stage2V2Orchestrator(FakeBackend()).preflight(  # type: ignore[arg-type]
        **common
    )
    store = CheckpointStore(root / "runs" / RUN_ID)
    ready = root / "child-lock-ready"
    script = (
        "import fcntl, os, pathlib, sys, time; "
        "lock=pathlib.Path(sys.argv[1]); ready=pathlib.Path(sys.argv[2]); "
        "fd=os.open(lock, os.O_RDWR|os.O_CREAT, 0o600); "
        "fcntl.flock(fd, fcntl.LOCK_EX); os.write(fd, b'crash-owner\\n'); os.fsync(fd); "
        "ready.write_text('ready'); time.sleep(300)"
    )
    child = subprocess.Popen([sys.executable, "-c", script, str(store.lock_path), str(ready)])
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.is_file()
        with pytest.raises(CheckpointConflict, match="writer is active"):
            store.replace(
                initial.advance(
                    phase="FOUNDATION",
                    status="IN_PROGRESS",
                    active_task=FOUNDATION_TASKS[0],
                ),
                expected_hash=initial.checkpoint_hash,
            )
        inode = store.lock_path.stat().st_ino
        os.kill(child.pid, signal.SIGKILL)
        child.wait(timeout=5)
        advanced = initial.advance(
            phase="FOUNDATION",
            status="IN_PROGRESS",
            active_task=FOUNDATION_TASKS[0],
        )
        store.replace(advanced, expected_hash=initial.checkpoint_hash)
        assert store.read() == advanced
        assert store.lock_path.stat().st_ino == inode
        assert store.lock_path.read_text(encoding="utf-8") == "crash-owner\n"
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_checkpoint_rejects_any_runtime_matrix_override(
    authority_paths: tuple[dict[str, object], Path],
) -> None:
    common, _ = authority_paths
    initial = Stage2V2Orchestrator(FakeBackend()).preflight(  # type: ignore[arg-type]
        **common
    )
    payload = initial.model_dump(mode="python", exclude={"checkpoint_hash"})
    payload["planned_tasks"] = (*FULL_TASK_MATRIX, "GROUP1:BTCUSDT:UNAPPROVED")
    with pytest.raises(ValueError, match="frozen full matrix"):
        RuntimeV2Checkpoint.seal(payload)


def test_keyboard_interrupt_is_recoverable_and_writes_user_stop(
    authority_paths: tuple[dict[str, object], Path],
) -> None:
    common, root = authority_paths
    orchestrator = Stage2V2Orchestrator(UserStopBackend())
    orchestrator.preflight(**common)  # type: ignore[arg-type]

    with pytest.raises(KeyboardInterrupt):
        orchestrator.build_foundation(**common)  # type: ignore[arg-type]

    run_root = root / "runs" / RUN_ID
    checkpoint = CheckpointStore(run_root).read()
    assert checkpoint.status == "INTERRUPTED_RECOVERABLE"
    assert checkpoint.failure is None
    reports = tuple((run_root / "reports").glob("user-stop-*.json"))
    assert len(reports) == 1
    payload = json.loads(reports[0].read_text(encoding="utf-8"))
    assert payload["checkpoint_before_hash"] != payload["checkpoint_after_hash"]
    assert payload["status"] == "INTERRUPTED_RECOVERABLE"


def test_group1_task_order_keeps_instrument_and_variant_isolated() -> None:
    assert GROUP1_TASKS == (
        "GROUP1:BTCUSDT:V1_PRICE",
        "GROUP1:BTCUSDT:V1_FLOW",
        "GROUP1:ETHUSDT:V1_PRICE",
        "GROUP1:ETHUSDT:V1_FLOW",
    )


def test_code_tree_hash_binds_transitive_group1_semantics(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    semantic = repo / "src" / "era100x" / "research" / "stage_2" / "episodes" / "sweep.py"
    cli = repo / "scripts" / "run_stage2_research.py"
    semantic.parent.mkdir(parents=True)
    cli.parent.mkdir(parents=True)
    semantic.write_text("def detect_sweep(): return 'v1'\n", encoding="utf-8")
    cli.write_text("# fixed cli\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)

    before = compute_v2_code_tree_sha256(repo)
    semantic.write_text("def detect_sweep(): return 'mutated'\n", encoding="utf-8")
    after = compute_v2_code_tree_sha256(repo)

    assert before != after
