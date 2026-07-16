from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import polars as pl


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
