"""CR-2026-028 append-only receipt supplement for sealed T10 price-trigger Context."""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter, defaultdict
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

from . import receipt_supplement as base
from .v14_contracts import canonical_hash

CONTEXT_DATASET = ("price_triggers", "group1-v1-price-v1")
EXPECTED_PARTITION_COUNT = 4_752
CR_PATH = base.REPOSITORY_ROOT / "docs/development/changes/CR-2026-028.md"
SUPPLEMENT_ROOT = base.STAGE2_ROOT / "authorities/S2-T15/v1.4/context-receiver-supplements"


def _module_hash() -> str:
    return base.sha256_file(Path(__file__))


def _receipts(reader: CatalogReaderV2) -> list[Receipt]:
    result: list[Receipt] = []
    for order_key, raw_payload in zip(
        reader.logical_index["semantic_order_key"].to_pylist(),
        reader.logical_index["payload"].to_pylist(),
        strict=True,
    ):
        parts = str(order_key).split("\x1f")
        if len(parts) != 9:
            raise ValueError("T10 semantic order key is malformed")
        if (parts[0], parts[1]) != CONTEXT_DATASET:
            continue
        receipt = Receipt.model_validate_json(bytes(raw_payload))
        spec = reader.specs[receipt.partition.dataset_spec_hash]
        expected_names = {f"field.{name}" for name in spec.distribution_fields}
        if {item.name for item in receipt.distributions}:
            raise ValueError("CR-2026-028 only accepts the known empty distribution tuple")
        if not expected_names:
            raise ValueError("price-trigger supplement declares no distribution fields")
        if receipt.terminal_state == "PRESENT" and len(receipt.fragment_hashes) != 1:
            raise ValueError("price-trigger supplement must bind one packed fragment")
        result.append(receipt)
    result.sort(key=lambda item: item.partition.partition_id)
    if len(result) != EXPECTED_PARTITION_COUNT:
        raise ValueError(f"context supplement partition universe drift: {len(result)}")
    return result


def _row(receipt: Receipt, normalized: pa.Table, spec: Any) -> dict[str, Any]:
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
        or identity != receipt.identity_multiset_sha256
        or payload != receipt.payload_association_sha256
    ):
        raise ValueError("T10 price-trigger semantic/identity/payload binding drift")
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
    result: dict[str, Any] = {
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
        "distribution_digests_json": base._canonical_json(distributions),
    }
    result["supplement_row_hash"] = base._row_hash(result)
    return result


def _validated_rows(reader: CatalogReaderV2) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    receipts = _receipts(reader)
    by_object: dict[str, list[tuple[Receipt, Any]]] = defaultdict(list)
    empty: list[Receipt] = []
    for receipt in receipts:
        if receipt.terminal_state == "EMPTY":
            empty.append(receipt)
            continue
        fragment = reader._fragment(receipt.fragment_hashes[0])
        if fragment.partition_id != receipt.partition.partition_id:
            raise ValueError("price-trigger fragment points at another receipt")
        by_object[fragment.artifact.object_sha256].append((receipt, fragment))

    rows: list[dict[str, Any]] = []
    dataset_counts: Counter[str] = Counter()
    validated_objects: dict[str, dict[str, int]] = {}
    for object_sha256, bindings in sorted(by_object.items()):
        artifact = reader.artifacts.get(object_sha256)
        if artifact is None or any(fragment.artifact != artifact for _, fragment in bindings):
            raise ValueError("price-trigger fragment/object graph conflict")
        object_path = _safe_relative(reader.catalog_root, artifact.relative_path, "objects")
        base._safe_file(object_path)
        if object_path.stat().st_size != artifact.byte_size:
            raise ValueError("price-trigger object size drift")
        if base.sha256_file(object_path) != object_sha256:
            raise ValueError("price-trigger object byte hash drift")
        parquet = pq.ParquetFile(object_path)
        if parquet.metadata.num_rows != artifact.row_count:
            raise ValueError("price-trigger object row count drift")
        validated_objects[object_sha256] = {
            "byte_size": artifact.byte_size,
            "row_count": artifact.row_count,
        }
        for receipt, fragment in sorted(bindings, key=lambda item: item[1].row_offset):
            spec = reader.specs[receipt.partition.dataset_spec_hash]
            table = base._read_fragment(
                parquet,
                row_offset=fragment.row_offset,
                row_count=fragment.row_count,
                columns=[field.name for field in spec.fields],
            )
            normalized = normalize_table(table, spec)
            _validate_owner_date(normalized, spec, receipt.partition)
            row = _row(receipt, normalized, spec)
            if row["original_semantic_sha256"] != fragment.semantic_sha256:
                raise ValueError("price-trigger fragment semantic binding drift")
            rows.append(row)
            dataset_counts[
                f"{receipt.partition.dataset_name}@{receipt.partition.dataset_version}"
            ] += 1

    for receipt in empty:
        spec = reader.specs[receipt.partition.dataset_spec_hash]
        schema = canonical_arrow_schema(spec)
        normalized = pa.Table.from_arrays(
            [pa.array([], type=field.type) for field in schema], schema=schema
        )
        rows.append(_row(receipt, normalized, spec))
        dataset_counts[f"{receipt.partition.dataset_name}@{receipt.partition.dataset_version}"] += 1

    rows.sort(key=lambda item: str(item["partition_id"]))
    if len(rows) != EXPECTED_PARTITION_COUNT:
        raise ValueError("context supplement output reconciliation failed")
    if len({str(item["partition_id"]) for item in rows}) != len(rows):
        raise ValueError("context supplement contains duplicate partition IDs")
    return rows, {
        "dataset_partition_counts": dict(sorted(dataset_counts.items())),
        "validated_object_count": len(validated_objects),
        "validated_object_bytes": sum(item["byte_size"] for item in validated_objects.values()),
        "validated_object_rows": sum(item["row_count"] for item in validated_objects.values()),
        "validated_objects_root_hash": canonical_hash(validated_objects),
    }


