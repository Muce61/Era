from __future__ import annotations

import hashlib
import inspect
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pytest

from era100x.research.stage_2.runtime_v2.catalog import (
    ArtifactStoreV2,
    CatalogCompactorV2,
    CatalogReaderV2,
    PartitionBatch,
    SealReducerV2,
)
from era100x.research.stage_2.runtime_v2.checkpoint import (
    FOUNDATION_TASKS,
    FULL_TASK_MATRIX,
    GROUP1_TASKS,
)
from era100x.research.stage_2.runtime_v2.compatibility import (
    CompatibilityDifference,
    CompatibilityMismatch,
    CompatibilityReport,
    LEGACY_HASH_ALGORITHM,
    PAYLOAD_AND_DISTRIBUTION_PROOF,
)
from era100x.research.stage_2.runtime_v2.hashing import canonical_arrow_schema
from era100x.research.stage_2.runtime_v2.manifest_factory import build_runtime_v2_manifest
from era100x.research.stage_2.runtime_v2.models import (
    ArrowFieldSpec,
    DatasetPlan,
    DatasetSpec,
    DigestBinding,
    LogicalPartitionKey,
    ManifestV2,
    Receipt,
)
from era100x.research.stage_2.runtime_v2.orchestrator import (
    FORMAL_GROUP1_PARTITION_COUNT,
    RuntimeV2Context,
)
from era100x.research.stage_2.runtime_v2.source_authority import (
    CONTRACT_PRICE_MANIFEST_AUTHORITY,
    TRADES_RESOLVED_INDEX_AUTHORITY,
)
from era100x.research.stage_2.runtime_v2.production_backend import (
    EvidenceFileBinding,
    PipelineTaskResult,
    ProductionBackendError,
    ProductionRuntimeV2Backend,
    TaskAggregateEvidence,
)
from era100x.research.stage_2.runtime_v2.resource_anomalies import (
    ResourceAnomalyReportV1,
    ResourceThresholdObservation,
)
from era100x.research.stage_2.pipelines.candidates.stage1_catalog import (
    Stage1TradesCatalogIndex,
    Stage1TradesPartition,
)
from era100x.research.stage_2.runtime_v2.foundation_sources import (
    ContractPriceInventoryIndex,
    ContractPricePartition,
)
from era100x.research.stage_2.runtime_v2.transition import (
    RunAPublishedSourceProtectionManifest,
    V2MigrationManifest,
    sha256_file,
)

H = "a" * 64
S = "b" * 64
C = "c" * 64
COMMIT = "d" * 40
RUN_ID = "stage2-g1-v2-b-production-test"


@dataclass(frozen=True)
class MatrixFixture:
    context: RuntimeV2Context
    keys: dict[str, LogicalPartitionKey]
    specs: dict[str, DatasetSpec]


