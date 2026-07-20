"""Merged columnar catalog, content-addressed objects, and fail-closed V2 reads."""

from __future__ import annotations

import hashlib
import os
import re
import struct
import tempfile
import uuid
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from .errors import (
    CatalogIntegrityError,
    ContractViolation,
    PublicationConflict,
    SnapshotMismatch,
)
from .hashing import (
    canonical_arrow_schema,
    canonical_projection_hash,
    canonical_semantic_hash,
    normalize_table,
)
from .models import (
    SHA256_PATTERN,
    ArtifactRef,
    CatalogIndexRef,
    CatalogV2,
    DatasetSemanticRoot,
    DatasetSpec,
    DistributionDigest,
    FragmentV2,
    LogicalPartitionKey,
    ManifestV2,
    QualityFact,
    Receipt,
    ShardSealV2,
    canonical_metadata_bytes,
    metadata_sha256,
)

_AGGREGATE_DOMAIN = b"ERA100X/STAGE2/V2/ORDERED-DIGEST-AGGREGATE/2.0"
_OBJECTS_SCHEMA = pa.schema(
    [
        pa.field("object_sha256", pa.string(), nullable=False),
        pa.field("snapshot_id", pa.string(), nullable=False),
        pa.field("dataset_spec_hash", pa.string(), nullable=False),
        pa.field("relative_path", pa.string(), nullable=False),
        pa.field("byte_size", pa.int64(), nullable=False),
        pa.field("row_count", pa.int64(), nullable=False),
        pa.field("semantic_sha256", pa.string(), nullable=False),
        pa.field("payload", pa.binary(), nullable=False),
    ]
)
_LOGICAL_PARTITIONS_SCHEMA = pa.schema(
    [
        pa.field("partition_id", pa.string(), nullable=False),
        pa.field("cross_run_partition_id", pa.string(), nullable=False),
        pa.field("semantic_order_key", pa.string(), nullable=False),
        pa.field("snapshot_id", pa.string(), nullable=False),
        pa.field("dataset_spec_hash", pa.string(), nullable=False),
        pa.field("shard_id", pa.string(), nullable=False),
        pa.field("terminal_state", pa.string(), nullable=False),
        pa.field("row_count", pa.int64(), nullable=False),
        pa.field("legacy_hash_algorithm", pa.string(), nullable=False),
        pa.field("legacy_logical_sha256", pa.string(), nullable=True),
        pa.field("semantic_sha256", pa.string(), nullable=False),
        pa.field("identity_multiset_sha256", pa.string(), nullable=False),
        pa.field("payload_association_sha256", pa.string(), nullable=False),
        pa.field("semantic_receipt_sha256", pa.string(), nullable=False),
        pa.field("receipt_hash", pa.string(), nullable=False),
        pa.field("fragment_hashes", pa.list_(pa.string()), nullable=False),
        pa.field("payload", pa.binary(), nullable=False),
    ]
)
_FRAGMENTS_SCHEMA = pa.schema(
    [
        pa.field("fragment_hash", pa.string(), nullable=False),
        pa.field("snapshot_id", pa.string(), nullable=False),
        pa.field("dataset_spec_hash", pa.string(), nullable=False),
        pa.field("partition_id", pa.string(), nullable=False),
        pa.field("object_sha256", pa.string(), nullable=False),
        pa.field("fragment_ordinal", pa.int32(), nullable=False),
        pa.field("row_offset", pa.int64(), nullable=False),
        pa.field("row_count", pa.int64(), nullable=False),
        pa.field("semantic_sha256", pa.string(), nullable=False),
        pa.field("payload", pa.binary(), nullable=False),
    ]
)


class _Digest(Protocol):
    def update(self, data: bytes | bytearray | memoryview, /) -> object: ...


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _feed(digest: _Digest, value: bytes) -> None:
    digest.update(struct.pack(">Q", len(value)))
    digest.update(value)


