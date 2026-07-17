"""Catalog-authoritative, read-only Stage 1 Trades partition resolution."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from era100x.research.stage_2.manifests.models import canonical_json

Instrument = Literal["BTCUSDT", "ETHUSDT"]
INSTRUMENTS: tuple[Instrument, ...] = ("BTCUSDT", "ETHUSDT")
DIRECT_RELATIVE_PATH = re.compile(r"^date=(\d{4}-\d{2}-\d{2})/part-000\.parquet$")
ARCHIVE_RELATIVE_PATH = re.compile(
    r"^archive=(\d{4}-\d{2}(?:-\d{2})?)/date=(\d{4}-\d{2}-\d{2})/part-000\.parquet$"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class Stage1CatalogAuthority:
    data_run_id: str
    dataset_version: str
    canonical_manifest_sha256: str
    physical_manifest_sha256: str
    catalog_sha256s: dict[Instrument, str]
    logical_hashes: dict[Instrument, str]


@dataclass(frozen=True, order=True)
class Stage1TradesPartition:
    instrument: Instrument
    partition_date: date
    archive_partition: str
    path: Path
    byte_sha256: str
    logical_sha256: str

    def canonical_record(self, published_root: Path) -> dict[str, str]:
        return {
            "instrument": self.instrument,
            "partition_date": self.partition_date.isoformat(),
            "archive_partition": self.archive_partition,
            "relative_path": self.path.relative_to(published_root).as_posix(),
            "byte_sha256": self.byte_sha256,
            "logical_sha256": self.logical_sha256,
        }


class Stage1TradesCatalogIndex:
    def __init__(
        self,
        *,
        published_root: Path,
        partitions: tuple[Stage1TradesPartition, ...],
    ) -> None:
        self.published_root = published_root.resolve()
        self.partitions = partitions
        self._by_key = {(item.instrument, item.partition_date): item for item in partitions}
        records = [item.canonical_record(self.published_root) for item in partitions]
        self.logical_hash = hashlib.sha256(canonical_json(records).encode()).hexdigest()

    @classmethod
    def load(
        cls,
        *,
        catalog_run_root: Path,
        published_root: Path,
        authority: Stage1CatalogAuthority,
    ) -> Stage1TradesCatalogIndex:
        catalog_run_root = catalog_run_root.resolve()
        published_root = published_root.resolve()
        manifest_path = catalog_run_root / "manifest.json"
        if sha256_file(manifest_path) != authority.physical_manifest_sha256:
            raise ValueError("Stage 1 physical Manifest hash mismatch")
        manifest = json.loads(manifest_path.read_bytes())
        claimed_hash = manifest.get("manifest_sha256")
        canonical_payload = dict(manifest)
        canonical_payload.pop("manifest_sha256", None)
        canonical_hash = hashlib.sha256(
            json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if claimed_hash != canonical_hash or canonical_hash != authority.canonical_manifest_sha256:
            raise ValueError("Stage 1 canonical Manifest hash mismatch")
        if manifest.get("run_id") != authority.data_run_id:
            raise ValueError("Stage 1 Data Run ID mismatch")
        if manifest.get("dataset_version") != authority.dataset_version:
            raise ValueError("Stage 1 dataset version mismatch")

        partitions: list[Stage1TradesPartition] = []
        for instrument in INSTRUMENTS:
            catalog_path = catalog_run_root / f"{instrument}.catalog.json"
            if sha256_file(catalog_path) != authority.catalog_sha256s[instrument]:
                raise ValueError(f"Stage 1 {instrument} Catalog hash mismatch")
            catalog = json.loads(catalog_path.read_bytes())
            if catalog.get("logical_data_hash") != authority.logical_hashes[instrument]:
                raise ValueError(f"Stage 1 {instrument} logical hash mismatch")
            manifest_symbol = manifest.get("symbols", {}).get(instrument)
            if not isinstance(manifest_symbol, dict):
                raise ValueError(f"Stage 1 Manifest missing instrument: {instrument}")
            if manifest_symbol.get("logical_data_hash") != authority.logical_hashes[instrument]:
                raise ValueError(f"Stage 1 Manifest {instrument} logical hash mismatch")
            if canonical_json(catalog.get("entries")) != canonical_json(
                manifest_symbol.get("entries")
            ):
                raise ValueError(f"Stage 1 {instrument} Catalog/Manifest entries mismatch")
            partitions.extend(
                cls._instrument_partitions(
                    published_root=published_root,
                    instrument=instrument,
                    entries=catalog.get("entries"),
                )
            )
        return cls(published_root=published_root, partitions=tuple(sorted(partitions)))

    @staticmethod
    def _instrument_partitions(
        *,
        published_root: Path,
        instrument: Instrument,
        entries: Any,
    ) -> list[Stage1TradesPartition]:
        if not isinstance(entries, list):
            raise ValueError(f"Stage 1 {instrument} Catalog entries are invalid")
        by_date: dict[date, tuple[str, Stage1TradesPartition]] = {}
        instrument_root = (published_root / instrument).resolve()
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("instrument") != instrument:
                raise ValueError(f"Stage 1 Catalog instrument mismatch: {instrument}")
            raw_date = str(entry.get("date"))
            partition_date = date.fromisoformat(raw_date)
            relative_path = str(entry.get("relative_path"))
            direct_match = DIRECT_RELATIVE_PATH.fullmatch(relative_path)
            archive_match = ARCHIVE_RELATIVE_PATH.fullmatch(relative_path)
            expected_month = partition_date.strftime("%Y-%m")
            if direct_match is not None:
                path_date = direct_match.group(1)
                primary = instrument_root / f"archive={expected_month}" / relative_path
                legacy = instrument_root / f"archive={raw_date}" / relative_path
                # The approved Stage 1 layout is archive=YYYY-MM.  Do not
                # eagerly stat the legacy archive=YYYY-MM-DD fallback for all
                # 4,752 partitions; inspect it only when the authoritative
                # primary path is absent.
                if primary.is_file():
                    path = primary.resolve()
                elif legacy.is_file():
                    path = legacy.resolve()
                else:
                    raise FileNotFoundError(
                        "missing Catalog-registered Stage 1 partition: "
                        + ", ".join(map(str, (primary, legacy)))
                    )
                archive_partition = path.parent.parent.name.removeprefix("archive=")
            elif archive_match is not None:
                archive_partition, path_date = archive_match.groups()
                if archive_partition not in (expected_month, raw_date):
                    raise ValueError("Stage 1 archive month/date mismatch")
                path = (instrument_root / relative_path).resolve()
            else:
                raise ValueError(f"unapproved Stage 1 Catalog relative path: {relative_path}")
            if path_date != raw_date:
                raise ValueError("Stage 1 Catalog path/date mismatch")
            if not path.is_relative_to(instrument_root):
                raise ValueError("Stage 1 Catalog path escapes published instrument root")
            if not path.is_file():
                raise FileNotFoundError(f"missing Catalog-registered Stage 1 partition: {path}")
            item = Stage1TradesPartition(
                instrument=instrument,
                partition_date=partition_date,
                archive_partition=archive_partition,
                path=path,
                byte_sha256=str(entry.get("byte_sha256")),
                logical_sha256=str(entry.get("logical_sha256")),
            )
            canonical = canonical_json(entry)
            existing = by_date.get(partition_date)
            if existing is None:
                by_date[partition_date] = (canonical, item)
            elif existing[0] != canonical or existing[1] != item:
                raise ValueError(f"conflicting Stage 1 Catalog partition: {instrument} {raw_date}")
        return [item for _, item in by_date.values()]

    def assert_coverage(self, start: date, end_exclusive: date) -> None:
        for instrument in INSTRUMENTS:
            current = start
            while current < end_exclusive:
                if (instrument, current) not in self._by_key:
                    raise FileNotFoundError(
                        f"Stage 1 Catalog coverage missing: {instrument} {current.isoformat()}"
                    )
                current += timedelta(days=1)

    def partitions_around(
        self, instrument: Instrument, partition_date: date
    ) -> tuple[Stage1TradesPartition, ...]:
        result = []
        for offset in (-1, 0, 1):
            item = self._by_key.get((instrument, partition_date + timedelta(days=offset)))
            if item is not None:
                result.append(item)
        return tuple(result)

    @staticmethod
    def select_for_windows(
        candidates: tuple[Stage1TradesPartition, ...], windows: list[dict[str, Any]]
    ) -> tuple[Path, ...]:
        if not windows:
            return ()
        start_ns = min(int(window["window_start_ts"]) for window in windows)
        end_ns = max(int(window["window_end_ts"]) for window in windows)
        if end_ns <= start_ns:
            raise ValueError("Flow window interval is invalid")
        start_date = datetime.fromtimestamp(start_ns // 1_000_000_000, tz=UTC).date()
        end_date = datetime.fromtimestamp((end_ns - 1) // 1_000_000_000, tz=UTC).date()
        by_date = {item.partition_date: item.path for item in candidates}
        paths = []
        current = start_date
        while current <= end_date:
            path = by_date.get(current)
            if path is None:
                raise FileNotFoundError(f"Catalog-authorized Flow partition missing: {current}")
            paths.append(path)
            current += timedelta(days=1)
        return tuple(paths)
