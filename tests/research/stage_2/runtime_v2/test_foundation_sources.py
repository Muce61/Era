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
from era100x.research.stage_2.runtime_v2.orchestrator import (
    STAGE1_DATA_RUN_ID,
    STAGE1_MANIFEST_SHA256,
)
from era100x.research.stage_2.runtime_v2.production_backend import (
    STAGE1_CATALOG_ROOT,
    STAGE1_CATALOG_SHA256S,
    STAGE1_LOGICAL_HASHES,
    STAGE1_PHYSICAL_MANIFEST_SHA256,
    STAGE1_PUBLISHED_ROOT,
)
from era100x.research.stage_2.runtime_v2.source_authority import (
    ContractPriceInventoryManifestV2,
    Stage1ResolvedSourceIndexV2,
    Stage1TradesResolvedEntryV2,
    freeze_contract_price_inventory_manifest,
    freeze_stage1_resolved_source_index,
    freeze_stage1_resolved_source_index_from_catalog,
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


def _resolved_entry(
    *,
    instrument: str = "BTCUSDT",
    owner_date: date = date(2026, 7, 1),
    archive: str = "2026-07-01",
    relative_path: str | None = None,
) -> Stage1TradesResolvedEntryV2:
    path = relative_path or (
        f"{instrument}/archive={archive}/date={owner_date.isoformat()}/part-000.parquet"
    )
    return Stage1TradesResolvedEntryV2(
        instrument=instrument,  # type: ignore[arg-type]
        partition_date=owner_date,
        archive_partition=archive,
        relative_path=path,
        byte_sha256="a" * 64,
        logical_sha256="b" * 64,
    )


@pytest.mark.parametrize("archive", ("2026-07", "2026-07-01"))
def test_resolved_trade_entry_accepts_catalog_authorized_month_or_daily_archive(
    archive: str,
) -> None:
    entry = _resolved_entry(archive=archive)

    assert entry.archive_partition == archive
    assert f"archive={archive}/date=2026-07-01/" in entry.relative_path


@pytest.mark.parametrize(
    ("archive", "owner_date"),
    (
        ("2026-06", date(2026, 7, 1)),
        ("2026-07-02", date(2026, 7, 1)),
    ),
)
def test_resolved_trade_entry_rejects_month_or_daily_archive_date_mismatch(
    archive: str,
    owner_date: date,
) -> None:
    with pytest.raises(ValueError, match="archive/date mismatch"):
        _resolved_entry(archive=archive, owner_date=owner_date)


def test_resolved_trade_entry_rejects_archive_field_path_mismatch() -> None:
    with pytest.raises(ValueError, match="archive/date mismatch"):
        _resolved_entry(
            archive="2026-07",
            relative_path=("BTCUSDT/archive=2026-07-01/date=2026-07-01/part-000.parquet"),
        )


def test_resolved_trade_entry_rejects_instrument_path_mismatch() -> None:
    with pytest.raises(ValueError, match="path field mismatch"):
        _resolved_entry(
            instrument="ETHUSDT",
            relative_path=("BTCUSDT/archive=2026-07-01/date=2026-07-01/part-000.parquet"),
        )


def test_resolved_trades_index_supports_mixed_archives_and_stable_order(
    tmp_path: Path,
) -> None:
    published = tmp_path / "published"
    partitions: list[Stage1TradesPartition] = []
    for instrument in ("BTCUSDT", "ETHUSDT"):
        for owner_date, archive in (
            (date(2026, 6, 30), "2026-06"),
            (date(2026, 7, 1), "2026-07-01"),
        ):
            relative = (
                Path(instrument)
                / f"archive={archive}"
                / f"date={owner_date.isoformat()}"
                / "part-000.parquet"
            )
            path = published / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"{instrument}-{owner_date}".encode())
            partitions.append(
                Stage1TradesPartition(
                    instrument=instrument,  # type: ignore[arg-type]
                    partition_date=owner_date,
                    archive_partition=archive,
                    path=path,
                    byte_sha256=sha256_file(path),
                    logical_sha256=("a" if instrument == "BTCUSDT" else "b") * 64,
                )
            )
    authority = Stage1CatalogAuthority(
        data_run_id="stage1-run",
        dataset_version="stage1-trades-v2",
        canonical_manifest_sha256="c" * 64,
        physical_manifest_sha256="d" * 64,
        catalog_sha256s={"BTCUSDT": "e" * 64, "ETHUSDT": "f" * 64},
        logical_hashes={"BTCUSDT": "a" * 64, "ETHUSDT": "b" * 64},
    )
    forward = freeze_stage1_resolved_source_index(
        index=Stage1TradesCatalogIndex(
            published_root=published,
            partitions=tuple(partitions),
        ),
        authority=authority,
        output_path=tmp_path / "forward.json",
        start=date(2026, 6, 30),
        end_exclusive=date(2026, 7, 2),
    )
    reverse = freeze_stage1_resolved_source_index(
        index=Stage1TradesCatalogIndex(
            published_root=published,
            partitions=tuple(reversed(partitions)),
        ),
        authority=authority,
        output_path=tmp_path / "reverse.json",
        start=date(2026, 6, 30),
        end_exclusive=date(2026, 7, 2),
    )

    assert forward.index_hash == reverse.index_hash
    assert forward.manifest_hash == reverse.manifest_hash
    assert [item.archive_partition for item in forward.entries] == [
        "2026-06",
        "2026-07-01",
        "2026-06",
        "2026-07-01",
    ]


