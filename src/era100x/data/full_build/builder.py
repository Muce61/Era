from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import time
import zipfile
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    wait,
)
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal, cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.data.ingest import archive_url
from era100x.data.normalize.identity import SCHEMA_VERSION, canonical_trade_identity

Symbol = Literal["BTCUSDT", "ETHUSDT"]
Frequency = Literal["monthly", "daily"]
SYMBOLS: tuple[Symbol, ...] = ("BTCUSDT", "ETHUSDT")
TARGET_START = date(2020, 1, 1)
TARGET_END = date(2026, 7, 4)
DETERMINISM_DATES = {date(2020, 1, 1), date(2023, 4, 2), date(2026, 7, 3)}
MINIMUM_FREE_BYTES = 585_983_717_541
DOWNLOAD_WORKERS = 6
UNAVAILABLE_FIELDS = (
    "ts_recv",
    "bid",
    "ask",
    "spread",
    "network_latency",
    "queue_position",
    "partial_fill_process",
    "order_slippage",
    "order_book_depth",
)


class ArchiveOrderingError(ValueError):
    """The official archive requires the audited external-sort path."""


ARROW_SCHEMA = pa.schema(
    [
        ("instrument", pa.string()),
        ("venue_trade_id", pa.int64()),
        ("canonical_trade_id", pa.string()),
        ("identity_status", pa.string()),
        ("venue_trade_id_conflict_group", pa.string()),
        ("source_archive_sha256", pa.string()),
        ("price", pa.decimal128(38, 18)),
        ("quantity", pa.decimal128(38, 18)),
        ("quote_quantity", pa.decimal128(38, 18)),
        ("ts_event_ns", pa.int64()),
        ("is_buyer_maker", pa.bool_()),
        ("aggressor_side", pa.string()),
    ]
)


def canonical_decimal(raw: str) -> tuple[Decimal, str]:
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal: {raw}") from exc
    if not value.is_finite():
        raise ValueError("decimal must be finite")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return value, text or "0"


