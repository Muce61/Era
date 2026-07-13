from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import stat
import time
import zipfile
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
    def __init__(self, root: Path, symbol: Symbol, partition_date: date) -> None:
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

    def append(self, values: list[str]) -> None:
        if len(values) != 6:
            raise ValueError(f"unexpected Trades column count: {len(values)}")
        trade_id = int(values[0])
        price, price_text = canonical_decimal(values[1])
        quantity, quantity_text = canonical_decimal(values[2])
        quote_quantity, quote_text = canonical_decimal(values[3])
        timestamp_ms = int(values[4])
        maker_text = values[5].strip().lower()
        if price <= 0 or quantity <= 0 or quote_quantity < 0:
            raise ValueError("trade price/quantity must be positive")
        if maker_text not in {"true", "false"}:
            raise ValueError(f"invalid isBuyerMaker: {values[5]}")
        event_date = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).date()
        if event_date != self.partition_date:
            raise ValueError(f"trade falls outside partition date: {event_date}")
        ts_event_ns = timestamp_ms * 1_000_000
        if self.last_trade_id is not None:
            if trade_id == self.last_trade_id:
                raise ValueError(f"duplicate trade_id: {trade_id}")
            if trade_id < self.last_trade_id:
                raise ValueError(f"trade_id reversal: {trade_id}")
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
        self.logical_hash.update(canonical)
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
        self.rows += 1
        if len(self.batch) >= 100_000:
            self.flush()

    def flush(self) -> None:
        if self.batch:
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
            "first_trade_id": self.first_trade_id,
            "last_trade_id": self.last_trade_id,
            "last_ts_ns": self.last_ts_ns,
            "trade_id_gap_count": self.gap_count,
            "trade_id_gap_examples": self.gap_examples,
            "byte_sha256": sha256_file(self.path),
            "logical_sha256": self.logical_hash.hexdigest(),
            "bytes": self.path.stat().st_size,
        }
        atomic_json(self.directory / "partition.json", result)
        return result


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
                            raise ValueError("archive date reversal")
                        if writer is not None:
                            entries.append(writer.close())
                        writer = PartitionWriter(output_root, symbol, row_date)
                        current_date = row_date
                    assert writer is not None
                    writer.append(values)
        if writer is not None:
            entries.append(writer.close())
        if not entries:
            raise ValueError("archive produced no target rows")
        return entries
    except Exception:
        if writer is not None:
            writer.writer.close()
        shutil.rmtree(output_root, ignore_errors=True)
        raise


def expected_dates() -> set[str]:
    days = (TARGET_END - TARGET_START).days
    return {(TARGET_START + timedelta(days=offset)).isoformat() for offset in range(days)}


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
        for symbol, period, frequency in archive_inventory():
            key = f"{symbol}/{frequency}/{period}"
            if key in completed:
                continue
            self.assert_disk()
            url = archive_url(symbol, period, frequency)
            filename = url.rsplit("/", 1)[-1]
            checksum_text = fetch_text(url + ".CHECKSUM")
            expected = parse_checksum(checksum_text, filename)
            raw_dir = self.work_root / "raw/trades" / symbol / frequency
            checksum_path = raw_dir / (filename + ".CHECKSUM")
            checksum_path.parent.mkdir(parents=True, exist_ok=True)
            if checksum_path.exists() and checksum_path.read_text() != checksum_text:
                raise FileExistsError(f"immutable checksum sidecar conflict: {checksum_path}")
            if not checksum_path.exists():
                checksum_path.write_text(checksum_text)
                os.chmod(checksum_path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
            archive = download_archive(url, raw_dir / filename, expected)
            archive_root = self.work_root / "staging" / self.run_id / symbol / f"archive={period}"
            if archive_root.exists():
                archive_summary = json.loads((archive_root / "archive.json").read_text())
                entries = archive_summary["entries"]
            else:
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
            checkpoint["symbols"][symbol]["entries"].extend(entries)
            checkpoint["completed_archives"].append(key)
            atomic_json(self.checkpoint_path, checkpoint)
            completed.add(key)
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