def _ordered_digest_root(domain: str, pairs: Iterable[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    _feed(digest, _AGGREGATE_DOMAIN)
    _feed(digest, domain.encode("utf-8"))
    count = 0
    for identifier, item_hash in pairs:
        _feed(digest, identifier.encode("utf-8"))
        _feed(digest, bytes.fromhex(item_hash))
        count += 1
    _feed(digest, struct.pack(">Q", count))
    return digest.hexdigest()


def _model_bytes(model: object) -> bytes:
    return canonical_metadata_bytes(model) + b"\n"


def _atomic_publish(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise PublicationConflict(f"different bytes already exist at {path}")
        return
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _safe_relative(root: Path, relative_path: str, prefix: str | None = None) -> Path:
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise CatalogIntegrityError(f"unsafe catalog path: {relative_path}")
    if prefix is not None and relative.parts[0] != prefix:
        raise CatalogIntegrityError(f"catalog path is outside {prefix}: {relative_path}")
    resolved = root.joinpath(*relative.parts)
    if not resolved.resolve().is_relative_to(root.resolve()):
        raise CatalogIntegrityError(f"catalog path escapes root: {relative_path}")
    return resolved


def _require_snapshot(actual: str, expected: str, label: str) -> None:
    if actual != expected:
        raise SnapshotMismatch(f"{label} snapshot {actual} != expected {expected}")


def _semantic_order_text(key: LogicalPartitionKey) -> str:
    return "\x1f".join(key.semantic_order_key())


def _schema_sha256(schema: pa.Schema) -> str:
    def describe(data_type: pa.DataType) -> object:
        if pa.types.is_list(data_type):
            return ("list", describe(data_type.value_type), data_type.value_field.nullable)
        if pa.types.is_large_list(data_type):
            return ("large_list", describe(data_type.value_type), data_type.value_field.nullable)
        if pa.types.is_struct(data_type):
            return (
                "struct",
                tuple((field.name, describe(field.type), field.nullable) for field in data_type),
            )
        return str(data_type)

    return metadata_sha256(
        tuple((field.name, describe(field.type), field.nullable) for field in schema)
    )


@dataclass(frozen=True, slots=True)
class PartitionBatch:
    key: LogicalPartitionKey
    table: pa.Table
    legacy_hash_algorithm: str
    legacy_logical_sha256: str | None
    distributions: tuple[DistributionDigest, ...] = ()
    quality_facts: tuple[QualityFact, ...] = ()


@dataclass(frozen=True, slots=True)
class CompactionResult:
    artifact: ArtifactRef | None
    receipts: tuple[Receipt, ...]
    fragments: tuple[FragmentV2, ...]
    seal: ShardSealV2


@dataclass(frozen=True, slots=True)
class CatalogComponentV2:
    """One self-contained task component consumed by the streaming publisher.

    A component is deliberately no larger than one fixed Runtime task.  The
    publisher validates and projects it to Arrow before requesting the next
    component, so the complete 80,784-receipt graph is never retained as
    Pydantic objects in one process heap.
    """

    artifacts: Sequence[ArtifactRef]
    receipts: Sequence[Receipt]
    fragments: Sequence[FragmentV2]
    seals: Sequence[ShardSealV2]


class ArtifactStoreV2:
    """Write immutable Parquet objects once and address them by physical bytes."""

    def __init__(self, catalog_root: Path) -> None:
        self.catalog_root = Path(catalog_root)
        self.object_root = self.catalog_root / "objects"

    def put_table(
        self,
        table: pa.Table,
        *,
        spec: DatasetSpec,
        snapshot_id: str,
        semantic_sha256: str,
        compression: str = "zstd",
        row_group_size: int = 262_144,
    ) -> ArtifactRef:
        if re.fullmatch(SHA256_PATTERN, snapshot_id) is None:
            raise ContractViolation("snapshot_id must be a lowercase SHA-256")
        if re.fullmatch(SHA256_PATTERN, semantic_sha256) is None:
            raise ContractViolation("semantic_sha256 must be a lowercase SHA-256")
        if row_group_size <= 0:
            raise ContractViolation("row_group_size must be positive")
        expected_schema = canonical_arrow_schema(spec)
        if not table.schema.equals(expected_schema, check_metadata=False):
            raise ContractViolation("artifact table must already use the canonical dataset schema")

        staging_root = self.object_root / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix="artifact-", suffix=".parquet.tmp", dir=staging_root, delete=False
        ) as handle:
            temporary = Path(handle.name)
        try:
            pq.write_table(
                table,
                temporary,
                compression=compression,
                row_group_size=row_group_size,
                write_statistics=True,
            )
            with temporary.open("rb") as handle:
                os.fsync(handle.fileno())
            object_sha256 = _sha256_file(temporary)
            byte_size = temporary.stat().st_size
            relative_path = f"objects/{object_sha256[:2]}/{object_sha256}.parquet"
            target = self.catalog_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if target.stat().st_size != byte_size or _sha256_file(target) != object_sha256:
                    raise PublicationConflict(f"content-addressed object conflict at {target}")
            else:
                os.replace(temporary, target)
                _fsync_directory(target.parent)
            return ArtifactRef(
                snapshot_id=snapshot_id,
                dataset_spec_hash=spec.spec_hash,
                object_sha256=object_sha256,
                relative_path=relative_path,
                byte_size=byte_size,
                row_count=table.num_rows,
                semantic_sha256=semantic_sha256,
            )
        finally:
            temporary.unlink(missing_ok=True)


class SealReducerV2:
    """Reduce a complete shard without embedding every receipt in catalog.json."""

    @staticmethod
    def reduce(
        *,
        snapshot_id: str,
        dataset_spec_hash: str,
        shard_id: str,
        receipts: Sequence[Receipt],
    ) -> ShardSealV2:
        if not receipts:
            raise ContractViolation("a shard seal requires at least one receipt")
        by_partition: dict[str, Receipt] = {}
        for receipt in receipts:
            _require_snapshot(receipt.snapshot_id, snapshot_id, "receipt")
            if receipt.shard_id != shard_id:
                raise ContractViolation("seal cannot mix shard IDs")
            if receipt.partition.dataset_spec_hash != dataset_spec_hash:
                raise ContractViolation("seal cannot mix dataset specifications")
            partition_id = receipt.partition.partition_id
            if partition_id in by_partition:
                raise ContractViolation(f"duplicate logical partition {partition_id}")
            by_partition[partition_id] = receipt

        partition_order = sorted(by_partition.items())
        semantic_order = sorted(receipts, key=lambda item: item.partition.semantic_order_key())
        algorithms = {item.legacy_hash_algorithm for item in receipts}
        if len(algorithms) != 1:
            raise ContractViolation("a shard cannot mix legacy hash algorithms")
        legacy_algorithm = next(iter(algorithms))
        legacy_root = None
        if legacy_algorithm == "ERA_CANONICAL_JSON_ROW_V1":
            legacy_root = _ordered_digest_root(
                "shard-receipt-legacy-semantics",
                (
                    (
                        receipt.partition.cross_run_partition_id,
                        receipt.legacy_logical_sha256 or "",
                    )
                    for receipt in semantic_order
                ),
            )
        return ShardSealV2.seal(
            {
                "snapshot_id": snapshot_id,
                "shard_id": shard_id,
                "dataset_spec_hash": dataset_spec_hash,
                "partition_count": len(receipts),
                "empty_partition_count": sum(
                    receipt.terminal_state == "EMPTY" for receipt in receipts
                ),
                "row_count": sum(receipt.row_count for receipt in receipts),
                "partition_ids_root_sha256": _ordered_digest_root(
                    "shard-partition-identities",
                    ((partition_id, partition_id) for partition_id, _receipt in partition_order),
                ),
                "receipt_metadata_root_sha256": _ordered_digest_root(
                    "shard-receipt-metadata",
                    (
                        (partition_id, receipt.receipt_hash)
                        for partition_id, receipt in partition_order
                    ),
                ),
                "legacy_hash_algorithm": legacy_algorithm,
                "legacy_semantic_root_sha256": legacy_root,
                "v2_semantic_root_sha256": _ordered_digest_root(
                    "shard-receipt-v2-semantics",
                    (
                        (
                            receipt.partition.cross_run_partition_id,
                            receipt.semantic_receipt_sha256,
                        )
                        for receipt in semantic_order
                    ),
                ),
            }
        )


def _validate_owner_date(table: pa.Table, spec: DatasetSpec, key: LogicalPartitionKey) -> None:
    if table.num_rows == 0 or spec.ownership_mode == "PARTITION_KEY_ONLY":
        return
    if spec.ownership_mode == "DATE_FIELD":
        if spec.owner_date_field is None:
            raise ContractViolation("DATE_FIELD ownership is missing its configured field")
        owner = table[spec.owner_date_field]
        owner_type = canonical_arrow_schema(spec).field(spec.owner_date_field).type
        scalar_value: object = (
            key.owner_date if pa.types.is_date32(owner_type) else key.owner_date.isoformat()
        )
        matches = pc.equal(owner, pa.scalar(scalar_value, type=owner_type))
    else:
        if spec.owner_timestamp_ns_field is None:
            raise ContractViolation("TIMESTAMP_NS_FIELD ownership is missing its configured field")
        owner = table[spec.owner_timestamp_ns_field]
        owner_type = canonical_arrow_schema(spec).field(spec.owner_timestamp_ns_field).type
        if pa.types.is_timestamp(owner_type):
            owner = pc.cast(owner, pa.int64(), safe=True)
        start_ns = (
            key.owner_date.toordinal() - __import__("datetime").date(1970, 1, 1).toordinal()
        ) * 86_400_000_000_000
        end_ns = start_ns + 86_400_000_000_000
        matches = pc.and_(pc.greater_equal(owner, start_ns), pc.less(owner, end_ns))
    if pc.all(matches).as_py() is not True:
        raise ContractViolation("table rows do not belong to the declared UTC owner date")


class CatalogCompactorV2:
    """Compact owner days only within the same dataset/setup/context/instrument/variant."""

    def __init__(self, store: ArtifactStoreV2) -> None:
        self.store = store

    def compact(
        self,
        *,
        spec: DatasetSpec,
        snapshot_id: str,
        shard_id: str,
        partitions: Sequence[PartitionBatch],
    ) -> CompactionResult:
        if not partitions:
            raise ContractViolation("compaction requires at least one logical partition")
        ordered = sorted(partitions, key=lambda item: item.key.semantic_order_key())
        partition_ids = tuple(item.key.partition_id for item in ordered)
        if len(set(partition_ids)) != len(partition_ids):
            raise ContractViolation("compaction received duplicate logical partitions")
        group_key = ordered[0].key.physical_group_key()
        normalized_tables: list[pa.Table] = []
        semantic_hashes: list[str] = []
        identity_hashes: list[str] = []
        payload_hashes: list[str] = []
        automatic_distributions: list[tuple[DistributionDigest, ...]] = []
        for batch in ordered:
            key = batch.key
            _require_snapshot(key.snapshot_id, snapshot_id, "logical partition")
            if batch.legacy_hash_algorithm != spec.legacy_hash_algorithm:
                raise ContractViolation("partition legacy hash algorithm differs from DatasetSpec")
            if batch.legacy_hash_algorithm == "ERA_CANONICAL_JSON_ROW_V1":
                if (
                    batch.legacy_logical_sha256 is None
                    or re.fullmatch(SHA256_PATTERN, batch.legacy_logical_sha256) is None
                ):
                    raise ContractViolation(
                        "Group-1 compatibility partitions require a legacy logical hash"
                    )
            elif batch.legacy_logical_sha256 is not None:
                raise ContractViolation(
                    "NOT_APPLICABLE partitions must not fabricate legacy hashes"
                )
            if key.dataset_spec_hash != spec.spec_hash:
                raise ContractViolation("logical partition uses a different dataset spec")
            if key.dataset_name != spec.dataset_name or key.dataset_version != spec.dataset_version:
                raise ContractViolation("logical partition dataset identity does not match spec")
            if key.physical_group_key() != group_key:
                raise ContractViolation("physical compaction cannot merge semantic data groups")
            if spec.row_multiplicity == "MULTISET_STABLE" and not any(
                fact.name == "stable_multiset_validated" and fact.value is True
                for fact in batch.quality_facts
            ):
                raise ContractViolation(
                    "multiset datasets require producer-side stable multiset validation"
                )
            normalized = normalize_table(batch.table, spec)
            _validate_owner_date(normalized, spec, key)
            normalized_tables.append(normalized)
            semantic_hashes.append(canonical_semantic_hash(normalized, spec))
            identity_hashes.append(
                canonical_projection_hash(
                    normalized,
                    spec,
                    projection_fields=spec.identity_fields,
                    sort_fields=spec.identity_fields,
                    domain="identity-multiset",
                    require_unique=False,
                )
            )
            payload_hashes.append(
                canonical_projection_hash(
                    normalized,
                    spec,
                    projection_fields=spec.payload_association_fields,
                    sort_fields=spec.stable_sort_keys,
                    domain="identity-payload-association",
                    require_unique=spec.row_multiplicity == "UNIQUE_IDENTITY",
                )
            )
            automatic_distributions.append(
                tuple(
                    DistributionDigest(
                        name=f"field.{name}",
                        sha256=canonical_projection_hash(
                            normalized,
                            spec,
                            projection_fields=(name,),
                            sort_fields=(name,),
                            domain=f"distribution-multiset:{name}",
                            require_unique=False,
                        ),
                    )
                    for name in spec.distribution_fields
                )
            )

        non_empty = [table for table in normalized_tables if table.num_rows]
        artifact: ArtifactRef | None = None
        if non_empty:
            physical_table = pa.concat_tables(non_empty).combine_chunks()
            artifact_semantic = _ordered_digest_root(
                "physical-shard-logical-membership",
                (
                    (batch.key.partition_id, semantic_hash)
                    for batch, semantic_hash, table in zip(
                        ordered, semantic_hashes, normalized_tables, strict=True
                    )
                    if table.num_rows
                ),
            )
            artifact = self.store.put_table(
                physical_table,
                spec=spec,
                snapshot_id=snapshot_id,
                semantic_sha256=artifact_semantic,
            )

        fragments: list[FragmentV2] = []
        fragment_by_partition: dict[str, FragmentV2] = {}
        row_offset = 0
        if artifact is not None:
            for batch, normalized, semantic_hash in zip(
                ordered, normalized_tables, semantic_hashes, strict=True
            ):
                if normalized.num_rows == 0:
                    continue
                fragment = FragmentV2.seal(
                    {
                        "snapshot_id": snapshot_id,
                        "dataset_spec_hash": spec.spec_hash,
                        "partition_id": batch.key.partition_id,
                        "artifact": artifact,
                        "fragment_ordinal": 0,
                        "row_offset": row_offset,
                        "row_count": normalized.num_rows,
                        "semantic_sha256": semantic_hash,
                    }
                )
                fragments.append(fragment)
                fragment_by_partition[batch.key.partition_id] = fragment
                row_offset += normalized.num_rows

        receipts: list[Receipt] = []
        values = zip(
            ordered,
            normalized_tables,
            semantic_hashes,
            identity_hashes,
            payload_hashes,
            automatic_distributions,
            strict=True,
        )
        for batch, normalized, semantic_hash, identity_hash, payload_hash, automatic in values:
            current_fragment = fragment_by_partition.get(batch.key.partition_id)
            distribution_by_name = {item.name: item for item in automatic}
            for item in batch.distributions:
                if item.name in distribution_by_name:
                    raise ContractViolation(f"duplicate distribution digest {item.name}")
                distribution_by_name[item.name] = item
            receipts.append(
                Receipt.seal(
                    {
                        "snapshot_id": snapshot_id,
                        "shard_id": shard_id,
                        "partition": batch.key,
                        "terminal_state": "EMPTY" if normalized.num_rows == 0 else "PRESENT",
                        "row_count": normalized.num_rows,
                        "legacy_hash_algorithm": batch.legacy_hash_algorithm,
                        "legacy_logical_sha256": batch.legacy_logical_sha256,
                        "semantic_sha256": semantic_hash,
                        "identity_multiset_sha256": identity_hash,
                        "payload_association_sha256": payload_hash,
                        "distributions": tuple(
                            distribution_by_name[name] for name in sorted(distribution_by_name)
                        ),
                        "quality_facts": tuple(
                            sorted(batch.quality_facts, key=lambda item: item.name)
                        ),
                        "fragment_hashes": ()
                        if current_fragment is None
                        else (current_fragment.fragment_hash,),
                    }
                )
            )

        seal = SealReducerV2.reduce(
            snapshot_id=snapshot_id,
            dataset_spec_hash=spec.spec_hash,
            shard_id=shard_id,
            receipts=receipts,
        )
        return CompactionResult(
            artifact=artifact,
            receipts=tuple(receipts),
            fragments=tuple(fragments),
            seal=seal,
        )


def _dataset_roots(receipts: Sequence[Receipt]) -> tuple[DatasetSemanticRoot, ...]:
    grouped: dict[str, list[Receipt]] = defaultdict(list)
    for receipt in receipts:
        grouped[receipt.partition.dataset_spec_hash].append(receipt)
    roots: list[DatasetSemanticRoot] = []
    for spec_hash, items in sorted(grouped.items()):
        ordered = sorted(items, key=lambda item: item.partition.semantic_order_key())
        algorithms = {item.legacy_hash_algorithm for item in ordered}
        if len(algorithms) != 1:
            raise CatalogIntegrityError("one dataset spec cannot mix legacy hash algorithms")
        legacy_algorithm = next(iter(algorithms))
        legacy_root = None
        if legacy_algorithm == "ERA_CANONICAL_JSON_ROW_V1":
            legacy_root = _ordered_digest_root(
                "dataset-receipt-legacy-semantics",
                (
                    (item.partition.cross_run_partition_id, item.legacy_logical_sha256 or "")
                    for item in ordered
                ),
            )
        roots.append(
            DatasetSemanticRoot(
                dataset_spec_hash=spec_hash,
                partition_count=len(ordered),
                empty_partition_count=sum(item.terminal_state == "EMPTY" for item in ordered),
                row_count=sum(item.row_count for item in ordered),
                legacy_hash_algorithm=legacy_algorithm,
                legacy_semantic_root_sha256=legacy_root,
                v2_semantic_root_sha256=_ordered_digest_root(
                    "dataset-receipt-v2-semantics",
                    (
                        (item.partition.cross_run_partition_id, item.semantic_receipt_sha256)
                        for item in ordered
                    ),
                ),
            )
        )
    return tuple(roots)


def _validate_graph(
    manifest: ManifestV2,
    *,
    artifacts: Sequence[ArtifactRef],
    receipts: Sequence[Receipt],
    fragments: Sequence[FragmentV2],
    seals: Sequence[ShardSealV2],
    expected_partition_ids: set[str] | None = None,
) -> tuple[DatasetSemanticRoot, ...]:
    snapshot_id = manifest.snapshot_id
    specs = {spec.spec_hash: spec for spec in manifest.dataset_specs}
    expected = expected_partition_ids or {
        partition_id
        for plan in manifest.dataset_plans
        for partition_id in plan.expected_partition_ids
    }
    receipt_by_partition: dict[str, Receipt] = {}
    for receipt in receipts:
        _require_snapshot(receipt.snapshot_id, snapshot_id, "receipt")
        partition_id = receipt.partition.partition_id
        if receipt.partition.dataset_spec_hash not in specs:
            raise CatalogIntegrityError("receipt uses an undeclared dataset spec")
        if partition_id in receipt_by_partition:
            raise CatalogIntegrityError(f"duplicate receipt for {partition_id}")
        receipt_by_partition[partition_id] = receipt
    if set(receipt_by_partition) != expected:
        missing = sorted(expected - set(receipt_by_partition))
        extra = sorted(set(receipt_by_partition) - expected)
        raise CatalogIntegrityError(
            f"receipt plan mismatch; missing={missing[:5]}, extra={extra[:5]}"
        )

    artifact_by_id: dict[str, ArtifactRef] = {}
    for artifact in artifacts:
        _require_snapshot(artifact.snapshot_id, snapshot_id, "artifact")
        if artifact.dataset_spec_hash not in specs:
            raise CatalogIntegrityError("artifact uses an undeclared dataset spec")
        if artifact.object_sha256 in artifact_by_id:
            raise CatalogIntegrityError("duplicate artifact object")
        artifact_by_id[artifact.object_sha256] = artifact

    fragment_by_id: dict[str, FragmentV2] = {}
    fragments_by_partition: dict[str, list[FragmentV2]] = defaultdict(list)
    for fragment in fragments:
        _require_snapshot(fragment.snapshot_id, snapshot_id, "fragment")
        if fragment.fragment_hash in fragment_by_id:
            raise CatalogIntegrityError("duplicate fragment")
        linked_receipt = receipt_by_partition.get(fragment.partition_id)
        if linked_receipt is None:
            raise CatalogIntegrityError("fragment references an unknown logical partition")
        linked_artifact = artifact_by_id.get(fragment.artifact.object_sha256)
        if linked_artifact is None or linked_artifact != fragment.artifact:
            raise CatalogIntegrityError("fragment references an unindexed or conflicting object")
        if fragment.dataset_spec_hash != linked_receipt.partition.dataset_spec_hash:
            raise CatalogIntegrityError("fragment/receipt dataset mismatch")
        fragment_by_id[fragment.fragment_hash] = fragment
        fragments_by_partition[fragment.partition_id].append(fragment)

    referenced_fragments: set[str] = set()
    for partition_id, receipt in receipt_by_partition.items():
        ordered = sorted(
            fragments_by_partition.get(partition_id, []), key=lambda item: item.fragment_ordinal
        )
        hashes = tuple(item.fragment_hash for item in ordered)
        if hashes != receipt.fragment_hashes:
            raise CatalogIntegrityError("receipt fragment list is incomplete or misordered")
        if sum(item.row_count for item in ordered) != receipt.row_count:
            raise CatalogIntegrityError("fragment row counts do not match receipt")
        referenced_fragments.update(hashes)
    if referenced_fragments != set(fragment_by_id):
        raise CatalogIntegrityError("catalog contains unreferenced fragments")
    if {item.artifact.object_sha256 for item in fragments} != set(artifact_by_id):
        raise CatalogIntegrityError("catalog contains unreferenced objects")

    receipts_by_shard: dict[str, list[Receipt]] = defaultdict(list)
    for receipt in receipts:
        receipts_by_shard[receipt.shard_id].append(receipt)
    seal_by_shard: dict[str, ShardSealV2] = {}
    for seal in seals:
        if seal.shard_id in seal_by_shard:
            raise CatalogIntegrityError("shard IDs must be globally unique")
        seal_by_shard[seal.shard_id] = seal
    if set(seal_by_shard) != set(receipts_by_shard):
        raise CatalogIntegrityError("seals do not cover the exact shard set")
    for shard_id, shard_receipts in receipts_by_shard.items():
        spec_hashes = {item.partition.dataset_spec_hash for item in shard_receipts}
        if len(spec_hashes) != 1:
            raise CatalogIntegrityError("a shard cannot mix dataset specifications")
        recomputed = SealReducerV2.reduce(
            snapshot_id=snapshot_id,
            dataset_spec_hash=next(iter(spec_hashes)),
            shard_id=shard_id,
            receipts=shard_receipts,
        )
        if recomputed != seal_by_shard[shard_id]:
            raise CatalogIntegrityError("shard seal reduction mismatch")
    return _dataset_roots(tuple(receipt_by_partition.values()))


def _objects_table(artifacts: Sequence[ArtifactRef]) -> pa.Table:
    ordered = sorted(artifacts, key=lambda item: item.object_sha256)
    return pa.Table.from_arrays(
        [
            pa.array([item.object_sha256 for item in ordered], type=pa.string()),
            pa.array([item.snapshot_id for item in ordered], type=pa.string()),
            pa.array([item.dataset_spec_hash for item in ordered], type=pa.string()),
            pa.array([item.relative_path for item in ordered], type=pa.string()),
            pa.array([item.byte_size for item in ordered], type=pa.int64()),
            pa.array([item.row_count for item in ordered], type=pa.int64()),
            pa.array([item.semantic_sha256 for item in ordered], type=pa.string()),
            pa.array([_model_bytes(item) for item in ordered], type=pa.binary()),
        ],
        schema=_OBJECTS_SCHEMA,
    )


def _logical_partitions_table(receipts: Sequence[Receipt]) -> pa.Table:
    ordered = sorted(receipts, key=lambda item: item.partition.partition_id)
    return pa.Table.from_arrays(
        [
            pa.array([item.partition.partition_id for item in ordered], type=pa.string()),
            pa.array([item.partition.cross_run_partition_id for item in ordered], type=pa.string()),
            pa.array([_semantic_order_text(item.partition) for item in ordered], type=pa.string()),
            pa.array([item.snapshot_id for item in ordered], type=pa.string()),
            pa.array([item.partition.dataset_spec_hash for item in ordered], type=pa.string()),
            pa.array([item.shard_id for item in ordered], type=pa.string()),
            pa.array([item.terminal_state for item in ordered], type=pa.string()),
            pa.array([item.row_count for item in ordered], type=pa.int64()),
            pa.array([item.legacy_hash_algorithm for item in ordered], type=pa.string()),
            pa.array([item.legacy_logical_sha256 for item in ordered], type=pa.string()),
            pa.array([item.semantic_sha256 for item in ordered], type=pa.string()),
            pa.array([item.identity_multiset_sha256 for item in ordered], type=pa.string()),
            pa.array([item.payload_association_sha256 for item in ordered], type=pa.string()),
            pa.array([item.semantic_receipt_sha256 for item in ordered], type=pa.string()),
            pa.array([item.receipt_hash for item in ordered], type=pa.string()),
            pa.array([list(item.fragment_hashes) for item in ordered], type=pa.list_(pa.string())),
            pa.array([_model_bytes(item) for item in ordered], type=pa.binary()),
        ],
        schema=_LOGICAL_PARTITIONS_SCHEMA,
    )


def _fragments_table(fragments: Sequence[FragmentV2]) -> pa.Table:
    ordered = sorted(fragments, key=lambda item: item.fragment_hash)
    return pa.Table.from_arrays(
        [
            pa.array([item.fragment_hash for item in ordered], type=pa.string()),
            pa.array([item.snapshot_id for item in ordered], type=pa.string()),
            pa.array([item.dataset_spec_hash for item in ordered], type=pa.string()),
            pa.array([item.partition_id for item in ordered], type=pa.string()),
            pa.array([item.artifact.object_sha256 for item in ordered], type=pa.string()),
            pa.array([item.fragment_ordinal for item in ordered], type=pa.int32()),
            pa.array([item.row_offset for item in ordered], type=pa.int64()),
            pa.array([item.row_count for item in ordered], type=pa.int64()),
            pa.array([item.semantic_sha256 for item in ordered], type=pa.string()),
            pa.array([_model_bytes(item) for item in ordered], type=pa.binary()),
        ],
        schema=_FRAGMENTS_SCHEMA,
    )


def _write_index(
    root: Path,
    name: Literal["objects", "logical_partitions", "fragments"],
    table: pa.Table,
) -> CatalogIndexRef:
    path = root / f"{name}.parquet"
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / f".{name}.{uuid.uuid4().hex}.parquet.tmp"
    try:
        pq.write_table(table, temporary, compression="zstd", row_group_size=65_536)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        physical_sha256 = _sha256_file(temporary)
        byte_size = temporary.stat().st_size
        if path.exists():
            if path.stat().st_size != byte_size or _sha256_file(path) != physical_sha256:
                raise PublicationConflict(f"merged catalog index conflict at {path}")
        else:
            os.replace(temporary, path)
            _fsync_directory(root)
        return CatalogIndexRef(
            index_name=name,
            relative_path=f"{name}.parquet",
            physical_sha256=physical_sha256,
            schema_sha256=_schema_sha256(table.schema),
            byte_size=byte_size,
            row_count=table.num_rows,
        )
    finally:
        temporary.unlink(missing_ok=True)


class CatalogPublisherV2:
    """Publish three merged indexes, then expose them atomically via catalog.json."""

    def __init__(self, catalog_root: Path) -> None:
        self.catalog_root = Path(catalog_root)

    def publish(
        self,
        manifest: ManifestV2,
        *,
        artifacts: Sequence[ArtifactRef],
        receipts: Sequence[Receipt],
        fragments: Sequence[FragmentV2],
        seals: Sequence[ShardSealV2],
    ) -> CatalogV2:
        return self.publish_components(
            manifest,
            components=(
                CatalogComponentV2(
                    artifacts=artifacts,
                    receipts=receipts,
                    fragments=fragments,
                    seals=seals,
                ),
            ),
        )

    def publish_components(
        self,
        manifest: ManifestV2,
        *,
        components: Iterable[CatalogComponentV2],
    ) -> CatalogV2:
        """Validate task shards sequentially and merge only Arrow metadata.

        This is the formal 80,784-partition path.  Pydantic component objects
        may be released by the caller immediately after this method consumes a
        component; only compact identity sets and Arrow index batches survive
        until the final deterministic merge.
        """

        expected = {
            partition_id
            for plan in manifest.dataset_plans
            for partition_id in plan.expected_partition_ids
        }
        seen_partitions: set[str] = set()
        seen_fragments: set[str] = set()
        artifacts_by_id: dict[str, ArtifactRef] = {}
        seals_by_id: dict[str, ShardSealV2] = {}
        logical_tables: list[tuple[tuple[tuple[str, ...], ...], pa.Table]] = []
        fragment_tables: list[tuple[tuple[tuple[str, ...], ...], pa.Table]] = []
        component_keys: set[tuple[tuple[str, ...], ...]] = set()
        component_count = 0
        for component in components:
            component_count += 1
            partition_ids = {item.partition.partition_id for item in component.receipts}
            if len(partition_ids) != len(component.receipts):
                raise CatalogIntegrityError("component contains duplicate logical partitions")
            overlap = seen_partitions.intersection(partition_ids)
            if overlap:
                raise CatalogIntegrityError(
                    f"logical partition appears in multiple components: {min(overlap)}"
                )
            fragment_ids = {item.fragment_hash for item in component.fragments}
            if len(fragment_ids) != len(component.fragments):
                raise CatalogIntegrityError("component contains duplicate fragments")
            fragment_overlap = seen_fragments.intersection(fragment_ids)
            if fragment_overlap:
                raise CatalogIntegrityError(
                    f"fragment appears in multiple components: {min(fragment_overlap)}"
                )
            component_key = tuple(
                sorted({item.partition.physical_group_key()[1:] for item in component.receipts})
            )
            if not component_key or component_key in component_keys:
                raise CatalogIntegrityError(
                    "component physical-group ownership must be non-empty and unique"
                )
            component_keys.add(component_key)
            _validate_graph(
                manifest,
                artifacts=component.artifacts,
                receipts=component.receipts,
                fragments=component.fragments,
                seals=component.seals,
                expected_partition_ids=partition_ids,
            )
            for artifact in component.artifacts:
                existing = artifacts_by_id.setdefault(artifact.object_sha256, artifact)
                if existing != artifact:
                    raise CatalogIntegrityError(
                        f"conflicting artifact identity: {artifact.object_sha256}"
                    )
            for seal in component.seals:
                existing_seal = seals_by_id.setdefault(seal.shard_id, seal)
                if existing_seal != seal:
                    raise CatalogIntegrityError(f"conflicting shard identity: {seal.shard_id}")
                if existing_seal is not seal and existing_seal == seal:
                    raise CatalogIntegrityError(
                        f"shard appears in multiple components: {seal.shard_id}"
                    )
            seen_partitions.update(partition_ids)
            seen_fragments.update(fragment_ids)
            logical_tables.append((component_key, _logical_partitions_table(component.receipts)))
            fragment_tables.append((component_key, _fragments_table(component.fragments)))

        if component_count == 0:
            raise CatalogIntegrityError("catalog publication requires at least one component")
        if seen_partitions != expected:
            missing = sorted(expected - seen_partitions)
            extra = sorted(seen_partitions - expected)
            raise CatalogIntegrityError(
                f"component plan mismatch; missing={missing[:5]}, extra={extra[:5]}"
            )
        artifacts = tuple(sorted(artifacts_by_id.values(), key=lambda item: item.object_sha256))
        seals = tuple(sorted(seals_by_id.values(), key=lambda item: item.seal_hash))
        # CR-2026-013 classifies object-count thresholds as resource
        # observations.  The sealed indexes remain authoritative at any count;
        # semantic, ownership, duplicate and physical-hash checks above and
        # below continue to fail closed.

        logical_table = _concat_component_tables(logical_tables, schema=_LOGICAL_PARTITIONS_SCHEMA)
        logical_tables.clear()
        roots = _index_dataset_roots(logical_table)
        for artifact in artifacts:
            path = _safe_relative(self.catalog_root, artifact.relative_path, "objects")
            if not path.is_file() or path.stat().st_size != artifact.byte_size:
                raise CatalogIntegrityError(f"artifact is missing or has wrong size: {path}")
            if _sha256_file(path) != artifact.object_sha256:
                raise CatalogIntegrityError(f"artifact byte hash mismatch before publish: {path}")

        _atomic_publish(self.catalog_root / "manifest.json", _model_bytes(manifest))
        objects_index = _write_index(self.catalog_root, "objects", _objects_table(artifacts))
        logical_index = _write_index(self.catalog_root, "logical_partitions", logical_table)
        del logical_table
        fragments_table = _concat_component_tables(fragment_tables, schema=_FRAGMENTS_SCHEMA)
        fragment_tables.clear()
        fragments_index = _write_index(self.catalog_root, "fragments", fragments_table)
        del fragments_table
        catalog = CatalogV2.seal(
            {
                "snapshot_id": manifest.snapshot_id,
                "manifest_hash": manifest.manifest_hash,
                "objects": tuple(sorted(artifacts, key=lambda item: item.object_sha256)),
                "seals": tuple(sorted(seals, key=lambda item: item.seal_hash)),
                "objects_index": objects_index,
                "logical_partitions_index": logical_index,
                "fragments_index": fragments_index,
                "dataset_roots": roots,
            }
        )
        _atomic_publish(self.catalog_root / "catalog.json", _model_bytes(catalog))
        return catalog


def _concat_component_tables(
    tables: Sequence[tuple[tuple[tuple[str, ...], ...], pa.Table]], *, schema: pa.Schema
) -> pa.Table:
    non_empty = [
        table for _key, table in sorted(tables, key=lambda item: item[0]) if table.num_rows
    ]
    if not non_empty:
        return pa.Table.from_batches([], schema=schema)
    # Each component is producer-sorted and owns disjoint physical groups.
    # Ordering components by those immutable groups makes the merge
    # deterministic without allocating a second 80k-row sorted copy.
    return pa.concat_tables(non_empty)


def _read_index(root: Path, reference: CatalogIndexRef, schema: pa.Schema) -> pa.Table:
    path = _safe_relative(root, reference.relative_path)
    if not path.is_file() or path.stat().st_size != reference.byte_size:
        raise CatalogIntegrityError(f"merged catalog index is missing or wrong-sized: {path}")
    if _sha256_file(path) != reference.physical_sha256:
        raise CatalogIntegrityError(f"merged catalog index byte hash mismatch: {path}")
    table = pq.read_table(path)
    if not table.schema.equals(schema, check_metadata=False):
        raise CatalogIntegrityError(f"merged catalog index schema mismatch: {path}")
    if _schema_sha256(table.schema) != reference.schema_sha256:
        raise CatalogIntegrityError(f"merged catalog index schema hash mismatch: {path}")
    if table.num_rows != reference.row_count:
        raise CatalogIntegrityError(f"merged catalog index row count mismatch: {path}")
    return table


def _column_values(table: pa.Table, name: str) -> list[Any]:
    return cast(list[Any], table[name].combine_chunks().to_pylist())


def _batch_records(table: pa.Table, names: Sequence[str]) -> Iterator[tuple[Any, ...]]:
    for batch in table.select(names).to_batches(max_chunksize=8_192):
        columns = [column.to_pylist() for column in batch.columns]
        yield from zip(*columns, strict=True)


def _column_set(table: pa.Table, name: str) -> set[str]:
    return {str(record[0]) for record in _batch_records(table, (name,))}


def _validate_sorted_unique(values: list[Any], label: str) -> None:
    if values != sorted(values) or len(set(values)) != len(values):
        raise CatalogIntegrityError(f"{label} index must be unique and sorted")


def _validate_unique(values: list[Any], label: str) -> None:
    if len(set(values)) != len(values):
        raise CatalogIntegrityError(f"{label} index must be unique")


def _index_dataset_roots(logical: pa.Table) -> tuple[DatasetSemanticRoot, ...]:
    grouped: dict[str, list[tuple[str, str, str, int, str, str | None, str]]] = defaultdict(list)
    names = (
        "dataset_spec_hash",
        "semantic_order_key",
        "cross_run_partition_id",
        "terminal_state",
        "row_count",
        "legacy_hash_algorithm",
        "legacy_logical_sha256",
        "semantic_receipt_sha256",
    )
    for batch in logical.select(names).to_batches(max_chunksize=8_192):
        columns = [column.to_pylist() for column in batch.columns]
        for spec_hash, order, cross_id, state, rows, algorithm, legacy_hash, v2_hash in zip(
            *columns, strict=True
        ):
            grouped[str(spec_hash)].append(
                (
                    str(order),
                    str(cross_id),
                    str(state),
                    int(rows),
                    str(algorithm),
                    None if legacy_hash is None else str(legacy_hash),
                    str(v2_hash),
                )
            )
    roots: list[DatasetSemanticRoot] = []
    for spec_hash, items in sorted(grouped.items()):
        items.sort(key=lambda item: item[0])
        algorithms = {item[4] for item in items}
        if len(algorithms) != 1:
            raise CatalogIntegrityError("logical index mixes legacy algorithms in one dataset")
        legacy_algorithm = cast(
            Literal["ERA_CANONICAL_JSON_ROW_V1", "NOT_APPLICABLE"],
            next(iter(algorithms)),
        )
        legacy_root = None
        if legacy_algorithm == "ERA_CANONICAL_JSON_ROW_V1":
            if any(item[5] is None for item in items):
                raise CatalogIntegrityError("legacy-compatible logical index has null hashes")
            legacy_root = _ordered_digest_root(
                "dataset-receipt-legacy-semantics",
                ((item[1], item[5] or "") for item in items),
            )
        elif any(item[5] is not None for item in items):
            raise CatalogIntegrityError("NOT_APPLICABLE logical index fabricated legacy hashes")
        roots.append(
            DatasetSemanticRoot(
                dataset_spec_hash=spec_hash,
                partition_count=len(items),
                empty_partition_count=sum(item[2] == "EMPTY" for item in items),
                row_count=sum(item[3] for item in items),
                legacy_hash_algorithm=legacy_algorithm,
                legacy_semantic_root_sha256=legacy_root,
                v2_semantic_root_sha256=_ordered_digest_root(
                    "dataset-receipt-v2-semantics",
                    ((item[1], item[6]) for item in items),
                ),
            )
        )
    return tuple(roots)


def _index_seals(logical: pa.Table, snapshot_id: str) -> tuple[ShardSealV2, ...]:
    names = (
        "shard_id",
        "dataset_spec_hash",
        "partition_id",
        "semantic_order_key",
        "cross_run_partition_id",
        "terminal_state",
        "row_count",
        "receipt_hash",
        "legacy_hash_algorithm",
        "legacy_logical_sha256",
        "semantic_receipt_sha256",
    )
    grouped: dict[str, list[tuple[str, str, str, str, str, int, str, str, str | None, str]]] = (
        defaultdict(list)
    )
    for record in _batch_records(logical, names):
        shard_id = str(record[0])
        grouped[shard_id].append(
            (
                str(record[1]),
                str(record[2]),
                str(record[3]),
                str(record[4]),
                str(record[5]),
                int(record[6]),
                str(record[7]),
                str(record[8]),
                None if record[9] is None else str(record[9]),
                str(record[10]),
            )
        )
    seals: list[ShardSealV2] = []
    for shard_id, items in sorted(grouped.items()):
        spec_hashes = {item[0] for item in items}
        if len(spec_hashes) != 1:
            raise CatalogIntegrityError("merged logical index mixes dataset specs in one shard")
        partition_order = sorted(items, key=lambda item: item[1])
        semantic_order = sorted(items, key=lambda item: item[2])
        algorithms = {item[7] for item in items}
        if len(algorithms) != 1:
            raise CatalogIntegrityError("logical index mixes legacy algorithms in one shard")
        legacy_algorithm = cast(
            Literal["ERA_CANONICAL_JSON_ROW_V1", "NOT_APPLICABLE"],
            next(iter(algorithms)),
        )
        legacy_root = None
        if legacy_algorithm == "ERA_CANONICAL_JSON_ROW_V1":
            if any(item[8] is None for item in items):
                raise CatalogIntegrityError("legacy-compatible shard has null legacy hashes")
            legacy_root = _ordered_digest_root(
                "shard-receipt-legacy-semantics",
                ((item[3], item[8] or "") for item in semantic_order),
            )
        elif any(item[8] is not None for item in items):
            raise CatalogIntegrityError("NOT_APPLICABLE shard fabricated legacy hashes")
        seals.append(
            ShardSealV2.seal(
                {
                    "snapshot_id": snapshot_id,
                    "shard_id": shard_id,
                    "dataset_spec_hash": next(iter(spec_hashes)),
                    "partition_count": len(items),
                    "empty_partition_count": sum(item[4] == "EMPTY" for item in items),
                    "row_count": sum(item[5] for item in items),
                    "partition_ids_root_sha256": _ordered_digest_root(
                        "shard-partition-identities",
                        ((item[1], item[1]) for item in partition_order),
                    ),
                    "receipt_metadata_root_sha256": _ordered_digest_root(
                        "shard-receipt-metadata",
                        ((item[1], item[6]) for item in partition_order),
                    ),
                    "legacy_hash_algorithm": legacy_algorithm,
                    "legacy_semantic_root_sha256": legacy_root,
                    "v2_semantic_root_sha256": _ordered_digest_root(
                        "shard-receipt-v2-semantics",
                        ((item[3], item[9]) for item in semantic_order),
                    ),
                }
            )
        )
    return tuple(sorted(seals, key=lambda item: item.seal_hash))


class CatalogReaderV2:
    """Open exactly three merged indexes and reject any inconsistent reference graph."""

    def __init__(
        self,
        *,
        catalog_root: Path,
        manifest: ManifestV2,
        catalog: CatalogV2,
        objects_index: pa.Table,
        logical_index: pa.Table,
        fragments_index: pa.Table,
    ) -> None:
        self.catalog_root = catalog_root
        self.manifest = manifest
        self.catalog = catalog
        self.objects_index = objects_index
        self.logical_index = logical_index
        self.fragments_index = fragments_index
        self.specs = {spec.spec_hash: spec for spec in manifest.dataset_specs}
        self.artifacts = {item.object_sha256: item for item in catalog.objects}
        self._fragment_rows = {
            str(value): index
            for index, (value,) in enumerate(_batch_records(fragments_index, ("fragment_hash",)))
        }

    @classmethod
    def open(
        cls,
        catalog_root: Path,
        *,
        expected_snapshot_id: str,
        deep_verify_objects: bool = False,
    ) -> CatalogReaderV2:
        root = Path(catalog_root)
        manifest_path = root / "manifest.json"
        catalog_path = root / "catalog.json"
        if not manifest_path.is_file() or not catalog_path.is_file():
            raise CatalogIntegrityError("manifest.json and catalog.json are both required")
        try:
            manifest = ManifestV2.model_validate_json(manifest_path.read_bytes())
            catalog = CatalogV2.model_validate_json(catalog_path.read_bytes())
        except ValueError as exc:
            raise CatalogIntegrityError(f"invalid catalog authority: {exc}") from exc
        _require_snapshot(manifest.snapshot_id, expected_snapshot_id, "manifest")
        _require_snapshot(catalog.snapshot_id, expected_snapshot_id, "catalog")
        if catalog.manifest_hash != manifest.manifest_hash:
            raise CatalogIntegrityError("catalog references a different manifest")

        objects = _read_index(root, catalog.objects_index, _OBJECTS_SCHEMA)
        logical = _read_index(root, catalog.logical_partitions_index, _LOGICAL_PARTITIONS_SCHEMA)
        fragments = _read_index(root, catalog.fragments_index, _FRAGMENTS_SCHEMA)
        cls._validate_indexes(manifest, catalog, objects, logical, fragments)
        for artifact in catalog.objects:
            path = _safe_relative(root, artifact.relative_path, "objects")
            if not path.is_file() or path.stat().st_size != artifact.byte_size:
                raise CatalogIntegrityError("catalog object is missing or has a wrong size")
            if deep_verify_objects and _sha256_file(path) != artifact.object_sha256:
                raise CatalogIntegrityError("catalog object byte hash mismatch")
        return cls(
            catalog_root=root,
            manifest=manifest,
            catalog=catalog,
            objects_index=objects,
            logical_index=logical,
            fragments_index=fragments,
        )

    @staticmethod
    def _validate_indexes(
        manifest: ManifestV2,
        catalog: CatalogV2,
        objects: pa.Table,
        logical: pa.Table,
        fragments: pa.Table,
    ) -> None:
        for label, table in (
            ("objects", objects),
            ("logical partitions", logical),
            ("fragments", fragments),
        ):
            if (
                table.num_rows
                and pc.all(pc.equal(table["snapshot_id"], manifest.snapshot_id)).as_py() is not True
            ):
                raise SnapshotMismatch(f"{label} index mixes snapshot IDs")

        object_ids = _column_values(objects, "object_sha256")
        partition_ids = _column_set(logical, "partition_id")
        fragment_ids = _column_set(fragments, "fragment_hash")
        _validate_sorted_unique(object_ids, "objects")
        if len(partition_ids) != logical.num_rows:
            raise CatalogIntegrityError("logical partitions index must be unique")
        if len(fragment_ids) != fragments.num_rows:
            raise CatalogIntegrityError("fragments index must be unique")
        expected = {item for plan in manifest.dataset_plans for item in plan.expected_partition_ids}
        if set(partition_ids) != expected:
            raise CatalogIntegrityError("logical index does not match the manifest partition plan")

        object_payloads = _column_values(objects, "payload")
        parsed_objects = tuple(
            sorted(
                (ArtifactRef.model_validate_json(bytes(value)) for value in object_payloads),
                key=lambda item: item.object_sha256,
            )
        )
        if parsed_objects != catalog.objects:
            raise CatalogIntegrityError("objects index differs from catalog object summaries")

        known_objects = set(object_ids)
        fragment_objects = _column_set(fragments, "object_sha256")
        if fragment_objects != known_objects:
            raise CatalogIntegrityError("fragment index does not reference the exact object set")
        fragment_partitions = _column_set(fragments, "partition_id")
        if not fragment_partitions.issubset(partition_ids):
            raise CatalogIntegrityError("fragment index references unknown logical partitions")

        fragment_by_partition: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for partition_id, fragment_id, row_count in _batch_records(
            fragments, ("partition_id", "fragment_hash", "row_count")
        ):
            fragment_by_partition[str(partition_id)].append((str(fragment_id), int(row_count)))
        for partition_id, expected_fragments, row_count in _batch_records(
            logical, ("partition_id", "fragment_hashes", "row_count")
        ):
            actual = fragment_by_partition.get(str(partition_id), [])
            if [item[0] for item in actual] != list(expected_fragments):
                raise CatalogIntegrityError("logical index fragment list mismatch")
            if sum(item[1] for item in actual) != int(row_count):
                raise CatalogIntegrityError("logical index fragment row count mismatch")

        roots = _index_dataset_roots(logical)
        if roots != catalog.dataset_roots:
            raise CatalogIntegrityError("dataset roots do not reduce from logical index")
        seals_by_shard = {item.shard_id: item for item in catalog.seals}
        shard_ids = _column_set(logical, "shard_id")
        if shard_ids != set(seals_by_shard):
            raise CatalogIntegrityError("Catalog seals do not cover the logical shard set")
        for shard_id, expected_seal in sorted(seals_by_shard.items()):
            selected = logical.filter(pc.equal(logical["shard_id"], shard_id))
            reduced = _index_seals(selected, manifest.snapshot_id)
            if reduced != (expected_seal,):
                raise CatalogIntegrityError("shard seal does not reduce from logical index")

    def verify_object_bytes(self) -> None:
        for artifact in self.catalog.objects:
            path = _safe_relative(self.catalog_root, artifact.relative_path, "objects")
            if _sha256_file(path) != artifact.object_sha256:
                raise CatalogIntegrityError(f"object byte hash mismatch: {path}")

    def receipt(self, partition_id: str) -> Receipt:
        mask = pc.equal(self.logical_index["partition_id"], partition_id)
        selected = self.logical_index.filter(mask)
        if selected.num_rows != 1:
            raise CatalogIntegrityError(f"logical partition is not cataloged: {partition_id}")
        payload = selected["payload"][0].as_py()
        try:
            receipt = Receipt.model_validate_json(payload)
        except ValueError as exc:
            raise CatalogIntegrityError(f"invalid receipt payload: {exc}") from exc
        if receipt.partition.partition_id != partition_id:
            raise CatalogIntegrityError("receipt payload partition ID mismatch")
        return receipt

    def _fragment(self, fragment_hash: str) -> FragmentV2:
        row = self._fragment_rows.get(fragment_hash)
        if row is None:
            raise CatalogIntegrityError(f"fragment is not cataloged: {fragment_hash}")
        payload = self.fragments_index["payload"][row].as_py()
        try:
            fragment = FragmentV2.model_validate_json(payload)
        except ValueError as exc:
            raise CatalogIntegrityError(f"invalid fragment payload: {exc}") from exc
        if fragment.fragment_hash != fragment_hash:
            raise CatalogIntegrityError("fragment payload hash mismatch")
        return fragment

    def read_partition(self, partition_id: str) -> pa.Table:
        receipt = self.receipt(partition_id)
        spec = self.specs[receipt.partition.dataset_spec_hash]
        schema = canonical_arrow_schema(spec)
        if receipt.terminal_state == "EMPTY":
            arrays = [pa.array([], type=field.type) for field in schema]
            table = pa.Table.from_arrays(arrays, schema=schema)
        else:
            artifact_cache: dict[str, pa.Table] = {}
            pieces: list[pa.Table] = []
            fragments = [self._fragment(item) for item in receipt.fragment_hashes]
            for fragment in sorted(fragments, key=lambda item: item.fragment_ordinal):
                artifact = self.artifacts.get(fragment.artifact.object_sha256)
                if artifact is None or artifact != fragment.artifact:
                    raise CatalogIntegrityError("fragment payload references a conflicting object")
                physical = artifact_cache.get(artifact.object_sha256)
                if physical is None:
                    path = _safe_relative(self.catalog_root, artifact.relative_path, "objects")
                    physical = pq.read_table(path, columns=list(schema.names))
                    artifact_cache[artifact.object_sha256] = physical
                piece = physical.slice(fragment.row_offset, fragment.row_count)
                if piece.num_rows != fragment.row_count:
                    raise CatalogIntegrityError("fragment range is outside its physical object")
                if canonical_semantic_hash(piece, spec) != fragment.semantic_sha256:
                    raise CatalogIntegrityError("fragment semantic hash mismatch")
                pieces.append(piece)
            table = pa.concat_tables(pieces).combine_chunks()

        normalized = normalize_table(table, spec)
        semantic_hash = canonical_semantic_hash(normalized, spec)
        identity_hash = canonical_projection_hash(
            normalized,
            spec,
            projection_fields=spec.identity_fields,
            sort_fields=spec.identity_fields,
            domain="identity-multiset",
            require_unique=False,
        )
        payload_hash = canonical_projection_hash(
            normalized,
            spec,
            projection_fields=spec.payload_association_fields,
            sort_fields=spec.stable_sort_keys,
            domain="identity-payload-association",
            require_unique=spec.row_multiplicity == "UNIQUE_IDENTITY",
        )
        if (
            normalized.num_rows != receipt.row_count
            or semantic_hash != receipt.semantic_sha256
            or identity_hash != receipt.identity_multiset_sha256
            or payload_hash != receipt.payload_association_sha256
        ):
            raise CatalogIntegrityError("logical partition does not match its receipt")
        distributions = {item.name: item.sha256 for item in receipt.distributions}
        for name in spec.distribution_fields:
            actual = canonical_projection_hash(
                normalized,
                spec,
                projection_fields=(name,),
                sort_fields=(name,),
                domain=f"distribution-multiset:{name}",
                require_unique=False,
            )
            if distributions.get(f"field.{name}") != actual:
                raise CatalogIntegrityError(f"distribution digest mismatch for {name}")
        _validate_owner_date(normalized, spec, receipt.partition)
        return normalized