def _fixture(tmp_path: Path, *, run_a_root: Path | None = None) -> MatrixFixture:
    run_root = tmp_path / "runs" / RUN_ID
    for name in ("staging/snapshot", "published", "reports", "manifests", "logs", "tmp"):
        (run_root / name).mkdir(parents=True, exist_ok=True)
    specs: dict[str, DatasetSpec] = {}
    keys: dict[str, LogicalPartitionKey] = {}
    plans: list[DatasetPlan] = []
    for ordinal, task_id in enumerate(FULL_TASK_MATRIX):
        group, instrument, *variant = task_id.split(":")
        dataset_name = f"fixture_{ordinal}"
        spec = DatasetSpec.seal(
            {
                "dataset_name": dataset_name,
                "dataset_version": "1.0",
                "fields": (ArrowFieldSpec(name="id", data_type="utf8"),),
                "stable_sort_keys": ("id",),
                "identity_fields": ("id",),
                "payload_association_fields": ("id",),
                "distribution_fields": (),
                "ownership_mode": "PARTITION_KEY_ONLY",
                "legacy_hash_algorithm": (
                    "NOT_APPLICABLE" if group == "FOUNDATION" else "ERA_CANONICAL_JSON_ROW_V1"
                ),
            }
        )
        key = LogicalPartitionKey(
            snapshot_id=S,
            dataset_name=dataset_name,
            dataset_version="1.0",
            dataset_spec_hash=spec.spec_hash,
            setup_id="FIXTURE_SETUP",
            context_id="FIXTURE_CONTEXT",
            instrument=instrument,
            variant=variant[0] if variant else f"FOUNDATION_{ordinal}",
            owner_date=date(2020, 1, 1),
        )
        specs[task_id] = spec
        keys[task_id] = key
        plans.append(
            DatasetPlan(
                dataset_spec_hash=spec.spec_hash,
                expected_partition_ids=(key.partition_id,),
            )
        )
    ordered_specs = tuple(sorted(specs.values(), key=lambda item: item.spec_hash))
    ordered_plans = tuple(sorted(plans, key=lambda item: item.dataset_spec_hash))
    manifest = ManifestV2.seal(
        {
            "snapshot_id": S,
            "stage1_data_run_id": ("stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682"),
            "stage1_authorities": tuple(
                sorted(
                    (
                        DigestBinding(name="stage1_manifest", sha256=H),
                        DigestBinding(name=CONTRACT_PRICE_MANIFEST_AUTHORITY, sha256=H),
                        DigestBinding(name=TRADES_RESOLVED_INDEX_AUTHORITY, sha256=S),
                    ),
                    key=lambda item: item.name,
                )
            ),
            "preregistration_manifest_sha256": H,
            "config_sha256": H,
            "code_tree_sha256": C,
            "dataset_specs": ordered_specs,
            "dataset_plans": ordered_plans,
            "invalidation_conditions": ("HASH_CHANGED",),
        }
    )
    if run_a_root is None:
        catalog_sha = H
        analysis_sha = H
    else:
        catalog_sha = sha256_file(run_a_root / "manifests" / "catalog.json")
        analysis_sha = sha256_file(run_a_root / "reports" / "release-analysis.json")
    protection = RunAPublishedSourceProtectionManifest.seal(
        {
            "schema_name": "stage2-run-a-source-protection-v1",
            "manifest_version": "1.0",
            "role": "IMMUTABLE_V2_MIGRATION_SOURCE",
            "source_run_id": "stage2-g1-full-a-20260716T144233Z-366a541b7956",
            "checkpoint_status": "PUBLISHED",
            "release_state": "PUBLISHED",
            "planned_count": 9508,
            "completed_count": 9508,
            "failed_count": 0,
            "catalog_entry_count": 61776,
            "execution_manifest_hash": H,
            "release_supplement_hash": H,
            "generator_commit": "e" * 40,
            "checkpoint_sha256": H,
            "catalog_sha256": catalog_sha,
            "catalog_logical_hash": H,
            "catalog_physical_hash": H,
            "quality_report_sha256": H,
            "count_summary_sha256": H,
            "release_analysis_sha256": analysis_sha,
            "preregistration_manifest_hash": H,
            "config_hash": H,
            "stage1_data_run_id": manifest.stage1_data_run_id,
            "stage1_logical_hashes": {"BTCUSDT": H, "ETHUSDT": H},
            "protected_relative_paths": (
                "manifests/catalog.json",
                "reports/release-analysis.json",
            ),
            "recorded_at": "2026-07-17T00:00:00+00:00",
        }
    )
    migration = V2MigrationManifest.seal(
        {
            "schema_name": "stage2-v2-migration-manifest-v1",
            "manifest_version": "1.0",
            "operation": "BUILD_V2_FOUNDATION_AND_RECONSTRUCT_GROUP1",
            "change_requests": ("CR-2026-007", "CR-2026-008"),
            "source_protection_manifest_hash": protection.manifest_hash,
            "source_run_id": protection.source_run_id,
            "destination_run_id": RUN_ID,
            "destination_root": str(run_root),
            "v2_code_commit": COMMIT,
            "v2_code_tree_hash": C,
            "catalog_schema_version": "2.0",
            "semantic_hash_algorithm": "era-canonical-binary-v2",
            "legacy_hash_algorithm": "era-canonical-json-row-v1",
            "snapshot_reader_mode": "EXPLICIT_SNAPSHOT_ID_ONLY",
            "source_delete_allowed": False,
            "run_a_artifact_reuse_allowed": False,
            "same_volume_atomic_publish": True,
            "contract_price_inventory_manifest_path": str(tmp_path / "prices.json"),
            "contract_price_inventory_manifest_hash": H,
            "contract_price_inventory_source_sha256": H,
            "stage1_resolved_source_index_path": str(tmp_path / "trades.json"),
            "stage1_resolved_source_index_manifest_hash": S,
            "stage1_resolved_source_index_source_sha256": S,
            "recorded_at": "2026-07-17T00:00:00+00:00",
        }
    )
    return MatrixFixture(
        context=RuntimeV2Context(
            run_id=RUN_ID,
            run_root=run_root,
            manifest=manifest,
            protection=protection,
            migration=migration,
        ),
        keys=keys,
        specs=specs,
    )


