"""Append-only recovery evidence for one damaged Stage 1 Trade partition."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, cast

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.data.full_build.builder import process_archive

from .orchestrator import canonical_hash

SUPPLEMENT_SCHEMA: Final = "stage2-trade-partition-supplement-v1"
ACCEPTANCE_SCHEMA: Final = "stage2-trade-partition-supplement-acceptance-v1"
VERIFY_SCHEMA: Final = "stage2-trade-partition-supplement-verify-v1"


def _file_hash(path: Path) -> str:
    stat = path.stat()
    return _file_hash_at_state(path, stat.st_size, stat.st_mtime_ns)


@lru_cache(maxsize=32)
def _file_hash_at_state(path: Path, size: int, mtime_ns: int) -> str:
    del size, mtime_ns
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.parent.is_symlink():
        raise ValueError(f"unsafe or missing Trade supplement evidence: {path}")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Trade supplement JSON root must be an object")
    return cast(dict[str, Any], value)


def _self_hash_valid(payload: dict[str, Any], field: str) -> bool:
    claimed = payload.get(field)
    body = {key: value for key, value in payload.items() if key != field}
    return isinstance(claimed, str) and claimed == canonical_hash(body)


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    with path.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _checksum(checksum_path: Path, archive: Path) -> str:
    if checksum_path.is_symlink() or not checksum_path.is_file():
        raise ValueError("official archive checksum is unsafe or missing")
    values = checksum_path.read_text(encoding="utf-8").strip().split()
    if len(values) != 2 or values[1] != archive.name or len(values[0]) != 64:
        raise ValueError("official archive checksum format drift")
    if _file_hash(archive) != values[0]:
        raise ValueError("official archive checksum mismatch")
    return values[0]


_SEMANTIC_FIELDS: Final = (
    "instrument",
    "date",
    "rows",
    "input_rows",
    "duplicate_exact_count",
    "first_venue_trade_id",
    "last_venue_trade_id",
    "last_ts_ns",
    "venue_trade_id_gap_count",
    "venue_trade_id_gap_examples",
    "venue_trade_id_reversal_count",
    "venue_trade_id_reversal_examples",
    "logical_sha256",
)


def build_trade_supplement(
    *,
    source_archive: Path,
    checksum_path: Path,
    original_partition_root: Path,
    output_root: Path,
    instrument: str,
    owner_date: date,
) -> Path:
    """Rebuild one selected day from an already accepted official monthly archive."""

    if instrument not in {"BTCUSDT", "ETHUSDT"}:
        raise ValueError("Trade supplement instrument is unsupported")
    if (
        source_archive.is_symlink()
        or not source_archive.is_file()
        or original_partition_root.is_symlink()
        or not original_partition_root.is_dir()
        or output_root.is_symlink()
        or output_root.exists()
        or not output_root.parent.is_dir()
        or output_root.parent.is_symlink()
    ):
        raise ValueError("Trade supplement path boundary is unsafe")
    official_archive_hash = _checksum(checksum_path, source_archive)
    original_receipt_path = original_partition_root / "partition.json"
    original_receipt = _read_json(original_receipt_path)
    if (
        original_receipt.get("instrument") != instrument
        or original_receipt.get("date") != owner_date.isoformat()
    ):
        raise ValueError("original Stage 1 Trade receipt identity mismatch")

    temporary = output_root.with_name(f".{output_root.name}.{os.getpid()}.tmp")
    if temporary.exists():
        raise FileExistsError(temporary)
    try:
        entries = process_archive(
            source_archive,
            temporary / "data",
            cast(Any, instrument),
            source_archive_sha256=official_archive_hash,
            selected_dates={owner_date},
        )
        if len(entries) != 1:
            raise ValueError("official archive did not rebuild exactly one selected day")
        rebuilt_receipt_path = (
            temporary / "data" / f"date={owner_date.isoformat()}" / "partition.json"
        )
        rebuilt_receipt = _read_json(rebuilt_receipt_path)
        differences = {
            field: {
                "original": original_receipt.get(field),
                "rebuilt": rebuilt_receipt.get(field),
            }
            for field in _SEMANTIC_FIELDS
            if rebuilt_receipt.get(field) != original_receipt.get(field)
        }
        if differences:
            raise ValueError(f"rebuilt Trade semantics differ from sealed receipt: {differences}")
        if rebuilt_receipt.get("byte_sha256") != original_receipt.get("byte_sha256"):
            raise ValueError("rebuilt Trade byte hash differs from sealed receipt")
        rebuilt_path = temporary / "data" / f"date={owner_date.isoformat()}" / "part-000.parquet"
        metadata = pq.ParquetFile(rebuilt_path).metadata
        if (
            metadata.num_rows != int(original_receipt["rows"])
            or _file_hash(rebuilt_path) != original_receipt["byte_sha256"]
        ):
            raise ValueError("rebuilt Trade Parquet read-back failed")

        final_rebuilt_path = output_root / "data" / f"date={owner_date.isoformat()}"
        manifest: dict[str, Any] = {
            "schema_name": SUPPLEMENT_SCHEMA,
            "status": "SEALED",
            "change_request": "CR-2026-043",
            "decision": "ADR-S2-020",
            "instrument": instrument,
            "date": owner_date.isoformat(),
            "source_archive_path": str(source_archive),
            "source_archive_sha256": official_archive_hash,
            "source_checksum_path": str(checksum_path),
            "original_partition_root": str(original_partition_root),
            "original_receipt_path": str(original_receipt_path),
            "original_receipt_sha256": _file_hash(original_receipt_path),
            "original_expected_byte_sha256": original_receipt["byte_sha256"],
            "rebuilt_partition_path": str(final_rebuilt_path / "part-000.parquet"),
            "rebuilt_receipt_path": str(final_rebuilt_path / "partition.json"),
            "rebuilt_byte_sha256": rebuilt_receipt["byte_sha256"],
            "rebuilt_logical_sha256": rebuilt_receipt["logical_sha256"],
            "row_count": rebuilt_receipt["rows"],
            "legacy_partition_modified": False,
            "append_only": True,
        }
        manifest["manifest_hash"] = canonical_hash(manifest)
        _write(temporary / "manifest.json", manifest)
        catalog: dict[str, Any] = {
            "schema_name": f"{SUPPLEMENT_SCHEMA}-catalog",
            "manifest_hash": manifest["manifest_hash"],
            "entries": [
                {
                    "instrument": instrument,
                    "date": owner_date.isoformat(),
                    "partition_path": manifest["rebuilt_partition_path"],
                    "receipt_path": manifest["rebuilt_receipt_path"],
                    "byte_sha256": rebuilt_receipt["byte_sha256"],
                    "logical_sha256": rebuilt_receipt["logical_sha256"],
                    "row_count": rebuilt_receipt["rows"],
                }
            ],
        }
        catalog["catalog_hash"] = canonical_hash(catalog)
        _write(temporary / "catalog.json", catalog)
        os.replace(temporary, output_root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    verify = verify_trade_supplement(output_root / "acceptance.json", allow_missing=True)
    acceptance: dict[str, Any] = {
        "schema_name": ACCEPTANCE_SCHEMA,
        "status": "PASS",
        "manifest_path": str(output_root / "manifest.json"),
        "manifest_hash": _read_json(output_root / "manifest.json")["manifest_hash"],
        "catalog_path": str(output_root / "catalog.json"),
        "catalog_hash": _read_json(output_root / "catalog.json")["catalog_hash"],
        "verify": verify,
        "legacy_partition_modified": False,
        "append_only": True,
    }
    acceptance["acceptance_hash"] = canonical_hash(acceptance)
    _write(output_root / "acceptance.json", acceptance)
    return output_root / "acceptance.json"


def verify_trade_supplement(
    acceptance_path: Path, *, allow_missing: bool = False
) -> dict[str, Any]:
    """Verify acceptance or, during the builder's final step, its sealed components."""

    root = acceptance_path.parent
    manifest = _read_json(root / "manifest.json")
    catalog = _read_json(root / "catalog.json")
    if (
        not _self_hash_valid(manifest, "manifest_hash")
        or not _self_hash_valid(catalog, "catalog_hash")
        or catalog.get("manifest_hash") != manifest.get("manifest_hash")
        or manifest.get("schema_name") != SUPPLEMENT_SCHEMA
        or manifest.get("status") != "SEALED"
        or manifest.get("append_only") is not True
        or manifest.get("legacy_partition_modified") is not False
    ):
        raise ValueError("Trade supplement Manifest/Catalog drift")
    partition_path = Path(str(manifest["rebuilt_partition_path"]))
    receipt_path = Path(str(manifest["rebuilt_receipt_path"]))
    original_receipt_path = Path(str(manifest["original_receipt_path"]))
    source_archive = Path(str(manifest["source_archive_path"]))
    checksum_path = Path(str(manifest["source_checksum_path"]))
    if any(path.is_symlink() or not path.is_file() for path in (partition_path, receipt_path)):
        raise ValueError("Trade supplement partition is unsafe or missing")
    receipt = _read_json(receipt_path)
    if (
        _file_hash(partition_path) != manifest["rebuilt_byte_sha256"]
        or receipt.get("byte_sha256") != manifest["rebuilt_byte_sha256"]
        or receipt.get("logical_sha256") != manifest["rebuilt_logical_sha256"]
        or int(receipt.get("rows", -1)) != int(manifest["row_count"])
        or pq.ParquetFile(partition_path).metadata.num_rows != int(manifest["row_count"])
        or _file_hash(original_receipt_path) != manifest["original_receipt_sha256"]
        or _checksum(checksum_path, source_archive) != manifest["source_archive_sha256"]
    ):
        raise ValueError("Trade supplement data/source read-back drift")
    result: dict[str, Any] = {
        "schema_name": VERIFY_SCHEMA,
        "status": "PASS",
        "manifest_hash": manifest["manifest_hash"],
        "catalog_hash": catalog["catalog_hash"],
        "instrument": manifest["instrument"],
        "date": manifest["date"],
        "partition_byte_sha256": manifest["rebuilt_byte_sha256"],
        "partition_logical_sha256": manifest["rebuilt_logical_sha256"],
        "row_count": manifest["row_count"],
        "legacy_partition_modified": False,
    }
    result["verify_hash"] = canonical_hash(result)
    if allow_missing:
        return result
    acceptance = _read_json(acceptance_path)
    if (
        not _self_hash_valid(acceptance, "acceptance_hash")
        or acceptance.get("schema_name") != ACCEPTANCE_SCHEMA
        or acceptance.get("status") != "PASS"
        or acceptance.get("manifest_hash") != manifest["manifest_hash"]
        or acceptance.get("catalog_hash") != catalog["catalog_hash"]
        or acceptance.get("verify") != result
    ):
        raise ValueError("Trade supplement acceptance drift")
    return {**result, "acceptance_hash": acceptance["acceptance_hash"]}


def partition_override(
    *, acceptance_path: Path, instrument: str, owner_date: date
) -> tuple[Path, Path, str] | None:
    accepted_instrument, accepted_date = _supplement_identity(acceptance_path)
    if accepted_instrument != instrument or accepted_date != owner_date.isoformat():
        return None
    verified = verify_trade_supplement(acceptance_path)
    manifest = _read_json(Path(str(_read_json(acceptance_path)["manifest_path"])))
    return (
        Path(str(manifest["rebuilt_partition_path"])),
        Path(str(manifest["rebuilt_receipt_path"])),
        str(verified["acceptance_hash"]),
    )


@lru_cache(maxsize=8)
def _supplement_identity(acceptance_path: Path) -> tuple[str, str]:
    acceptance = _read_json(acceptance_path)
    if (
        not _self_hash_valid(acceptance, "acceptance_hash")
        or acceptance.get("schema_name") != ACCEPTANCE_SCHEMA
        or acceptance.get("status") != "PASS"
    ):
        raise ValueError("Trade supplement acceptance identity drift")
    manifest = _read_json(Path(str(acceptance["manifest_path"])))
    return str(manifest.get("instrument", "")), str(manifest.get("date", ""))
