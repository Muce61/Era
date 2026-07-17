"""Append-only resolved source authorities for the formal Runtime V2 build.

The expensive source discovery and byte hashing pass is a one-time governance
operation.  Formal preflight parses these sealed manifests and validates their
coverage in memory; the Foundation reader then authenticates each selected
source file exactly once, immediately before its first decode.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import date, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from era100x.research.stage_2.manifests.models import canonical_json
from era100x.research.stage_2.pipelines.candidates.stage1_catalog import (
    INSTRUMENTS,
    Stage1CatalogAuthority,
    Stage1TradesCatalogIndex,
    Stage1TradesPartition,
    sha256_file,
)

from .foundation_sources import (
    CONTRACT_FILE,
    ContractPriceInventoryIndex,
    ContractPricePartition,
)
from .models import SHA256_PATTERN, ZERO_SHA256, metadata_sha256

CONTRACT_PRICE_MANIFEST_AUTHORITY = "contract_price_inventory_manifest_v2"
TRADES_RESOLVED_INDEX_AUTHORITY = "stage1_trades_resolved_index_v2"
_CONTRACT_FORMAT_ORDER = {"CSV": 0, "PARQUET": 1}
_ARCHIVE_PATH = re.compile(
    r"^(BTCUSDT|ETHUSDT)/archive=(\d{4}-\d{2})/"
    r"date=(\d{4}-\d{2}-\d{2})/part-000\.parquet$"
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ContractPriceInventoryEntryV2(_FrozenModel):
    instrument: Literal["BTCUSDT", "ETHUSDT"]
    partition_date: date
    relative_path: str = Field(min_length=1)
    source_format: Literal["CSV", "PARQUET"]
    byte_size: int = Field(gt=0)
    byte_sha256: str = Field(pattern=SHA256_PATTERN)
    canonical_for_date: bool

    @model_validator(mode="after")
    def path_matches_fields(self) -> Self:
        path = PurePosixPath(self.relative_path)
        if path.is_absolute() or ".." in path.parts or len(path.parts) != 2:
            raise ValueError("Contract Price inventory path is unsafe")
        if path.parts[0] != f"{self.instrument}_1s_agg":
            raise ValueError("Contract Price inventory instrument/path mismatch")
        match = CONTRACT_FILE.fullmatch(path.name)
        if match is None or match.group(1) != self.instrument:
            raise ValueError("Contract Price inventory filename is invalid")
        compact = self.partition_date.strftime("%Y%m%d")
        if match.group(2) != compact:
            raise ValueError("Contract Price inventory date/path mismatch")
        expected_format = "CSV" if match.group(3) == "csv" else "PARQUET"
        if self.source_format != expected_format:
            raise ValueError("Contract Price inventory format/path mismatch")
        return self

    def legacy_record(self) -> dict[str, object]:
        return {
            "instrument": self.instrument,
            "date": self.partition_date.strftime("%Y%m%d"),
            "relative_path": self.relative_path,
            "bytes": self.byte_size,
            "sha256": self.byte_sha256,
            "canonical_for_date": self.canonical_for_date,
        }


class ContractPriceInventoryManifestV2(_FrozenModel):
    schema_name: Literal["stage2-v2-contract-price-inventory"] = (
        "stage2-v2-contract-price-inventory"
    )
    manifest_version: Literal["2.0"] = "2.0"
    root_authority: str
    start_date: date
    end_exclusive: date
    entries: tuple[ContractPriceInventoryEntryV2, ...]
    inventory_file_count: int = Field(gt=0)
    canonical_partition_count: int = Field(gt=0)
    legacy_inventory_sha256: str = Field(pattern=SHA256_PATTERN)
    manifest_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_legacy_inventory_sha256(self) -> str:
        return hashlib.sha256(
            canonical_json([item.legacy_record() for item in self.entries]).encode()
        ).hexdigest()

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))

    @model_validator(mode="after")
    def complete_and_sealed(self) -> Self:
        if not Path(self.root_authority).is_absolute():
            raise ValueError("Contract Price root authority must be absolute")
        if self.end_exclusive <= self.start_date:
            raise ValueError("Contract Price inventory period is empty")
        keys = tuple(
            (
                item.instrument,
                _CONTRACT_FORMAT_ORDER[item.source_format],
                item.partition_date,
                item.relative_path,
            )
            for item in self.entries
        )
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("Contract Price inventory entries are not unique and sorted")
        if self.inventory_file_count != len(self.entries):
            raise ValueError("Contract Price inventory file count mismatch")
        canonical = [item for item in self.entries if item.canonical_for_date]
        if self.canonical_partition_count != len(canonical):
            raise ValueError("Contract Price canonical partition count mismatch")
        expected_days = (self.end_exclusive - self.start_date).days
        expected_keys = {
            (instrument, self.start_date + timedelta(days=offset))
            for instrument in INSTRUMENTS
            for offset in range(expected_days)
        }
        canonical_keys = {(item.instrument, item.partition_date) for item in canonical}
        if canonical_keys != expected_keys or len(canonical) != len(canonical_keys):
            raise ValueError("Contract Price canonical coverage is incomplete")
        if self.legacy_inventory_sha256 != self.computed_legacy_inventory_sha256():
            raise ValueError("Contract Price legacy inventory hash mismatch")
        if self.manifest_hash != ZERO_SHA256 and self.manifest_hash != self.computed_hash():
            raise ValueError("Contract Price inventory Manifest hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "manifest_hash": ZERO_SHA256})
        return provisional.model_copy(update={"manifest_hash": provisional.computed_hash()})

    def to_index(self, *, root: Path) -> ContractPriceInventoryIndex:
        root = root.resolve()
        if str(root) != self.root_authority or not root.is_dir() or root.is_symlink():
            raise ValueError("Contract Price root authority changed")
        partitions = tuple(
            sorted(
                ContractPricePartition(
                    instrument=item.instrument,
                    partition_date=item.partition_date,
                    path=_bound_source_path(root, item.relative_path),
                    source_format=item.source_format,
                    byte_size=item.byte_size,
                    byte_sha256=item.byte_sha256,
                )
                for item in self.entries
                if item.canonical_for_date
            )
        )
        return ContractPriceInventoryIndex(
            root=root,
            partitions=partitions,
            inventory_hash=self.legacy_inventory_sha256,
            inventory_file_count=self.inventory_file_count,
        )


class Stage1TradesResolvedEntryV2(_FrozenModel):
    instrument: Literal["BTCUSDT", "ETHUSDT"]
    partition_date: date
    archive_partition: str = Field(pattern=r"^\d{4}-\d{2}$")
    relative_path: str = Field(min_length=1)
    byte_sha256: str = Field(pattern=SHA256_PATTERN)
    logical_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def path_matches_fields(self) -> Self:
        match = _ARCHIVE_PATH.fullmatch(self.relative_path)
        if match is None:
            raise ValueError("resolved Stage 1 Trades path is not archive-authoritative")
        instrument, archive, raw_date = match.groups()
        if instrument != self.instrument or date.fromisoformat(raw_date) != self.partition_date:
            raise ValueError("resolved Stage 1 Trades path field mismatch")
        if archive != self.archive_partition or archive != self.partition_date.strftime("%Y-%m"):
            raise ValueError("resolved Stage 1 Trades archive/date mismatch")
        return self


class Stage1ResolvedSourceIndexV2(_FrozenModel):
    schema_name: Literal["stage2-v2-stage1-resolved-source-index"] = (
        "stage2-v2-stage1-resolved-source-index"
    )
    manifest_version: Literal["2.0"] = "2.0"
    published_root_authority: str
    data_run_id: str
    dataset_version: str
    canonical_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    physical_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    catalog_sha256s: dict[Literal["BTCUSDT", "ETHUSDT"], str]
    instrument_logical_hashes: dict[Literal["BTCUSDT", "ETHUSDT"], str]
    start_date: date
    end_exclusive: date
    entries: tuple[Stage1TradesResolvedEntryV2, ...]
    resolved_partition_count: int = Field(gt=0)
    index_hash: str = Field(pattern=SHA256_PATTERN)
    manifest_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_index_hash(self) -> str:
        return metadata_sha256([item.model_dump(mode="json") for item in self.entries])

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))

    @model_validator(mode="after")
    def complete_and_sealed(self) -> Self:
        if not Path(self.published_root_authority).is_absolute():
            raise ValueError("Stage 1 Trades root authority must be absolute")
        if set(self.catalog_sha256s) != set(INSTRUMENTS):
            raise ValueError("resolved Trades index Catalog authorities are incomplete")
        if set(self.instrument_logical_hashes) != set(INSTRUMENTS):
            raise ValueError("resolved Trades index logical authorities are incomplete")
        if any(not re.fullmatch(SHA256_PATTERN, value) for value in self.catalog_sha256s.values()):
            raise ValueError("resolved Trades Catalog hash is invalid")
        if any(
            not re.fullmatch(SHA256_PATTERN, value)
            for value in self.instrument_logical_hashes.values()
        ):
            raise ValueError("resolved Trades logical hash is invalid")
        keys = tuple((item.instrument, item.partition_date) for item in self.entries)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("resolved Trades entries are not unique and sorted")
        if self.resolved_partition_count != len(self.entries):
            raise ValueError("resolved Trades partition count mismatch")
        expected_days = (self.end_exclusive - self.start_date).days
        expected = {
            (instrument, self.start_date + timedelta(days=offset))
            for instrument in INSTRUMENTS
            for offset in range(expected_days)
        }
        if set(keys) != expected:
            raise ValueError("resolved Trades coverage is incomplete")
        if self.index_hash != ZERO_SHA256 and self.index_hash != self.computed_index_hash():
            raise ValueError("resolved Trades index hash mismatch")
        if self.manifest_hash != ZERO_SHA256 and self.manifest_hash != self.computed_hash():
            raise ValueError("resolved Trades Manifest hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        with_zero = {**payload, "index_hash": ZERO_SHA256, "manifest_hash": ZERO_SHA256}
        provisional = cls.model_validate(with_zero)
        with_index = provisional.model_copy(
            update={"index_hash": provisional.computed_index_hash()}
        )
        return with_index.model_copy(update={"manifest_hash": with_index.computed_hash()})

    def to_index(self, *, published_root: Path) -> Stage1TradesCatalogIndex:
        published_root = published_root.resolve()
        if (
            str(published_root) != self.published_root_authority
            or not published_root.is_dir()
            or published_root.is_symlink()
        ):
            raise ValueError("Stage 1 Trades published root authority changed")
        partitions = tuple(
            Stage1TradesPartition(
                instrument=item.instrument,
                partition_date=item.partition_date,
                archive_partition=item.archive_partition,
                path=_bound_source_path(published_root, item.relative_path),
                byte_sha256=item.byte_sha256,
                logical_sha256=item.logical_sha256,
            )
            for item in self.entries
        )
        return Stage1TradesCatalogIndex(published_root=published_root, partitions=partitions)


def freeze_contract_price_inventory_manifest(
    *,
    root: Path,
    output_path: Path,
    expected_inventory_hash: str,
    start: date = date(2020, 1, 1),
    end_exclusive: date = date(2026, 7, 4),
    expected_csv_count: int = 2016,
    expected_parquet_count: int = 371,
    expected_overlap_count: int = 11,
) -> ContractPriceInventoryManifestV2:
    """Perform the sole expensive Contract Price discovery/hash freeze."""

    root = root.resolve()
    entries: list[ContractPriceInventoryEntryV2] = []
    for instrument in INSTRUMENTS:
        directory = (root / f"{instrument}_1s_agg").resolve()
        if not directory.is_dir() or not directory.is_relative_to(root):
            raise FileNotFoundError(f"missing Contract Price directory: {directory}")
        csv_files = tuple(sorted(directory.glob(f"{instrument}_1s_*.csv")))
        parquet_files = tuple(sorted(directory.glob(f"{instrument}_1s_*.parquet")))
        if len(csv_files) != expected_csv_count or len(parquet_files) != expected_parquet_count:
            raise ValueError(f"{instrument} Contract Price physical inventory changed")
        by_date: dict[date, set[str]] = {}
        for path in (*csv_files, *parquet_files):
            if path.name.startswith("._"):
                raise ValueError("AppleDouble cannot enter the Contract Price inventory")
            match = CONTRACT_FILE.fullmatch(path.name)
            if match is None or match.group(1) != instrument:
                raise ValueError(f"unrecognized Contract Price filename: {path.name}")
            owner_date = _compact_date(match.group(2))
            source_format: Literal["CSV", "PARQUET"] = (
                "CSV" if match.group(3) == "csv" else "PARQUET"
            )
            formats = by_date.setdefault(owner_date, set())
            if source_format in formats:
                raise ValueError("duplicate Contract Price format")
            formats.add(source_format)
            resolved = path.resolve()
            if not resolved.is_file() or not resolved.is_relative_to(directory):
                raise ValueError("unsafe Contract Price file")
            entries.append(
                ContractPriceInventoryEntryV2(
                    instrument=instrument,
                    partition_date=owner_date,
                    relative_path=resolved.relative_to(root).as_posix(),
                    source_format=source_format,
                    byte_size=resolved.stat().st_size,
                    byte_sha256=sha256_file(resolved),
                    canonical_for_date=source_format == "CSV",
                )
            )
        if len(by_date) != (end_exclusive - start).days:
            raise ValueError("Contract Price date coverage changed")
        if sum(formats == {"CSV", "PARQUET"} for formats in by_date.values()) != (
            expected_overlap_count
        ):
            raise ValueError("Contract Price overlap policy changed")
        # A Parquet day is canonical only when its date has no CSV authority.
        csv_dates = {
            item.partition_date
            for item in entries
            if item.instrument == instrument and item.source_format == "CSV"
        }
        entries = [
            item.model_copy(
                update={
                    "canonical_for_date": item.source_format == "CSV"
                    or item.partition_date not in csv_dates
                }
            )
            if item.instrument == instrument
            else item
            for item in entries
        ]
    ordered = tuple(
        sorted(
            entries,
            key=lambda item: (
                item.instrument,
                _CONTRACT_FORMAT_ORDER[item.source_format],
                item.partition_date,
                item.relative_path,
            ),
        )
    )
    manifest = ContractPriceInventoryManifestV2.seal(
        {
            "root_authority": str(root),
            "start_date": start,
            "end_exclusive": end_exclusive,
            "entries": ordered,
            "inventory_file_count": len(ordered),
            "canonical_partition_count": sum(item.canonical_for_date for item in ordered),
            "legacy_inventory_sha256": expected_inventory_hash,
        }
    )
    _write_once_model(output_path, manifest)
    return manifest


def freeze_stage1_resolved_source_index(
    *,
    index: Stage1TradesCatalogIndex,
    authority: Stage1CatalogAuthority,
    output_path: Path,
    start: date = date(2020, 1, 1),
    end_exclusive: date = date(2026, 7, 4),
) -> Stage1ResolvedSourceIndexV2:
    """Seal already Catalog-authorized archive paths without rehashing source data."""

    entries = tuple(
        Stage1TradesResolvedEntryV2(
            instrument=item.instrument,
            partition_date=item.partition_date,
            archive_partition=item.archive_partition,
            relative_path=item.path.relative_to(index.published_root).as_posix(),
            byte_sha256=item.byte_sha256,
            logical_sha256=item.logical_sha256,
        )
        for item in sorted(index.partitions)
    )
    manifest = Stage1ResolvedSourceIndexV2.seal(
        {
            "published_root_authority": str(index.published_root),
            "data_run_id": authority.data_run_id,
            "dataset_version": authority.dataset_version,
            "canonical_manifest_sha256": authority.canonical_manifest_sha256,
            "physical_manifest_sha256": authority.physical_manifest_sha256,
            "catalog_sha256s": authority.catalog_sha256s,
            "instrument_logical_hashes": authority.logical_hashes,
            "start_date": start,
            "end_exclusive": end_exclusive,
            "entries": entries,
            "resolved_partition_count": len(entries),
        }
    )
    _write_once_model(output_path, manifest)
    return manifest


def freeze_stage1_resolved_source_index_from_catalog(
    *,
    catalog_run_root: Path,
    published_root: Path,
    authority: Stage1CatalogAuthority,
    output_path: Path,
    start: date = date(2020, 1, 1),
    end_exclusive: date = date(2026, 7, 4),
) -> Stage1ResolvedSourceIndexV2:
    """One-time governance entry point that authenticates Catalog then resolves paths."""

    index = Stage1TradesCatalogIndex.load(
        catalog_run_root=catalog_run_root,
        published_root=published_root,
        authority=authority,
    )
    return freeze_stage1_resolved_source_index(
        index=index,
        authority=authority,
        output_path=output_path,
        start=start,
        end_exclusive=end_exclusive,
    )


def load_sealed_source_manifest[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"sealed source Manifest is missing: {path}")
    loaded = model.model_validate_json(path.read_bytes())
    manifest_hash = getattr(loaded, "manifest_hash", None)
    computed_hash = getattr(loaded, "computed_hash", None)
    if (
        not isinstance(manifest_hash, str)
        or manifest_hash == ZERO_SHA256
        or not callable(computed_hash)
        or manifest_hash != computed_hash()
    ):
        raise ValueError("source authority Manifest is not sealed")
    return loaded


def _bound_source_path(root: Path, relative_path: str) -> Path:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError("source authority path is unsafe")
    # PurePosixPath validation above makes this a bounded lexical join.  Do not
    # resolve/stat every one of the 9,526 external files during formal
    # preflight; the single-reader consumption gate resolves and hashes each
    # selected file immediately before decode.
    return root.joinpath(*path.parts)


def _compact_date(value: str) -> date:
    if len(value) != 8 or not value.isdigit():
        raise ValueError(f"invalid compact UTC date: {value}")
    return date(int(value[:4]), int(value[4:6]), int(value[6:]))


def _write_once_model(path: Path, model: BaseModel) -> None:
    payload = (canonical_json(model.model_dump(mode="json")) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != payload:
            raise FileExistsError(f"append-only source authority differs: {path}")
        return
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)
