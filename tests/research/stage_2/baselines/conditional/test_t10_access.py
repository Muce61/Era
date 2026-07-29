from __future__ import annotations

from datetime import date
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from era100x.research.stage_2.baselines.conditional.t10_access import FixedT10Reader
from era100x.research.stage_2.runtime_v2.models import (
    ArtifactRef,
    FragmentV2,
    LogicalPartitionKey,
    Receipt,
)

HASH = "a" * 64


def _fixture(root: Path) -> tuple[Path, str]:
    snapshot_id = "b" * 64
    object_path = root / "objects/aa/source.parquet"
    object_path.parent.mkdir(parents=True)
    table = pa.table({"instrument": ["BTCUSDT"] * 6, "value": list(range(6))})
    pq.write_table(table, object_path, row_group_size=2)
    import hashlib

    object_hash = hashlib.sha256(object_path.read_bytes()).hexdigest()
    relative = f"objects/{object_hash[:2]}/{object_hash}.parquet"
    final_path = root / relative
    final_path.parent.mkdir(parents=True, exist_ok=True)
    object_path.replace(final_path)
    artifact = ArtifactRef(
        snapshot_id=snapshot_id,
        dataset_spec_hash=HASH,
        relative_path=relative,
        media_type="application/vnd.apache.parquet",
        byte_size=final_path.stat().st_size,
        row_count=6,
        object_sha256=object_hash,
        semantic_sha256="c" * 64,
    )
    partition = LogicalPartitionKey(
        dataset_name="sample",
        dataset_version="1.0",
        dataset_spec_hash=HASH,
        setup_id="SETUP",
        context_id="CONTEXT",
        instrument="BTCUSDT",
        variant="FOUNDATION",
        owner_date=date(2024, 1, 1),
        snapshot_id=snapshot_id,
    )
    fragment = FragmentV2.seal(
        {
            "snapshot_id": snapshot_id,
            "dataset_spec_hash": HASH,
            "partition_id": partition.partition_id,
            "artifact": artifact,
            "fragment_ordinal": 0,
            "row_offset": 1,
            "row_count": 4,
            "semantic_sha256": "d" * 64,
        }
    )
    receipt = Receipt.seal(
        {
            "snapshot_id": snapshot_id,
            "partition": partition,
            "shard_id": "fixture",
            "terminal_state": "PRESENT",
            "row_count": 4,
            "legacy_hash_algorithm": "NOT_APPLICABLE",
            "legacy_logical_sha256": None,
            "semantic_sha256": "d" * 64,
            "identity_multiset_sha256": "e" * 64,
            "payload_association_sha256": "f" * 64,
            "fragment_hashes": (fragment.fragment_hash,),
            "quality_status": "PASS",
        }
    )
    pq.write_table(
        pa.table({"payload": [artifact.model_dump_json().encode()]}), root / "objects.parquet"
    )
    pq.write_table(
        pa.table({"payload": [fragment.model_dump_json().encode()]}), root / "fragments.parquet"
    )
    pq.write_table(
        pa.table(
            {
                "partition_id": [partition.partition_id],
                "payload": [receipt.model_dump_json().encode()],
            }
        ),
        root / "logical_partitions.parquet",
    )
    return root, snapshot_id


def test_fragment_aware_reader_reads_only_exact_logical_slice(tmp_path: Path) -> None:
    root, snapshot_id = _fixture(tmp_path)
    reader = FixedT10Reader(root, expected_snapshot_id=snapshot_id)
    table = reader.read(
        dataset_name="sample",
        dataset_version="1.0",
        instrument="BTCUSDT",
        variant="FOUNDATION",
        owner_date=date(2024, 1, 1),
        columns=["value"],
    )
    assert table["value"].to_pylist() == [1, 2, 3, 4]
    assert reader.inventory_binding() == {
        "snapshot_id": snapshot_id,
        "object_count": 1,
        "fragment_count": 1,
        "logical_partition_count": 1,
    }
    assert (
        reader.constant_partition_column_value(
            dataset_name="sample",
            dataset_version="1.0",
            instrument="BTCUSDT",
            variant="FOUNDATION",
            owner_date=date(2024, 1, 1),
            column="instrument",
        )
        == "BTCUSDT"
    )
    with pytest.raises(ValueError, match="not provably constant"):
        reader.constant_partition_column_value(
            dataset_name="sample",
            dataset_version="1.0",
            instrument="BTCUSDT",
            variant="FOUNDATION",
            owner_date=date(2024, 1, 1),
            column="value",
        )


def test_physical_dataset_requires_complete_object_tiling(tmp_path: Path) -> None:
    root, snapshot_id = _fixture(tmp_path)
    reader = FixedT10Reader(root, expected_snapshot_id=snapshot_id)
    with pytest.raises(ValueError, match="do not tile"):
        reader.read_physical_dataset(
            dataset_name="sample",
            dataset_version="1.0",
            instrument="BTCUSDT",
            variant="FOUNDATION",
            columns=["value"],
        )


def test_reader_rejects_symlinked_snapshot(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(ValueError, match="unsafe or missing T10 snapshot"):
        FixedT10Reader(link, expected_snapshot_id="b" * 64)
