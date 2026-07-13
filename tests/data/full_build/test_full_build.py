import hashlib
import json
import zipfile
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from era100x.data.full_build.builder import (
    ARROW_SCHEMA,
    FullBuild,
    archive_inventory,
    atomic_json,
    parse_checksum,
    process_archive,
)


def make_zip(path: Path, rows: list[str]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(
            "BTCUSDT-trades-test.csv",
            "id,price,qty,quoteQty,time,isBuyerMaker\n" + "\n".join(rows) + "\n",
        )
    return path


def test_checksum_and_inventory_are_exact() -> None:
    digest = "a" * 64
    assert parse_checksum(f"{digest}  BTCUSDT.zip\n", "BTCUSDT.zip") == digest
    with pytest.raises(ValueError):
        parse_checksum(f"{digest}  other.zip\n", "BTCUSDT.zip")
    assert len(archive_inventory()) == 162


def test_streaming_archive_splits_dates_and_is_deterministic(tmp_path: Path) -> None:
    archive = make_zip(
        tmp_path / "trades.zip",
        [
            "1,100.000,1.0,100.0,1577836800000,true",
            "2,101,2,202,1577836801000,false",
            "3,102,1,102,1577923200000,true",
        ],
    )
    first = process_archive(archive, tmp_path / "first", "BTCUSDT")
    second = process_archive(archive, tmp_path / "second", "BTCUSDT")
    assert [entry["date"] for entry in first] == ["2020-01-01", "2020-01-02"]
    assert [entry["logical_sha256"] for entry in first] == [
        entry["logical_sha256"] for entry in second
    ]
    table = pq.ParquetFile(tmp_path / "first/date=2020-01-01/part-000.parquet").read()
    assert table.schema == ARROW_SCHEMA
    assert table.num_rows == 2


def test_exact_duplicates_are_audited_and_deterministically_removed(tmp_path: Path) -> None:
    exact = make_zip(
        tmp_path / "exact.zip",
        [
            "2126346263,39915.9,0.55,21953.74,1649980800061,true",
            "2126346263,39915.9,0.55,21953.74,1649980800061,true",
            "2126346263,39915.9,0.55,21953.74,1649980800061,true",
        ],
    )
    entries = process_archive(exact, tmp_path / "exact-output", "BTCUSDT")
    assert entries[0]["input_rows"] == 3
    assert entries[0]["rows"] == 1
    assert entries[0]["duplicate_exact_count"] == 2


def test_conflicting_duplicate_does_not_leave_output(tmp_path: Path) -> None:
    conflict = make_zip(
        tmp_path / "duplicate.zip",
        [
            "1,100,1,100,1577836800000,true",
            "1,101,1,101,1577836800001,true",
        ],
    )
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="conflicting duplicate"):
        process_archive(conflict, output, "BTCUSDT")
    assert not output.exists()


def test_checkpoint_is_atomic_and_run_identity_is_fixed(tmp_path: Path) -> None:
    root = tmp_path / "work"
    root.mkdir()
    builder = FullBuild(root, "run-1", "abc", "def")
    checkpoint = builder.load_or_create()
    assert checkpoint["run_id"] == "run-1"
    assert not builder.checkpoint_path.with_suffix(".json.tmp").exists()
    conflicting = FullBuild(root, "run-1", "changed", "def")
    with pytest.raises(ValueError, match="identity"):
        conflicting.load_or_create()


def test_atomic_json_has_stable_content(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    atomic_json(path, {"b": 2, "a": 1})
    assert json.loads(path.read_text()) == {"a": 1, "b": 2}
    assert (
        hashlib.sha256(path.read_bytes()).hexdigest()
        == hashlib.sha256(path.read_bytes()).hexdigest()
    )
