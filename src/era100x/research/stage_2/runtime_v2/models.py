"""Immutable contracts for the Stage 2 V2 artifact and catalog runtime.

The contracts deliberately keep logical semantics separate from physical layout.
Dataset roots are derived from receipt semantic projections, never from paths,
Parquet bytes, compression settings, or fragment identifiers.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from era100x.research.stage_2.manifests.models import canonical_json

SHA256_PATTERN = r"^[0-9a-f]{64}$"
ZERO_SHA256 = "0" * 64
MAX_PROCESS_CURRENT_RSS_BYTES: Final[Literal[3_221_225_472]] = 3_221_225_472
MAX_PROCESS_RSS_DELTA_BYTES: Final[Literal[1_073_741_824]] = 1_073_741_824
# Compatibility name for evidence fields that still store absolute peak RSS.
MAX_PROCESS_RSS_BYTES: Final[Literal[3_221_225_472]] = MAX_PROCESS_CURRENT_RSS_BYTES
SAFE_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
_DECIMAL_PATTERN = re.compile(r"^decimal(128|256)\(([1-9][0-9]?),(-?[0-9]+)\)$")
_FIXED_BINARY_PATTERN = re.compile(r"^fixed_binary\(([1-9][0-9]*)\)$")
_SIMPLE_ARROW_TYPES = {
    "null",
    "bool",
    "int8",
    "int16",
    "int32",
    "int64",
    "uint8",
    "uint16",
    "uint32",
    "uint64",
    "utf8",
    "large_utf8",
    "binary",
    "large_binary",
    "date32",
    "timestamp_ns_utc",
}
_NESTED_ARROW_TYPES = {"list", "large_list", "struct"}


def canonical_metadata_bytes(value: Any) -> bytes:
    """Return the repository's float-free canonical metadata representation."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return canonical_json(value).encode("utf-8")


def metadata_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_metadata_bytes(value)).hexdigest()


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ArrowFieldSpec(FrozenModel):
    """Small, explicit Arrow type vocabulary supported by canonical hashing."""

    name: str = Field(pattern=SAFE_NAME_PATTERN)
    data_type: str
    nullable: bool = False
    children: tuple[ArrowFieldSpec, ...] = ()

    @field_validator("data_type")
    @classmethod
    def supported_type(cls, value: str) -> str:
        if value in _SIMPLE_ARROW_TYPES or value in _NESTED_ARROW_TYPES:
            return value
        decimal_match = _DECIMAL_PATTERN.fullmatch(value)
        if decimal_match is not None:
            bit_width = int(decimal_match.group(1))
            precision = int(decimal_match.group(2))
            scale = int(decimal_match.group(3))
            max_precision = 38 if bit_width == 128 else 76
            if precision > max_precision or abs(scale) > precision:
                raise ValueError("decimal precision/scale is outside the canonical range")
            return value
        if _FIXED_BINARY_PATTERN.fullmatch(value) is not None:
            return value
        if value in {"float16", "float32", "float64"}:
            raise ValueError("binary floating-point fields are forbidden in semantic datasets")
        raise ValueError(f"unsupported canonical Arrow type: {value}")

    @model_validator(mode="after")
    def nested_shape(self) -> Self:
        if self.data_type in {"list", "large_list"}:
            if len(self.children) != 1:
                raise ValueError("list and large_list require exactly one child field")
        elif self.data_type == "struct":
            if not self.children:
                raise ValueError("struct requires at least one child field")
            names = tuple(item.name for item in self.children)
            if len(set(names)) != len(names):
                raise ValueError("struct child names must be unique")
        elif self.children:
            raise ValueError("scalar and fixed-width fields cannot have child fields")
        return self


