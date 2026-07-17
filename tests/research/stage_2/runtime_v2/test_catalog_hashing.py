from __future__ import annotations

from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pytest

from era100x.research.stage_2.runtime_v2.catalog import (
    ArtifactStoreV2,
    CatalogComponentV2,
    CatalogCompactorV2,
    CatalogPublisherV2,
    CatalogReaderV2,
    PartitionBatch,
    SealReducerV2,
)
from era100x.research.stage_2.runtime_v2.errors import (
    CatalogIntegrityError,
    ContractViolation,
    SnapshotMismatch,
)
from era100x.research.stage_2.runtime_v2.hashing import (
    canonical_arrow_schema,
    canonical_semantic_hash,
    normalize_table,
)
from era100x.research.stage_2.runtime_v2.models import (
    ArrowFieldSpec,
    DatasetPlan,
    DatasetSpec,
    DigestBinding,
    LogicalPartitionKey,
    ManifestV2,
    QualityFact,
    Receipt,
)

H1 = "1" * 64
H2 = "2" * 64


def _field(
    name: str,
    data_type: str,
    *,
    nullable: bool = False,
    children: tuple[ArrowFieldSpec, ...] = (),
) -> ArrowFieldSpec:
    return ArrowFieldSpec(
        name=name,
        data_type=data_type,
        nullable=nullable,
        children=children,
    )


def _partition(spec: DatasetSpec, snapshot_id: str, owner_date: date) -> LogicalPartitionKey:
    return LogicalPartitionKey(
        snapshot_id=snapshot_id,
        dataset_name=spec.dataset_name,
        dataset_version=spec.dataset_version,
        dataset_spec_hash=spec.spec_hash,
        setup_id="KEY_LOW_SWEEP_RECLAIM_HOLD_V1",
        context_id="CAUSAL_EMA20_1H",
        instrument="BTCUSDT",
        variant="V1_PRICE",
        owner_date=owner_date,
    )


def _partition_only_spec(*, legacy: str = "NOT_APPLICABLE") -> DatasetSpec:
    return DatasetSpec.seal(
        {
            "dataset_name": "candidate_inclusions",
            "dataset_version": "2.0",
            "fields": (
                _field("canonical_candidate_id", "int64"),
                _field("research_role", "utf8"),
                _field("parameter_set_id", "utf8"),
                _field("payload", "utf8", nullable=True),
            ),
            "stable_sort_keys": ("canonical_candidate_id",),
            "identity_fields": ("canonical_candidate_id",),
            "payload_association_fields": (
                "canonical_candidate_id",
                "research_role",
                "parameter_set_id",
                "payload",
            ),
            "distribution_fields": ("parameter_set_id", "research_role"),
            "ownership_mode": "PARTITION_KEY_ONLY",
            "legacy_hash_algorithm": legacy,
        }
    )


def _empty_table(spec: DatasetSpec) -> pa.Table:
    schema = canonical_arrow_schema(spec)
    return pa.Table.from_arrays([pa.array([], type=item.type) for item in schema], schema=schema)


def test_cross_run_projection_excludes_snapshot_but_integrity_does_not() -> None:
    spec = _partition_only_spec()
    key_a = _partition(spec, H1, date(2020, 1, 1))
    key_b = _partition(spec, H2, date(2020, 1, 1))

    def receipt(key: LogicalPartitionKey) -> Receipt:
        return Receipt.seal(
            {
                "snapshot_id": key.snapshot_id,
                "shard_id": "btc-price-2020-01",
                "partition": key,
                "terminal_state": "EMPTY",
                "row_count": 0,
                "legacy_hash_algorithm": "NOT_APPLICABLE",
                "legacy_logical_sha256": None,
                "semantic_sha256": H1,
                "identity_multiset_sha256": H1,
                "payload_association_sha256": H1,
            }
        )

    receipt_a = receipt(key_a)
    receipt_b = receipt(key_b)
    assert key_a.partition_id != key_b.partition_id
    assert key_a.cross_run_partition_id == key_b.cross_run_partition_id
    assert receipt_a.receipt_hash != receipt_b.receipt_hash
    assert receipt_a.semantic_receipt_sha256 == receipt_b.semantic_receipt_sha256
    assert "snapshot_id" not in str(receipt_a.semantic_projection())

    seal_a = SealReducerV2.reduce(
        snapshot_id=H1,
        dataset_spec_hash=spec.spec_hash,
        shard_id="btc-price-2020-01",
        receipts=(receipt_a,),
    )
    seal_b = SealReducerV2.reduce(
        snapshot_id=H2,
        dataset_spec_hash=spec.spec_hash,
        shard_id="btc-price-2020-01",
        receipts=(receipt_b,),
    )
    assert seal_a.seal_hash != seal_b.seal_hash
    assert seal_a.v2_semantic_root_sha256 == seal_b.v2_semantic_root_sha256
    assert seal_a.legacy_semantic_root_sha256 is None


