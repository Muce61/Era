from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from era100x.research.stage_2.manifests.models import canonical_json
from era100x.research.stage_2.pipelines.candidates.stage1_catalog import (
    Stage1CatalogAuthority,
    Stage1TradesCatalogIndex,
    Stage1TradesPartition,
    sha256_file,
)
from era100x.research.stage_2.runtime_v2.foundation_sources import (
    ContractPriceInventoryIndex,
    trade_row_group_index,
)
from era100x.research.stage_2.runtime_v2.source_authority import (
    ContractPriceInventoryManifestV2,
    Stage1ResolvedSourceIndexV2,
    freeze_contract_price_inventory_manifest,
    freeze_stage1_resolved_source_index,
    load_sealed_source_manifest,
)


def _price_inventory(root: Path) -> str:
    records: list[dict[str, object]] = []
    for instrument in ("BTCUSDT", "ETHUSDT"):
        directory = root / f"{instrument}_1s_agg"
        by_date: dict[str, set[str]] = {}
        files = sorted(directory.glob(f"{instrument}_1s_*.csv")) + sorted(
            directory.glob(f"{instrument}_1s_*.parquet")
        )
        for path in files:
            day = path.stem.rsplit("_", 1)[1]
            by_date.setdefault(day, set()).add(path.suffix)
            records.append(
                {
                    "instrument": instrument,
                    "date": day,
                    "relative_path": str(path.relative_to(root)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                    "canonical_for_date": path.suffix == ".csv" or ".csv" not in by_date[day],
                }
            )
    return hashlib.sha256(canonical_json(records).encode()).hexdigest()


def _price_files(root: Path) -> None:
    for instrument in ("BTCUSDT", "ETHUSDT"):
        directory = root / f"{instrument}_1s_agg"
        directory.mkdir(parents=True)
        (directory / f"{instrument}_1s_20200101.csv").write_text(
            "ts_sec,open,high,low,close,volume\n1,1,1,1,1,1\n",
            encoding="utf-8",
        )
        pl.DataFrame(
            {
                "timestamp": [date(2020, 1, 2)],
                "open": [1.0],
                "high": [1.0],
                "low": [1.0],
                "close": [1.0],
                "volume": [1.0],
            }
        ).write_parquet(directory / f"{instrument}_1s_20200102.parquet")
        (directory / "._part-ignored.parquet").write_bytes(b"metadata")


def test_contract_price_inventory_is_bounded_and_canonical(tmp_path: Path) -> None:
    _price_files(tmp_path)
    expected = _price_inventory(tmp_path)

    index = ContractPriceInventoryIndex.load(
        root=tmp_path,
        expected_inventory_hash=expected,
        start=date(2020, 1, 1),
        end_exclusive=date(2020, 1, 3),
        expected_csv_count=1,
        expected_parquet_count=1,
        expected_overlap_count=0,
    )

    assert index.inventory_file_count == 4
    assert len(index.partitions) == 4
    assert index.get("BTCUSDT", date(2020, 1, 1)).source_format == "CSV"
    assert index.get("ETHUSDT", date(2020, 1, 2)).source_format == "PARQUET"
    assert all(not item.path.name.startswith("._") for item in index.partitions)


def test_contract_price_inventory_hash_mismatch_fails(tmp_path: Path) -> None:
    _price_files(tmp_path)
    with pytest.raises(ValueError, match="inventory hash changed"):
        ContractPriceInventoryIndex.load(
            root=tmp_path,
            expected_inventory_hash="0" * 64,
            start=date(2020, 1, 1),
            end_exclusive=date(2020, 1, 3),
            expected_csv_count=1,
            expected_parquet_count=1,
            expected_overlap_count=0,
        )


def test_contract_price_manifest_freezes_once_then_loads_without_source_rehash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    _price_files(source)
    expected = _price_inventory(source)
    manifest_path = tmp_path / "transition" / "contract-price.json"
    frozen = freeze_contract_price_inventory_manifest(
        root=source,
        output_path=manifest_path,
        expected_inventory_hash=expected,
        start=date(2020, 1, 1),
        end_exclusive=date(2020, 1, 3),
        expected_csv_count=1,
        expected_parquet_count=1,
        expected_overlap_count=0,
    )

    def forbidden_rehash(_path: Path) -> str:
        raise AssertionError("formal manifest load must not hash Contract Price source files")

    monkeypatch.setattr(
        "era100x.research.stage_2.runtime_v2.source_authority.sha256_file",
        forbidden_rehash,
    )
    loaded = load_sealed_source_manifest(manifest_path, ContractPriceInventoryManifestV2)
    index = loaded.to_index(root=source)

    assert loaded.manifest_hash == frozen.manifest_hash
    assert index.inventory_hash == expected
    assert len(index.partitions) == 4


def test_resolved_trades_index_loads_paths_in_memory_without_source_stat(tmp_path: Path) -> None:
    published = tmp_path / "published"
    partitions: list[Stage1TradesPartition] = []
    for instrument in ("BTCUSDT", "ETHUSDT"):
        for owner_date in (date(2020, 1, 1), date(2020, 1, 2)):
            relative = (
                Path(instrument)
                / "archive=2020-01"
                / f"date={owner_date.isoformat()}"
                / "part-000.parquet"
            )
            path = published / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"source")
            partitions.append(
                Stage1TradesPartition(
                    instrument=instrument,  # type: ignore[arg-type]
                    partition_date=owner_date,
                    archive_partition="2020-01",
                    path=path,
                    byte_sha256=sha256_file(path),
                    logical_sha256=("a" if instrument == "BTCUSDT" else "b") * 64,
                )
            )
    index = Stage1TradesCatalogIndex(
        published_root=published,
        partitions=tuple(sorted(partitions)),
    )
    authority = Stage1CatalogAuthority(
        data_run_id="stage1-run",
        dataset_version="stage1-trades-v2",
        canonical_manifest_sha256="c" * 64,
        physical_manifest_sha256="d" * 64,
        catalog_sha256s={"BTCUSDT": "e" * 64, "ETHUSDT": "f" * 64},
        logical_hashes={"BTCUSDT": "a" * 64, "ETHUSDT": "b" * 64},
    )
    manifest_path = tmp_path / "transition" / "trades.json"
    frozen = freeze_stage1_resolved_source_index(
        index=index,
        authority=authority,
        output_path=manifest_path,
        start=date(2020, 1, 1),
        end_exclusive=date(2020, 1, 3),
    )
    # The formal in-memory resolution does not touch each physical file.
    for partition in partitions:
        partition.path.unlink()
    loaded = load_sealed_source_manifest(manifest_path, Stage1ResolvedSourceIndexV2)
    restored = loaded.to_index(published_root=published)

    assert loaded.manifest_hash == frozen.manifest_hash
    assert len(restored.partitions) == 4
    assert all(not item.path.exists() for item in restored.partitions)


