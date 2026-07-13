from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import time
import zipfile
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
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

Symbol = Literal["BTCUSDT", "ETHUSDT"]
Frequency = Literal["monthly", "daily"]
SYMBOLS: tuple[Symbol, ...] = ("BTCUSDT", "ETHUSDT")
TARGET_START = date(2020, 1, 1)
TARGET_END = date(2026, 7, 4)
DETERMINISM_DATES = {date(2020, 1, 1), date(2023, 4, 2), date(2026, 7, 3)}
MINIMUM_FREE_BYTES = 585_983_717_541
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

ARROW_SCHEMA = pa.schema(
    [
        ("instrument", pa.string()),
        ("trade_id", pa.int64()),
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
                    partial.unlink(missing_ok=True)
                    raise OSError("server refused Range resume; partial reset")
                with partial.open("ab" if offset else "wb") as output:
                    for block in iter(lambda: response.read(4 * 1024 * 1024), b""):
                        output.write(block)
            actual = sha256_file(partial)
            if actual != expected_sha256:
                partial.unlink(missing_ok=True)
                raise ValueError(f"archive checksum mismatch: {actual}")
            os.chmod(partial, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
            os.replace(partial, destination)
            return destination
        except HTTPError as exc:
            if exc.code == 404:
                raise FileNotFoundError(url) from exc
            if attempt == 7:
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
        permit_trade_id_reversal: bool = False,
    ) -> None:
        self.symbol = symbol
        self.partition_date = partition_date
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
        if len(values) != 6:
            raise ValueError(f"unexpected Trades column count: {len(values)}")
        self.input_rows += 1
        trade_id = int(values[0])
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
        signature = (
            trade_id,
            price_text,
            quantity_text,
            quote_text,
            ts_event_ns,
            maker_text,
        )
        if self.last_trade_id is not None:
            if trade_id == self.last_trade_id:
                if signature == self.last_signature:
                    self.duplicate_exact_count += 1
                    return
                raise ValueError(f"conflicting duplicate trade_id: {trade_id}")
            if trade_id < self.last_trade_id:
                if not self.permit_trade_id_reversal:
                    raise ValueError(f"trade_id reversal: {trade_id}")
                self.trade_id_reversal_count += 1
                if len(self.trade_id_reversal_examples) < 100:
                    self.trade_id_reversal_examples.append(f"{self.last_trade_id}->{trade_id}")
            if trade_id > self.last_trade_id + 1:
                self.gap_count += trade_id - self.last_trade_id - 1
                if len(self.gap_examples) < 100:
                    self.gap_examples.append(f"{self.last_trade_id + 1}-{trade_id - 1}")
        if self.last_ts_ns is not None and ts_event_ns < self.last_ts_ns:
            raise ValueError(f"timestamp reversal at trade_id {trade_id}")
        maker = maker_text == "true"
        canonical = (
            f"{self.symbol}|{trade_id}|{price_text}|{quantity_text}|{quote_text}|"
            f"{ts_event_ns}|{maker_text}|{'SELL' if maker else 'BUY'}\n"
        ).encode()
        self.hash_batch.extend(canonical)
        self.batch.append(
            {
                "instrument": self.symbol,
                "trade_id": trade_id,
                "price": price,
                "quantity": quantity,
                "quote_quantity": quote_quantity,
                "ts_event_ns": ts_event_ns,
                "is_buyer_maker": maker,
                "aggressor_side": "SELL" if maker else "BUY",
            }
        )
        self.first_trade_id = trade_id if self.first_trade_id is None else self.first_trade_id
        self.last_trade_id = trade_id
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
            "first_trade_id": self.first_trade_id,
            "last_trade_id": self.last_trade_id,
            "last_ts_ns": self.last_ts_ns,
            "trade_id_gap_count": self.gap_count,
            "trade_id_gap_examples": self.gap_examples,
            "trade_id_reversal_count": self.trade_id_reversal_count,
            "trade_id_reversal_examples": self.trade_id_reversal_examples,
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


def _assert_no_conflicting_trade_ids(path: Path) -> None:
    previous_id: str | None = None
    previous_line: bytes | None = None
    with path.open("rb") as stream:
        for line in stream:
            fields = line.rstrip(b"\n").split(b"\t")
            trade_id = fields[1].decode()
            if trade_id == previous_id and line != previous_line:
                raise ValueError(f"conflicting duplicate trade_id: {trade_id}")
            previous_id = trade_id
            previous_line = line


def process_archive(
    archive: Path,
    output_root: Path,
    symbol: Symbol,
    *,
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
                        row_date, {"timestamp": 0, "trade_id": 0}
                    )
                    if previous is not None:
                        counters["timestamp"] += int(timestamp_ms < previous[0])
                        counters["trade_id"] += int(trade_id < previous[1])
                    source_previous[row_date] = (timestamp_ms, trade_id)
                    spool = spools.get(row_date)
                    if spool is None:
                        spool = (sort_root / f"{row_date.isoformat()}.input.tsv").open("w")
                        spools[row_date] = spool
                        raw_hashes[row_date] = hashlib.sha256()
                        input_rows[row_date] = 0
                    canonical_line = (
                        f"{timestamp_ms}\t{trade_id}\t{price_text}\t{quantity_text}\t"
                        f"{quote_text}\t{maker_text}\n"
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
            ordered = sort_root / f"{partition_date.isoformat()}.ordered.tsv"
            _external_sort(
                source,
                by_id,
                ("-k2,2n", "-k1,1n", "-k3,3", "-k4,4", "-k5,5", "-k6,6"),
                sort_root,
            )
            _assert_no_conflicting_trade_ids(by_id)
            _external_sort(
                by_id,
                ordered,
                ("-k1,1n", "-k2,2n", "-k3,3", "-k4,4", "-k5,5", "-k6,6"),
                sort_root,
            )
            writer = PartitionWriter(
                output_root,
                symbol,
                partition_date,
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
                    ) = line.rstrip("\n").split("\t")
                    writer.append(
                        [
                            sorted_trade_id,
                            sorted_price,
                            sorted_quantity,
                            sorted_quote,
                            timestamp_text,
                            sorted_maker,
                        ],
                        partition_date,
                        int(timestamp_text),
                    )
            entry = writer.close()
            entry["source_input_rows"] = input_rows[partition_date]
            entry["source_order_sha256"] = raw_hashes[partition_date].hexdigest()
            entry["source_timestamp_reversal_count"] = source_reversals[partition_date]["timestamp"]
            entry["source_trade_id_reversal_count"] = source_reversals[partition_date]["trade_id"]
            entry["archive_date_reversal_count"] = date_reversal_count
            entry["archive_interleaved_dates"] = [
                value.isoformat() for value in sorted(interleaved_dates)
            ]
            entries.append(entry)
            source.unlink()
            by_id.unlink()
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


def expected_dates() -> set[str]:
    days = (TARGET_END - TARGET_START).days
    return {(TARGET_START + timedelta(days=offset)).isoformat() for offset in range(days)}


def build_one_archive(
    work_root_text: str,
    run_id: str,
    symbol: Symbol,
    period: str,
    frequency: Frequency,
) -> tuple[str, list[dict[str, object]]]:
    """Download, validate and build one immutable archive in an isolated path."""
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
    archive = download_archive(url, raw_dir / filename, expected)
    archive_root = work_root / "staging" / run_id / symbol / f"archive={period}"
    if archive_root.exists():
        archive_summary = json.loads((archive_root / "archive.json").read_text())
        return key, cast(list[dict[str, object]], archive_summary["entries"])
    temporary = archive_root.with_name(archive_root.name + ".tmp")
    shutil.rmtree(temporary, ignore_errors=True)
    entries = process_archive(archive, temporary, symbol)
    atomic_json(
        temporary / "archive.json",
        {
            "archive": key,
            "url": url,
            "official_sha256": expected,
            "archive_bytes": archive.stat().st_size,
            "entries": entries,
        },
    )
    os.replace(temporary, archive_root)
    return key, entries


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
            "dataset_version": "stage1-v1.0",
            "code_commit": self.code_commit,
            "config_hash": self.config_hash,
            "status": "IN_PROGRESS",
            "created_at": datetime.now(tz=UTC).isoformat(),
            "completed_archives": [],
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
        with ProcessPoolExecutor(max_workers=len(SYMBOLS)) as executor:
            active: dict[Future[tuple[str, list[dict[str, object]]]], Symbol] = {}

            def submit_next(symbol: Symbol) -> None:
                if not pending_by_symbol[symbol]:
                    return
                self.assert_disk()
                item = pending_by_symbol[symbol].pop(0)
                future = executor.submit(
                    build_one_archive,
                    str(self.work_root),
                    self.run_id,
                    item[0],
                    item[1],
                    item[2],
                )
                active[future] = symbol

            for symbol in SYMBOLS:
                submit_next(symbol)
            while active:
                done, _ = wait(active, return_when=FIRST_COMPLETED)
                for future in done:
                    symbol = active.pop(future)
                    key, entries = future.result()
                    checkpoint["symbols"][symbol]["entries"].extend(entries)
                    checkpoint["completed_archives"].append(key)
                    completed.add(key)
                    atomic_json(self.checkpoint_path, checkpoint)
                    submit_next(symbol)
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
                    "input_rows": sum(int(entry["input_rows"]) for entry in entries),
                    "duplicate_exact_count": sum(
                        int(entry["duplicate_exact_count"]) for entry in entries
                    ),
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
            published = self.work_root / "published/stage1-v1.0" / self.run_id / symbol
            published.parent.mkdir(parents=True, exist_ok=True)
            if published.exists():
                raise FileExistsError(f"published symbol already exists: {published}")
            os.replace(staging, published)
            checkpoint["symbols"][symbol]["status"] = "PUBLISHED"
            atomic_json(self.checkpoint_path, checkpoint)
        manifest = {
            "run_id": self.run_id,
            "dataset_version": "stage1-v1.0",
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