def test_nested_struct_and_large_list_hash_is_permutation_and_chunk_independent() -> None:
    tags = _field(
        "tags",
        "large_list",
        nullable=True,
        children=(_field("item", "utf8", nullable=True),),
    )
    metadata = _field(
        "metadata",
        "struct",
        nullable=True,
        children=(tags, _field("active", "bool", nullable=True)),
    )
    spec = DatasetSpec.seal(
        {
            "dataset_name": "nested_feature",
            "dataset_version": "2.0",
            "fields": (
                _field("id", "int64"),
                _field("available_at_ts", "int64"),
                metadata,
            ),
            "stable_sort_keys": ("id",),
            "identity_fields": ("id",),
            "payload_association_fields": ("id", "metadata"),
            "ownership_mode": "TIMESTAMP_NS_FIELD",
            "owner_timestamp_ns_field": "available_at_ts",
            "legacy_hash_algorithm": "NOT_APPLICABLE",
        }
    )
    schema = canonical_arrow_schema(spec)
    table = pa.Table.from_arrays(
        [
            pa.array([2, 1, 3], type=pa.int64()),
            pa.array(
                [1577923200000000002, 1577923200000000001, 1577923200000000003],
                type=pa.int64(),
            ),
            pa.array(
                [
                    {"tags": ["b", "c"], "active": True},
                    {"tags": ["a", None], "active": False},
                    None,
                ],
                type=schema.field("metadata").type,
            ),
        ],
        schema=schema,
    )
    reversed_table = pc.take(table, pa.array([2, 1, 0], type=pa.int64()))
    chunked = pa.concat_tables([reversed_table.slice(0, 1), reversed_table.slice(1)])
    assert canonical_semantic_hash(table, spec) == canonical_semantic_hash(chunked, spec)

    changed = table.set_column(
        2,
        schema.field("metadata"),
        pa.array(
            [
                {"tags": ["changed"], "active": True},
                {"tags": ["a", None], "active": False},
                None,
            ],
            type=schema.field("metadata").type,
        ),
    )
    assert canonical_semantic_hash(table, spec) != canonical_semantic_hash(changed, spec)


def test_multiset_preserves_multiplicity_but_requires_producer_validation(
    tmp_path: Path,
) -> None:
    spec = DatasetSpec.seal(
        {
            "dataset_name": "arbitration_multiset",
            "dataset_version": "2.0",
            "fields": (
                _field("id", "int64"),
                _field("version", "int64"),
                _field(
                    "members",
                    "large_list",
                    children=(_field("item", "utf8"),),
                ),
            ),
            "stable_sort_keys": ("id", "version"),
            "identity_fields": ("id",),
            "payload_association_fields": ("id", "version", "members"),
            "row_multiplicity": "MULTISET_STABLE",
            "ownership_mode": "PARTITION_KEY_ONLY",
            "legacy_hash_algorithm": "NOT_APPLICABLE",
        }
    )
    schema = canonical_arrow_schema(spec)
    first = pa.Table.from_pylist(
        [
            {"id": 1, "version": 2, "members": ["b"]},
            {"id": 1, "version": 1, "members": ["a"]},
            {"id": 1, "version": 1, "members": ["a"]},
        ],
        schema=schema,
    )
    reverse = pc.take(first, pa.array([2, 1, 0], type=pa.int64()))
    assert canonical_semantic_hash(first, spec) == canonical_semantic_hash(reverse, spec)
    assert normalize_table(first, spec).num_rows == 3

    key = _partition(spec, H1, date(2020, 1, 1))
    compactor = CatalogCompactorV2(ArtifactStoreV2(tmp_path))
    with pytest.raises(ContractViolation, match="producer-side stable multiset"):
        compactor.compact(
            spec=spec,
            snapshot_id=H1,
            shard_id="missing-multiset-proof",
            partitions=(
                PartitionBatch(
                    key=key,
                    table=first,
                    legacy_hash_algorithm="NOT_APPLICABLE",
                    legacy_logical_sha256=None,
                ),
            ),
        )

    result = compactor.compact(
        spec=spec,
        snapshot_id=H1,
        shard_id="validated-multiset",
        partitions=(
            PartitionBatch(
                key=key,
                table=first,
                legacy_hash_algorithm="NOT_APPLICABLE",
                legacy_logical_sha256=None,
                quality_facts=(QualityFact(name="stable_multiset_validated", value=True),),
            ),
        ),
    )
    assert result.receipts[0].row_count == 3

    manifest = ManifestV2.seal(
        {
            "snapshot_id": H1,
            "stage1_data_run_id": "stage1-baseline-v1",
            "stage1_authorities": (DigestBinding(name="stage1_manifest", sha256=H2),),
            "preregistration_manifest_sha256": H1,
            "config_sha256": H2,
            "code_tree_sha256": H1,
            "dataset_specs": (spec,),
            "dataset_plans": (
                DatasetPlan(
                    dataset_spec_hash=spec.spec_hash,
                    expected_partition_ids=(key.partition_id,),
                ),
            ),
            "invalidation_conditions": ("SOURCE_OR_SCHEMA_CHANGED",),
        }
    )
    CatalogPublisherV2(tmp_path).publish(
        manifest,
        artifacts=() if result.artifact is None else (result.artifact,),
        receipts=result.receipts,
        fragments=result.fragments,
        seals=(result.seal,),
    )
    reader = CatalogReaderV2.open(tmp_path, expected_snapshot_id=H1)
    assert reader.read_partition(key.partition_id).equals(normalize_table(first, spec))