def test_resolved_trades_index_deduplicates_identical_catalog_partitions(
    tmp_path: Path,
) -> None:
    published = tmp_path / "published"
    partitions: list[Stage1TradesPartition] = []
    for instrument in ("BTCUSDT", "ETHUSDT"):
        path = (
            published / instrument / "archive=2026-07-01" / "date=2026-07-01" / "part-000.parquet"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(instrument.encode())
        item = Stage1TradesPartition(
            instrument=instrument,  # type: ignore[arg-type]
            partition_date=date(2026, 7, 1),
            archive_partition="2026-07-01",
            path=path,
            byte_sha256=sha256_file(path),
            logical_sha256=("a" if instrument == "BTCUSDT" else "b") * 64,
        )
        partitions.extend((item, item))
    authority = Stage1CatalogAuthority(
        data_run_id="stage1-run",
        dataset_version="stage1-trades-v2",
        canonical_manifest_sha256="c" * 64,
        physical_manifest_sha256="d" * 64,
        catalog_sha256s={"BTCUSDT": "e" * 64, "ETHUSDT": "f" * 64},
        logical_hashes={"BTCUSDT": "a" * 64, "ETHUSDT": "b" * 64},
    )

    frozen = freeze_stage1_resolved_source_index(
        index=Stage1TradesCatalogIndex(
            published_root=published,
            partitions=tuple(reversed(partitions)),
        ),
        authority=authority,
        output_path=tmp_path / "deduplicated.json",
        start=date(2026, 7, 1),
        end_exclusive=date(2026, 7, 2),
    )

    assert frozen.resolved_partition_count == 2
    assert len(frozen.entries) == 2


def test_resolved_trades_index_rejects_same_date_conflicting_partitions(tmp_path: Path) -> None:
    published = tmp_path / "published"
    partitions: list[Stage1TradesPartition] = []
    for instrument in ("BTCUSDT", "ETHUSDT"):
        for archive in ("2026-07", "2026-07-01"):
            path = (
                published
                / instrument
                / f"archive={archive}"
                / "date=2026-07-01"
                / "part-000.parquet"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"{instrument}-{archive}".encode())
            partitions.append(
                Stage1TradesPartition(
                    instrument=instrument,  # type: ignore[arg-type]
                    partition_date=date(2026, 7, 1),
                    archive_partition=archive,
                    path=path,
                    byte_sha256=sha256_file(path),
                    logical_sha256=("a" if instrument == "BTCUSDT" else "b") * 64,
                )
            )
    authority = Stage1CatalogAuthority(
        data_run_id="stage1-run",
        dataset_version="stage1-trades-v2",
        canonical_manifest_sha256="c" * 64,
        physical_manifest_sha256="d" * 64,
        catalog_sha256s={"BTCUSDT": "e" * 64, "ETHUSDT": "f" * 64},
        logical_hashes={"BTCUSDT": "a" * 64, "ETHUSDT": "b" * 64},
    )

    with pytest.raises(ValueError, match="conflict|not unique and sorted"):
        freeze_stage1_resolved_source_index(
            index=Stage1TradesCatalogIndex(
                published_root=published,
                partitions=tuple(partitions),
            ),
            authority=authority,
            output_path=tmp_path / "conflict.json",
            start=date(2026, 7, 1),
            end_exclusive=date(2026, 7, 2),
        )


@pytest.mark.skipif(
    not STAGE1_CATALOG_ROOT.is_dir() or not STAGE1_PUBLISHED_ROOT.is_dir(),
    reason="frozen Stage 1 external baseline unavailable",
)
def test_real_resolved_authority_covers_mixed_archives_and_six_daily_tails(
    tmp_path: Path,
) -> None:
    authority = Stage1CatalogAuthority(
        data_run_id=STAGE1_DATA_RUN_ID,
        dataset_version="stage1-trades-v2",
        canonical_manifest_sha256=STAGE1_MANIFEST_SHA256,
        physical_manifest_sha256=STAGE1_PHYSICAL_MANIFEST_SHA256,
        catalog_sha256s=STAGE1_CATALOG_SHA256S,
        logical_hashes=STAGE1_LOGICAL_HASHES,
    )
    frozen = freeze_stage1_resolved_source_index_from_catalog(
        catalog_run_root=STAGE1_CATALOG_ROOT,
        published_root=STAGE1_PUBLISHED_ROOT,
        authority=authority,
        output_path=tmp_path / "real-stage1-trades-resolved-index-v2.json",
    )
    daily = [item for item in frozen.entries if len(item.archive_partition) == 10]

    assert frozen.resolved_partition_count == 4_752
    assert len(daily) == 6
    assert {(item.instrument, item.partition_date) for item in daily} == {
        (instrument, owner_date)
        for instrument in ("BTCUSDT", "ETHUSDT")
        for owner_date in (date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3))
    }
    for instrument in ("BTCUSDT", "ETHUSDT"):
        instrument_entries = [item for item in frozen.entries if item.instrument == instrument]
        month_archives = {
            item.archive_partition
            for item in instrument_entries
            if len(item.archive_partition) == 7
        }
        day_archives = {
            item.archive_partition
            for item in instrument_entries
            if len(item.archive_partition) == 10
        }
        assert len(month_archives) == 78
        assert day_archives == {"2026-07-01", "2026-07-02", "2026-07-03"}


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
