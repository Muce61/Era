from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import polars as pl
from pydantic_core import to_json


_CANONICAL_JSON_ROW_V1_ENCODER = json.JSONEncoder(
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=True,
    default=str,
)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_partition(path: Path, records: list[dict[str, Any]], schema_name: str) -> dict[str, Any]:
    if path.exists():
        raise FileExistsError(f"append-only partition exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = records or [{"schema_name": schema_name, "empty_partition": True}]
    frame = pl.DataFrame(normalized, strict=False)
    temporary = path.with_suffix(".parquet.tmp")
    frame.write_parquet(temporary, compression="zstd", statistics=True)
    os.replace(temporary, path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    logical = records_logical_hash(records, schema_name)
    return {"rows": len(records), "byte_sha256": digest, "logical_sha256": logical}


def records_logical_hash(records: list[dict[str, Any]], schema_name: str) -> str:
    normalized = records or [{"schema_name": schema_name, "empty_partition": True}]
    serialized = sorted(
        json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
        for record in normalized
    )
    return hashlib.sha256("\n".join(serialized).encode()).hexdigest()


def legacy_sorted_record_bytes(
    records: Sequence[Mapping[str, Any]],
    *,
    validated_no_floats: bool = False,
) -> tuple[bytes, ...]:
    """Serialize one bounded compatibility batch for an external hash merge.

    This helper exists only to preserve ``ERA_CANONICAL_JSON_ROW_V1`` while the
    Runtime V2 producer remains Arrow-native at day scope.  Callers must bound
    ``records``; the helper deliberately returns one sorted run rather than a
    day-sized collection or a composable digest.
    """

    encoder = (
        _canonical_json_row_v1_bytes_validated
        if validated_no_floats
        else canonical_json_row_v1_bytes
    )
    return tuple(sorted(encoder(record) for record in records))


def canonical_json_row_v1_bytes(record: Mapping[str, Any]) -> bytes:
    """Encode one exact ``ERA_CANONICAL_JSON_ROW_V1`` record without ``json.dumps``.

    The encoder is deliberately narrow.  It preserves the legacy UTF-8, compact
    separators, recursive map ordering, list order and ``default=str`` behavior
    while rejecting floats from the Runtime V2 hot path.
    """

    _reject_json_v1_float(record)
    return _CANONICAL_JSON_ROW_V1_ENCODER.encode(record).encode("utf-8")


def _canonical_json_row_v1_bytes_validated(record: Mapping[str, Any]) -> bytes:
    """Encode an already type-validated producer row through the C encoder."""

    # ``json.dumps(sort_keys=True)`` sorts *every* nested map, not only the
    # top-level schema fields.  Group-1 metadata is small but its insertion
    # order is not contractual, so normalize nested maps before entering the C
    # encoder.  This preserves the frozen V1 bytes without paying the much
    # larger Python JSON encoding cost for every scalar field.
    normalized, ascii_only = _sorted_json_maps(record)
    if normalized is record:
        return _CANONICAL_JSON_ROW_V1_ENCODER.encode(record).encode("utf-8")
    encoded = to_json(normalized, serialize_unknown=True)
    if not ascii_only:
        return _CANONICAL_JSON_ROW_V1_ENCODER.encode(record).encode("utf-8")
    return encoded


def _sorted_json_maps(value: Any) -> tuple[Any, bool]:
    """Sort approved Group-1 maps, falling back for deeper dynamic shapes."""

    if not isinstance(value, Mapping):
        return value, not isinstance(value, str) or value.isascii()
    ordered: dict[str, Any] = {}
    ascii_only = True
    for key in sorted(value):
        item = value[key]
        ascii_only = ascii_only and key.isascii()
        if isinstance(item, Mapping):
            nested: dict[str, Any] = {}
            for nested_key in sorted(item):
                nested_item = item[nested_key]
                if isinstance(nested_item, (Mapping, list, tuple)):
                    # No approved Group-1 struct is deeper than one level.  A
                    # future dynamic shape must use the exact general encoder
                    # until its schema receives an explicit fast-path proof.
                    return value, False
                ascii_only = ascii_only and nested_key.isascii()
                if isinstance(nested_item, str):
                    ascii_only = ascii_only and nested_item.isascii()
                nested[nested_key] = nested_item
            item = nested
        elif isinstance(item, (list, tuple)):
            if any(isinstance(member, (Mapping, list, tuple)) for member in item):
                return value, False
            ascii_only = ascii_only and all(
                not isinstance(member, str) or member.isascii() for member in item
            )
        elif isinstance(item, str):
            ascii_only = ascii_only and item.isascii()
        ordered[key] = item
    return ordered, ascii_only


def _reject_json_v1_float(value: Any) -> None:
    if isinstance(value, float):
        raise TypeError("ERA_CANONICAL_JSON_ROW_V1 hot path forbids float")
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_json_v1_float(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_json_v1_float(item)


def write_or_verify_partition(
    path: Path, records: list[dict[str, Any]], schema_name: str
) -> dict[str, Any]:
    expected = records_logical_hash(records, schema_name)
    if path.exists():
        frame = pl.read_parquet(path)
        actual_records = frame.to_dicts()
        actual = records_logical_hash(
            [] if "empty_partition" in frame.columns else actual_records, schema_name
        )
        if actual != expected:
            raise ValueError(f"resume partition logical hash mismatch: {path}")
        return {
            "rows": 0 if "empty_partition" in frame.columns else frame.height,
            "byte_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "logical_sha256": actual,
        }
    return write_partition(path, records, schema_name)


def catalog_tree(root: Path) -> dict[str, Any]:
    entries = []
    logical_aggregate = hashlib.sha256()
    physical_aggregate = hashlib.sha256()
    # External macOS volumes may materialize AppleDouble sidecars named
    # ``._part-000.parquet``.  They are filesystem metadata, not published
    # dataset partitions, and must never enter a Stage 2 Catalog.
    for path in sorted(
        candidate
        for candidate in root.rglob("part-*.parquet")
        if not candidate.name.startswith("._")
    ):
        relative = str(path.relative_to(root))
        byte_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        frame = pl.read_parquet(path)
        empty = "empty_partition" in frame.columns
        records = [] if empty else frame.to_dicts()
        rows = 0 if empty else frame.height
        dataset = _dataset_name(Path(relative))
        logical_hash = records_logical_hash(records, dataset)
        entry = {
            "relative_path": relative,
            "rows": rows,
            "byte_sha256": byte_hash,
            "logical_sha256": logical_hash,
        }
        entries.append(entry)
        logical_aggregate.update(
            json.dumps(
                {
                    "relative_path": relative,
                    "rows": rows,
                    "logical_sha256": logical_hash,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )
        physical_aggregate.update(
            json.dumps(
                {"relative_path": relative, "rows": rows, "byte_sha256": byte_hash},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )
    return {
        "entries": entries,
        "logical_hash": logical_aggregate.hexdigest(),
        "physical_hash": physical_aggregate.hexdigest(),
    }


def _dataset_name(relative: Path) -> str:
    parts = relative.parts
    for index, part in enumerate(parts):
        if part.startswith("variant=") and index + 1 < len(parts):
            return parts[index + 1]
    for part in parts:
        if not part.startswith(("instrument=", "variant=", "date=")) and not part.startswith(
            "part-"
        ):
            return part
    raise ValueError(f"cannot infer dataset name from {relative}")