def test_catalog_publish_rejects_same_size_artifact_tamper(tmp_path: Path) -> None:
    spec = _partition_only_spec()
    key = _partition(spec, H1, date(2020, 1, 1))
    schema = canonical_arrow_schema(spec)
    table = pa.Table.from_pylist(
        [
            {
                "canonical_candidate_id": 1,
                "research_role": "PRIMARY",
                "parameter_set_id": "PRIMARY",
                "payload": "sealed",
            }
        ],
        schema=schema,
    )
    result = CatalogCompactorV2(ArtifactStoreV2(tmp_path)).compact(
        spec=spec,
        snapshot_id=H1,
        shard_id="same-size-tamper",
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
    object_path = tmp_path / result.artifact.relative_path
    payload = bytearray(object_path.read_bytes())
    payload[len(payload) // 2] ^= 0x01
    object_path.write_bytes(payload)
    assert object_path.stat().st_size == result.artifact.byte_size

    manifest = ManifestV2.seal(
        {
            "snapshot_id": H1,
            "stage1_data_run_id": "stage1-baseline-v1",
            "stage1_authorities": (DigestBinding(name="stage1_manifest", sha256=H2),),
            "preregistration_manifest_sha256": H1,
            "config_sha256": H2,
            "code_tree_sha256": H1,
            "dataset_specs": (spec,),
            "dataset_plans": (
                DatasetPlan(
                    dataset_spec_hash=spec.spec_hash,
                    expected_partition_ids=(key.partition_id,),
                ),
            ),
            "invalidation_conditions": ("SOURCE_OR_SCHEMA_CHANGED",),
        }
    )
    with pytest.raises(CatalogIntegrityError, match="artifact byte hash mismatch"):
        CatalogPublisherV2(tmp_path).publish(
            manifest,
            artifacts=(result.artifact,),
            receipts=result.receipts,
            fragments=result.fragments,
            seals=(result.seal,),
        )


def test_catalog_component_publisher_streams_and_sorts_task_shards(tmp_path: Path) -> None:
    spec = _partition_only_spec()
    first = _partition(spec, H1, date(2020, 1, 1))
    keys = (
        first,
        LogicalPartitionKey(
            **{
                **first.model_dump(),
                "variant": "V1_FLOW",
                "owner_date": date(2020, 1, 2),
            }
        ),
    )
    store = ArtifactStoreV2(tmp_path)
    compactor = CatalogCompactorV2(store)
    components: list[CatalogComponentV2] = []
    for ordinal, key in enumerate(keys, start=1):
        table = pa.Table.from_pylist(
            [
                {
                    "canonical_candidate_id": ordinal,
                    "research_role": "PRIMARY",
                    "parameter_set_id": "PRIMARY",
                    "payload": f"component-{ordinal}",
                }
            ],
            schema=canonical_arrow_schema(spec),
        )
        result = compactor.compact(
            spec=spec,
            snapshot_id=H1,
            shard_id=f"component-{ordinal}",
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
        components.append(
            CatalogComponentV2(
                artifacts=(result.artifact,),
                receipts=result.receipts,
                fragments=result.fragments,
                seals=(result.seal,),
            )
        )
    manifest = ManifestV2.seal(
        {
            "snapshot_id": H1,
            "stage1_data_run_id": "stage1-baseline-v1",
            "stage1_authorities": (DigestBinding(name="stage1_manifest", sha256=H2),),
            "preregistration_manifest_sha256": H1,
            "config_sha256": H2,
            "code_tree_sha256": H1,
            "dataset_specs": (spec,),
            "dataset_plans": (
                DatasetPlan(
                    dataset_spec_hash=spec.spec_hash,
                    expected_partition_ids=tuple(sorted(key.partition_id for key in keys)),
                ),
            ),
            "invalidation_conditions": ("SOURCE_OR_SCHEMA_CHANGED",),
        }
    )

    catalog = CatalogPublisherV2(tmp_path).publish_components(
        manifest,
        components=reversed(components),
    )
    # Reversing producer order must reproduce the same append-only indexes.
    assert (
        CatalogPublisherV2(tmp_path).publish_components(manifest, components=components) == catalog
    )
    reader = CatalogReaderV2.open(tmp_path, expected_snapshot_id=H1)
    assert catalog.logical_partitions_index.row_count == 2
    assert catalog.fragments_index.row_count == 2
    assert set(reader.logical_index["partition_id"].to_pylist()) == {
        key.partition_id for key in keys
    }


def test_catalog_component_publisher_rejects_cross_shard_duplicates(tmp_path: Path) -> None:
    spec = _partition_only_spec()
    key = _partition(spec, H1, date(2020, 1, 1))
    result = CatalogCompactorV2(ArtifactStoreV2(tmp_path)).compact(
        spec=spec,
        snapshot_id=H1,
        shard_id="duplicate-component",
        partitions=(
            PartitionBatch(
                key=key,
                table=_empty_table(spec),
                legacy_hash_algorithm="NOT_APPLICABLE",
                legacy_logical_sha256=None,
            ),
        ),
    )
    manifest = ManifestV2.seal(
        {
            "snapshot_id": H1,
            "stage1_data_run_id": "stage1-baseline-v1",
            "stage1_authorities": (DigestBinding(name="stage1_manifest", sha256=H2),),
            "preregistration_manifest_sha256": H1,
            "config_sha256": H2,
            "code_tree_sha256": H1,
            "dataset_specs": (spec,),
            "dataset_plans": (
                DatasetPlan(
                    dataset_spec_hash=spec.spec_hash,
                    expected_partition_ids=(key.partition_id,),
                ),
            ),
            "invalidation_conditions": ("SOURCE_OR_SCHEMA_CHANGED",),
        }
    )
    component = CatalogComponentV2(
        artifacts=(),
        receipts=result.receipts,
        fragments=(),
        seals=(result.seal,),
    )
    with pytest.raises(CatalogIntegrityError, match="multiple components"):
        CatalogPublisherV2(tmp_path).publish_components(
            manifest,
            components=(component, component),
        )


def test_timestamp_owner_validation_and_legacy_requirement(tmp_path: Path) -> None:
    spec = DatasetSpec.seal(
        {
            "dataset_name": "timestamp_owned",
            "dataset_version": "2.0",
            "fields": (_field("id", "int64"), _field("available_at_ts", "int64")),
            "stable_sort_keys": ("id",),
            "identity_fields": ("id",),
            "payload_association_fields": ("id", "available_at_ts"),
            "ownership_mode": "TIMESTAMP_NS_FIELD",
            "owner_timestamp_ns_field": "available_at_ts",
            "legacy_hash_algorithm": "NOT_APPLICABLE",
        }
    )
    key = _partition(spec, H1, date(2020, 1, 2))
    schema = canonical_arrow_schema(spec)
    good = pa.Table.from_arrays([pa.array([1]), pa.array([1577923200000000000])], schema=schema)
    compactor = CatalogCompactorV2(ArtifactStoreV2(tmp_path / "timestamp"))
    compactor.compact(
        spec=spec,
        snapshot_id=H1,
        shard_id="timestamp-shard",
        partitions=(
            PartitionBatch(
                key=key,
                table=good,
                legacy_hash_algorithm="NOT_APPLICABLE",
                legacy_logical_sha256=None,
            ),
        ),
    )
    bad = pa.Table.from_arrays([pa.array([1]), pa.array([1578009600000000000])], schema=schema)
    with pytest.raises(ContractViolation, match="UTC owner date"):
        compactor.compact(
            spec=spec,
            snapshot_id=H1,
            shard_id="bad-timestamp-shard",
            partitions=(
                PartitionBatch(
                    key=key,
                    table=bad,
                    legacy_hash_algorithm="NOT_APPLICABLE",
                    legacy_logical_sha256=None,
                ),
            ),
        )

    legacy_spec = _partition_only_spec(legacy="ERA_CANONICAL_JSON_ROW_V1")
    with pytest.raises(ContractViolation, match="legacy logical hash"):
        CatalogCompactorV2(ArtifactStoreV2(tmp_path / "legacy")).compact(
            spec=legacy_spec,
            snapshot_id=H1,
            shard_id="legacy-shard",
            partitions=(
                PartitionBatch(
                    key=_partition(legacy_spec, H1, date(2020, 1, 1)),
                    table=_empty_table(legacy_spec),
                    legacy_hash_algorithm="ERA_CANONICAL_JSON_ROW_V1",
                    legacy_logical_sha256=None,
                ),
            ),
        )


def test_catalog_uses_three_merged_indexes_and_reads_empty_and_present_days(
    tmp_path: Path,
) -> None:
    root = tmp_path / "catalog"
    spec = _partition_only_spec()
    schema = canonical_arrow_schema(spec)
    present = pa.Table.from_arrays(
        [
            pa.array([2, 1]),
            pa.array(["EXPLORATORY", "PRIMARY"]),
            pa.array(["G1-P02", "G1-PRIMARY"]),
            pa.array(["second", "first"]),
        ],
        schema=schema,
    )
    keys = (
        _partition(spec, H1, date(2020, 1, 1)),
        _partition(spec, H1, date(2020, 1, 2)),
    )
    compacted = CatalogCompactorV2(ArtifactStoreV2(root)).compact(
        spec=spec,
        snapshot_id=H1,
        shard_id="btc-price-2020-01",
        partitions=(
            PartitionBatch(
                key=keys[0],
                table=present,
                legacy_hash_algorithm="NOT_APPLICABLE",
                legacy_logical_sha256=None,
            ),
            PartitionBatch(
                key=keys[1],
                table=_empty_table(spec),
                legacy_hash_algorithm="NOT_APPLICABLE",
                legacy_logical_sha256=None,
            ),
        ),
    )
    manifest = ManifestV2.seal(
        {
            "snapshot_id": H1,
            "stage1_data_run_id": "stage1-baseline-v1",
            "stage1_authorities": (DigestBinding(name="stage1_manifest", sha256=H2),),
            "preregistration_manifest_sha256": H1,
            "config_sha256": H2,
            "code_tree_sha256": H1,
            "dataset_specs": (spec,),
            "dataset_plans": (
                DatasetPlan(
                    dataset_spec_hash=spec.spec_hash,
                    expected_partition_ids=tuple(sorted(key.partition_id for key in keys)),
                ),
            ),
            "invalidation_conditions": ("SOURCE_OR_SCHEMA_CHANGED",),
        }
    )
    artifacts = () if compacted.artifact is None else (compacted.artifact,)
    catalog = CatalogPublisherV2(root).publish(
        manifest,
        artifacts=artifacts,
        receipts=compacted.receipts,
        fragments=compacted.fragments,
        seals=(compacted.seal,),
    )
    assert (root / "objects.parquet").is_file()
    assert (root / "logical_partitions.parquet").is_file()
    assert (root / "fragments.parquet").is_file()
    assert not (root / "logical_partitions").exists()
    assert not (root / "fragments").exists()
    assert catalog.logical_partitions_index.row_count == 2
    assert catalog.dataset_roots[0].legacy_hash_algorithm == "NOT_APPLICABLE"
    assert catalog.dataset_roots[0].legacy_semantic_root_sha256 is None

    reader = CatalogReaderV2.open(root, expected_snapshot_id=H1, deep_verify_objects=True)
    assert reader.read_partition(keys[0].partition_id).equals(normalize_table(present, spec))
    assert reader.read_partition(keys[1].partition_id).num_rows == 0
    with pytest.raises(SnapshotMismatch):
        CatalogReaderV2.open(root, expected_snapshot_id=H2)


def test_formal_runtime_avoids_row_dictionary_serialization() -> None:
    root = Path(__file__).parents[4] / "src" / "era100x" / "research" / "stage_2" / "runtime_v2"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    for forbidden in ("to_dicts", "iter_rows", "json" + ".dumps"):
        assert forbidden not in source