def _empty_result(fixture: MatrixFixture, task_id: str) -> PipelineTaskResult:
    key = fixture.keys[task_id]
    legacy = "NOT_APPLICABLE" if task_id in FOUNDATION_TASKS else "ERA_CANONICAL_JSON_ROW_V1"
    receipt = Receipt.seal(
        {
            "snapshot_id": S,
            "shard_id": f"fixture-shard-{FULL_TASK_MATRIX.index(task_id)}",
            "partition": key,
            "terminal_state": "EMPTY",
            "row_count": 0,
            "legacy_hash_algorithm": legacy,
            "legacy_logical_sha256": None if legacy == "NOT_APPLICABLE" else H,
            "semantic_sha256": H,
            "identity_multiset_sha256": H,
            "payload_association_sha256": H,
            "fragment_hashes": (),
        }
    )
    seal = SealReducerV2.reduce(
        snapshot_id=S,
        dataset_spec_hash=key.dataset_spec_hash,
        shard_id=receipt.shard_id,
        receipts=(receipt,),
    )
    return PipelineTaskResult(artifacts=(), receipts=(receipt,), fragments=(), seals=(seal,))


def _present_result(fixture: MatrixFixture, task_id: str) -> PipelineTaskResult:
    spec = fixture.specs[task_id]
    key = fixture.keys[task_id]
    table = pa.Table.from_pylist([{"id": "one"}], schema=canonical_arrow_schema(spec))
    compactor = CatalogCompactorV2(
        ArtifactStoreV2(fixture.context.run_root / "staging" / "snapshot")
    )
    result = compactor.compact(
        spec=spec,
        snapshot_id=S,
        shard_id="fixture-present-shard",
        partitions=(
            PartitionBatch(
                key=key,
                table=table,
                legacy_hash_algorithm="NOT_APPLICABLE",
                legacy_logical_sha256=None,
            ),
        ),
    )
    assert result.artifact is not None
    return PipelineTaskResult(
        artifacts=(result.artifact,),
        receipts=result.receipts,
        fragments=result.fragments,
        seals=(result.seal,),
    )


def _generic_builder(
    fixture: MatrixFixture,
    *,
    present_task: str | None = None,
):
    def build(context: RuntimeV2Context, task_id: str) -> PipelineTaskResult:
        assert context == fixture.context
        if task_id == present_task:
            return _present_result(fixture, task_id)
        return _empty_result(fixture, task_id)

    return build


