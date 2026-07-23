"""Frozen authorities for the reusable Stage 2 Feature Foundation."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import Field, model_validator

from .models import (
    SHA256_PATTERN,
    ZERO_SHA256,
    DigestBinding,
    FrozenModel,
    metadata_sha256,
)


class FeatureDefinition(FrozenModel):
    schema_name: Literal["stage2-v2-feature-definition"] = "stage2-v2-feature-definition"
    definition_version: str = Field(min_length=1)
    definition_id: str = Field(min_length=1)
    source_kind: Literal[
        "CONTRACT_PRICE_1S",
        "CAUSAL_PRICE_BARS",
        "TRADES_1S_PRIMITIVE",
        "EXACT_TRADE_ROW_GROUP_INDEX",
        "GROUP1_EVENT_FACT",
    ]
    evidence_capability: Literal["H1", "H2"]
    formula_id: str = Field(min_length=1)
    availability_rule: str = Field(min_length=1)
    schema_sha256: str = Field(pattern=SHA256_PATTERN)
    implementation_tree_sha256: str = Field(pattern=SHA256_PATTERN)
    config_sha256: str = Field(pattern=SHA256_PATTERN)
    required_source_columns: tuple[str, ...] = Field(min_length=1)
    prohibited_capabilities: tuple[str, ...]
    definition_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"definition_hash"}))

    @model_validator(mode="after")
    def validate_definition(self) -> Self:
        if tuple(sorted(set(self.required_source_columns))) != self.required_source_columns:
            raise ValueError("feature source columns must be unique and sorted")
        h2_sources = {"TRADES_1S_PRIMITIVE", "EXACT_TRADE_ROW_GROUP_INDEX"}
        if self.source_kind in h2_sources and self.evidence_capability != "H2":
            raise ValueError("Trades-derived definitions require H2 capability")
        if self.definition_hash != ZERO_SHA256 and self.definition_hash != self.computed_hash():
            raise ValueError("feature definition hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "definition_hash": ZERO_SHA256})
        return provisional.model_copy(update={"definition_hash": provisional.computed_hash()})


class FeatureSnapshot(FrozenModel):
    schema_name: Literal["stage2-v2-feature-snapshot"] = "stage2-v2-feature-snapshot"
    snapshot_version: Literal["2.0"] = "2.0"
    definition_hash: str = Field(pattern=SHA256_PATTERN)
    instrument: Literal["BTCUSDT", "ETHUSDT"]
    utc_partition: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}$")
    window_start_ns: int = Field(ge=0)
    window_end_ns: int = Field(gt=0)
    available_at_ns: int = Field(gt=0)
    node_key: str = Field(pattern=SHA256_PATTERN)
    source_logical_hashes: tuple[str, ...] = Field(min_length=1)
    artifact_object_hashes: tuple[str, ...]
    logical_receipt_hashes: tuple[str, ...] = Field(min_length=1)
    row_count: int = Field(ge=0)
    quality_status: Literal["PASS"]
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"snapshot_hash"}))

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.window_end_ns <= self.window_start_ns:
            raise ValueError("feature snapshot window must be ordered")
        if self.available_at_ns < self.window_end_ns:
            raise ValueError("feature snapshot cannot be available before its window closes")
        for label, values in (
            ("source logical hashes", self.source_logical_hashes),
            ("artifact hashes", self.artifact_object_hashes),
            ("receipt hashes", self.logical_receipt_hashes),
        ):
            if tuple(sorted(set(values))) != values:
                raise ValueError(f"{label} must be unique and sorted")
            if any(len(value) != 64 for value in values):
                raise ValueError(f"{label} contains an invalid digest")
        if self.row_count and not self.artifact_object_hashes:
            raise ValueError("non-empty snapshot requires a physical artifact")
        if self.snapshot_hash != ZERO_SHA256 and self.snapshot_hash != self.computed_hash():
            raise ValueError("feature snapshot hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "snapshot_hash": ZERO_SHA256})
        return provisional.model_copy(update={"snapshot_hash": provisional.computed_hash()})


class FeatureFoundationManifest(FrozenModel):
    schema_name: Literal["stage2-v2-feature-foundation-manifest"] = (
        "stage2-v2-feature-foundation-manifest"
    )
    manifest_version: Literal["2.0"] = "2.0"
    task_id: Literal["S2-T10"] = "S2-T10"
    task_version: Literal["1.8"] = "1.8"
    change_requests: tuple[Literal["CR-2026-007", "CR-2026-008"], ...]
    stage1_data_run_id: str
    stage1_authorities: tuple[DigestBinding, ...] = Field(min_length=1)
    contract_price_inventory_sha256: str = Field(pattern=SHA256_PATTERN)
    preregistration_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    config_sha256: str = Field(pattern=SHA256_PATTERN)
    code_commit: str = Field(min_length=40, max_length=40)
    code_tree_sha256: str = Field(pattern=SHA256_PATTERN)
    external_root: str
    definitions: tuple[FeatureDefinition, ...] = Field(min_length=1)
    snapshots: tuple[FeatureSnapshot, ...] = Field(min_length=1)
    instruments: tuple[Literal["BTCUSDT", "ETHUSDT"], Literal["BTCUSDT", "ETHUSDT"]]
    prohibited_capabilities: tuple[str, ...]
    invalidation_conditions: tuple[str, ...] = Field(min_length=1)
    manifest_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if self.instruments != ("BTCUSDT", "ETHUSDT"):
            raise ValueError("Feature Foundation must keep BTC and ETH ordered and separate")
        authority_names = tuple(item.name for item in self.stage1_authorities)
        if authority_names != tuple(sorted(set(authority_names))):
            raise ValueError("Stage 1 authorities must be unique and sorted")
        definition_hashes = tuple(item.definition_hash for item in self.definitions)
        if definition_hashes != tuple(sorted(set(definition_hashes))):
            raise ValueError("Feature Definitions must be unique and sorted by hash")
        known = set(definition_hashes)
        snapshot_keys = [
            (item.definition_hash, item.instrument, item.utc_partition) for item in self.snapshots
        ]
        if any(item.definition_hash not in known for item in self.snapshots):
            raise ValueError("Feature Snapshot references an unknown definition")
        if snapshot_keys != sorted(set(snapshot_keys)):
            raise ValueError("Feature Snapshots must be complete, unique and ordered")
        if self.manifest_hash != ZERO_SHA256 and self.manifest_hash != self.computed_hash():
            raise ValueError("Feature Foundation manifest hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "manifest_hash": ZERO_SHA256})
        return provisional.model_copy(update={"manifest_hash": provisional.computed_hash()})


class Stage2V2ExecutionManifest(FrozenModel):
    schema_name: Literal["stage2-v2-group1-execution-manifest"] = (
        "stage2-v2-group1-execution-manifest"
    )
    manifest_version: Literal["2.0"] = "2.0"
    run_id: str = Field(min_length=1)
    source_run_a_protection_hash: str = Field(pattern=SHA256_PATTERN)
    migration_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    feature_foundation_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    preregistration_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    config_sha256: str = Field(pattern=SHA256_PATTERN)
    code_commit: str = Field(min_length=40, max_length=40)
    code_tree_sha256: str = Field(pattern=SHA256_PATTERN)
    approved_setup_id: Literal["KEY_LOW_SWEEP_RECLAIM_HOLD_V1"]
    approved_context_id: Literal["CAUSAL_EMA20_1H"]
    approved_variants: tuple[Literal["V1_PRICE", "V1_FLOW"], Literal["V1_PRICE", "V1_FLOW"]]
    instruments: tuple[Literal["BTCUSDT", "ETHUSDT"], Literal["BTCUSDT", "ETHUSDT"]]
    no_run_a_artifact_reuse: Literal[True]
    full_period_start: Literal["2020-01-01"]
    full_period_end_exclusive: Literal["2026-07-04"]
    invalidation_conditions: tuple[str, ...] = Field(min_length=1)
    manifest_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))

    @model_validator(mode="after")
    def validate_execution(self) -> Self:
        if self.approved_variants != ("V1_PRICE", "V1_FLOW"):
            raise ValueError("V2 Group-1 variants must be complete and ordered")
        if self.instruments != ("BTCUSDT", "ETHUSDT"):
            raise ValueError("V2 Group-1 instruments must be complete and ordered")
        if self.manifest_hash != ZERO_SHA256 and self.manifest_hash != self.computed_hash():
            raise ValueError("V2 execution manifest hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "manifest_hash": ZERO_SHA256})
        return provisional.model_copy(update={"manifest_hash": provisional.computed_hash()})
