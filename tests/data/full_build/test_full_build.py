import hashlib
import json
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import era100x.data.full_build.builder as builder_module

from era100x.data.full_build.builder import (
    ARROW_SCHEMA,
    Frequency,
    FullBuild,
    Symbol,
    archive_inventory,
    atomic_json,
    download_archive,
    parse_checksum,
    process_archive,
    round_robin_inventory,
    validate_official_conflicts,
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


def test_cross_date_interleaving_routes_without_weakening_daily_order(tmp_path: Path) -> None:
    interleaved = make_zip(
        tmp_path / "interleaved.zip",
        [
            "1,100,1,100,1577836800000,true",
            "3,102,1,102,1577923200000,true",
            "2,101,1,101,1577836801000,false",
            "4,103,1,103,1577923201000,false",
        ],
    )
    grouped = make_zip(
        tmp_path / "grouped.zip",
        [
            "1,100,1,100,1577836800000,true",
            "2,101,1,101,1577836801000,false",
            "3,102,1,102,1577923200000,true",
            "4,103,1,103,1577923201000,false",
        ],
    )
    routed = process_archive(interleaved, tmp_path / "routed", "BTCUSDT")
    reference = process_archive(grouped, tmp_path / "reference", "BTCUSDT")
    assert [entry["date"] for entry in routed] == ["2020-01-01", "2020-01-02"]
    assert routed[0]["archive_date_reversal_count"] == 1
    assert routed[0]["archive_interleaved_dates"] == ["2020-01-01", "2020-01-02"]
    assert [entry["logical_sha256"] for entry in routed] == [
        entry["logical_sha256"] for entry in reference
    ]


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


def test_exact_duplicates_remain_counted_on_external_sort_path(tmp_path: Path) -> None:
    archive = make_zip(
        tmp_path / "sorted-exact.zip",
        [
            "2,101,1,101,1577836801000,true",
            "1,100,1,100,1577836800000,true",
            "1,100,1,100,1577836800000,true",
        ],
    )
    entry = process_archive(archive, tmp_path / "sorted-exact", "BTCUSDT")[0]
    assert entry["rows"] == 2
    assert entry["input_rows"] == 2
    assert entry["source_input_rows"] == 3
    assert entry["duplicate_exact_count"] == 1


def test_conflicting_venue_id_preserves_both_official_facts(tmp_path: Path) -> None:
    conflict = make_zip(
        tmp_path / "duplicate.zip",
        [
            "1,100,1,100,1577836800000,true",
            "1,101,1,101,1577836800001,true",
        ],
    )
    output = tmp_path / "output"
    entries = process_archive(conflict, output, "BTCUSDT")
    assert entries[0]["rows"] == 2
    assert entries[0]["venue_trade_id_conflict_count"] == 1
    table = pq.read_table(output / "date=2020-01-01/part-000.parquet")
    assert table.column("identity_status").to_pylist() == [
        "CONFLICTING_VENUE_ID",
        "CONFLICTING_VENUE_ID",
    ]
    assert len(set(table.column("canonical_trade_id").to_pylist())) == 2


def test_input_shuffle_keeps_partition_logical_hash(tmp_path: Path) -> None:
    rows = [
        "1,100,1,100,1577836800000,true",
        "1,101,1,101,1577836801000,true",
        "2,99,1,99,1577836800500,false",
    ]
    first = process_archive(make_zip(tmp_path / "first.zip", rows), tmp_path / "a", "BTCUSDT")
    second = process_archive(
        make_zip(tmp_path / "second.zip", list(reversed(rows))), tmp_path / "b", "BTCUSDT"
    )
    assert first[0]["logical_sha256"] == second[0]["logical_sha256"]


def test_monthly_daily_conflict_sets_must_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        "7,100,1,100,1577836800000,true",
        "7,101,1,101,1577836801000,true",
    ]
    monthly_entries = process_archive(
        make_zip(tmp_path / "monthly.zip", rows), tmp_path / "monthly", "BTCUSDT"
    )
    daily = make_zip(tmp_path / "daily.zip", rows)
    digest = hashlib.sha256(daily.read_bytes()).hexdigest()
    monkeypatch.setattr(builder_module, "archive_url", lambda *_: "https://official/daily.zip")
    monkeypatch.setattr(builder_module, "fetch_text", lambda *_: f"{digest}  daily.zip\n")
    monkeypatch.setattr(builder_module, "download_archive", lambda *_: daily)
    results = validate_official_conflicts(tmp_path, "BTCUSDT", "monthly", monthly_entries)
    assert results[0]["status"] == "CONFIRMED_OFFICIAL_CONFLICT"

    mismatched = make_zip(tmp_path / "mismatch.zip", rows[:1])
    monkeypatch.setattr(builder_module, "download_archive", lambda *_: mismatched)
    with pytest.raises(ValueError, match="source disagreement"):
        validate_official_conflicts(tmp_path / "other", "BTCUSDT", "monthly", monthly_entries)