def build_context_receipt_supplement() -> tuple[dict[str, Any], Path]:
    """Recompute only price-trigger distribution digests without mutating T10."""

    base._safe_file(CR_PATH)
    reader = CatalogReaderV2.open(base.T10_SNAPSHOT, expected_snapshot_id=base.T10_SNAPSHOT_ID)
    rows, validation = _validated_rows(reader)
    table = pa.Table.from_pylist(rows, schema=base.SUPPLEMENT_SCHEMA)
    SUPPLEMENT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".staging-", dir=SUPPLEMENT_ROOT) as temporary:
        staging = Path(temporary)
        parquet_path = staging / "context_receipt_distribution_supplement.parquet"
        pq.write_table(table, parquet_path, compression="zstd", row_group_size=8_192)
        manifest: dict[str, Any] = {
            "schema_name": "stage2-s2t15-context-receipt-distribution-supplement",
            "schema_version": "1.0",
            "change_request": "CR-2026-028",
            "task_version": "1.4",
            "source_t10_run_id": base.T10_RUN_ID,
            "source_t10_snapshot_id": base.T10_SNAPSHOT_ID,
            "source_hashes": base._source_hashes(),
            "cr_sha256": base.sha256_file(CR_PATH),
            "receiver_implementation_sha256": _module_hash(),
            "supplement_parquet_sha256": base.sha256_file(parquet_path),
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
            existing = verify_context_receipt_supplement(destination)
            if existing != manifest:
                raise ValueError("append-only context supplement conflict")
        else:
            os.replace(staging, destination)
        return manifest, destination


def verify_context_receipt_supplement(path: Path) -> dict[str, Any]:
    root = Path(path)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("unsafe or missing context supplement directory")
    manifest_path = root / "manifest.json"
    parquet_path = root / "context_receipt_distribution_supplement.parquet"
    base._safe_file(manifest_path)
    base._safe_file(parquet_path)
    manifest = cast(dict[str, Any], json.loads(manifest_path.read_bytes()))
    expected_hash = manifest.pop("manifest_hash", None)
    actual_hash = canonical_hash(manifest)
    manifest["manifest_hash"] = expected_hash
    if expected_hash != actual_hash or root.name != f"supplement-{actual_hash}":
        raise ValueError("context supplement Manifest hash mismatch")
    if (
        manifest.get("schema_name") != "stage2-s2t15-context-receipt-distribution-supplement"
        or manifest.get("schema_version") != "1.0"
        or manifest.get("change_request") != "CR-2026-028"
        or manifest.get("task_version") != "1.4"
        or manifest.get("source_t10_run_id") != base.T10_RUN_ID
        or manifest.get("source_t10_snapshot_id") != base.T10_SNAPSHOT_ID
        or manifest.get("status") != "PASS"
        or manifest.get("read_only_receiver") is not True
        or manifest.get("source_bytes_modified") is not False
        or manifest.get("accepted_original_receipt_mutations") != 0
    ):
        raise ValueError("context supplement violates the read-only contract")
    if manifest.get("source_hashes") != base._source_hashes():
        raise ValueError("context supplement source binding drift")
    if manifest.get("cr_sha256") != base.sha256_file(CR_PATH):
        raise ValueError("context supplement CR binding drift")
    if manifest.get("receiver_implementation_sha256") != _module_hash():
        raise ValueError("context supplement implementation drift")
    if manifest.get("supplement_parquet_sha256") != base.sha256_file(parquet_path):
        raise ValueError("context supplement Parquet hash mismatch")
    table = pq.read_table(parquet_path)
    if not table.schema.equals(base.SUPPLEMENT_SCHEMA, check_metadata=False):
        raise ValueError("context supplement schema drift")
    if table.num_rows != EXPECTED_PARTITION_COUNT:
        raise ValueError("context supplement count drift")
    rows = table.to_pylist()
    if [row["partition_id"] for row in rows] != sorted(row["partition_id"] for row in rows):
        raise ValueError("context supplement rows are not deterministically ordered")
    if any(row["supplement_row_hash"] != base._row_hash(row) for row in rows):
        raise ValueError("context supplement row hash mismatch")
    if {f"{row['dataset_name']}@{row['dataset_version']}" for row in rows} != {
        "price_triggers@group1-v1-price-v1"
    }:
        raise ValueError("context supplement contains an unauthorized dataset")
    dataset_counts = Counter(f"{row['dataset_name']}@{row['dataset_version']}" for row in rows)
    if manifest.get("dataset_partition_counts") != dict(sorted(dataset_counts.items())):
        raise ValueError("context supplement dataset reconciliation drift")
    if manifest.get("supplement_partition_count") != table.num_rows:
        raise ValueError("context supplement Manifest count drift")
    return manifest


def latest_valid_context_receipt_supplement() -> tuple[dict[str, Any], Path] | None:
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
            return verify_context_receipt_supplement(path), path
        except ValueError:
            continue
    return None