def parse_checksum(text: str, expected_filename: str) -> str:
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[1].lstrip("*") == expected_filename:
            digest = parts[0].lower()
            if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest):
                return digest
    raise ValueError(f"official checksum missing for {expected_filename}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    os.replace(temporary, path)


def archive_inventory() -> list[tuple[Symbol, str, Frequency]]:
    inventory: list[tuple[Symbol, str, Frequency]] = []
    for symbol in SYMBOLS:
        year, month = 2020, 1
        while (year, month) <= (2026, 6):
            inventory.append((symbol, f"{year:04d}-{month:02d}", "monthly"))
            month += 1
            if month == 13:
                year += 1
                month = 1
        for day in range(1, 4):
            inventory.append((symbol, f"2026-07-{day:02d}", "daily"))
    return inventory


def fetch_text(url: str, attempts: int = 5) -> str:
    for attempt in range(attempts):
        try:
            with urlopen(Request(url), timeout=30) as response:
                return cast(str, response.read().decode("utf-8"))
        except Exception:
            if attempt + 1 == attempts:
                raise
            time.sleep(min(30, 2**attempt))
    raise AssertionError("unreachable")


def download_archive(url: str, destination: Path, expected_sha256: str) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256_file(destination) != expected_sha256:
            raise FileExistsError(f"immutable archive conflict: {destination}")
        return destination
    partial = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(8):
        offset = partial.stat().st_size if partial.exists() else 0
        request = Request(url, headers={"Range": f"bytes={offset}-"} if offset else {})
        try:
            with urlopen(request, timeout=60) as response:
                status_code = getattr(response, "status", 200)
                if offset and status_code != 206:
                    raise OSError("server refused Range resume; partial preserved")
                content_range = response.headers.get("Content-Range")
                content_length = response.headers.get("Content-Length")
                expected_size: int | None = None
                if content_range:
                    match = re.fullmatch(r"bytes \d+-\d+/(\d+)", content_range.strip())
                    if match:
                        expected_size = int(match.group(1))
                elif content_length:
                    expected_size = offset + int(content_length)
                with partial.open("ab" if offset else "wb") as output:
                    for block in iter(lambda: response.read(4 * 1024 * 1024), b""):
                        output.write(block)
            if expected_size is not None and partial.stat().st_size < expected_size:
                raise OSError(
                    "truncated response; partial preserved for Range resume: "
                    f"{partial.stat().st_size}/{expected_size}"
                )
            if expected_size is not None and partial.stat().st_size > expected_size:
                partial_size = partial.stat().st_size
                raise ValueError(
                    f"partial exceeds official object length: {partial_size}/{expected_size}"
                )
            actual = sha256_file(partial)
            if actual != expected_sha256:
                raise ValueError(f"archive checksum mismatch; partial preserved: {actual}")
            os.chmod(partial, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
            os.replace(partial, destination)
            return destination
        except HTTPError as exc:
            if exc.code == 404:
                raise FileNotFoundError(url) from exc
            if attempt == 7:
                raise
        except ValueError:
            raise
        except Exception:
            if attempt == 7:
                raise
        time.sleep(min(60, 2**attempt))
    raise AssertionError("unreachable")


class PartitionWriter:
    def __init__(
        self,
        root: Path,
        symbol: Symbol,
        partition_date: date,
        *,
        source_archive_sha256: str,
        permit_trade_id_reversal: bool = False,
    ) -> None:
        self.symbol = symbol
        self.partition_date = partition_date
        self.source_archive_sha256 = source_archive_sha256
        self.directory = root / f"date={partition_date.isoformat()}"
        self.directory.mkdir(parents=True, exist_ok=False)
        self.path = self.directory / "part-000.parquet"
        self.writer = pq.ParquetWriter(self.path, ARROW_SCHEMA, compression="zstd")
        self.batch: list[dict[str, object]] = []
        self.logical_hash = hashlib.sha256()
        self.rows = 0
        self.first_trade_id: int | None = None
        self.last_trade_id: int | None = None
        self.last_ts_ns: int | None = None
        self.gap_count = 0
        self.gap_examples: list[str] = []
        self.trade_id_reversal_count = 0
        self.trade_id_reversal_examples: list[str] = []
        self.permit_trade_id_reversal = permit_trade_id_reversal
        self.input_rows = 0
        self.duplicate_exact_count = 0
        self.last_signature: tuple[object, ...] | None = None
        self.hash_batch = bytearray()

    def append(self, values: list[str], row_date: date, timestamp_ms: int) -> None:
        if len(values) not in {6, 9}:
            raise ValueError(f"unexpected Trades column count: {len(values)}")
        self.input_rows += 1
        venue_trade_id = int(values[0])
        price, price_text = canonical_decimal(values[1])
        quantity, quantity_text = canonical_decimal(values[2])
        quote_quantity, quote_text = canonical_decimal(values[3])
        maker_text = values[5].strip().lower()
        if price <= 0 or quantity <= 0 or quote_quantity < 0:
            raise ValueError("trade price/quantity must be positive")
        if maker_text not in {"true", "false"}:
            raise ValueError(f"invalid isBuyerMaker: {values[5]}")
        if row_date != self.partition_date:
            raise ValueError(f"trade falls outside partition date: {row_date}")
        ts_event_ns = timestamp_ms * 1_000_000
        canonical_trade_id = canonical_trade_identity(
            instrument=self.symbol,
            venue_trade_id=venue_trade_id,
            ts_event_ns=ts_event_ns,
            price=price,
            quantity=quantity,
            quote_quantity=quote_quantity,
            is_buyer_maker=maker_text == "true",
        )
        identity_status = values[6] if len(values) == 9 else "UNIQUE_VENUE_ID"
        conflict_group = values[7] or None if len(values) == 9 else None
        supplied_canonical_id = values[8] if len(values) == 9 else canonical_trade_id
        if supplied_canonical_id != canonical_trade_id:
            raise ValueError("canonical trade identity mismatch")
        signature = (
            venue_trade_id,
            price_text,
            quantity_text,
            quote_text,
            ts_event_ns,
            maker_text,
        )
        if self.last_trade_id is not None:
            if venue_trade_id == self.last_trade_id:
                if signature == self.last_signature:
                    self.duplicate_exact_count += 1
                    return
                if identity_status != "CONFLICTING_VENUE_ID" or conflict_group is None:
                    raise ArchiveOrderingError(
                        f"unclassified conflicting venue_trade_id: {venue_trade_id}"
                    )
            if venue_trade_id < self.last_trade_id:
                if not self.permit_trade_id_reversal:
                    raise ArchiveOrderingError(f"venue_trade_id reversal: {venue_trade_id}")
                self.trade_id_reversal_count += 1
                if len(self.trade_id_reversal_examples) < 100:
                    self.trade_id_reversal_examples.append(
                        f"{self.last_trade_id}->{venue_trade_id}"
                    )
            if venue_trade_id > self.last_trade_id + 1:
                self.gap_count += venue_trade_id - self.last_trade_id - 1
                if len(self.gap_examples) < 100:
                    self.gap_examples.append(f"{self.last_trade_id + 1}-{venue_trade_id - 1}")
        if self.last_ts_ns is not None and ts_event_ns < self.last_ts_ns:
            raise ArchiveOrderingError(f"timestamp reversal at venue_trade_id {venue_trade_id}")
        maker = maker_text == "true"
        canonical = (
            f"{self.symbol}|{venue_trade_id}|{canonical_trade_id}|{price_text}|{quantity_text}|"
            f"{quote_text}|{ts_event_ns}|{maker_text}|{identity_status}|{conflict_group or ''}|"
            f"{'SELL' if maker else 'BUY'}\n"
        ).encode()
        self.hash_batch.extend(canonical)
        self.batch.append(
            {
                "instrument": self.symbol,
                "venue_trade_id": venue_trade_id,
                "canonical_trade_id": canonical_trade_id,
                "identity_status": identity_status,
                "venue_trade_id_conflict_group": conflict_group,
                "source_archive_sha256": self.source_archive_sha256,
                "price": price,
                "quantity": quantity,
                "quote_quantity": quote_quantity,
                "ts_event_ns": ts_event_ns,
                "is_buyer_maker": maker,
                "aggressor_side": "SELL" if maker else "BUY",
            }
        )
        self.first_trade_id = venue_trade_id if self.first_trade_id is None else self.first_trade_id
        self.last_trade_id = venue_trade_id
        self.last_ts_ns = ts_event_ns
        self.last_signature = signature
        self.rows += 1
        if len(self.batch) >= 25_000:
            self.flush()

    def flush(self) -> None:
        if self.batch:
            self.logical_hash.update(self.hash_batch)
            self.hash_batch.clear()
            self.writer.write_table(pa.Table.from_pylist(self.batch, schema=ARROW_SCHEMA))
            self.batch.clear()

    def close(self) -> dict[str, object]:
        self.flush()
        self.writer.close()
        if self.rows == 0:
            raise ValueError(f"zero-row partition: {self.partition_date}")
        result = {
            "instrument": self.symbol,
            "date": self.partition_date.isoformat(),
            "relative_path": str(self.directory.name + "/" + self.path.name),
            "rows": self.rows,
            "input_rows": self.input_rows,
            "duplicate_exact_count": self.duplicate_exact_count,
            "first_venue_trade_id": self.first_trade_id,
            "last_venue_trade_id": self.last_trade_id,
            "last_ts_ns": self.last_ts_ns,
            "venue_trade_id_gap_count": self.gap_count,
            "venue_trade_id_gap_examples": self.gap_examples,
            "venue_trade_id_reversal_count": self.trade_id_reversal_count,
            "venue_trade_id_reversal_examples": self.trade_id_reversal_examples,
            "byte_sha256": sha256_file(self.path),
            "logical_sha256": self.logical_hash.hexdigest(),
            "bytes": self.path.stat().st_size,
        }
        atomic_json(self.directory / "partition.json", result)
        return result


def _external_sort(source: Path, destination: Path, keys: tuple[str, ...], temp: Path) -> None:
    environment = dict(os.environ)
    environment["LC_ALL"] = "C"
    with destination.open("wb") as output:
        completed = subprocess.run(
            ["sort", "-t", "\t", "-T", str(temp), *keys, str(source)],
            stdout=output,
            stderr=subprocess.PIPE,
            env=environment,
            check=False,
        )
    if completed.returncode:
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace"))


def _classify_venue_id_groups(
    source: Path, destination: Path, symbol: Symbol
) -> tuple[list[dict[str, object]], int]:
    groups: list[dict[str, object]] = []
    duplicate_exact_count = 0
    current_id: str | None = None
    lines: dict[str, str] = {}

    def flush(output: io.TextIOWrapper) -> None:
        if current_id is None:
            return
        conflicting = len(lines) > 1
        group = f"{symbol}:{current_id}" if conflicting else ""
        status = "CONFLICTING_VENUE_ID" if conflicting else "UNIQUE_VENUE_ID"
        for canonical_id in sorted(lines):
            output.write(lines[canonical_id].rstrip("\n") + f"\t{status}\t{group}\n")
        if conflicting:
            groups.append(
                {
                    "venue_trade_id": int(current_id),
                    "canonical_trade_ids": sorted(lines),
                    "conflict_group": group,
                }
            )

    with source.open() as stream, destination.open("w") as output:
        for line in stream:
            fields = line.rstrip("\n").split("\t")
            venue_id = fields[1]
            canonical_id = fields[6]
            if current_id is not None and venue_id != current_id:
                flush(output)
                lines = {}
            current_id = venue_id
            if canonical_id in lines:
                duplicate_exact_count += 1
            else:
                lines[canonical_id] = line
        flush(output)
    return groups, duplicate_exact_count


def _process_archive_streaming(
    archive: Path,
    output_root: Path,
    symbol: Symbol,
    *,
    source_archive_sha256: str,
    selected_dates: set[date] | None = None,
) -> list[dict[str, object]]:
    if output_root.exists():
        raise FileExistsError(output_root)
    output_root.mkdir(parents=True)
    entries: list[dict[str, object]] = []
    writer: PartitionWriter | None = None
    current_date: date | None = None
    try:
        with zipfile.ZipFile(archive) as bundle:
            members = [name for name in bundle.namelist() if name.lower().endswith(".csv")]
            if len(members) != 1:
                raise ValueError("archive must contain exactly one CSV")
            with bundle.open(members[0]) as raw_stream:
                rows = csv.reader(io.TextIOWrapper(raw_stream, encoding="utf-8", newline=""))
                for values in rows:
                    if not values or not values[0].strip().lstrip("-").isdigit():
                        continue
                    timestamp_ms = int(values[4])
                    row_date = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).date()
                    if not (TARGET_START <= row_date < TARGET_END):
                        continue
                    if selected_dates is not None and row_date not in selected_dates:
                        continue
                    if current_date != row_date:
                        if current_date is not None and row_date < current_date:
                            raise ArchiveOrderingError("archive date reversal")
                        if writer is not None:
                            entry = writer.close()
                            entry["ordering_mode"] = "SOURCE_ORDER"
                            entries.append(entry)
                        writer = PartitionWriter(
                            output_root,
                            symbol,
                            row_date,
                            source_archive_sha256=source_archive_sha256,
                        )
                        current_date = row_date
                    assert writer is not None
                    writer.append(values, row_date, timestamp_ms)
        if writer is not None:
            entry = writer.close()
            entry["ordering_mode"] = "SOURCE_ORDER"
            entries.append(entry)
        if not entries:
            raise ValueError("archive produced no target rows")
        return entries
    except Exception:
        if writer is not None:
            with suppress(Exception):
                writer.writer.close()
        shutil.rmtree(output_root, ignore_errors=True)
        raise


def _process_archive_sorted(
    archive: Path,
    output_root: Path,
    symbol: Symbol,
    *,
    source_archive_sha256: str,
    selected_dates: set[date] | None = None,
) -> list[dict[str, object]]:
    if output_root.exists():
        raise FileExistsError(output_root)
    output_root.mkdir(parents=True)
    sort_root = output_root / "_sort"
    sort_root.mkdir()
    spools: dict[date, io.TextIOWrapper] = {}
    raw_hashes: dict[date, Any] = {}
    input_rows: dict[date, int] = {}
    source_reversals: dict[date, dict[str, int]] = {}
    source_previous: dict[date, tuple[int, int]] = {}
    previous_source_date: date | None = None
    date_reversal_count = 0
    interleaved_dates: set[date] = set()
    try:
        with zipfile.ZipFile(archive) as bundle:
            members = [name for name in bundle.namelist() if name.lower().endswith(".csv")]
            if len(members) != 1:
                raise ValueError("archive must contain exactly one CSV")
            with bundle.open(members[0]) as raw_stream:
                rows = csv.reader(io.TextIOWrapper(raw_stream, encoding="utf-8", newline=""))
                for values in rows:
                    if not values or not values[0].strip().lstrip("-").isdigit():
                        continue
                    timestamp_ms = int(values[4])
                    row_date = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).date()
                    if not (TARGET_START <= row_date < TARGET_END):
                        continue
                    if selected_dates is not None and row_date not in selected_dates:
                        continue
                    if len(values) != 6:
                        raise ValueError(f"unexpected Trades column count: {len(values)}")
                    trade_id = int(values[0])
                    _, price_text = canonical_decimal(values[1])
                    price = Decimal(price_text)
                    _, quantity_text = canonical_decimal(values[2])
                    quantity = Decimal(quantity_text)
                    _, quote_text = canonical_decimal(values[3])
                    quote_quantity = Decimal(quote_text)
                    maker_text = values[5].strip().lower()
                    if price <= 0 or quantity <= 0 or quote_quantity < 0:
                        raise ValueError("trade price/quantity must be positive")
                    if maker_text not in {"true", "false"}:
                        raise ValueError(f"invalid isBuyerMaker: {values[5]}")
                    if previous_source_date is not None and row_date < previous_source_date:
                        date_reversal_count += 1
                        interleaved_dates.update((previous_source_date, row_date))
                    previous_source_date = row_date
                    previous = source_previous.get(row_date)
                    counters = source_reversals.setdefault(
                        row_date, {"timestamp": 0, "venue_trade_id": 0}
                    )
                    if previous is not None:
                        counters["timestamp"] += int(timestamp_ms < previous[0])
                        counters["venue_trade_id"] += int(trade_id < previous[1])
                    source_previous[row_date] = (timestamp_ms, trade_id)
                    spool = spools.get(row_date)
                    if spool is None:
                        spool = (sort_root / f"{row_date.isoformat()}.input.tsv").open("w")
                        spools[row_date] = spool
                        raw_hashes[row_date] = hashlib.sha256()
                        input_rows[row_date] = 0
                    canonical_id = canonical_trade_identity(
                        instrument=symbol,
                        venue_trade_id=trade_id,
                        ts_event_ns=timestamp_ms * 1_000_000,
                        price=price,
                        quantity=quantity,
                        quote_quantity=quote_quantity,
                        is_buyer_maker=maker_text == "true",
                    )
                    canonical_line = (
                        f"{timestamp_ms}\t{trade_id}\t{price_text}\t{quantity_text}\t"
                        f"{quote_text}\t{maker_text}\t{canonical_id}\n"
                    )
                    spool.write(canonical_line)
                    raw_hashes[row_date].update(canonical_line.encode())
                    input_rows[row_date] += 1
        for spool in spools.values():
            spool.close()
        entries = []
        for partition_date in sorted(spools):
            source = sort_root / f"{partition_date.isoformat()}.input.tsv"
            by_id = sort_root / f"{partition_date.isoformat()}.by-id.tsv"
            classified = sort_root / f"{partition_date.isoformat()}.classified.tsv"
            ordered = sort_root / f"{partition_date.isoformat()}.ordered.tsv"
            _external_sort(
                source,
                by_id,
                ("-k2,2n", "-k7,7", "-k1,1n"),
                sort_root,
            )
            conflict_groups, sorted_duplicate_exact_count = _classify_venue_id_groups(
                by_id, classified, symbol
            )
            _external_sort(
                classified,
                ordered,
                ("-k1,1n", "-k2,2n", "-k7,7"),
                sort_root,
            )
            writer = PartitionWriter(
                output_root,
                symbol,
                partition_date,
                source_archive_sha256=source_archive_sha256,
                permit_trade_id_reversal=True,
            )
            with ordered.open() as stream:
                for line in stream:
                    (
                        timestamp_text,
                        sorted_trade_id,
                        sorted_price,
                        sorted_quantity,
                        sorted_quote,
                        sorted_maker,
                        canonical_id,
                        identity_status,
                        conflict_group,
                    ) = line.rstrip("\n").split("\t")
                    writer.append(
                        [
                            sorted_trade_id,
                            sorted_price,
                            sorted_quantity,
                            sorted_quote,
                            timestamp_text,
                            sorted_maker,
                            identity_status,
                            conflict_group,
                            canonical_id,
                        ],
                        partition_date,
                        int(timestamp_text),
                    )
            entry = writer.close()
            entry["duplicate_exact_count"] = (
                cast(int, entry["duplicate_exact_count"]) + sorted_duplicate_exact_count
            )
            entry["source_input_rows"] = input_rows[partition_date]
            entry["source_order_sha256"] = raw_hashes[partition_date].hexdigest()
            entry["source_timestamp_reversal_count"] = source_reversals[partition_date]["timestamp"]
            entry["source_venue_trade_id_reversal_count"] = source_reversals[partition_date][
                "venue_trade_id"
            ]
            entry["archive_date_reversal_count"] = date_reversal_count
            entry["ordering_mode"] = "EXTERNAL_STABLE_SORT"
            entry["venue_trade_id_conflict_groups"] = conflict_groups
            entry["venue_trade_id_conflict_count"] = len(conflict_groups)
            entry["archive_interleaved_dates"] = [
                value.isoformat() for value in sorted(interleaved_dates)
            ]
            entries.append(entry)
            source.unlink()
            by_id.unlink()
            classified.unlink()
            ordered.unlink()
        sort_root.rmdir()
        if not entries:
            raise ValueError("archive produced no target rows")
        return entries
    except Exception:
        for spool in spools.values():
            with suppress(Exception):
                spool.close()
        shutil.rmtree(output_root, ignore_errors=True)
        raise


