"""Authoritative Stage 1 source indexes for the reusable Feature Foundation.

The indexes deliberately use the frozen Stage 1 Catalog and the bounded
Contract Price inventory.  They never discover research input through a
recursive glob and never treat staging, temporary, or AppleDouble files as
source data.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.research.stage_2.manifests.models import canonical_json
from era100x.research.stage_2.pipelines.candidates.stage1_catalog import (
    Stage1TradesPartition,
    sha256_file,
)

Instrument = Literal["BTCUSDT", "ETHUSDT"]
INSTRUMENTS: tuple[Instrument, ...] = ("BTCUSDT", "ETHUSDT")
CONTRACT_FILE = re.compile(r"^(BTCUSDT|ETHUSDT)_1s_(\d{8})\.(csv|parquet)$")
ROW_GROUP_INDEX_SCHEMA = pa.schema(
    [
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("partition_date", pa.date32(), nullable=False),
        pa.field("source_relative_path", pa.string(), nullable=False),
        pa.field("source_byte_sha256", pa.string(), nullable=False),
        pa.field("source_logical_sha256", pa.string(), nullable=False),
        pa.field("row_group_ordinal", pa.int32(), nullable=False),
        pa.field("row_count", pa.int64(), nullable=False),
        pa.field("event_start_ns", pa.int64(), nullable=False),
        pa.field("event_end_ns_exclusive", pa.int64(), nullable=False),
    ]
)


@dataclass(frozen=True, order=True, slots=True)
class ContractPricePartition:
    instrument: Instrument
    partition_date: date
    path: Path
    source_format: Literal["CSV", "PARQUET"]
    byte_size: int
    byte_sha256: str


class ContractPriceInventoryIndex:
    """Exact, read-only view of the preregistered Contract Price inventory."""

    def __init__(
        self,
        *,
        root: Path,
        partitions: tuple[ContractPricePartition, ...],
        inventory_hash: str,
        inventory_file_count: int,
    ) -> None:
        self.root = root.resolve()
        self.partitions = partitions
        self.inventory_hash = inventory_hash
        self.inventory_file_count = inventory_file_count
        self._by_key = {
            (partition.instrument, partition.partition_date): partition for partition in partitions
        }

    @classmethod
    def load(
        cls,
        *,
        root: Path,
        expected_inventory_hash: str,
        start: date = date(2020, 1, 1),
        end_exclusive: date = date(2026, 7, 4),
        expected_csv_count: int = 2016,
        expected_parquet_count: int = 371,
        expected_overlap_count: int = 11,
    ) -> ContractPriceInventoryIndex:
        root = root.resolve()
        records: list[dict[str, object]] = []
        canonical: list[ContractPricePartition] = []
        inventory_count = 0
        for instrument in INSTRUMENTS:
            directory = (root / f"{instrument}_1s_agg").resolve()
            if not directory.is_dir() or not directory.is_relative_to(root):
                raise FileNotFoundError(f"missing Contract Price directory: {directory}")
            csv_files = tuple(sorted(directory.glob(f"{instrument}_1s_*.csv")))
            parquet_files = tuple(sorted(directory.glob(f"{instrument}_1s_*.parquet")))
            if len(csv_files) != expected_csv_count or len(parquet_files) != expected_parquet_count:
                raise ValueError(
                    f"{instrument} Contract Price inventory changed: "
                    f"csv={len(csv_files)}, parquet={len(parquet_files)}"
                )
            by_date: dict[str, dict[str, ContractPricePartition]] = {}
            for path in (*csv_files, *parquet_files):
                if path.name.startswith("._"):
                    raise ValueError("AppleDouble cannot enter the Contract Price inventory")
                match = CONTRACT_FILE.fullmatch(path.name)
                if match is None or match.group(1) != instrument:
                    raise ValueError(f"unrecognized Contract Price filename: {path.name}")
                partition_date = _compact_date(match.group(2))
                suffix = path.suffix
                source_format: Literal["CSV", "PARQUET"] = "CSV" if suffix == ".csv" else "PARQUET"
                resolved = path.resolve()
                if not resolved.is_file() or not resolved.is_relative_to(directory):
                    raise ValueError(f"unsafe Contract Price path: {path}")
                item = ContractPricePartition(
                    instrument=instrument,
                    partition_date=partition_date,
                    path=resolved,
                    source_format=source_format,
                    byte_size=resolved.stat().st_size,
                    byte_sha256=sha256_file(resolved),
                )
                day_formats = by_date.setdefault(match.group(2), {})
                if suffix in day_formats:
                    raise ValueError(f"duplicate Contract Price format: {instrument} {path.name}")
                day_formats[suffix] = item
                records.append(
                    {
                        "instrument": instrument,
                        "date": match.group(2),
                        "relative_path": str(resolved.relative_to(root)),
                        "bytes": item.byte_size,
                        "sha256": item.byte_sha256,
                        "canonical_for_date": suffix == ".csv" or ".csv" not in day_formats,
                    }
                )
                inventory_count += 1
            expected_days = (end_exclusive - start).days
            if len(by_date) != expected_days:
                raise ValueError(
                    f"{instrument} Contract Price date coverage changed: {len(by_date)}"
                )
            if sum(set(formats) == {".csv", ".parquet"} for formats in by_date.values()) != (
                expected_overlap_count
            ):
                raise ValueError(f"{instrument} Contract Price overlap policy changed")
            current = start
            while current < end_exclusive:
                formats = by_date.get(current.strftime("%Y%m%d"))
                if formats is None:
                    raise FileNotFoundError(
                        f"Contract Price coverage missing: {instrument} {current.isoformat()}"
                    )
                canonical.append(formats[".csv"] if ".csv" in formats else formats[".parquet"])
                current += timedelta(days=1)

        computed = hashlib.sha256(canonical_json(records).encode()).hexdigest()
        if computed != expected_inventory_hash:
            raise ValueError("Contract Price inventory hash changed")
        return cls(
            root=root,
            partitions=tuple(sorted(canonical)),
            inventory_hash=computed,
            inventory_file_count=inventory_count,
        )

    def get(self, instrument: Instrument, partition_date: date) -> ContractPricePartition:
        try:
            return self._by_key[(instrument, partition_date)]
        except KeyError as exc:
            raise FileNotFoundError(
                f"Contract Price coverage missing: {instrument} {partition_date.isoformat()}"
            ) from exc


def trade_row_group_index(
    partition: Stage1TradesPartition,
    *,
    published_root: Path,
) -> pa.Table:
    """Read only Parquet footer statistics for exact H2 row-group routing."""

    published_root = published_root.resolve()
    source = partition.path.resolve()
    if not source.is_relative_to(published_root) or not source.is_file():
        raise ValueError("Stage 1 Trades path is outside the frozen published root")
    parquet = pq.ParquetFile(source)
    metadata = parquet.metadata
    if metadata is None:
        raise ValueError("Stage 1 Trades Parquet metadata is unavailable")
    schema_names = tuple(parquet.schema_arrow.names)
    try:
        timestamp_index = schema_names.index("ts_event_ns")
    except ValueError as exc:
        raise ValueError("Stage 1 Trades is missing ts_event_ns") from exc
    rows: list[dict[str, object]] = []
    for ordinal in range(metadata.num_row_groups):
        row_group = metadata.row_group(ordinal)
        statistics = row_group.column(timestamp_index).statistics
        if statistics is None or not statistics.has_min_max:
            raise ValueError("Stage 1 Trades row group lacks timestamp statistics")
        minimum = int(statistics.min)
        maximum = int(statistics.max)
        if minimum < 0 or maximum < minimum:
            raise ValueError("Stage 1 Trades row-group timestamp statistics are invalid")
        rows.append(
            {
                "instrument": partition.instrument,
                "partition_date": partition.partition_date,
                "source_relative_path": source.relative_to(published_root).as_posix(),
                "source_byte_sha256": partition.byte_sha256,
                "source_logical_sha256": partition.logical_sha256,
                "row_group_ordinal": ordinal,
                "row_count": row_group.num_rows,
                "event_start_ns": minimum,
                "event_end_ns_exclusive": maximum + 1,
            }
        )
    table = pa.Table.from_pylist(rows, schema=ROW_GROUP_INDEX_SCHEMA)
    if table.num_rows != metadata.num_row_groups:
        raise AssertionError("row-group index is incomplete")
    return table


def _compact_date(value: str) -> date:
    if len(value) != 8 or not value.isdigit():
        raise ValueError(f"invalid compact UTC date: {value}")
    return date(int(value[:4]), int(value[4:6]), int(value[6:]))
