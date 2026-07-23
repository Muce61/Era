"""Small, fragment-aware read-only access layer for the fixed S2-T10 snapshot.

The accepted T10 catalog packs many logical UTC-day partitions into larger
Parquet objects.  T15 must never copy or rewrite those objects, and reading an
entire object for every day is needlessly expensive.  This module resolves the
immutable Receipt -> Fragment -> Object graph once and reads only the row
groups intersecting the requested logical partition.
"""

from __future__ import annotations

import json
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.research.stage_2.runtime_v2.models import ArtifactRef, FragmentV2, Receipt


@dataclass(frozen=True, slots=True)
class LogicalPartition:
    receipt: Receipt
    fragments: tuple[FragmentV2, ...]


class FixedT10Reader:
    """Read exact logical partitions without mutating or following symlinks."""

    def __init__(self, snapshot_root: Path, *, expected_snapshot_id: str) -> None:
        if snapshot_root.is_symlink() or not snapshot_root.is_dir():
            raise ValueError("unsafe or missing T10 snapshot root")
        self.snapshot_root = snapshot_root
        self.expected_snapshot_id = expected_snapshot_id
        self._artifacts = self._load_artifacts()
        self._fragments = self._load_fragments()
        self._partitions = self._load_partitions()

    def _safe_index(self, name: str) -> Path:
        path = self.snapshot_root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"unsafe or missing T10 index: {name}")
        return path

    def _load_artifacts(self) -> dict[str, ArtifactRef]:
        result: dict[str, ArtifactRef] = {}
        table = pq.read_table(self._safe_index("objects.parquet"), columns=["payload"])
        for payload in table["payload"].to_pylist():
            artifact = ArtifactRef.model_validate_json(bytes(payload))
            if artifact.snapshot_id != self.expected_snapshot_id:
                raise ValueError("T10 object snapshot binding drift")
            if artifact.object_sha256 in result:
                raise ValueError("duplicate T10 object identity")
            result[artifact.object_sha256] = artifact
        return result

    def _load_fragments(self) -> dict[str, FragmentV2]:
        result: dict[str, FragmentV2] = {}
        table = pq.read_table(self._safe_index("fragments.parquet"), columns=["payload"])
        for payload in table["payload"].to_pylist():
            fragment = FragmentV2.model_validate_json(bytes(payload))
            if fragment.snapshot_id != self.expected_snapshot_id:
                raise ValueError("T10 fragment snapshot binding drift")
            artifact = self._artifacts.get(fragment.artifact.object_sha256)
            if artifact is None or fragment.artifact != artifact:
                raise ValueError("T10 fragment/object graph conflict")
            if fragment.fragment_hash in result:
                raise ValueError("duplicate T10 fragment identity")
            result[fragment.fragment_hash] = fragment
        return result

    def _load_partitions(self) -> dict[tuple[str, str, str, str, date], LogicalPartition]:
        result: dict[tuple[str, str, str, str, date], LogicalPartition] = {}
        table = pq.read_table(
            self._safe_index("logical_partitions.parquet"),
            columns=["partition_id", "payload"],
        )
        for partition_id, payload in zip(
            table["partition_id"].to_pylist(), table["payload"].to_pylist(), strict=True
        ):
            receipt = Receipt.model_validate_json(bytes(payload))
            if receipt.snapshot_id != self.expected_snapshot_id:
                raise ValueError("T10 receipt snapshot binding drift")
            if receipt.partition.partition_id != str(partition_id):
                raise ValueError("T10 receipt partition identity drift")
            fragments = tuple(self._fragments[value] for value in receipt.fragment_hashes)
            if any(fragment.partition_id != str(partition_id) for fragment in fragments):
                raise ValueError("T10 fragment points at another partition")
            key = (
                receipt.partition.dataset_name,
                receipt.partition.dataset_version,
                receipt.partition.instrument,
                receipt.partition.variant,
                receipt.partition.owner_date,
            )
            if key in result:
                raise ValueError(f"duplicate T10 logical partition: {key}")
            result[key] = LogicalPartition(receipt=receipt, fragments=fragments)
        return result

    def partition(
        self,
        *,
        dataset_name: str,
        dataset_version: str,
        instrument: str,
        variant: str,
        owner_date: date,
    ) -> LogicalPartition:
        key = (dataset_name, dataset_version, instrument, variant, owner_date)
        try:
            return self._partitions[key]
        except KeyError as exc:
            raise ValueError(f"missing T10 logical partition: {key}") from exc

    def read(
        self,
        *,
        dataset_name: str,
        dataset_version: str,
        instrument: str,
        variant: str,
        owner_date: date,
        columns: list[str] | None = None,
    ) -> pa.Table:
        logical = self.partition(
            dataset_name=dataset_name,
            dataset_version=dataset_version,
            instrument=instrument,
            variant=variant,
            owner_date=owner_date,
        )
        if logical.receipt.terminal_state == "EMPTY":
            if logical.receipt.row_count or logical.fragments:
                raise ValueError("EMPTY T10 receipt contains rows or fragments")
            return pa.table({}) if columns is None else pa.table({name: [] for name in columns})
        pieces = tuple(
            self._read_fragment(fragment, columns=columns) for fragment in logical.fragments
        )
        if not pieces:
            raise ValueError("PRESENT T10 receipt has no fragment")
        table = pa.concat_tables(pieces).combine_chunks()
        if table.num_rows != logical.receipt.row_count:
            raise ValueError("T10 logical partition row count drift")
        return table

    def _read_fragment(self, fragment: FragmentV2, *, columns: list[str] | None) -> pa.Table:
        artifact = self._artifacts[fragment.artifact.object_sha256]
        path = self._artifact_path(artifact)
        parquet = pq.ParquetFile(path)
        starts: list[int] = []
        total = 0
        for ordinal in range(parquet.num_row_groups):
            starts.append(total)
            total += parquet.metadata.row_group(ordinal).num_rows
        end = fragment.row_offset + fragment.row_count
        if fragment.row_offset < 0 or fragment.row_count <= 0 or end > total:
            raise ValueError("T10 fragment range exceeds packed object")
        first = bisect_right(starts, fragment.row_offset) - 1
        last = bisect_right(starts, end - 1) - 1
        selected = parquet.read_row_groups(list(range(first, last + 1)), columns=columns)
        table = selected.slice(fragment.row_offset - starts[first], fragment.row_count)
        if table.num_rows != fragment.row_count:
            raise ValueError("T10 fragment row count drift")
        return table.combine_chunks()

    def _artifact_path(self, artifact: ArtifactRef) -> Path:
        relative = Path(artifact.relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe T10 object relative path")
        path = (self.snapshot_root / relative).resolve()
        if (
            not path.is_relative_to(self.snapshot_root.resolve())
            or path.is_symlink()
            or not path.is_file()
        ):
            raise ValueError("unsafe or missing T10 packed object")
        return path

    def read_physical_dataset(
        self,
        *,
        dataset_name: str,
        dataset_version: str,
        instrument: str,
        variant: str,
        columns: list[str] | None = None,
    ) -> pa.Table:
        """Read tiled physical objects once after proving exact logical coverage."""

        selected = tuple(
            logical
            for key, logical in self._partitions.items()
            if key[:4] == (dataset_name, dataset_version, instrument, variant)
        )
        if not selected:
            raise ValueError("T10 physical dataset selection is empty")
        fragments_by_object: dict[str, list[FragmentV2]] = {}
        expected_rows = 0
        for logical in selected:
            expected_rows += logical.receipt.row_count
            for fragment in logical.fragments:
                fragments_by_object.setdefault(fragment.artifact.object_sha256, []).append(fragment)
        tables: list[pa.Table] = []
        for object_hash, fragments in sorted(fragments_by_object.items()):
            artifact = self._artifacts[object_hash]
            ordered = sorted(fragments, key=lambda item: item.row_offset)
            cursor = 0
            for fragment in ordered:
                if fragment.row_offset != cursor:
                    raise ValueError("selected T10 fragments do not tile their packed object")
                cursor += fragment.row_count
            if cursor != artifact.row_count:
                raise ValueError("selected T10 dataset does not cover its packed object")
            table = pq.read_table(self._artifact_path(artifact), columns=columns)
            if table.num_rows != artifact.row_count:
                raise ValueError("T10 packed object row count drift")
            tables.append(table)
        result = pa.concat_tables(tables).combine_chunks()
        if result.num_rows != expected_rows:
            raise ValueError("T10 physical dataset total row count drift")
        return result

    def inventory_binding(self) -> dict[str, Any]:
        """Compact deterministic graph counts used by run Manifests."""

        return {
            "snapshot_id": self.expected_snapshot_id,
            "object_count": len(self._artifacts),
            "fragment_count": len(self._fragments),
            "logical_partition_count": len(self._partitions),
        }


def read_json_file(path: Path) -> dict[str, Any]:
    """Strict JSON helper shared by production evidence readers."""

    if path.is_symlink() or not path.is_file():
        raise ValueError(f"unsafe or missing JSON evidence: {path}")
    return cast(dict[str, Any], json.loads(path.read_bytes()))