def _run_all(
    backend: ProductionRuntimeV2Backend,
    fixture: MatrixFixture,
) -> list[object]:
    receipts = [backend.execute_task(fixture.context, task_id) for task_id in FULL_TASK_MATRIX]
    backend.release_run(fixture.context)
    return receipts


def test_fixed_task_order_and_merged_catalog_publication(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    backend = ProductionRuntimeV2Backend(
        task_builder=_generic_builder(fixture), peak_rss_reader=lambda: 1
    )
    with pytest.raises(ProductionBackendError, match="task order violation"):
        backend.execute_task(fixture.context, FOUNDATION_TASKS[1])

    receipts = _run_all(backend, fixture)
    published = fixture.context.run_root / "published" / "snapshots" / S
    reader = CatalogReaderV2.open(published, expected_snapshot_id=S)
    assert reader.logical_index.num_rows == len(FULL_TASK_MATRIX)
    assert not (fixture.context.run_root / "staging" / "snapshot").exists()
    for receipt in receipts:
        backend.verify_completed_task(fixture.context, receipt)  # type: ignore[arg-type]
    verification = backend.verify_run(fixture.context)
    assert verification.publication_state == "PUBLISHED"
    assert verification.checked_task_count == 6


def test_group1_full_aggregate_is_built_once_then_sliced(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    calls = 0

    def foundation(context: RuntimeV2Context, instrument: str) -> PipelineTaskResult:
        task = f"FOUNDATION:{instrument}"
        return _empty_result(fixture, task)

    def group1(context: RuntimeV2Context) -> PipelineTaskResult:
        nonlocal calls
        calls += 1
        parts = [_empty_result(fixture, task) for task in GROUP1_TASKS]
        return PipelineTaskResult(
            artifacts=(),
            receipts=tuple(item.receipts[0] for item in parts),
            fragments=(),
            seals=tuple(item.seals[0] for item in parts),
            global_distributions={
                "ownership_status": {"OWNER": 4},
                "research_role": {"PRIMARY": 4},
                "time_combination_id": {"T2": 4},
                "parameter_set_id": {"PRIMARY": 4},
                "reason_code": {"INCLUDED": 4},
            },
        )

    backend = ProductionRuntimeV2Backend(
        foundation_task_builder=foundation,  # type: ignore[arg-type]
        group1_aggregate_builder=group1,
        peak_rss_reader=lambda: 1,
    )
    _run_all(backend, fixture)

    assert calls == 1
    aggregate = fixture.context.run_root / "staging" / "group1" / "production-aggregate.json"
    assert aggregate.is_file()


def test_group1_loader_validates_but_does_not_parse_resource_anomaly_as_checkpoint(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    for task_id in FOUNDATION_TASKS:
        safe = task_id.lower().replace(":", "-")
        report = ResourceAnomalyReportV1.seal(
            run_id=fixture.context.run_id,
            task_id=task_id,
            snapshot_id=fixture.context.manifest.snapshot_id,
            manifest_hash=fixture.context.manifest.manifest_hash,
            config_sha256=fixture.context.manifest.config_sha256,
            code_tree_sha256=fixture.context.manifest.code_tree_sha256,
            observations=(
                ResourceThresholdObservation(
                    category="OBJECT_COUNT",
                    phase="Foundation seal",
                    metric_name="TASK_OBJECT_COUNT",
                    unit="objects",
                    threshold=1,
                    observed=2,
                    observed_at_ns=1,
                ),
            ),
        )
        relative = f"staging/evidence/resource-anomalies/{safe}.json"
        report_path = fixture.context.run_root / relative
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report.model_dump_json(), encoding="utf-8")
        evidence = TaskAggregateEvidence.seal(
            {
                "task_id": task_id,
                "snapshot_id": fixture.context.manifest.snapshot_id,
                "manifest_hash": fixture.context.manifest.manifest_hash,
                "artifacts": (),
                "receipts": (),
                "fragments": (),
                "seals": (),
                "supporting_evidence": (
                    EvidenceFileBinding(
                        relative_path=relative,
                        physical_sha256=sha256_file(report_path),
                    ),
                ),
                "max_inflight_bytes_observed": 2,
                "peak_process_rss_bytes": 2,
                "resource_anomaly_count": 1,
            }
        )
        evidence_path = fixture.context.run_root / "staging/backend-evidence" / f"{safe}.json"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(evidence.model_dump_json(), encoding="utf-8")

    backend = ProductionRuntimeV2Backend(peak_rss_reader=lambda: 1)

    assert backend._load_foundation_checkpoints(fixture.context) == ()


def test_same_size_object_tamper_blocks_catalog_seal(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    backend = ProductionRuntimeV2Backend(
        task_builder=_generic_builder(fixture, present_task=FOUNDATION_TASKS[0]),
        peak_rss_reader=lambda: 1,
    )
    for task_id in FULL_TASK_MATRIX[:-1]:
        backend.execute_task(fixture.context, task_id)
    objects = tuple(
        (fixture.context.run_root / "staging" / "snapshot" / "objects").rglob("*.parquet")
    )
    assert len(objects) == 1
    original = objects[0].read_bytes()
    objects[0].write_bytes(bytes([original[0] ^ 1]) + original[1:])
    assert objects[0].stat().st_size == len(original)

    backend.execute_task(fixture.context, FULL_TASK_MATRIX[-1])
    with pytest.raises(ProductionBackendError, match="byte hash differs"):
        backend.release_run(fixture.context)
    assert not (fixture.context.run_root / "published" / "snapshots" / S).exists()


def test_crash_after_atomic_rename_resumes_without_rebuild(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    calls: list[str] = []

    def builder(context: RuntimeV2Context, task_id: str) -> PipelineTaskResult:
        calls.append(task_id)
        return _empty_result(fixture, task_id)

    def crash(phase: str) -> None:
        assert phase == "AFTER_DATA_RENAMED"
        raise OSError("controlled crash after rename")

    interrupted = ProductionRuntimeV2Backend(
        task_builder=builder,
        peak_rss_reader=lambda: 1,
        publication_fault=crash,
    )
    for task_id in FULL_TASK_MATRIX:
        interrupted.execute_task(fixture.context, task_id)
    with pytest.raises(InterruptedError, match="after DATA_RENAMED"):
        interrupted.release_run(fixture.context)
    published = fixture.context.run_root / "published" / "snapshots" / S
    assert published.is_dir()
    assert not (fixture.context.run_root / "reports" / "v2-publication-record.json").exists()

    resumed = ProductionRuntimeV2Backend(
        task_builder=builder,
        peak_rss_reader=lambda: 1,
    )
    resumed.release_run(fixture.context)
    assert calls == list(FULL_TASK_MATRIX)
    assert (fixture.context.run_root / "reports" / "v2-publication-record.json").is_file()
    assert (
        fixture.context.run_root / "reports" / "publication-journal" / "03-published.json"
    ).is_file()


def test_compare_mismatch_is_append_only_and_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_a_root = tmp_path / "run-a"
    (run_a_root / "manifests").mkdir(parents=True)
    (run_a_root / "reports").mkdir(parents=True)
    (run_a_root / "manifests" / "catalog.json").write_text("{}", encoding="utf-8")
    (run_a_root / "reports" / "release-analysis.json").write_text("{}", encoding="utf-8")
    fixture = _fixture(tmp_path, run_a_root=run_a_root)
    backend = ProductionRuntimeV2Backend(
        task_builder=_generic_builder(fixture),
        run_a_root=run_a_root,
        peak_rss_reader=lambda: 1,
    )
    _run_all(backend, fixture)
    mismatch = CompatibilityReport(
        status="FAIL",
        payload_and_distribution_proof=PAYLOAD_AND_DISTRIBUTION_PROOF,
        run_a_partition_count=FORMAL_GROUP1_PARTITION_COUNT,
        v2_partition_count=FORMAL_GROUP1_PARTITION_COUNT,
        matched_partition_count=FORMAL_GROUP1_PARTITION_COUNT,
        daily_row_hash_match_count=FORMAL_GROUP1_PARTITION_COUNT - 1,
        daily_id_set_checked_count=0,
        global_distributions_equal=True,
        missing_in_v2=(),
        extra_in_v2=(),
        differences=(
            CompatibilityDifference(
                key=None,
                field="legacy_logical_sha256",
                run_a_value=H,
                v2_value=S,
            ),
        ),
    )
    monkeypatch.setattr(
        "era100x.research.stage_2.runtime_v2.production_backend.project_formal_run_a",
        lambda *args, **kwargs: object(),
    )

    def compare_with_authority(*args: object, **kwargs: object) -> CompatibilityReport:
        assert kwargs["v2_legacy_hash_algorithm"] == LEGACY_HASH_ALGORITHM
        return mismatch

    monkeypatch.setattr(
        "era100x.research.stage_2.runtime_v2.production_backend.compare_run_a_to_v2_sorted_stream",
        compare_with_authority,
    )

    with pytest.raises(CompatibilityMismatch):
        backend.compare_run_a(fixture.context)
    report = fixture.context.run_root / "reports" / "v2-run-a-comparison.json"
    first_hash = hashlib.sha256(report.read_bytes()).hexdigest()
    with pytest.raises(CompatibilityMismatch):
        backend.compare_run_a(fixture.context)
    assert hashlib.sha256(report.read_bytes()).hexdigest() == first_hash


def test_production_backend_has_no_dynamic_import_or_source_discovery() -> None:
    source = inspect.getsource(ProductionRuntimeV2Backend)
    for forbidden in ("importlib", ".glob(", ".rglob(", "requests", "socket"):
        assert forbidden not in source


def test_production_preflight_validates_formal_capacity_without_writing(tmp_path: Path) -> None:
    run_a_root = tmp_path / "run-a"
    (run_a_root / "manifests").mkdir(parents=True)
    (run_a_root / "reports").mkdir(parents=True)
    catalog_path = run_a_root / "manifests" / "catalog.json"
    analysis_path = run_a_root / "reports" / "release-analysis.json"
    catalog_path.write_text("{}", encoding="utf-8")
    analysis_path.write_text("{}", encoding="utf-8")
    manifest = build_runtime_v2_manifest(
        stage1_data_run_id="stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682",
        stage1_authorities=(
            DigestBinding(name="stage1_manifest", sha256=H),
            DigestBinding(name=CONTRACT_PRICE_MANIFEST_AUTHORITY, sha256=H),
            DigestBinding(name=TRADES_RESOLVED_INDEX_AUTHORITY, sha256=S),
        ),
        preregistration_manifest_sha256=H,
        config_sha256=H,
        code_tree_sha256=C,
    )
    protection = RunAPublishedSourceProtectionManifest.seal(
        {
            "schema_name": "stage2-run-a-source-protection-v1",
            "manifest_version": "1.0",
            "role": "IMMUTABLE_V2_MIGRATION_SOURCE",
            "source_run_id": "stage2-g1-full-a-20260716T144233Z-366a541b7956",
            "checkpoint_status": "PUBLISHED",
            "release_state": "PUBLISHED",
            "planned_count": 9508,
            "completed_count": 9508,
            "failed_count": 0,
            "catalog_entry_count": 61776,
            "execution_manifest_hash": H,
            "release_supplement_hash": H,
            "generator_commit": "e" * 40,
            "checkpoint_sha256": H,
            "catalog_sha256": sha256_file(catalog_path),
            "catalog_logical_hash": H,
            "catalog_physical_hash": H,
            "quality_report_sha256": H,
            "count_summary_sha256": H,
            "release_analysis_sha256": sha256_file(analysis_path),
            "preregistration_manifest_hash": H,
            "config_hash": H,
            "stage1_data_run_id": manifest.stage1_data_run_id,
            "stage1_logical_hashes": {"BTCUSDT": H, "ETHUSDT": H},
            "protected_relative_paths": (
                "manifests/catalog.json",
                "reports/release-analysis.json",
            ),
            "recorded_at": "2026-07-17T00:00:00+00:00",
        }
    )
    run_root = tmp_path / "not-created" / RUN_ID
    migration = V2MigrationManifest.seal(
        {
            "schema_name": "stage2-v2-migration-manifest-v1",
            "manifest_version": "1.0",
            "operation": "BUILD_V2_FOUNDATION_AND_RECONSTRUCT_GROUP1",
            "change_requests": ("CR-2026-007", "CR-2026-008"),
            "source_protection_manifest_hash": protection.manifest_hash,
            "source_run_id": protection.source_run_id,
            "destination_run_id": RUN_ID,
            "destination_root": str(run_root),
            "v2_code_commit": COMMIT,
            "v2_code_tree_hash": C,
            "catalog_schema_version": "2.0",
            "semantic_hash_algorithm": "era-canonical-binary-v2",
            "legacy_hash_algorithm": "era-canonical-json-row-v1",
            "snapshot_reader_mode": "EXPLICIT_SNAPSHOT_ID_ONLY",
            "source_delete_allowed": False,
            "run_a_artifact_reuse_allowed": False,
            "same_volume_atomic_publish": True,
            "contract_price_inventory_manifest_path": str(tmp_path / "prices.json"),
            "contract_price_inventory_manifest_hash": H,
            "contract_price_inventory_source_sha256": H,
            "stage1_resolved_source_index_path": str(tmp_path / "trades.json"),
            "stage1_resolved_source_index_manifest_hash": S,
            "stage1_resolved_source_index_source_sha256": S,
            "recorded_at": "2026-07-17T00:00:00+00:00",
        }
    )
    published = tmp_path / "stage1-published"
    contract_root = tmp_path / "contract"
    trade_path = published / "shared.parquet"
    price_path = contract_root / "shared.csv"
    start = date(2020, 1, 1)
    end = date(2026, 7, 4)
    trades = []
    prices = []
    current = start
    while current < end:
        for instrument in ("BTCUSDT", "ETHUSDT"):
            trades.append(
                Stage1TradesPartition(
                    instrument=instrument,
                    partition_date=current,
                    archive_partition=current.strftime("%Y-%m"),
                    path=trade_path,
                    byte_sha256=H,
                    logical_sha256=H,
                )
            )
            prices.append(
                ContractPricePartition(
                    instrument=instrument,
                    partition_date=current,
                    path=price_path,
                    source_format="CSV",
                    byte_size=1,
                    byte_sha256=H,
                )
            )
        current += timedelta(days=1)
    indexes = (
        Stage1TradesCatalogIndex(published_root=published, partitions=tuple(trades)),
        ContractPriceInventoryIndex(
            root=contract_root,
            partitions=tuple(prices),
            inventory_hash=H,
            inventory_file_count=4774,
        ),
    )
    context = RuntimeV2Context(
        run_id=RUN_ID,
        run_root=run_root,
        manifest=manifest,
        protection=protection,
        migration=migration,
    )
    source_load_calls = 0

    def load_indexes(_context: RuntimeV2Context):  # type: ignore[no-untyped-def]
        nonlocal source_load_calls
        source_load_calls += 1
        return indexes

    backend = ProductionRuntimeV2Backend(
        source_index_loader=load_indexes,
        run_a_root=run_a_root,
        peak_rss_reader=lambda: 1,
    )

    backend.validate_preflight(context)
    assert backend._load_source_indexes(context) is indexes

    assert not run_root.exists()
    assert source_load_calls == 1