def test_within_date_time_reversal_is_stably_sorted_and_audited(tmp_path: Path) -> None:
    reversal = make_zip(
        tmp_path / "reversal.zip",
        [
            "1,100,1,100,1577836801000,true",
            "2,101,1,101,1577836800000,false",
        ],
    )
    output = tmp_path / "reversal-output"
    entries = process_archive(reversal, output, "BTCUSDT")
    assert entries[0]["source_timestamp_reversal_count"] == 1
    assert entries[0]["rows"] == 2


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


def test_truncated_download_resumes_without_resetting_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"abcdefghij"
    requests: list[str | None] = []

    class Response:
        def __init__(self, payload: bytes, status: int, headers: dict[str, str]) -> None:
            self.payload = payload
            self.status = status
            self.headers = headers
            self.offset = 0

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self, size: int) -> bytes:
            block = self.payload[self.offset : self.offset + size]
            self.offset += len(block)
            return block

    def fake_urlopen(request: object, timeout: int) -> Response:
        del timeout
        range_header = request.get_header("Range")  # type: ignore[attr-defined]
        requests.append(range_header)
        if len(requests) == 1:
            return Response(content[:3], 200, {"Content-Length": str(len(content))})
        assert range_header == "bytes=3-"
        return Response(content[3:], 206, {"Content-Range": "bytes 3-9/10"})

    monkeypatch.setattr(builder_module, "urlopen", fake_urlopen)
    monkeypatch.setattr("era100x.data.full_build.builder.time.sleep", lambda _: None)
    destination = tmp_path / "archive.zip"
    expected = hashlib.sha256(content).hexdigest()
    assert download_archive("https://official/archive.zip", destination, expected) == destination
    assert destination.read_bytes() == content
    assert requests == [None, "bytes=3-"]


def test_round_robin_inventory_keeps_symbols_separate_and_chronological() -> None:
    pending: dict[Symbol, list[tuple[Symbol, str, Frequency]]] = {
        "BTCUSDT": [
            ("BTCUSDT", "2020-01", "monthly"),
            ("BTCUSDT", "2020-02", "monthly"),
        ],
        "ETHUSDT": [
            ("ETHUSDT", "2020-01", "monthly"),
            ("ETHUSDT", "2020-02", "monthly"),
        ],
    }
    assert round_robin_inventory(pending) == [
        ("BTCUSDT", "2020-01", "monthly"),
        ("ETHUSDT", "2020-01", "monthly"),
        ("BTCUSDT", "2020-02", "monthly"),
        ("ETHUSDT", "2020-02", "monthly"),
    ]


def test_full_build_overlaps_prefetch_with_symbol_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inventory: list[tuple[Symbol, str, Frequency]] = [
        ("BTCUSDT", "2020-01", "monthly"),
        ("BTCUSDT", "2020-02", "monthly"),
        ("ETHUSDT", "2020-01", "monthly"),
        ("ETHUSDT", "2020-02", "monthly"),
    ]
    build_started = threading.Event()
    later_download_saw_build = threading.Event()

    def fake_prepare(
        work_root: str, symbol: Symbol, period: str, frequency: Frequency
    ) -> tuple[str, str]:
        del work_root
        if period == "2020-02":
            assert build_started.wait(timeout=2)
            later_download_saw_build.set()
        return f"{symbol}/{frequency}/{period}", "a" * 64

    def fake_build(
        work_root: str,
        run_id: str,
        symbol: Symbol,
        period: str,
        frequency: Frequency,
        expected: str,
    ) -> tuple[str, list[dict[str, object]]]:
        del work_root, run_id, expected
        build_started.set()
        return f"{symbol}/{frequency}/{period}", []

    monkeypatch.setattr(builder_module, "archive_inventory", lambda: inventory)
    monkeypatch.setattr(builder_module, "prepare_archive", fake_prepare)
    monkeypatch.setattr(builder_module, "build_prepared_archive", fake_build)
    monkeypatch.setattr(builder_module, "ProcessPoolExecutor", ThreadPoolExecutor)
    monkeypatch.setattr(builder_module, "DOWNLOAD_WORKERS", 4)
    monkeypatch.setattr(builder_module, "MINIMUM_FREE_BYTES", 0)
    monkeypatch.setattr(FullBuild, "_finalize", lambda self, checkpoint: None)
    root = tmp_path / "work"
    root.mkdir()
    checkpoint = FullBuild(root, "run", "commit", "config").run()
    assert later_download_saw_build.is_set()
    assert checkpoint["completed_archives"] == [
        "BTCUSDT/monthly/2020-01",
        "ETHUSDT/monthly/2020-01",
        "BTCUSDT/monthly/2020-02",
        "ETHUSDT/monthly/2020-02",
    ] or set(checkpoint["completed_archives"]) == {
        "BTCUSDT/monthly/2020-01",
        "ETHUSDT/monthly/2020-01",
        "BTCUSDT/monthly/2020-02",
        "ETHUSDT/monthly/2020-02",
    }
