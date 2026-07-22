"""CR-2026-027 read-only receipt-distribution supplement for fixed T10 evidence."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.research.stage_2.runtime_v2.catalog import (
    CatalogReaderV2,
    _safe_relative,
    _validate_owner_date,
)
from era100x.research.stage_2.runtime_v2.hashing import (
    canonical_arrow_schema,
    canonical_projection_hash,
    canonical_semantic_hash,
    normalize_table,
)
from era100x.research.stage_2.runtime_v2.models import Receipt

from .v14_contracts import canonical_hash

REPOSITORY_ROOT = Path(__file__).resolve().parents[6]
STAGE2_ROOT = Path("/Volumes/FuckingLife/era100x_stage2")
T10_RUN_ID = "stage2-g1-v2-b-20260720T111704Z-9c4b7c423a04"
T10_SNAPSHOT_ID = "df15b9cbb208a6f921b3a68bee24be44f77e83eb2c8ac1582ef942b108708d33"
T10_SNAPSHOT = STAGE2_ROOT / "runs" / T10_RUN_ID / "published" / "snapshots" / T10_SNAPSHOT_ID
SUPPLEMENT_ROOT = STAGE2_ROOT / "authorities/S2-T15/v1.4/receiver-supplements"
CR_PATH = REPOSITORY_ROOT / "docs/development/changes/CR-2026-027.md"
SUPPLEMENT_DATASETS = {
    ("canonical_key_levels", "group1-v1-price-v1"),
    ("market_episodes", "group1-v1-price-v1"),
    ("market_episodes", "group1-v1-flow-v1"),
}
EXPECTED_PARTITION_COUNT = 14_256

SUPPLEMENT_SCHEMA = pa.schema(
    [
        pa.field("partition_id", pa.string(), nullable=False),
        pa.field("dataset_name", pa.string(), nullable=False),
        pa.field("dataset_version", pa.string(), nullable=False),
        pa.field("dataset_spec_hash", pa.string(), nullable=False),
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("variant", pa.string(), nullable=False),
        pa.field("owner_date", pa.date32(), nullable=False),
        pa.field("original_receipt_hash", pa.string(), nullable=False),
        pa.field("original_semantic_sha256", pa.string(), nullable=False),
        pa.field("original_identity_multiset_sha256", pa.string(), nullable=False),
        pa.field("original_payload_association_sha256", pa.string(), nullable=False),
        pa.field("distribution_digests_json", pa.string(), nullable=False),
        pa.field("supplement_row_hash", pa.string(), nullable=False),
    ]
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"unsafe, symlinked or missing supplement evidence: {path}")


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _module_hash() -> str:
    return sha256_file(Path(__file__))


def _source_hashes() -> dict[str, str]:
    paths = {
        "manifest_sha256": T10_SNAPSHOT / "manifest.json",
        "catalog_sha256": T10_SNAPSHOT / "catalog.json",
        "objects_index_sha256": T10_SNAPSHOT / "objects.parquet",
        "fragments_index_sha256": T10_SNAPSHOT / "fragments.parquet",
        "logical_partitions_index_sha256": T10_SNAPSHOT / "logical_partitions.parquet",
    }
    for path in paths.values():
        _safe_file(path)
    return {name: sha256_file(path) for name, path in paths.items()}


def _row_hash(row: dict[str, Any]) -> str:
    payload = {key: value for key, value in row.items() if key != "supplement_row_hash"}
    if isinstance(payload.get("owner_date"), date):
        payload["owner_date"] = payload["owner_date"].isoformat()
    return canonical_hash(payload)


def _read_fragment(
    parquet: pq.ParquetFile,
    *,
    row_offset: int,
    row_count: int,
    columns: list[str],
) -> pa.Table:
    if row_offset < 0 or row_count <= 0:
        raise ValueError("invalid T10 fragment range")
    starts: list[int] = []
    total = 0
    for index in range(parquet.num_row_groups):
        starts.append(total)
        total += parquet.metadata.row_group(index).num_rows
    end_offset = row_offset + row_count
    if end_offset > total:
        raise ValueError("T10 fragment exceeds its packed object")
    first = bisect_right(starts, row_offset) - 1
    last = bisect_right(starts, end_offset - 1) - 1
    table = parquet.read_row_groups(list(range(first, last + 1)), columns=columns)
    result = table.slice(row_offset - starts[first], row_count).combine_chunks()
    if result.num_rows != row_count:
        raise ValueError("T10 fragment row count changed while reading supplement")
    return result


def _supplement_receipts(reader: CatalogReaderV2) -> list[Receipt]:
    receipts: list[Receipt] = []
    for order_key, raw_payload in zip(
        reader.logical_index["semantic_order_key"].to_pylist(),
        reader.logical_index["payload"].to_pylist(),
        strict=True,
    ):
        parts = str(order_key).split("\x1f")
        if len(parts) != 9:
            raise ValueError("T10 semantic order key is malformed")
        if (parts[0], parts[1]) not in SUPPLEMENT_DATASETS:
            continue
        receipt = Receipt.model_validate_json(bytes(raw_payload))
        expected_names = {
            f"field.{name}"
            for name in reader.specs[receipt.partition.dataset_spec_hash].distribution_fields
        }
        actual_names = {item.name for item in receipt.distributions}
        if actual_names:
            raise ValueError("CR-2026-027 only accepts the known empty distribution tuple")
        if not expected_names:
            raise ValueError("supplement target unexpectedly declares no distribution fields")
        if receipt.terminal_state == "PRESENT" and len(receipt.fragment_hashes) != 1:
            raise ValueError("supplement target must bind exactly one packed fragment")
        receipts.append(receipt)
    receipts.sort(key=lambda item: item.partition.partition_id)
    if len(receipts) != EXPECTED_PARTITION_COUNT:
        raise ValueError(f"supplement partition universe drift: {len(receipts)}")
    return receipts


def _validated_rows(reader: CatalogReaderV2) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    receipts = _supplement_receipts(reader)
    by_object: dict[str, list[tuple[Receipt, Any]]] = defaultdict(list)
    empty_receipts: list[Receipt] = []
    for receipt in receipts:
        if receipt.terminal_state == "EMPTY":
            empty_receipts.append(receipt)
            continue
        fragment = reader._fragment(receipt.fragment_hashes[0])
        if fragment.partition_id != receipt.partition.partition_id:
            raise ValueError("T10 fragment points at a different receipt")
        by_object[fragment.artifact.object_sha256].append((receipt, fragment))

    rows: list[dict[str, Any]] = []
    dataset_counts: Counter[str] = Counter()
    validated_objects: dict[str, dict[str, int]] = {}

    for object_sha256, bindings in sorted(by_object.items()):
        artifact = reader.artifacts.get(object_sha256)
        if artifact is None or any(fragment.artifact != artifact for _, fragment in bindings):
            raise ValueError("T10 supplement fragment/object graph conflict")
        object_path = _safe_relative(reader.catalog_root, artifact.relative_path, "objects")
        _safe_file(object_path)
        if object_path.stat().st_size != artifact.byte_size:
            raise ValueError("T10 supplement object size drift")
        if sha256_file(object_path) != object_sha256:
            raise ValueError("T10 supplement object byte hash drift")
        parquet = pq.ParquetFile(object_path)
        if parquet.metadata.num_rows != artifact.row_count:
            raise ValueError("T10 supplement object row count drift")
        validated_objects[object_sha256] = {
            "byte_size": artifact.byte_size,
            "row_count": artifact.row_count,
        }
        for receipt, fragment in sorted(bindings, key=lambda item: item[1].row_offset):
            spec = reader.specs[receipt.partition.dataset_spec_hash]
            table = _read_fragment(
                parquet,
                row_offset=fragment.row_offset,
                row_count=fragment.row_count,
                columns=[field.name for field in spec.fields],
            )
            normalized = normalize_table(table, spec)
            _validate_owner_date(normalized, spec, receipt.partition)
            semantic = canonical_semantic_hash(normalized, spec)
            identity = canonical_projection_hash(
                normalized,
                spec,
                projection_fields=spec.identity_fields,
                sort_fields=spec.identity_fields,
                domain="identity-multiset",
                require_unique=False,
            )
            payload = canonical_projection_hash(
                normalized,
                spec,
                projection_fields=spec.payload_association_fields,
                sort_fields=spec.stable_sort_keys,
                domain="identity-payload-association",
                require_unique=spec.row_multiplicity == "UNIQUE_IDENTITY",
            )
            if (
                normalized.num_rows != receipt.row_count
                or semantic != receipt.semantic_sha256
                or semantic != fragment.semantic_sha256
                or identity != receipt.identity_multiset_sha256
                or payload != receipt.payload_association_sha256
            ):
                raise ValueError("T10 supplement semantic/identity/payload binding drift")
            distributions = {
                f"field.{name}": canonical_projection_hash(
                    normalized,
                    spec,
                    projection_fields=(name,),
                    sort_fields=(name,),
                    domain=f"distribution-multiset:{name}",
                    require_unique=False,
                )
                for name in spec.distribution_fields
            }
            row: dict[str, Any] = {
                "partition_id": receipt.partition.partition_id,
                "dataset_name": receipt.partition.dataset_name,
                "dataset_version": receipt.partition.dataset_version,
                "dataset_spec_hash": receipt.partition.dataset_spec_hash,
                "instrument": receipt.partition.instrument,
                "variant": receipt.partition.variant,
                "owner_date": receipt.partition.owner_date,
                "original_receipt_hash": receipt.receipt_hash,
                "original_semantic_sha256": semantic,
                "original_identity_multiset_sha256": identity,
                "original_payload_association_sha256": payload,
                "distribution_digests_json": _canonical_json(distributions),
            }
            row["supplement_row_hash"] = _row_hash(row)
            rows.append(row)
            dataset_counts[
                f"{receipt.partition.dataset_name}@{receipt.partition.dataset_version}"
            ] += 1

    for receipt in empty_receipts:
        spec = reader.specs[receipt.partition.dataset_spec_hash]
        schema = canonical_arrow_schema(spec)
        empty = pa.Table.from_arrays(
            [pa.array([], type=field.type) for field in schema], schema=schema
        )
        semantic = canonical_semantic_hash(empty, spec)
        identity = canonical_projection_hash(
            empty,
            spec,
            projection_fields=spec.identity_fields,
            sort_fields=spec.identity_fields,
            domain="identity-multiset",
            require_unique=False,
        )
        payload = canonical_projection_hash(
            empty,
            spec,
            projection_fields=spec.payload_association_fields,
            sort_fields=spec.stable_sort_keys,
            domain="identity-payload-association",
            require_unique=spec.row_multiplicity == "UNIQUE_IDENTITY",
        )
        if (
            semantic != receipt.semantic_sha256
            or identity != receipt.identity_multiset_sha256
            or payload != receipt.payload_association_sha256
        ):
            raise ValueError("empty T10 supplement receipt binding drift")
        distributions = {
            f"field.{name}": canonical_projection_hash(
                empty,
                spec,
                projection_fields=(name,),
                sort_fields=(name,),
                domain=f"distribution-multiset:{name}",
                require_unique=False,
            )
            for name in spec.distribution_fields
        }
        row = {
            "partition_id": receipt.partition.partition_id,
            "dataset_name": receipt.partition.dataset_name,
            "dataset_version": receipt.partition.dataset_version,
            "dataset_spec_hash": receipt.partition.dataset_spec_hash,
            "instrument": receipt.partition.instrument,
            "variant": receipt.partition.variant,
            "owner_date": receipt.partition.owner_date,
            "original_receipt_hash": receipt.receipt_hash,
            "original_semantic_sha256": semantic,
            "original_identity_multiset_sha256": identity,
            "original_payload_association_sha256": payload,
            "distribution_digests_json": _canonical_json(distributions),
        }
        row["supplement_row_hash"] = _row_hash(row)
        rows.append(row)
        dataset_counts[f"{receipt.partition.dataset_name}@{receipt.partition.dataset_version}"] += 1

    rows.sort(key=lambda item: str(item["partition_id"]))
    if len(rows) != EXPECTED_PARTITION_COUNT:
        raise ValueError("supplement output reconciliation failed")
    if len({str(item["partition_id"]) for item in rows}) != len(rows):
        raise ValueError("supplement contains duplicate partition IDs")
    return rows, {
        "dataset_partition_counts": dict(sorted(dataset_counts.items())),
        "validated_object_count": len(validated_objects),
        "validated_object_bytes": sum(item["byte_size"] for item in validated_objects.values()),
        "validated_object_rows": sum(item["row_count"] for item in validated_objects.values()),
        "validated_objects_root_hash": canonical_hash(validated_objects),
    }


def build_receipt_distribution_supplement() -> tuple[dict[str, Any], Path]:
    """Recompute only missing field digests while preserving every sealed T10 byte."""

    _safe_file(CR_PATH)
    reader = CatalogReaderV2.open(T10_SNAPSHOT, expected_snapshot_id=T10_SNAPSHOT_ID)
    rows, validation = _validated_rows(reader)
    table = pa.Table.from_pylist(rows, schema=SUPPLEMENT_SCHEMA)
    SUPPLEMENT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".staging-", dir=SUPPLEMENT_ROOT) as temporary:
        staging = Path(temporary)
        parquet_path = staging / "receipt_distribution_supplement.parquet"
        pq.write_table(table, parquet_path, compression="zstd", row_group_size=16_384)
        parquet_hash = sha256_file(parquet_path)
        manifest: dict[str, Any] = {
            "schema_name": "stage2-s2t15-receipt-distribution-supplement",
            "schema_version": "1.0",
            "change_request": "CR-2026-027",
            "task_version": "1.4",
            "source_t10_run_id": T10_RUN_ID,
            "source_t10_snapshot_id": T10_SNAPSHOT_ID,
            "source_hashes": _source_hashes(),
            "cr_sha256": sha256_file(CR_PATH),
            "receiver_implementation_sha256": _module_hash(),
            "supplement_parquet_sha256": parquet_hash,
            "supplement_partition_count": table.num_rows,
            "accepted_original_receipt_mutations": 0,
            "source_bytes_modified": False,
            "read_only_receiver": True,
            "status": "PASS",
            **validation,
        }
        manifest["manifest_hash"] = canonical_hash(manifest)
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        destination = SUPPLEMENT_ROOT / f"supplement-{manifest['manifest_hash']}"
        if destination.exists():
            if destination.is_symlink() or not destination.is_dir():
                raise ValueError("supplement destination is unsafe")
            existing = verify_receipt_distribution_supplement(destination)
            if existing != manifest:
                raise ValueError("append-only supplement conflict")
        else:
            os.replace(staging, destination)
        return manifest, destination


def verify_receipt_distribution_supplement(path: Path) -> dict[str, Any]:
    root = Path(path)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("unsafe or missing receipt supplement directory")
    manifest_path = root / "manifest.json"
    parquet_path = root / "receipt_distribution_supplement.parquet"
    _safe_file(manifest_path)
    _safe_file(parquet_path)
    manifest = cast(dict[str, Any], json.loads(manifest_path.read_bytes()))
    expected_hash = manifest.pop("manifest_hash", None)
    actual_hash = canonical_hash(manifest)
    manifest["manifest_hash"] = expected_hash
    if expected_hash != actual_hash or root.name != f"supplement-{actual_hash}":
        raise ValueError("receipt supplement Manifest hash mismatch")
    if manifest.get("status") != "PASS" or manifest.get("read_only_receiver") is not True:
        raise ValueError("receipt supplement is not a PASS read-only receiver")
    if manifest.get("source_bytes_modified") is not False:
        raise ValueError("receipt supplement claims a source mutation")
    if manifest.get("accepted_original_receipt_mutations") != 0:
        raise ValueError("receipt supplement accepted a receipt mutation")
    if manifest.get("source_t10_snapshot_id") != T10_SNAPSHOT_ID:
        raise ValueError("receipt supplement binds a different T10 snapshot")
    if manifest.get("source_hashes") != _source_hashes():
        raise ValueError("receipt supplement source binding drift")
    if manifest.get("cr_sha256") != sha256_file(CR_PATH):
        raise ValueError("receipt supplement CR binding drift")
    if manifest.get("receiver_implementation_sha256") != _module_hash():
        raise ValueError("receipt supplement implementation drift")
    if manifest.get("supplement_parquet_sha256") != sha256_file(parquet_path):
        raise ValueError("receipt supplement Parquet hash mismatch")
    table = pq.read_table(parquet_path)
    if not table.schema.equals(SUPPLEMENT_SCHEMA, check_metadata=False):
        raise ValueError("receipt supplement schema drift")
    if table.num_rows != EXPECTED_PARTITION_COUNT:
        raise ValueError("receipt supplement count drift")
    rows = table.to_pylist()
    if [row["partition_id"] for row in rows] != sorted(row["partition_id"] for row in rows):
        raise ValueError("receipt supplement rows are not deterministically ordered")
    if len({row["partition_id"] for row in rows}) != len(rows):
        raise ValueError("receipt supplement contains duplicate partitions")
    for row in rows:
        if row["supplement_row_hash"] != _row_hash(row):
            raise ValueError("receipt supplement row hash mismatch")
        distributions = json.loads(str(row["distribution_digests_json"]))
        if not isinstance(distributions, dict) or not distributions:
            raise ValueError("receipt supplement distribution set is empty")
        if any(not str(name).startswith("field.") for name in distributions):
            raise ValueError("receipt supplement contains a non-field distribution")
    return manifest


def latest_valid_receipt_distribution_supplement() -> tuple[dict[str, Any], Path] | None:
    if not SUPPLEMENT_ROOT.is_dir() or SUPPLEMENT_ROOT.is_symlink():
        return None
    candidates = sorted(
        (
            path
            for path in SUPPLEMENT_ROOT.glob("supplement-*")
            if path.is_dir() and not path.is_symlink() and not path.name.startswith("._")
        ),
        key=lambda path: path.name,
        reverse=True,
    )
    for path in candidates:
        try:
            return verify_receipt_distribution_supplement(path), path
        except ValueError:
            continue
    return None