def process_archive(
    archive: Path,
    output_root: Path,
    symbol: Symbol,
    *,
    source_archive_sha256: str | None = None,
    selected_dates: set[date] | None = None,
) -> list[dict[str, object]]:
    lineage_sha256 = source_archive_sha256 or sha256_file(archive)
    try:
        return _process_archive_streaming(
            archive,
            output_root,
            symbol,
            source_archive_sha256=lineage_sha256,
            selected_dates=selected_dates,
        )
    except ArchiveOrderingError:
        return _process_archive_sorted(
            archive,
            output_root,
            symbol,
            source_archive_sha256=lineage_sha256,
            selected_dates=selected_dates,
        )


def _canonical_ids_for_venue_id(archive: Path, symbol: Symbol, venue_trade_id: int) -> set[str]:
    identities: set[str] = set()
    with zipfile.ZipFile(archive) as bundle:
        members = [name for name in bundle.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError("archive must contain exactly one CSV")
        with bundle.open(members[0]) as raw_stream:
            rows = csv.reader(io.TextIOWrapper(raw_stream, encoding="utf-8", newline=""))
            for values in rows:
                if not values or not values[0].strip().lstrip("-").isdigit():
                    continue
                if int(values[0]) != venue_trade_id:
                    continue
                price, _ = canonical_decimal(values[1])
                quantity, _ = canonical_decimal(values[2])
                quote_quantity, _ = canonical_decimal(values[3])
                maker_text = values[5].strip().lower()
                if maker_text not in {"true", "false"}:
                    raise ValueError("invalid isBuyerMaker in conflict evidence")
                identities.add(
                    canonical_trade_identity(
                        instrument=symbol,
                        venue_trade_id=venue_trade_id,
                        ts_event_ns=int(values[4]) * 1_000_000,
                        price=price,
                        quantity=quantity,
                        quote_quantity=quote_quantity,
                        is_buyer_maker=maker_text == "true",
                    )
                )
    return identities


def validate_official_conflicts(
    work_root: Path,
    symbol: Symbol,
    frequency: Frequency,
    entries: list[dict[str, object]],
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for entry in entries:
        groups = cast(list[dict[str, object]], entry.get("venue_trade_id_conflict_groups", []))
        for group in groups:
            partition_date = str(entry["date"])
            result: dict[str, object] = {
                "date": partition_date,
                "conflict_group": group["conflict_group"],
                "monthly_canonical_trade_ids": group["canonical_trade_ids"],
                "monthly_sha256": entry.get("source_archive_sha256"),
            }
            if frequency != "monthly":
                result["status"] = "SOURCE_DISAGREEMENT"
                result["reason"] = "independent daily cross-validation source unavailable"
                results.append(result)
                continue
            daily_url = archive_url(symbol, partition_date, "daily")
            filename = daily_url.rsplit("/", 1)[-1]
            try:
                checksum_text = fetch_text(daily_url + ".CHECKSUM")
                daily_sha = parse_checksum(checksum_text, filename)
                raw_dir = work_root / "raw/trades" / symbol / "daily"
                checksum_path = raw_dir / (filename + ".CHECKSUM")
                checksum_path.parent.mkdir(parents=True, exist_ok=True)
                if checksum_path.exists() and checksum_path.read_text() != checksum_text:
                    raise FileExistsError(f"immutable checksum sidecar conflict: {checksum_path}")
                if not checksum_path.exists():
                    checksum_path.write_text(checksum_text)
                    os.chmod(checksum_path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
                daily_archive = download_archive(daily_url, raw_dir / filename, daily_sha)
                daily_ids = _canonical_ids_for_venue_id(
                    daily_archive, symbol, cast(int, group["venue_trade_id"])
                )
                monthly_ids = set(cast(list[str], group["canonical_trade_ids"]))
                result["daily_sha256"] = daily_sha
                result["daily_canonical_trade_ids"] = sorted(daily_ids)
                result["status"] = (
                    "CONFIRMED_OFFICIAL_CONFLICT"
                    if daily_ids == monthly_ids
                    else "SOURCE_DISAGREEMENT"
                )
            except Exception as exc:
                result["status"] = "SOURCE_DISAGREEMENT"
                result["reason"] = f"{type(exc).__name__}: {exc}"
            results.append(result)
    disagreements = [item for item in results if item["status"] == "SOURCE_DISAGREEMENT"]
    if disagreements:
        raise ValueError(f"official conflict source disagreement: {disagreements}")
    return results


def expected_dates() -> set[str]:
    days = (TARGET_END - TARGET_START).days
    return {(TARGET_START + timedelta(days=offset)).isoformat() for offset in range(days)}


def prepare_archive(
    work_root_text: str,
    symbol: Symbol,
    period: str,
    frequency: Frequency,
) -> tuple[str, str]:
    """Prefetch one immutable official archive and return its key and checksum."""
    work_root = Path(work_root_text)
    key = f"{symbol}/{frequency}/{period}"
    url = archive_url(symbol, period, frequency)
    filename = url.rsplit("/", 1)[-1]
    checksum_text = fetch_text(url + ".CHECKSUM")
    expected = parse_checksum(checksum_text, filename)
    raw_dir = work_root / "raw/trades" / symbol / frequency
    checksum_path = raw_dir / (filename + ".CHECKSUM")
    checksum_path.parent.mkdir(parents=True, exist_ok=True)
    if checksum_path.exists() and checksum_path.read_text() != checksum_text:
        raise FileExistsError(f"immutable checksum sidecar conflict: {checksum_path}")
    if not checksum_path.exists():
        checksum_path.write_text(checksum_text)
        os.chmod(checksum_path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    download_archive(url, raw_dir / filename, expected)
    return key, expected


def build_prepared_archive(
    work_root_text: str,
    run_id: str,
    symbol: Symbol,
    period: str,
    frequency: Frequency,
    expected: str,
) -> tuple[str, list[dict[str, object]]]:
    """Build one previously checksummed raw archive in an isolated staging path."""
    work_root = Path(work_root_text)
    key = f"{symbol}/{frequency}/{period}"
    url = archive_url(symbol, period, frequency)
    filename = url.rsplit("/", 1)[-1]
    archive = work_root / "raw/trades" / symbol / frequency / filename
    if not archive.exists():
        raise FileNotFoundError(f"prefetched archive missing: {archive}")
    archive_root = work_root / "staging" / run_id / symbol / f"archive={period}"
    if archive_root.exists():
        archive_summary = json.loads((archive_root / "archive.json").read_text())
        return key, cast(list[dict[str, object]], archive_summary["entries"])
    temporary = archive_root.with_name(archive_root.name + ".tmp")
    shutil.rmtree(temporary, ignore_errors=True)
    entries = process_archive(archive, temporary, symbol, source_archive_sha256=expected)
    for entry in entries:
        entry["source_archive_sha256"] = expected
    conflict_validation = validate_official_conflicts(work_root, symbol, frequency, entries)
    for entry in entries:
        entry["official_conflict_validation"] = [
            item for item in conflict_validation if item["date"] == entry["date"]
        ]
    atomic_json(
        temporary / "archive.json",
        {
            "archive": key,
            "url": url,
            "official_sha256": expected,
            "archive_bytes": archive.stat().st_size,
            "entries": entries,
            "conflict_validation": conflict_validation,
        },
    )
    os.replace(temporary, archive_root)
    return key, entries


def build_one_archive(
    work_root_text: str,
    run_id: str,
    symbol: Symbol,
    period: str,
    frequency: Frequency,
) -> tuple[str, list[dict[str, object]]]:
    """Compatibility wrapper for one-shot download and build."""
    _, expected = prepare_archive(work_root_text, symbol, period, frequency)
    return build_prepared_archive(work_root_text, run_id, symbol, period, frequency, expected)


def round_robin_inventory(
    pending_by_symbol: dict[Symbol, list[tuple[Symbol, str, Frequency]]],
) -> list[tuple[Symbol, str, Frequency]]:
    """Interleave BTC and ETH downloads without changing per-symbol chronology."""
    ordered: list[tuple[Symbol, str, Frequency]] = []
    longest = max((len(items) for items in pending_by_symbol.values()), default=0)
    for index in range(longest):
        for symbol in SYMBOLS:
            if index < len(pending_by_symbol[symbol]):
                ordered.append(pending_by_symbol[symbol][index])
    return ordered


class FullBuild:
    def __init__(self, work_root: Path, run_id: str, code_commit: str, config_hash: str) -> None:
        self.work_root = work_root
        self.run_id = run_id
        self.code_commit = code_commit
        self.config_hash = config_hash
        self.checkpoint_path = work_root / "catalog/runs" / run_id / "checkpoint.json"
        self.manifest_path = work_root / "catalog/runs" / run_id / "manifest.json"
        self.report_path = work_root / "catalog/runs" / run_id / "quality_report.json"

    def initial_checkpoint(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "dataset_version": SCHEMA_VERSION,
            "code_commit": self.code_commit,
            "config_hash": self.config_hash,
            "status": "IN_PROGRESS",
            "created_at": datetime.now(tz=UTC).isoformat(),
            "completed_archives": [],
            "prefetched_archives": [],
            "download_workers": DOWNLOAD_WORKERS,
            "symbols": {symbol: {"status": "PENDING", "entries": []} for symbol in SYMBOLS},
            "errors": [],
        }

    def load_or_create(self) -> dict[str, Any]:
        if self.checkpoint_path.exists():
            checkpoint: dict[str, Any] = json.loads(self.checkpoint_path.read_text())
            if (
                checkpoint["code_commit"] != self.code_commit
                or checkpoint["config_hash"] != self.config_hash
            ):
                raise ValueError("run identity does not match code/config")
            checkpoint.setdefault("prefetched_archives", [])
            checkpoint.setdefault("download_workers", DOWNLOAD_WORKERS)
            return checkpoint
        checkpoint = self.initial_checkpoint()
        atomic_json(self.checkpoint_path, checkpoint)
        return checkpoint

    def assert_disk(self) -> None:
        free = shutil.disk_usage(self.work_root).free
        if free < MINIMUM_FREE_BYTES:
            raise OSError(f"disk safety gate: free={free}, required={MINIMUM_FREE_BYTES}")

    def run(self) -> dict[str, Any]:
        checkpoint = self.load_or_create()
        completed = set(checkpoint["completed_archives"])
        pending_by_symbol = {
            symbol: [
                item
                for item in archive_inventory()
                if item[0] == symbol and f"{item[0]}/{item[2]}/{item[1]}" not in completed
            ]
            for symbol in SYMBOLS
        }
        download_queue = iter(round_robin_inventory(pending_by_symbol))
        ready: dict[str, str] = {}
        prefetched = set(cast(list[str], checkpoint["prefetched_archives"]))
        with (
            ThreadPoolExecutor(
                max_workers=DOWNLOAD_WORKERS, thread_name_prefix="stage1-download"
            ) as download_executor,
            ProcessPoolExecutor(max_workers=len(SYMBOLS)) as build_executor,
        ):
            active_downloads: dict[Future[tuple[str, str]], tuple[Symbol, str, Frequency]] = {}
            active_builds: dict[
                Future[tuple[str, list[dict[str, object]]]],
                tuple[Symbol, str, Frequency],
            ] = {}
            download_exhausted = False

            def fill_download_pool() -> None:
                nonlocal download_exhausted
                while not download_exhausted and len(active_downloads) < DOWNLOAD_WORKERS:
                    try:
                        item = next(download_queue)
                    except StopIteration:
                        download_exhausted = True
                        return
                    self.assert_disk()
                    future = download_executor.submit(
                        prepare_archive,
                        str(self.work_root),
                        item[0],
                        item[1],
                        item[2],
                    )
                    active_downloads[future] = item

            def submit_ready_builds() -> None:
                busy_symbols = {item[0] for item in active_builds.values()}
                for symbol in SYMBOLS:
                    if symbol in busy_symbols or not pending_by_symbol[symbol]:
                        continue
                    item = pending_by_symbol[symbol][0]
                    key = f"{item[0]}/{item[2]}/{item[1]}"
                    expected = ready.get(key)
                    if expected is None:
                        continue
                    self.assert_disk()
                    future = build_executor.submit(
                        build_prepared_archive,
                        str(self.work_root),
                        self.run_id,
                        item[0],
                        item[1],
                        item[2],
                        expected,
                    )
                    active_builds[future] = item

            def record_failure(kind: str, key: str, exc: BaseException) -> None:
                checkpoint["last_error"] = {
                    "at": datetime.now(tz=UTC).isoformat(),
                    "kind": kind,
                    "archive": key,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                checkpoint["errors"].append(checkpoint["last_error"])
                atomic_json(self.checkpoint_path, checkpoint)

            fill_download_pool()
            while active_downloads or active_builds:
                submit_ready_builds()
                all_active: set[Future[Any]] = set(active_downloads) | set(active_builds)
                if not all_active:
                    raise RuntimeError("pipeline stalled with pending archives")
                done, _ = wait(all_active, return_when=FIRST_COMPLETED)
                for future in done:
                    if future in active_downloads:
                        item = active_downloads.pop(cast(Future[tuple[str, str]], future))
                        key = f"{item[0]}/{item[2]}/{item[1]}"
                        try:
                            prepared_key, expected = future.result()
                        except BaseException as exc:
                            record_failure("DOWNLOAD", key, exc)
                            for download_pending in active_downloads:
                                download_pending.cancel()
                            for build_pending in active_builds:
                                build_pending.cancel()
                            raise
                        ready[prepared_key] = expected
                        if prepared_key not in prefetched:
                            checkpoint["prefetched_archives"].append(prepared_key)
                            prefetched.add(prepared_key)
                            atomic_json(self.checkpoint_path, checkpoint)
                    else:
                        typed_future = cast(Future[tuple[str, list[dict[str, object]]]], future)
                        item = active_builds.pop(typed_future)
                        key = f"{item[0]}/{item[2]}/{item[1]}"
                        try:
                            built_key, entries = typed_future.result()
                        except BaseException as exc:
                            record_failure("BUILD", key, exc)
                            for download_pending in active_downloads:
                                download_pending.cancel()
                            for build_pending in active_builds:
                                build_pending.cancel()
                            raise
                        symbol = item[0]
                        if built_key != key or pending_by_symbol[symbol][0] != item:
                            raise RuntimeError("pipeline archive ordering invariant failed")
                        pending_by_symbol[symbol].pop(0)
                        ready.pop(built_key, None)
                        checkpoint["symbols"][symbol]["entries"].extend(entries)
                        checkpoint["completed_archives"].append(built_key)
                        completed.add(built_key)
                        atomic_json(self.checkpoint_path, checkpoint)
                fill_download_pool()
        self._finalize(checkpoint)
        return checkpoint

    def _finalize(self, checkpoint: dict[str, Any]) -> None:
        expected = expected_dates()
        for symbol in SYMBOLS:
            entries = checkpoint["symbols"][symbol]["entries"]
            dates = {entry["date"] for entry in entries}
            missing = sorted(expected - dates)
            duplicates = len(entries) - len(dates)
            if missing or duplicates:
                raise ValueError(
                    f"{symbol} coverage invalid: missing={missing[:20]}, duplicates={duplicates}"
                )
            counts = sorted(int(entry["rows"]) for entry in entries)
            median = counts[len(counts) // 2]
            outliers = [
                entry["date"]
                for entry in entries
                if int(entry["rows"]) < median / 10 or int(entry["rows"]) > median * 10
            ]
            logical = hashlib.sha256()
            for entry in sorted(entries, key=lambda item: item["date"]):
                logical.update(
                    f"{entry['date']}|{entry['rows']}|{entry['logical_sha256']}\n".encode()
                )
            checkpoint["symbols"][symbol].update(
                {
                    "status": "READY_TO_PUBLISH",
                    "date_start": min(dates),
                    "date_end_inclusive": max(dates),
                    "rows": sum(int(entry["rows"]) for entry in entries),
                    "input_rows": sum(
                        int(entry.get("source_input_rows", entry["input_rows"]))
                        for entry in entries
                    ),
                    "duplicate_exact_count": sum(
                        int(entry["duplicate_exact_count"]) for entry in entries
                    ),
                    "venue_trade_id_conflict_count": sum(
                        int(entry.get("venue_trade_id_conflict_count", 0)) for entry in entries
                    ),
                    "official_conflict_validation": [
                        validation
                        for entry in entries
                        for validation in cast(
                            list[dict[str, object]], entry.get("official_conflict_validation", [])
                        )
                    ],
                    "partitions": len(entries),
                    "logical_data_hash": logical.hexdigest(),
                    "count_outlier_review": outliers,
                }
            )
            atomic_json(
                self.work_root / "catalog/runs" / self.run_id / f"{symbol}.catalog.json",
                checkpoint["symbols"][symbol],
            )
        self._verify_determinism(checkpoint)
        for symbol in SYMBOLS:
            staging = self.work_root / "staging" / self.run_id / symbol
            published = self.work_root / "published" / SCHEMA_VERSION / self.run_id / symbol
            published.parent.mkdir(parents=True, exist_ok=True)
            if published.exists():
                raise FileExistsError(f"published symbol already exists: {published}")
            os.replace(staging, published)
            checkpoint["symbols"][symbol]["status"] = "PUBLISHED"
            atomic_json(self.checkpoint_path, checkpoint)
        manifest = {
            "run_id": self.run_id,
            "dataset_version": SCHEMA_VERSION,
            "code_commit": self.code_commit,
            "config_hash": self.config_hash,
            "source": "Binance official public USD-M Futures Trades archives",
            "target_interval": "[2020-01-01T00:00:00Z,2026-07-04T00:00:00Z)",
            "historical_unavailable_fields": UNAVAILABLE_FIELDS,
            "symbols": checkpoint["symbols"],
        }
        canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        manifest["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
        atomic_json(self.manifest_path, manifest)
        atomic_json(
            self.report_path,
            {
                "status": "PASS",
                "symbols": {
                    symbol: {
                        "rows": checkpoint["symbols"][symbol]["rows"],
                        "input_rows": checkpoint["symbols"][symbol]["input_rows"],
                        "duplicate_exact_count": checkpoint["symbols"][symbol][
                            "duplicate_exact_count"
                        ],
                        "venue_trade_id_conflict_count": checkpoint["symbols"][symbol][
                            "venue_trade_id_conflict_count"
                        ],
                        "official_conflict_validation": checkpoint["symbols"][symbol][
                            "official_conflict_validation"
                        ],
                        "partitions": checkpoint["symbols"][symbol]["partitions"],
                        "count_outlier_review": checkpoint["symbols"][symbol][
                            "count_outlier_review"
                        ],
                    }
                    for symbol in SYMBOLS
                },
                "errors": checkpoint["errors"],
            },
        )
        checkpoint["status"] = "COMPLETE"
        checkpoint["completed_at"] = datetime.now(tz=UTC).isoformat()
        atomic_json(self.checkpoint_path, checkpoint)

    def _verify_determinism(self, checkpoint: dict[str, Any]) -> None:
        verification_root = self.work_root / "tmp" / self.run_id / "determinism"
        shutil.rmtree(verification_root, ignore_errors=True)
        for symbol in SYMBOLS:
            original = {entry["date"]: entry for entry in checkpoint["symbols"][symbol]["entries"]}
            for target in sorted(DETERMINISM_DATES):
                frequency: Frequency = "daily" if target >= date(2026, 7, 1) else "monthly"
                period = target.isoformat() if frequency == "daily" else target.strftime("%Y-%m")
                url = archive_url(symbol, period, frequency)
                archive = (
                    self.work_root / "raw/trades" / symbol / frequency / url.rsplit("/", 1)[-1]
                )
                output = verification_root / symbol / target.isoformat()
                rebuilt = process_archive(archive, output, symbol, selected_dates={target})
                if len(rebuilt) != 1:
                    raise ValueError("determinism rebuild produced wrong partition count")
                expected = original[target.isoformat()]
                for field in ("date", "rows", "logical_sha256"):
                    if rebuilt[0][field] != expected[field]:
                        raise ValueError(f"determinism mismatch {symbol} {target} {field}")
        shutil.rmtree(verification_root, ignore_errors=True)


def checkpoint_status(work_root: Path, run_id: str) -> dict[str, Any]:
    path = work_root / "catalog/runs" / run_id / "checkpoint.json"
    if not path.exists():
        raise FileNotFoundError(path)
    checkpoint: dict[str, Any] = json.loads(path.read_text())
    return checkpoint
