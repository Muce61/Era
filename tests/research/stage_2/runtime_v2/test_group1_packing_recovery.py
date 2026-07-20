from __future__ import annotations

from datetime import date
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from era100x.research.stage_2.runtime_v2.catalog import SealReducerV2
from era100x.research.stage_2.runtime_v2.group1_packing_recovery import (
    AdoptedFileV1,
    EXPECTED_FOUNDATION_CHECKPOINTS,
    EXPECTED_FOUNDATION_MONTHLY_CHECKPOINTS,
    EXPECTED_FOUNDATION_PACKED_CHECKPOINTS,
    _record_adopted,
    _resign_graph,
)
from era100x.research.stage_2.runtime_v2.models import (
    ArtifactRef,
    FragmentV2,
    LogicalPartitionKey,
    Receipt,
)
from era100x.research.stage_2.runtime_v2.transition import sha256_file

SOURCE_SNAPSHOT = "1" * 64
DESTINATION_SNAPSHOT = "2" * 64
DATASET_HASH = "3" * 64
SEMANTIC_HASH = "4" * 64


def test_foundation_recovery_coverage_includes_monthly_and_packed_checkpoints() -> None:
    assert EXPECTED_FOUNDATION_MONTHLY_CHECKPOINTS == 632
    assert EXPECTED_FOUNDATION_PACKED_CHECKPOINTS == 164
    assert EXPECTED_FOUNDATION_CHECKPOINTS == 796


def test_resign_graph_preserves_physical_and_semantic_evidence(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_catalog = source_root / "catalog"
    destination_catalog = destination_root / "catalog"
    temporary_object = source_catalog / "object.parquet"
    temporary_object.parent.mkdir(parents=True)
    pq.write_table(pa.table({"value": [1]}), temporary_object)
    object_hash = sha256_file(temporary_object)
    source_object = source_catalog / "objects" / object_hash[:2] / f"{object_hash}.parquet"
    source_object.parent.mkdir(parents=True)
    temporary_object.replace(source_object)
    artifact = ArtifactRef(
        snapshot_id=SOURCE_SNAPSHOT,
        dataset_spec_hash=DATASET_HASH,
        object_sha256=object_hash,
        relative_path=f"objects/{object_hash[:2]}/{object_hash}.parquet",
        byte_size=source_object.stat().st_size,
        row_count=1,
        semantic_sha256=SEMANTIC_HASH,
    )
    partition = LogicalPartitionKey(
        snapshot_id=SOURCE_SNAPSHOT,
        dataset_name="test_dataset",
        dataset_version="2.0",
        dataset_spec_hash=DATASET_HASH,
        setup_id="SETUP",
        context_id="CONTEXT",
        instrument="BTCUSDT",
        variant="V1_PRICE",
        owner_date=date(2020, 1, 1),
    )
    fragment = FragmentV2.seal(
        {
            "snapshot_id": SOURCE_SNAPSHOT,
            "dataset_spec_hash": DATASET_HASH,
            "partition_id": partition.partition_id,
            "artifact": artifact,
            "fragment_ordinal": 0,
            "row_offset": 0,
            "row_count": 1,
            "semantic_sha256": SEMANTIC_HASH,
        }
    )
    receipt = Receipt.seal(
        {
            "snapshot_id": SOURCE_SNAPSHOT,
            "shard_id": "test-shard",
            "partition": partition,
            "terminal_state": "PRESENT",
            "row_count": 1,
            "legacy_hash_algorithm": "NOT_APPLICABLE",
            "semantic_sha256": SEMANTIC_HASH,
            "identity_multiset_sha256": SEMANTIC_HASH,
            "payload_association_sha256": SEMANTIC_HASH,
            "fragment_hashes": (fragment.fragment_hash,),
        }
    )
    source_seal = source_root / "seal.json"
    source_seal.write_text("sealed-source", encoding="utf-8")
    original_seal = SealReducerV2.reduce(
        snapshot_id=SOURCE_SNAPSHOT,
        dataset_spec_hash=DATASET_HASH,
        shard_id="test-shard",
        receipts=(receipt,),
    )

    new_artifact, new_receipts, new_fragments, new_seal, object_entry = _resign_graph(
        source_root=source_root,
        destination_root=destination_root,
        source_object_root=source_catalog,
        destination_object_root=destination_catalog,
        artifact=artifact,
        receipts=(receipt,),
        fragments=(fragment,),
        source_seal_path=source_seal,
        source_seal_file_sha256=sha256_file(source_seal),
        source_shard_id="test-shard",
        dataset_spec_hash=DATASET_HASH,
        destination_snapshot_id=DESTINATION_SNAPSHOT,
        object_category="FOUNDATION_OBJECT",
    )

    assert new_artifact is not None
    assert new_artifact.snapshot_id == DESTINATION_SNAPSHOT
    assert new_artifact.object_sha256 == artifact.object_sha256
    assert new_receipts[0].semantic_receipt_sha256 == receipt.semantic_receipt_sha256
    assert new_receipts[0].receipt_hash != receipt.receipt_hash
    assert new_fragments[0].fragment_hash != fragment.fragment_hash
    assert new_fragments[0].partition_id == new_receipts[0].partition.partition_id
    assert new_receipts[0].fragment_hashes == (new_fragments[0].fragment_hash,)
    assert new_seal.v2_semantic_root_sha256 == original_seal.v2_semantic_root_sha256
    assert object_entry is not None
    assert sha256_file(destination_catalog / artifact.relative_path) == object_hash


def test_record_adopted_deduplicates_identical_paths_and_rejects_conflicts() -> None:
    first = AdoptedFileV1(
        relative_path="objects/a.parquet",
        physical_sha256="a" * 64,
        byte_size=1,
        category="FOUNDATION_OBJECT",
    )
    adopted: dict[str, AdoptedFileV1] = {}

    _record_adopted(adopted, (first, first))
    assert adopted == {first.relative_path: first}

    conflicting = first.model_copy(update={"byte_size": 2})
    with pytest.raises(ValueError, match="conflicting evidence"):
        _record_adopted(adopted, (conflicting,))