class DatasetSpec(FrozenModel):
    """Versioned semantic schema and stable ordering contract for one dataset."""

    schema_name: Literal["stage2-v2-dataset-spec"] = "stage2-v2-dataset-spec"
    spec_version: Literal["2.0"] = "2.0"
    dataset_name: str = Field(pattern=SAFE_NAME_PATTERN)
    dataset_version: str = Field(pattern=SAFE_NAME_PATTERN)
    fields: tuple[ArrowFieldSpec, ...] = Field(min_length=1)
    stable_sort_keys: tuple[str, ...] = Field(min_length=1)
    identity_fields: tuple[str, ...] = Field(min_length=1)
    payload_association_fields: tuple[str, ...] = Field(min_length=1)
    distribution_fields: tuple[str, ...] = ()
    row_multiplicity: Literal["UNIQUE_IDENTITY", "MULTISET_STABLE"] = "UNIQUE_IDENTITY"
    ownership_mode: Literal["DATE_FIELD", "TIMESTAMP_NS_FIELD", "PARTITION_KEY_ONLY"]
    owner_date_field: str | None = Field(default=None, pattern=SAFE_NAME_PATTERN)
    owner_timestamp_ns_field: str | None = Field(default=None, pattern=SAFE_NAME_PATTERN)
    legacy_hash_algorithm: Literal["ERA_CANONICAL_JSON_ROW_V1", "NOT_APPLICABLE"]
    spec_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"spec_hash"}))

    @model_validator(mode="after")
    def validate_schema(self) -> Self:
        names = tuple(field.name for field in self.fields)
        if len(set(names)) != len(names):
            raise ValueError("dataset field names must be unique")
        known = set(names)
        for label, selected in (
            ("stable_sort_keys", self.stable_sort_keys),
            ("identity_fields", self.identity_fields),
            ("payload_association_fields", self.payload_association_fields),
            ("distribution_fields", self.distribution_fields),
        ):
            if len(set(selected)) != len(selected):
                raise ValueError(f"{label} must not contain duplicates")
            unknown = set(selected) - known
            if unknown:
                raise ValueError(f"{label} contains unknown fields: {sorted(unknown)}")
        if not set(self.identity_fields).issubset(self.payload_association_fields):
            raise ValueError("payload association must include every identity field")
        if not set(self.identity_fields).issubset(self.stable_sort_keys):
            raise ValueError("stable sort keys must include every identity field")
        if self.stable_sort_keys[: len(self.identity_fields)] != self.identity_fields:
            raise ValueError("stable sort keys must start with identity_fields in the same order")
        required_distributions = {"research_role", "parameter_set_id"}.intersection(known)
        if not required_distributions.issubset(self.distribution_fields):
            raise ValueError(
                "research_role and parameter_set_id fields require distribution preservation"
            )
        field_by_name = {field.name: field for field in self.fields}
        if self.ownership_mode == "DATE_FIELD":
            if self.owner_date_field is None or self.owner_timestamp_ns_field is not None:
                raise ValueError("DATE_FIELD requires only owner_date_field")
            owner_field = field_by_name.get(self.owner_date_field)
            if (
                owner_field is None
                or owner_field.nullable
                or owner_field.data_type
                not in {
                    "date32",
                    "utf8",
                }
            ):
                raise ValueError("owner_date_field must be a non-null date32 or utf8 field")
        elif self.ownership_mode == "TIMESTAMP_NS_FIELD":
            if self.owner_timestamp_ns_field is None or self.owner_date_field is not None:
                raise ValueError("TIMESTAMP_NS_FIELD requires only owner_timestamp_ns_field")
            owner_field = field_by_name.get(self.owner_timestamp_ns_field)
            if (
                owner_field is None
                or owner_field.nullable
                or owner_field.data_type
                not in {
                    "int64",
                    "timestamp_ns_utc",
                }
            ):
                raise ValueError(
                    "owner_timestamp_ns_field must be non-null int64 or timestamp_ns_utc"
                )
        elif self.owner_date_field is not None or self.owner_timestamp_ns_field is not None:
            raise ValueError("PARTITION_KEY_ONLY cannot name a record ownership field")
        scalar_types = {
            field.name: field.data_type not in _NESTED_ARROW_TYPES for field in self.fields
        }
        if any(not scalar_types[name] for name in (*self.stable_sort_keys, *self.identity_fields)):
            raise ValueError("stable sort and identity fields must use scalar canonical types")
        if self.spec_hash != ZERO_SHA256 and self.spec_hash != self.computed_hash():
            raise ValueError("dataset spec_hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "spec_hash": ZERO_SHA256})
        return provisional.model_copy(update={"spec_hash": provisional.computed_hash()})


class LogicalPartitionKey(FrozenModel):
    """Physical-layout-independent ownership identity for one UTC owner day."""

    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    dataset_name: str = Field(pattern=SAFE_NAME_PATTERN)
    dataset_version: str = Field(pattern=SAFE_NAME_PATTERN)
    dataset_spec_hash: str = Field(pattern=SHA256_PATTERN)
    setup_id: str = Field(pattern=SAFE_NAME_PATTERN)
    context_id: str = Field(pattern=SAFE_NAME_PATTERN)
    instrument: str = Field(pattern=SAFE_NAME_PATTERN)
    variant: str = Field(pattern=SAFE_NAME_PATTERN)
    owner_date: date

    @property
    def partition_id(self) -> str:
        return metadata_sha256(self)

    @property
    def cross_run_partition_id(self) -> str:
        """Snapshot-independent identity used only for Run-A/Run-B comparison."""

        return metadata_sha256(self.model_dump(mode="json", exclude={"snapshot_id"}))

    def physical_group_key(self) -> tuple[str, ...]:
        """Dimensions that compaction is forbidden to merge across."""

        return (
            self.snapshot_id,
            self.dataset_name,
            self.dataset_version,
            self.dataset_spec_hash,
            self.setup_id,
            self.context_id,
            self.instrument,
            self.variant,
        )

    def semantic_order_key(self) -> tuple[str, ...]:
        return (*self.physical_group_key()[1:], self.owner_date.isoformat(), self.partition_id)


class ArtifactRef(FrozenModel):
    """Immutable reference to one content-addressed physical Parquet object."""

    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    dataset_spec_hash: str = Field(pattern=SHA256_PATTERN)
    object_sha256: str = Field(pattern=SHA256_PATTERN)
    relative_path: str = Field(min_length=1)
    byte_size: int = Field(gt=0)
    row_count: int = Field(ge=0)
    semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    media_type: Literal["application/vnd.apache.parquet"] = "application/vnd.apache.parquet"

    @model_validator(mode="after")
    def content_addressed_path(self) -> Self:
        expected = f"objects/{self.object_sha256[:2]}/{self.object_sha256}.parquet"
        if self.relative_path != expected:
            raise ValueError("artifact path must be derived from object_sha256")
        return self


ScalarFact = str | int | bool | None


class QualityFact(FrozenModel):
    name: str = Field(pattern=SAFE_NAME_PATTERN)
    value: ScalarFact


class DistributionDigest(FrozenModel):
    name: str = Field(pattern=SAFE_NAME_PATTERN)
    sha256: str = Field(pattern=SHA256_PATTERN)


class FragmentV2(FrozenModel):
    """A logical partition slice inside a possibly compacted physical object."""

    schema_name: Literal["stage2-v2-fragment"] = "stage2-v2-fragment"
    fragment_version: Literal["2.0"] = "2.0"
    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    dataset_spec_hash: str = Field(pattern=SHA256_PATTERN)
    partition_id: str = Field(pattern=SHA256_PATTERN)
    artifact: ArtifactRef
    fragment_ordinal: int = Field(ge=0)
    row_offset: int = Field(ge=0)
    row_count: int = Field(gt=0)
    semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    fragment_hash: str = Field(pattern=SHA256_PATTERN)

    @property
    def fragment_id(self) -> str:
        return self.fragment_hash

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"fragment_hash"}))

    @model_validator(mode="after")
    def validate_fragment(self) -> Self:
        if self.snapshot_id != self.artifact.snapshot_id:
            raise ValueError("fragment/artifact snapshot mismatch")
        if self.dataset_spec_hash != self.artifact.dataset_spec_hash:
            raise ValueError("fragment/artifact dataset mismatch")
        if self.row_offset + self.row_count > self.artifact.row_count:
            raise ValueError("fragment row range exceeds the artifact")
        if self.fragment_hash != ZERO_SHA256 and self.fragment_hash != self.computed_hash():
            raise ValueError("fragment_hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "fragment_hash": ZERO_SHA256})
        return provisional.model_copy(update={"fragment_hash": provisional.computed_hash()})


class Receipt(FrozenModel):
    """Complete logical owner-day result, including explicit empty partitions."""

    schema_name: Literal["stage2-v2-receipt"] = "stage2-v2-receipt"
    receipt_version: Literal["2.0"] = "2.0"
    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    shard_id: str = Field(pattern=SAFE_NAME_PATTERN)
    partition: LogicalPartitionKey
    terminal_state: Literal["EMPTY", "PRESENT"]
    row_count: int = Field(ge=0)
    legacy_hash_algorithm: Literal["ERA_CANONICAL_JSON_ROW_V1", "NOT_APPLICABLE"]
    legacy_logical_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    identity_multiset_sha256: str = Field(pattern=SHA256_PATTERN)
    payload_association_sha256: str = Field(pattern=SHA256_PATTERN)
    distributions: tuple[DistributionDigest, ...] = ()
    quality_status: Literal["PASS"] = "PASS"
    quality_facts: tuple[QualityFact, ...] = ()
    fragment_hashes: tuple[str, ...] = ()
    receipt_hash: str = Field(pattern=SHA256_PATTERN)

    @property
    def receipt_id(self) -> str:
        return self.receipt_hash

    def semantic_projection(self) -> dict[str, Any]:
        """Projection used for cross-layout comparison; contains no physical facts."""

        return {
            "schema_name": "stage2-v2-receipt-semantic-projection",
            "projection_version": "2.0",
            "cross_run_partition_id": self.partition.cross_run_partition_id,
            "partition": self.partition.model_dump(mode="json", exclude={"snapshot_id"}),
            "terminal_state": self.terminal_state,
            "row_count": self.row_count,
            "legacy_hash_algorithm": self.legacy_hash_algorithm,
            "legacy_logical_sha256": self.legacy_logical_sha256,
            "semantic_sha256": self.semantic_sha256,
            "identity_multiset_sha256": self.identity_multiset_sha256,
            "payload_association_sha256": self.payload_association_sha256,
            "distributions": [item.model_dump(mode="json") for item in self.distributions],
            "quality_status": self.quality_status,
            "quality_facts": [item.model_dump(mode="json") for item in self.quality_facts],
        }

    @property
    def semantic_receipt_sha256(self) -> str:
        return metadata_sha256(self.semantic_projection())

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"receipt_hash"}))

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        if self.snapshot_id != self.partition.snapshot_id:
            raise ValueError("receipt/partition snapshot mismatch")
        if self.legacy_hash_algorithm == "ERA_CANONICAL_JSON_ROW_V1":
            if self.legacy_logical_sha256 is None:
                raise ValueError("legacy compatibility receipts require the legacy logical hash")
        elif self.legacy_logical_sha256 is not None:
            raise ValueError("NOT_APPLICABLE receipts must not fabricate a legacy logical hash")
        if self.terminal_state == "EMPTY":
            if self.row_count != 0 or self.fragment_hashes:
                raise ValueError("EMPTY receipts must have zero rows and no fragments")
        elif self.row_count == 0 or not self.fragment_hashes:
            raise ValueError("PRESENT receipts require rows and fragments")
        if len(set(self.fragment_hashes)) != len(self.fragment_hashes):
            raise ValueError("receipt fragment hashes must be unique")
        if len({item.name for item in self.distributions}) != len(self.distributions):
            raise ValueError("distribution names must be unique")
        if tuple(sorted(self.distributions, key=lambda item: item.name)) != self.distributions:
            raise ValueError("distributions must be sorted by name")
        if len({item.name for item in self.quality_facts}) != len(self.quality_facts):
            raise ValueError("quality fact names must be unique")
        if tuple(sorted(self.quality_facts, key=lambda item: item.name)) != self.quality_facts:
            raise ValueError("quality facts must be sorted by name")
        if self.receipt_hash != ZERO_SHA256 and self.receipt_hash != self.computed_hash():
            raise ValueError("receipt_hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "receipt_hash": ZERO_SHA256})
        return provisional.model_copy(update={"receipt_hash": provisional.computed_hash()})


class ReceiptBinding(FrozenModel):
    partition_id: str = Field(pattern=SHA256_PATTERN)
    receipt_hash: str = Field(pattern=SHA256_PATTERN)
    semantic_receipt_sha256: str = Field(pattern=SHA256_PATTERN)


class ShardSealV2(FrozenModel):
    """Deterministic reduction of a complete set of logical receipts."""

    schema_name: Literal["stage2-v2-shard-seal"] = "stage2-v2-shard-seal"
    seal_version: Literal["2.0"] = "2.0"
    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    shard_id: str = Field(pattern=SAFE_NAME_PATTERN)
    dataset_spec_hash: str = Field(pattern=SHA256_PATTERN)
    partition_count: int = Field(gt=0)
    empty_partition_count: int = Field(ge=0)
    row_count: int = Field(ge=0)
    partition_ids_root_sha256: str = Field(pattern=SHA256_PATTERN)
    receipt_metadata_root_sha256: str = Field(pattern=SHA256_PATTERN)
    legacy_hash_algorithm: Literal["ERA_CANONICAL_JSON_ROW_V1", "NOT_APPLICABLE"]
    legacy_semantic_root_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    v2_semantic_root_sha256: str = Field(pattern=SHA256_PATTERN)
    seal_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"seal_hash"}))

    @model_validator(mode="after")
    def validate_seal(self) -> Self:
        if self.empty_partition_count > self.partition_count:
            raise ValueError("seal empty count exceeds partition count")
        if self.legacy_hash_algorithm == "ERA_CANONICAL_JSON_ROW_V1":
            if self.legacy_semantic_root_sha256 is None:
                raise ValueError("legacy-compatible seal requires a legacy semantic root")
        elif self.legacy_semantic_root_sha256 is not None:
            raise ValueError("NOT_APPLICABLE seal must not have a legacy semantic root")
        if self.seal_hash != ZERO_SHA256 and self.seal_hash != self.computed_hash():
            raise ValueError("seal_hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "seal_hash": ZERO_SHA256})
        return provisional.model_copy(update={"seal_hash": provisional.computed_hash()})


class DigestBinding(FrozenModel):
    name: str = Field(pattern=SAFE_NAME_PATTERN)
    sha256: str = Field(pattern=SHA256_PATTERN)


class DatasetPlan(FrozenModel):
    dataset_spec_hash: str = Field(pattern=SHA256_PATTERN)
    expected_partition_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def sorted_partitions(self) -> Self:
        if self.expected_partition_ids != tuple(sorted(self.expected_partition_ids)):
            raise ValueError("expected_partition_ids must be sorted")
        if len(set(self.expected_partition_ids)) != len(self.expected_partition_ids):
            raise ValueError("expected_partition_ids must be unique")
        if any(re.fullmatch(SHA256_PATTERN, item) is None for item in self.expected_partition_ids):
            raise ValueError("invalid expected partition ID")
        return self


class ManifestV2(FrozenModel):
    """Locked authority for one immutable V2 snapshot publication."""

    schema_name: Literal["stage2-v2-execution-manifest"] = "stage2-v2-execution-manifest"
    manifest_version: Literal["2.0"] = "2.0"
    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    manual_version: Literal["V1.3.4"] = "V1.3.4"
    stage_plan_version: Literal["1.2"] = "1.2"
    task_id: Literal["S2-T10"] = "S2-T10"
    task_version: Literal["1.8"] = "1.8"
    stage1_data_run_id: str = Field(min_length=1)
    stage1_authorities: tuple[DigestBinding, ...] = Field(min_length=1)
    preregistration_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    config_sha256: str = Field(pattern=SHA256_PATTERN)
    code_tree_sha256: str = Field(pattern=SHA256_PATTERN)
    dataset_specs: tuple[DatasetSpec, ...] = Field(min_length=1)
    dataset_plans: tuple[DatasetPlan, ...] = Field(min_length=1)
    invalidation_conditions: tuple[str, ...] = Field(min_length=1)
    manifest_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        authority_names = tuple(item.name for item in self.stage1_authorities)
        if authority_names != tuple(sorted(authority_names)) or len(set(authority_names)) != len(
            authority_names
        ):
            raise ValueError("Stage 1 authorities must be unique and sorted")
        spec_hashes = tuple(spec.spec_hash for spec in self.dataset_specs)
        if spec_hashes != tuple(sorted(spec_hashes)) or len(set(spec_hashes)) != len(spec_hashes):
            raise ValueError("dataset specs must be unique and sorted by spec_hash")
        plan_hashes = tuple(plan.dataset_spec_hash for plan in self.dataset_plans)
        if plan_hashes != tuple(sorted(plan_hashes)) or len(set(plan_hashes)) != len(plan_hashes):
            raise ValueError("dataset plans must be unique and sorted by dataset_spec_hash")
        if plan_hashes != spec_hashes:
            raise ValueError("every dataset spec requires exactly one dataset plan")
        all_partition_ids = [
            item for plan in self.dataset_plans for item in plan.expected_partition_ids
        ]
        if len(set(all_partition_ids)) != len(all_partition_ids):
            raise ValueError("logical partition IDs must be globally unique in a snapshot")
        if self.manifest_hash != ZERO_SHA256 and self.manifest_hash != self.computed_hash():
            raise ValueError("manifest_hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "manifest_hash": ZERO_SHA256})
        return provisional.model_copy(update={"manifest_hash": provisional.computed_hash()})


class MetadataIndexEntry(FrozenModel):
    identifier: str = Field(pattern=SHA256_PATTERN)
    relative_path: str = Field(min_length=1)
    metadata_sha256: str = Field(pattern=SHA256_PATTERN)


class CatalogIndexRef(FrozenModel):
    """Integrity summary for one merged columnar catalog index."""

    index_name: Literal["objects", "logical_partitions", "fragments"]
    relative_path: str
    physical_sha256: str = Field(pattern=SHA256_PATTERN)
    schema_sha256: str = Field(pattern=SHA256_PATTERN)
    byte_size: int = Field(gt=0)
    row_count: int = Field(ge=0)

    @model_validator(mode="after")
    def fixed_path(self) -> Self:
        if self.relative_path != f"{self.index_name}.parquet":
            raise ValueError("catalog index path must be the approved fixed filename")
        return self


class DatasetSemanticRoot(FrozenModel):
    dataset_spec_hash: str = Field(pattern=SHA256_PATTERN)
    partition_count: int = Field(gt=0)
    empty_partition_count: int = Field(ge=0)
    row_count: int = Field(ge=0)
    legacy_hash_algorithm: Literal["ERA_CANONICAL_JSON_ROW_V1", "NOT_APPLICABLE"]
    legacy_semantic_root_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    v2_semantic_root_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def counts_are_valid(self) -> Self:
        if self.empty_partition_count > self.partition_count:
            raise ValueError("empty partition count exceeds partition count")
        if self.legacy_hash_algorithm == "ERA_CANONICAL_JSON_ROW_V1":
            if self.legacy_semantic_root_sha256 is None:
                raise ValueError("legacy-compatible dataset requires a legacy semantic root")
        elif self.legacy_semantic_root_sha256 is not None:
            raise ValueError("NOT_APPLICABLE dataset must not have a legacy semantic root")
        return self


class CatalogV2(FrozenModel):
    """Atomic catalog index; written only after every referenced entry exists."""

    schema_name: Literal["stage2-v2-catalog"] = "stage2-v2-catalog"
    catalog_version: Literal["2.0"] = "2.0"
    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    manifest_hash: str = Field(pattern=SHA256_PATTERN)
    objects: tuple[ArtifactRef, ...]
    seals: tuple[ShardSealV2, ...] = Field(min_length=1)
    objects_index: CatalogIndexRef
    logical_partitions_index: CatalogIndexRef
    fragments_index: CatalogIndexRef
    dataset_roots: tuple[DatasetSemanticRoot, ...] = Field(min_length=1)
    catalog_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"catalog_hash"}))

    @model_validator(mode="after")
    def validate_catalog(self) -> Self:
        for label, identifiers in (
            ("objects", tuple(item.object_sha256 for item in self.objects)),
            ("seals", tuple(item.seal_hash for item in self.seals)),
            (
                "dataset_roots",
                tuple(item.dataset_spec_hash for item in self.dataset_roots),
            ),
        ):
            if identifiers != tuple(sorted(identifiers)) or len(set(identifiers)) != len(
                identifiers
            ):
                raise ValueError(f"catalog {label} must be unique and sorted")
        if any(item.snapshot_id != self.snapshot_id for item in self.objects):
            raise ValueError("catalog object snapshot mismatch")
        if any(item.snapshot_id != self.snapshot_id for item in self.seals):
            raise ValueError("catalog seal snapshot mismatch")
        indexes = (
            self.objects_index,
            self.logical_partitions_index,
            self.fragments_index,
        )
        if tuple(item.index_name for item in indexes) != (
            "objects",
            "logical_partitions",
            "fragments",
        ):
            raise ValueError("catalog must reference the three approved merged indexes")
        if self.catalog_hash != ZERO_SHA256 and self.catalog_hash != self.computed_hash():
            raise ValueError("catalog_hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "catalog_hash": ZERO_SHA256})
        return provisional.model_copy(update={"catalog_hash": provisional.computed_hash()})
