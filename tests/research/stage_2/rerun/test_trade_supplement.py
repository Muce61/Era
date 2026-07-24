from __future__ import annotations

import hashlib
import zipfile
from datetime import date
from pathlib import Path

import pytest

from era100x.data.full_build.builder import process_archive
from era100x.research.stage_2.rerun.trade_supplement import (
    build_trade_supplement,
    partition_override,
    verify_trade_supplement,
)


def _archive(tmp_path: Path) -> tuple[Path, Path]:
    archive = tmp_path / "BTCUSDT-trades-2022-03.zip"
    rows = (
        "id,price,qty,quote_qty,time,is_buyer_maker\n"
        "1,40000,0.1,4000,1646092800000,false\n"
        "2,40001,0.2,8000.2,1646092801000,true\n"
    )
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("BTCUSDT-trades-2022-03.csv", rows)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = archive.with_suffix(".zip.CHECKSUM")
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return archive, checksum


def test_append_only_trade_supplement_exactly_rebuilds_sealed_receipt(
    tmp_path: Path,
) -> None:
    archive, checksum = _archive(tmp_path)
    original = tmp_path / "original"
    process_archive(
        archive,
        original,
        "BTCUSDT",
        source_archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        selected_dates={date(2022, 3, 1)},
    )
    original_day = original / "date=2022-03-01"
    original_parquet = original_day / "part-000.parquet"
    original_parquet.write_bytes(original_parquet.read_bytes()[:-8])

    output = tmp_path / "supplement"
    acceptance = build_trade_supplement(
        source_archive=archive,
        checksum_path=checksum,
        original_partition_root=original_day,
        output_root=output,
        instrument="BTCUSDT",
        owner_date=date(2022, 3, 1),
    )
    verified = verify_trade_supplement(acceptance)
    assert verified["status"] == "PASS"
    assert verified["row_count"] == 2
    override = partition_override(
        acceptance_path=acceptance,
        instrument="BTCUSDT",
        owner_date=date(2022, 3, 1),
    )
    assert override is not None
    assert override[0].is_file()
    assert (
        partition_override(
            acceptance_path=acceptance,
            instrument="ETHUSDT",
            owner_date=date(2022, 3, 1),
        )
        is None
    )


def test_trade_supplement_tamper_fails_closed(tmp_path: Path) -> None:
    archive, checksum = _archive(tmp_path)
    original = tmp_path / "original"
    process_archive(
        archive,
        original,
        "BTCUSDT",
        source_archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        selected_dates={date(2022, 3, 1)},
    )
    acceptance = build_trade_supplement(
        source_archive=archive,
        checksum_path=checksum,
        original_partition_root=original / "date=2022-03-01",
        output_root=tmp_path / "supplement",
        instrument="BTCUSDT",
        owner_date=date(2022, 3, 1),
    )
    partition = tmp_path / "supplement/data/date=2022-03-01/part-000.parquet"
    partition.write_bytes(partition.read_bytes()[:-1] + b"x")
    with pytest.raises(ValueError, match="read-back drift"):
        verify_trade_supplement(acceptance)