def test_trade_row_group_index_uses_footer_statistics(tmp_path: Path) -> None:
    published = tmp_path / "published"
    path = published / "BTCUSDT" / "archive=2020-01" / "date=2020-01-01" / "part-000.parquet"
    path.parent.mkdir(parents=True)
    pl.DataFrame(
        {
            "ts_event_ns": [1, 2, 3, 10, 11],
            "quantity": [1, 1, 1, 1, 1],
        }
    ).write_parquet(path, row_group_size=3, statistics=True)
    partition = Stage1TradesPartition(
        instrument="BTCUSDT",
        partition_date=date(2020, 1, 1),
        archive_partition="2020-01",
        path=path,
        byte_sha256=sha256_file(path),
        logical_sha256="a" * 64,
    )

    table = trade_row_group_index(partition, published_root=published)

    assert table.num_rows == 2
    assert table.column("row_count").to_pylist() == [3, 2]
    assert table.column("event_start_ns").to_pylist() == [1, 10]
    assert table.column("event_end_ns_exclusive").to_pylist() == [4, 12]


def test_trade_row_group_index_rejects_path_outside_authority(tmp_path: Path) -> None:
    path = tmp_path / "other" / "part-000.parquet"
    path.parent.mkdir()
    pl.DataFrame({"ts_event_ns": [1]}).write_parquet(path)
    partition = Stage1TradesPartition(
        instrument="ETHUSDT",
        partition_date=date(2020, 1, 1),
        archive_partition="2020-01",
        path=path,
        byte_sha256=sha256_file(path),
        logical_sha256="b" * 64,
    )
    with pytest.raises(ValueError, match="outside the frozen published root"):
        trade_row_group_index(partition, published_root=tmp_path / "published")
