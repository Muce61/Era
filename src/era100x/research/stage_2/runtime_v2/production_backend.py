"""Fail-closed production backend for the approved S2-T10 v1.8 matrix.

The backend owns release orchestration, never research semantics.  Foundation
and Group-1 builders return immutable catalog components; this module seals one
append-only task evidence record per fixed matrix task and publishes only after
all six records cover the exact Manifest plan.

The Group-1 production backend is statically imported and registry-bound.  An
unavailable or incompatible builder is therefore a hard stop rather than an
implicit fallback to the V1 runner.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol, Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from era100x.research.stage_2.manifests.models import canonical_json
from era100x.research.stage_2.pipelines.candidates.stage1_catalog import (
    Stage1TradesCatalogIndex,
)

from .catalog import CatalogComponentV2, CatalogPublisherV2, CatalogReaderV2
from .checkpoint import (
    FOUNDATION_TASKS,
    FULL_TASK_MATRIX,
    GROUP1_TASKS,
    BackendTaskReceipt,
    write_once_model,
)
from .compatibility import (
    LEGACY_HASH_ALGORITHM,
    V2_RECEIPT_LEGACY_HASH_ALGORITHM,
    RunACompatibilityAuthority,
    compare_run_a_to_v2_sorted_stream,
    project_formal_run_a,
)
from .foundation_pipeline import (
    FeatureFoundationPipeline,
    FoundationPipelineConfig,
    FoundationPipelineResult,
    FoundationShardCheckpoint,
    planned_packed_object_count,
)
from .errors import CatalogIntegrityError
from .foundation_sources import ContractPriceInventoryIndex, Instrument
from .group1_feature_builder import Group1Lineage
from .group1_pipeline import (
    Group1FeaturePipeline,
    Group1PackedTaskComponent,
    Group1PipelineConfig,
    Group1PipelineResult,
    Group1StreamingPipelineResult,
)
from .models import (
    MAX_PROCESS_CURRENT_RSS_BYTES,
    MAX_PROCESS_RSS_DELTA_BYTES,
    SHA256_PATTERN,
    ZERO_SHA256,
    ArtifactRef,
    CatalogV2,
    FragmentV2,
    Receipt,
    ShardSealV2,
    metadata_sha256,
)
from .memory import ProcessMemoryBudget, process_current_rss_bytes, process_peak_rss_bytes
from .resource_anomalies import ResourceAnomalyReportV1
from .orchestrator import (
    FORMAL_GROUP1_PARTITION_COUNT,
    RUN_A_ID,
    RuntimeComparison,
    RuntimeV2Context,
    RuntimeV2OrchestrationError,
    RuntimeVerification,
)
from .transition import sha256_file
from .source_authority import (
    CONTRACT_PRICE_MANIFEST_AUTHORITY,
    TRADES_RESOLVED_INDEX_AUTHORITY,
    ContractPriceInventoryManifestV2,
    Stage1ResolvedSourceIndexV2,
    load_sealed_source_manifest,
)

STAGE1_CATALOG_ROOT = Path(
    "/Volumes/FuckingLife/era100x_stage1/catalog/runs/"
    "stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682"
)
STAGE1_PUBLISHED_ROOT = Path(
    "/Volumes/FuckingLife/era100x_stage1/published/stage1-trades-v2/"
    "stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682"
)
CONTRACT_PRICE_ROOT = Path("/Users/muce/1m_data/klines_data_usdm_1s_agg")
RUN_A_ROOT = Path("/Volumes/FuckingLife/era100x_stage2/runs") / RUN_A_ID

STAGE1_DATA_RUN_ID = "stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682"
STAGE1_CANONICAL_MANIFEST_SHA256 = (
    "436ffbe36e310dd015a962a29593360729d06db25ff96eddf12644c62d76e94f"
)
STAGE1_PHYSICAL_MANIFEST_SHA256 = "f2ff20a35c26705c32de097a4df851717bffaeb872e900e8d988ddd2c4ac0ff0"
STAGE1_CATALOG_SHA256S: dict[Instrument, str] = {
    "BTCUSDT": "7381af50ae39675334cc378ad1a7a1c8ace16100ae007b9a3671744c3dd2a269",
    "ETHUSDT": "38397a3bcb2ef48412b8ebc7edf34013049b20c15831f363372406ef9ab60cfc",
}
STAGE1_LOGICAL_HASHES: dict[Instrument, str] = {
    "BTCUSDT": "03d437ed9a6c19d92162e5c9dd115df4988e8accce3c8180b749f15cfdcc36a8",
    "ETHUSDT": "6db4d5e411edae3838b352944b83c38ba68915841a1f9c9de8f16ef44c3b8332",
}
CONTRACT_PRICE_INVENTORY_SHA256 = "f7798be7e5441d3dc5e9c6470da71bb15ecd10b2750e273bdf9860b9e9d06a69"
RUN_A_GENERATOR_COMMIT = "366a541b7956030d1a0ea2b5c67b4b30e2154c76"

FORMAL_START = date(2020, 1, 1)
FORMAL_END_EXCLUSIVE = date(2026, 7, 4)
MAX_CATALOG_OBJECTS = 200
FOUNDATION_PLANNED_OBJECTS = 164
GROUP1_RESERVED_OBJECTS = 36
FORMAL_FOUNDATION_PARTITION_COUNT = 19_008
FORMAL_TOTAL_PARTITION_COUNT = 80_784
# Leave a deterministic safety margin below the approved absolute 1 GiB cap.


class ProductionBackendError(RuntimeV2OrchestrationError):
    """Production evidence is incomplete, conflicting, or unsafe to publish."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EvidenceFileBinding(_FrozenModel):
    relative_path: str = Field(min_length=1)
    physical_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def safe_path(self) -> Self:
        path = PurePosixPath(self.relative_path)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise ValueError("supporting evidence path must be safe and relative")
        if path.parts[0] != "staging":
            raise ValueError("supporting evidence must remain below staging/")
        return self


class DistributionCategory(_FrozenModel):
    value: str
    count: int = Field(ge=0)


class EvidenceDistribution(_FrozenModel):
    name: str
    counts: tuple[DistributionCategory, ...]

    @model_validator(mode="after")
    def deterministic(self) -> Self:
        values = tuple(item.value for item in self.counts)
        if values != tuple(sorted(values)) or len(values) != len(set(values)):
            raise ValueError("distribution categories must be unique and sorted")
        return self


class TaskAggregateEvidence(_FrozenModel):
    schema_name: Literal["stage2-v2-task-aggregate-evidence"] = "stage2-v2-task-aggregate-evidence"
    evidence_version: Literal["1.0"] = "1.0"
    task_id: str
    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    manifest_hash: str = Field(pattern=SHA256_PATTERN)
    artifacts: tuple[ArtifactRef, ...]
    receipts: tuple[Receipt, ...]
    fragments: tuple[FragmentV2, ...]
    seals: tuple[ShardSealV2, ...]
    supporting_evidence: tuple[EvidenceFileBinding, ...] = ()
    global_distributions: tuple[EvidenceDistribution, ...] = ()
    max_inflight_bytes_observed: int = Field(ge=0)
    peak_process_rss_bytes: int = Field(ge=0)
    resource_anomaly_count: int = Field(ge=0, default=0)
    quality_status: Literal["PASS"] = "PASS"
    semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    evidence_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_semantic_sha256(self) -> str:
        return metadata_sha256(
            {
                "task_id": self.task_id,
                "snapshot_id": self.snapshot_id,
                "manifest_hash": self.manifest_hash,
                "artifacts": tuple(
                    (item.object_sha256, item.semantic_sha256) for item in self.artifacts
                ),
                "receipts": tuple(
                    (item.partition.semantic_order_key(), item.semantic_receipt_sha256)
                    for item in self.receipts
                ),
                "fragments": tuple(item.fragment_hash for item in self.fragments),
                "seals": tuple(item.seal_hash for item in self.seals),
                "global_distributions": tuple(
                    item.model_dump(mode="json") for item in self.global_distributions
                ),
            }
        )

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"evidence_hash"}))

    @model_validator(mode="after")
    def complete_and_deterministic(self) -> Self:
        if self.task_id not in FULL_TASK_MATRIX:
            raise ValueError("task evidence is outside the fixed matrix")
        if self.semantic_sha256 != ZERO_SHA256:
            if self.semantic_sha256 != self.computed_semantic_sha256():
                raise ValueError("task evidence semantic hash mismatch")
        if self.evidence_hash != ZERO_SHA256 and self.evidence_hash != self.computed_hash():
            raise ValueError("task evidence hash mismatch")
        if any(item.snapshot_id != self.snapshot_id for item in self.artifacts):
            raise ValueError("task evidence mixes artifact snapshots")
        if any(item.snapshot_id != self.snapshot_id for item in self.receipts):
            raise ValueError("task evidence mixes receipt snapshots")
        if any(item.snapshot_id != self.snapshot_id for item in self.fragments):
            raise ValueError("task evidence mixes fragment snapshots")
        if any(item.snapshot_id != self.snapshot_id for item in self.seals):
            raise ValueError("task evidence mixes seal snapshots")
        _require_sorted_unique(self.artifacts, lambda item: item.object_sha256)
        _require_sorted_unique(
            self.receipts, lambda item: "\x1f".join(item.partition.semantic_order_key())
        )
        _require_sorted_unique(self.fragments, lambda item: item.fragment_hash)
        _require_sorted_unique(self.seals, lambda item: item.seal_hash)
        _require_sorted_unique(self.supporting_evidence, lambda item: item.relative_path)
        _require_sorted_unique(self.global_distributions, lambda item: item.name)
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate(
            {**payload, "semantic_sha256": ZERO_SHA256, "evidence_hash": ZERO_SHA256}
        )
        semantic = provisional.computed_semantic_sha256()
        with_semantic = provisional.model_copy(update={"semantic_sha256": semantic})
        return with_semantic.model_copy(update={"evidence_hash": with_semantic.computed_hash()})


class Group1ComponentBinding(_FrozenModel):
    task_id: str
    relative_path: str = Field(min_length=1)
    physical_sha256: str = Field(pattern=SHA256_PATTERN)
    component_hash: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def safe_and_approved(self) -> Self:
        if self.task_id not in GROUP1_TASKS:
            raise ValueError("Group-1 component is outside the fixed task matrix")
        path = PurePosixPath(self.relative_path)
        if (
            path.is_absolute()
            or ".." in path.parts
            or path.parts[:3]
            != (
                "staging",
                "evidence",
                "group1-components",
            )
        ):
            raise ValueError("Group-1 component must remain below staging/evidence")
        return self


class Group1TaskComponent(_FrozenModel):
    """One bounded instrument/variant metadata shard for Group-1."""

    schema_name: Literal["stage2-v2-group1-task-component"] = "stage2-v2-group1-task-component"
    component_version: Literal["1.0"] = "1.0"
    task_id: str
    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    manifest_hash: str = Field(pattern=SHA256_PATTERN)
    generator_commit: Literal["366a541b7956030d1a0ea2b5c67b4b30e2154c76"] = (
        "366a541b7956030d1a0ea2b5c67b4b30e2154c76"
    )
    artifacts: tuple[ArtifactRef, ...]
    receipts: tuple[Receipt, ...]
    fragments: tuple[FragmentV2, ...]
    seals: tuple[ShardSealV2, ...]
    component_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"component_hash"}))

    @model_validator(mode="after")
    def deterministic(self) -> Self:
        if self.task_id not in GROUP1_TASKS:
            raise ValueError("Group-1 component is outside the fixed task matrix")
        _require_sorted_unique(self.artifacts, lambda item: item.object_sha256)
        _require_sorted_unique(
            self.receipts, lambda item: "\x1f".join(item.partition.semantic_order_key())
        )
        _require_sorted_unique(self.fragments, lambda item: item.fragment_hash)
        _require_sorted_unique(self.seals, lambda item: item.seal_hash)
        if self.component_hash != ZERO_SHA256 and self.component_hash != self.computed_hash():
            raise ValueError("Group-1 task component hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "component_hash": ZERO_SHA256})
        return provisional.model_copy(update={"component_hash": provisional.computed_hash()})


class Group1ProductionAggregate(_FrozenModel):
    """Small immutable index over four bounded Group-1 component shards."""

    schema_name: Literal["stage2-v2-group1-production-aggregate"] = (
        "stage2-v2-group1-production-aggregate"
    )
    aggregate_version: Literal["2.0"] = "2.0"
    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    manifest_hash: str = Field(pattern=SHA256_PATTERN)
    generator_commit: Literal["366a541b7956030d1a0ea2b5c67b4b30e2154c76"] = (
        "366a541b7956030d1a0ea2b5c67b4b30e2154c76"
    )
    components: tuple[Group1ComponentBinding, ...]
    global_distributions: tuple[EvidenceDistribution, ...]
    max_inflight_bytes_observed: int = Field(ge=0)
    peak_process_rss_bytes: int = Field(ge=0)
    quality_status: Literal["PASS"] = "PASS"
    aggregate_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"aggregate_hash"}))

    @model_validator(mode="after")
    def deterministic(self) -> Self:
        _require_sorted_unique(self.components, lambda item: item.task_id)
        if tuple(item.task_id for item in self.components) != tuple(sorted(GROUP1_TASKS)):
            raise ValueError("Group-1 aggregate must bind all four task components")
        _require_sorted_unique(self.global_distributions, lambda item: item.name)
        if self.aggregate_hash != ZERO_SHA256 and self.aggregate_hash != self.computed_hash():
            raise ValueError("Group-1 production aggregate hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "aggregate_hash": ZERO_SHA256})
        return provisional.model_copy(update={"aggregate_hash": provisional.computed_hash()})


class PublicationQualityReport(_FrozenModel):
    schema_name: Literal["stage2-v2-publication-quality"] = "stage2-v2-publication-quality"
    report_version: Literal["1.0"] = "1.0"
    run_id: str
    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    manifest_hash: str = Field(pattern=SHA256_PATTERN)
    catalog_hash: str = Field(pattern=SHA256_PATTERN)
    task_count: Literal[6] = 6
    partition_count: int = Field(gt=0)
    object_count: int = Field(ge=0)
    fragment_count: int = Field(ge=0)
    seal_count: int = Field(gt=0)
    unknown_count: Literal[0] = 0
    error_count: Literal[0] = 0
    identity_conflict_count: Literal[0] = 0
    resource_anomaly_count: int = Field(ge=0, default=0)
    quality_status: Literal["PASS"] = "PASS"
    task_evidence_hashes: tuple[str, ...]
    report_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"report_hash"}))

    @model_validator(mode="after")
    def hash_matches(self) -> Self:
        if self.report_hash != ZERO_SHA256 and self.report_hash != self.computed_hash():
            raise ValueError("quality report hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "report_hash": ZERO_SHA256})
        return provisional.model_copy(update={"report_hash": provisional.computed_hash()})


class PublicationRecord(_FrozenModel):
    schema_name: Literal["stage2-v2-publication-record"] = "stage2-v2-publication-record"
    record_version: Literal["1.0"] = "1.0"
    run_id: str
    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    manifest_hash: str = Field(pattern=SHA256_PATTERN)
    catalog_hash: str = Field(pattern=SHA256_PATTERN)
    quality_report_hash: str = Field(pattern=SHA256_PATTERN)
    operation: Literal["SAME_VOLUME_ATOMIC_RENAME"] = "SAME_VOLUME_ATOMIC_RENAME"
    publication_state: Literal["PUBLISHED", "PUBLISHED_WITH_RESOURCE_ANOMALIES"] = "PUBLISHED"
    record_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"record_hash"}))

    @model_validator(mode="after")
    def hash_matches(self) -> Self:
        if self.record_hash != ZERO_SHA256 and self.record_hash != self.computed_hash():
            raise ValueError("publication record hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "record_hash": ZERO_SHA256})
        return provisional.model_copy(update={"record_hash": provisional.computed_hash()})


class PublicationPhaseRecord(_FrozenModel):
    schema_name: Literal["stage2-v2-publication-phase"] = "stage2-v2-publication-phase"
    record_version: Literal["1.0"] = "1.0"
    run_id: str
    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    manifest_hash: str = Field(pattern=SHA256_PATTERN)
    catalog_hash: str = Field(pattern=SHA256_PATTERN)
    phase: Literal["CATALOG_SEALED", "DATA_RENAMED", "PUBLISHED"]
    record_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"record_hash"}))

    @model_validator(mode="after")
    def hash_matches(self) -> Self:
        if self.record_hash != ZERO_SHA256 and self.record_hash != self.computed_hash():
            raise ValueError("publication phase record hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "record_hash": ZERO_SHA256})
        return provisional.model_copy(update={"record_hash": provisional.computed_hash()})


@dataclass(frozen=True, slots=True)
class PipelineTaskResult:
    artifacts: tuple[ArtifactRef, ...]
    receipts: tuple[Receipt, ...]
    fragments: tuple[FragmentV2, ...]
    seals: tuple[ShardSealV2, ...]
    supporting_evidence: tuple[EvidenceFileBinding, ...] = ()
    global_distributions: Mapping[str, Mapping[str, int]] | None = None
    max_inflight_bytes_observed: int = 0


class TaskBuilder(Protocol):
    def __call__(self, context: RuntimeV2Context, task_id: str) -> PipelineTaskResult: ...


class Group1AggregateBuilder(Protocol):
    def __call__(self, context: RuntimeV2Context) -> PipelineTaskResult: ...


class FoundationTaskBuilder(Protocol):
    def __call__(self, context: RuntimeV2Context, instrument: Instrument) -> PipelineTaskResult: ...


class SourceIndexLoader(Protocol):
    def __call__(
        self, context: RuntimeV2Context
    ) -> tuple[Stage1TradesCatalogIndex, ContractPriceInventoryIndex]: ...


class ProductionRuntimeV2Backend:
    """Static production backend with append-only evidence and publication."""

    def __init__(
        self,
        *,
        task_builder: TaskBuilder | None = None,
        foundation_task_builder: FoundationTaskBuilder | None = None,
        group1_aggregate_builder: Group1AggregateBuilder | None = None,
        source_index_loader: SourceIndexLoader | None = None,
        run_a_root: Path = RUN_A_ROOT,
        peak_rss_reader: Callable[[], int] | None = None,
        current_rss_reader: Callable[[], int] | None = None,
        publication_fault: Callable[[str], None] | None = None,
    ) -> None:
        self._task_builder = task_builder or self._build_production_task
        self._foundation_task_builder = (
            foundation_task_builder or self._build_foundation_production_task
        )
        self._uses_default_group1_builder = group1_aggregate_builder is None
        self._group1_aggregate_builder = (
            group1_aggregate_builder or self._build_group1_production_aggregate
        )
        self._source_index_loader = source_index_loader or self._load_authoritative_source_indexes
        self._run_a_root = Path(run_a_root)
        peak_reader = peak_rss_reader or process_peak_rss_bytes
        current_reader = current_rss_reader or (
            peak_rss_reader if peak_rss_reader is not None else process_current_rss_bytes
        )
        self._memory_budget = ProcessMemoryBudget(
            current_limit_bytes=MAX_PROCESS_CURRENT_RSS_BYTES,
            delta_limit_bytes=MAX_PROCESS_RSS_DELTA_BYTES,
            current_reader=current_reader,
            peak_reader=peak_reader,
        )
        self._publication_fault = publication_fault
        self._source_indexes: (
            tuple[Stage1TradesCatalogIndex, ContractPriceInventoryIndex] | None
        ) = None
        self._source_index_authority_key: tuple[str, str] | None = None

    def validate_preflight(self, context: RuntimeV2Context) -> None:
        """Validate all read-only authorities before consuming a new run_id."""

        self._assert_context(context)
        trades, prices = self._load_source_indexes(context)
        expected_days = (FORMAL_END_EXCLUSIVE - FORMAL_START).days
        expected_dates = tuple(
            FORMAL_START + timedelta(days=offset) for offset in range(expected_days)
        )
        for instrument in cast(tuple[Instrument, ...], ("BTCUSDT", "ETHUSDT")):
            trade_dates = tuple(
                item.partition_date for item in trades.partitions if item.instrument == instrument
            )
            price_dates = tuple(
                item.partition_date for item in prices.partitions if item.instrument == instrument
            )
            if trade_dates != expected_dates:
                raise ProductionBackendError(f"Stage 1 Trades coverage changed: {instrument}")
            if price_dates != expected_dates:
                raise ProductionBackendError(
                    f"Contract Price canonical coverage changed: {instrument}"
                )

        specs = {item.spec_hash: item for item in context.manifest.dataset_specs}
        group1_count = sum(
            len(plan.expected_partition_ids)
            for plan in context.manifest.dataset_plans
            if specs[plan.dataset_spec_hash].legacy_hash_algorithm == "ERA_CANONICAL_JSON_ROW_V1"
        )
        foundation_count = sum(
            len(plan.expected_partition_ids)
            for plan in context.manifest.dataset_plans
            if specs[plan.dataset_spec_hash].legacy_hash_algorithm == "NOT_APPLICABLE"
        )
        if (
            group1_count != FORMAL_GROUP1_PARTITION_COUNT
            or foundation_count != FORMAL_FOUNDATION_PARTITION_COUNT
            or group1_count + foundation_count != FORMAL_TOTAL_PARTITION_COUNT
        ):
            raise ProductionBackendError("Manifest partition capacity plan changed")

        catalog_path = self._run_a_root / "manifests" / "catalog.json"
        analysis_path = self._run_a_root / "reports" / "release-analysis.json"
        if sha256_file(catalog_path) != context.protection.catalog_sha256:
            raise ProductionBackendError("Run A comparison Catalog authority changed")
        if sha256_file(analysis_path) != context.protection.release_analysis_sha256:
            raise ProductionBackendError("Run A comparison analysis authority changed")

    def execute_task(
        self,
        context: RuntimeV2Context,
        task_id: str,
    ) -> BackendTaskReceipt:
        self._assert_context(context)
        self._assert_task_prefix(context, task_id)
        evidence_path = _task_evidence_path(context.run_root, task_id)
        if evidence_path.exists():
            evidence = _read_task_evidence(evidence_path)
        else:
            with self._memory_budget.monitor_phase(f"task {task_id}"):
                result = self._task_builder(context, task_id)
                evidence = self._seal_task_result(context, task_id, result)
                write_once_model(evidence_path, evidence)
        self._assert_task_evidence_authority(context, task_id, evidence)
        evidence_file_hash = sha256_file(evidence_path)
        return BackendTaskReceipt.seal(
            {
                "task_id": task_id,
                "snapshot_id": context.manifest.snapshot_id,
                "manifest_hash": context.manifest.manifest_hash,
                "semantic_sha256": evidence.semantic_sha256,
                "evidence_sha256": evidence_file_hash,
                "quality_status": "PASS",
                "resource_anomaly_count": evidence.resource_anomaly_count,
            }
        )

    def release_run(self, context: RuntimeV2Context) -> None:
        """Seal and publish in a fresh CLI process, separate from generation."""

        self._assert_context(context)
        if sum(1 for _item in self._iter_complete_evidence(context)) != len(FULL_TASK_MATRIX):
            raise ProductionBackendError("release evidence matrix is incomplete")
        self._ensure_published(context)

    def verify_completed_task(
        self,
        context: RuntimeV2Context,
        receipt: BackendTaskReceipt,
    ) -> None:
        self._assert_context(context)
        evidence_path = _task_evidence_path(context.run_root, receipt.task_id)
        if sha256_file(evidence_path) != receipt.evidence_sha256:
            raise ProductionBackendError("completed task evidence bytes changed")
        evidence = _read_task_evidence(evidence_path)
        if (
            evidence.task_id != receipt.task_id
            or evidence.snapshot_id != context.manifest.snapshot_id
            or evidence.manifest_hash != context.manifest.manifest_hash
            or evidence.semantic_sha256 != receipt.semantic_sha256
        ):
            raise ProductionBackendError("completed task evidence authority mismatch")
        for binding in evidence.supporting_evidence:
            path = _bound_path(context.run_root, binding.relative_path)
            if sha256_file(path) != binding.physical_sha256:
                raise ProductionBackendError("supporting evidence bytes changed")
        snapshot_root = _active_snapshot_root(context)
        for artifact in evidence.artifacts:
            path = _object_path(snapshot_root, artifact)
            if path.stat().st_size != artifact.byte_size or sha256_file(path) != (
                artifact.object_sha256
            ):
                raise ProductionBackendError("sealed object byte hash changed")

    def verify_run(self, context: RuntimeV2Context) -> RuntimeVerification:
        self._assert_context(context)
        checked_task_count = sum(1 for _item in self._iter_complete_evidence(context))
        reader = CatalogReaderV2.open(
            _published_snapshot_root(context),
            expected_snapshot_id=context.manifest.snapshot_id,
            deep_verify_objects=False,
        )
        quality = _read_model(_quality_path(context.run_root), PublicationQualityReport)
        publication = _read_model(_publication_path(context.run_root), PublicationRecord)
        if quality.catalog_hash != reader.catalog.catalog_hash:
            raise ProductionBackendError("quality report references another Catalog")
        if publication.catalog_hash != reader.catalog.catalog_hash:
            raise ProductionBackendError("publication record references another Catalog")
        return RuntimeVerification(
            snapshot_id=context.manifest.snapshot_id,
            manifest_hash=context.manifest.manifest_hash,
            publication_state=publication.publication_state,
            checked_task_count=checked_task_count,
            checked_partition_count=reader.logical_index.num_rows,
            unknown_count=0,
            error_count=0,
            semantic_sha256=reader.catalog.catalog_hash,
        )

    def compare_run_a(self, context: RuntimeV2Context) -> RuntimeComparison:
        self._assert_context(context)
        published_root = _published_snapshot_root(context)
        catalog = _read_model(published_root / "catalog.json", CatalogV2)
        publication = _read_model(_publication_path(context.run_root), PublicationRecord)
        quality = _read_model(_quality_path(context.run_root), PublicationQualityReport)
        if (
            catalog.snapshot_id != context.manifest.snapshot_id
            or publication.catalog_hash != catalog.catalog_hash
            or quality.catalog_hash != catalog.catalog_hash
        ):
            raise ProductionBackendError("comparison publication authority changed")
        catalog_path = self._run_a_root / "manifests" / "catalog.json"
        analysis_path = self._run_a_root / "reports" / "release-analysis.json"
        if sha256_file(catalog_path) != context.protection.catalog_sha256:
            raise ProductionBackendError("protected Run A Catalog bytes changed")
        if sha256_file(analysis_path) != context.protection.release_analysis_sha256:
            raise ProductionBackendError("protected Run A release analysis bytes changed")
        run_a = project_formal_run_a(
            _read_json_object(catalog_path),
            _read_json_object(analysis_path),
            authority=RunACompatibilityAuthority(
                source_run_id=context.protection.source_run_id,
                catalog_logical_hash=context.protection.catalog_logical_hash,
                legacy_hash_algorithm=LEGACY_HASH_ALGORITHM,
                catalog_entry_count=context.protection.catalog_entry_count,
            ),
        )
        self._enforce_compare_rss("Run A projection")

        def group1_receipts() -> Iterator[Receipt]:
            for task_id in sorted(GROUP1_TASKS):
                evidence = _read_task_evidence(_task_evidence_path(context.run_root, task_id))
                self._assert_task_evidence_authority(context, task_id, evidence)
                for receipt in evidence.receipts:
                    if receipt.legacy_hash_algorithm == V2_RECEIPT_LEGACY_HASH_ALGORITHM:
                        yield receipt

        distributions = _merge_evidence_distributions(
            evidence
            for evidence in self._iter_complete_evidence(context)
            if evidence.task_id in GROUP1_TASKS
        )
        report = compare_run_a_to_v2_sorted_stream(
            run_a,
            group1_receipts(),
            v2_legacy_hash_algorithm=LEGACY_HASH_ALGORITHM,
            v2_global_distributions=distributions,
        )
        self._enforce_compare_rss("semantic comparison")
        report_payload = _jsonable(report)
        report_hash = metadata_sha256(report_payload)
        _write_once_payload(
            _comparison_path(context.run_root),
            {
                "schema_name": "stage2-v2-run-a-compatibility-report",
                "report_version": "1.0",
                "snapshot_id": context.manifest.snapshot_id,
                "manifest_hash": context.manifest.manifest_hash,
                "report": report_payload,
                "report_hash": report_hash,
            },
        )
        report.require_pass()
        return RuntimeComparison(
            snapshot_id=context.manifest.snapshot_id,
            manifest_hash=context.manifest.manifest_hash,
            matched_partition_count=report.matched_partition_count,
            difference_count=len(report.differences),
            comparison_sha256=report_hash,
        )

    def _enforce_compare_rss(self, phase: str) -> None:
        self._memory_budget.check(phase)

    def _seal_task_result(
        self,
        context: RuntimeV2Context,
        task_id: str,
        result: PipelineTaskResult,
    ) -> TaskAggregateEvidence:
        sample = self._memory_budget.check(
            f"seal task {task_id}",
            arrow_inflight_bytes=result.max_inflight_bytes_observed,
        )
        peak_rss = sample.peak_rss_bytes
        self._memory_budget.observe_threshold(
            category="OBJECT_COUNT",
            phase=f"seal task {task_id}",
            metric_name="TASK_OBJECT_COUNT",
            threshold=(
                FOUNDATION_PLANNED_OBJECTS if task_id in FOUNDATION_TASKS else MAX_CATALOG_OBJECTS
            ),
            observed=len(result.artifacts),
            unit="objects",
        )
        for artifact in result.artifacts:
            self._memory_budget.observe_threshold(
                category="SHARD_SIZE",
                phase=f"seal task {task_id}",
                metric_name="PACKED_OBJECT_BYTES",
                threshold=512 << 20,
                observed=artifact.byte_size,
            )
        safe_task = task_id.lower().replace(":", "-")
        anomaly_relative_path = f"staging/evidence/resource-anomalies/{safe_task}.json"
        anomaly_path = context.run_root / anomaly_relative_path
        observations = self._memory_budget.drain_anomalies()
        if anomaly_path.is_file() and not anomaly_path.is_symlink():
            anomaly_report = ResourceAnomalyReportV1.model_validate_json(anomaly_path.read_bytes())
            if (
                anomaly_report.run_id != context.run_id
                or anomaly_report.task_id != task_id
                or anomaly_report.snapshot_id != context.manifest.snapshot_id
                or anomaly_report.manifest_hash != context.manifest.manifest_hash
            ):
                raise ProductionBackendError("resource anomaly evidence authority mismatch")
        else:
            anomaly_report = ResourceAnomalyReportV1.seal(
                run_id=context.run_id,
                task_id=task_id,
                snapshot_id=context.manifest.snapshot_id,
                manifest_hash=context.manifest.manifest_hash,
                config_sha256=context.manifest.config_sha256,
                code_tree_sha256=context.manifest.code_tree_sha256,
                observations=observations,
            )
        anomaly_file_hash = write_once_model(anomaly_path, anomaly_report)
        distributions = _normalize_distributions(result.global_distributions or {})
        evidence = TaskAggregateEvidence.seal(
            {
                "task_id": task_id,
                "snapshot_id": context.manifest.snapshot_id,
                "manifest_hash": context.manifest.manifest_hash,
                "artifacts": tuple(sorted(result.artifacts, key=lambda item: item.object_sha256)),
                "receipts": tuple(
                    sorted(result.receipts, key=lambda item: item.partition.semantic_order_key())
                ),
                "fragments": tuple(sorted(result.fragments, key=lambda item: item.fragment_hash)),
                "seals": tuple(sorted(result.seals, key=lambda item: item.seal_hash)),
                "supporting_evidence": tuple(
                    sorted(
                        (
                            *result.supporting_evidence,
                            EvidenceFileBinding(
                                relative_path=anomaly_relative_path,
                                physical_sha256=anomaly_file_hash,
                            ),
                        ),
                        key=lambda item: item.relative_path,
                    )
                ),
                "global_distributions": distributions,
                "max_inflight_bytes_observed": result.max_inflight_bytes_observed,
                "peak_process_rss_bytes": peak_rss,
                "resource_anomaly_count": len(anomaly_report.anomalies),
                "quality_status": "PASS",
            }
        )
        self._assert_task_scope(task_id, evidence.receipts)
        return evidence

    def _ensure_published(self, context: RuntimeV2Context) -> None:
        staging = _staging_snapshot_root(context)
        published = _published_snapshot_root(context)
        if published.exists():
            if staging.exists():
                raise ProductionBackendError("staging and published snapshot both exist")
            reader = CatalogReaderV2.open(
                published,
                expected_snapshot_id=context.manifest.snapshot_id,
                deep_verify_objects=True,
            )
            quality = _read_model(_quality_path(context.run_root), PublicationQualityReport)
            published_evidence_hashes = tuple(
                item.evidence_hash for item in self._iter_complete_evidence(context)
            )
            if quality.task_evidence_hashes != published_evidence_hashes:
                raise ProductionBackendError("published quality/task evidence authority changed")
            try:
                self._write_publication_phase(context, reader.catalog.catalog_hash, "DATA_RENAMED")
                self._write_publication_record(context, reader.catalog.catalog_hash, quality)
                self._write_publication_phase(context, reader.catalog.catalog_hash, "PUBLISHED")
            except OSError as exc:
                raise InterruptedError(
                    "published snapshot is intact; publication evidence append is recoverable"
                ) from exc
            return
        if not staging.is_dir() or staging.is_symlink():
            raise ProductionBackendError("complete staging snapshot is missing")

        evidence_hashes: list[str] = []
        partition_count = 0
        fragment_count = 0
        object_ids: set[str] = set()
        seal_ids: set[str] = set()

        def components() -> Iterator[CatalogComponentV2]:
            nonlocal partition_count, fragment_count
            for evidence in self._iter_complete_evidence(context):
                evidence_hashes.append(evidence.evidence_hash)
                partition_count += len(evidence.receipts)
                fragment_count += len(evidence.fragments)
                object_ids.update(item.object_sha256 for item in evidence.artifacts)
                seal_ids.update(item.shard_id for item in evidence.seals)
                yield CatalogComponentV2(
                    artifacts=evidence.artifacts,
                    receipts=evidence.receipts,
                    fragments=evidence.fragments,
                    seals=evidence.seals,
                )

        try:
            catalog = CatalogPublisherV2(staging).publish_components(
                context.manifest, components=components()
            )
            # The publisher has already validated every component, object,
            # partition and index hash.  Reopening the 80,784-partition
            # Catalog in this same process would overlap Arrow allocator
            # high-water state with publication metadata.  The explicit
            # ``verify`` CLI performs
            # this reopen in a fresh read-only process after publication.
            self._write_publication_phase(context, catalog.catalog_hash, "CATALOG_SEALED")
        except CatalogIntegrityError as exc:
            if "artifact byte hash mismatch" in str(exc):
                raise ProductionBackendError(
                    "staged object byte hash differs from ArtifactRef"
                ) from exc
            raise ProductionBackendError(f"Catalog sealing integrity failure: {exc}") from exc
        except OSError as exc:
            raise InterruptedError("Catalog sealing I/O interruption is recoverable") from exc
        resource_anomaly_count = sum(
            evidence.resource_anomaly_count for evidence in self._iter_complete_evidence(context)
        )
        quality = PublicationQualityReport.seal(
            {
                "run_id": context.run_id,
                "snapshot_id": context.manifest.snapshot_id,
                "manifest_hash": context.manifest.manifest_hash,
                "catalog_hash": catalog.catalog_hash,
                "task_count": 6,
                "partition_count": partition_count,
                "object_count": len(object_ids),
                "fragment_count": fragment_count,
                "seal_count": len(seal_ids),
                "unknown_count": 0,
                "error_count": 0,
                "identity_conflict_count": 0,
                "resource_anomaly_count": resource_anomaly_count,
                "quality_status": "PASS",
                "task_evidence_hashes": tuple(evidence_hashes),
            }
        )
        try:
            write_once_model(_quality_path(context.run_root), quality)
            published.parent.mkdir(parents=True, exist_ok=True)
            if staging.stat().st_dev != published.parent.stat().st_dev:
                raise ProductionBackendError("snapshot publication is not a same-volume rename")
            os.replace(staging, published)
            _fsync_directory(published.parent)
            if self._publication_fault is not None:
                self._publication_fault("AFTER_DATA_RENAMED")
            self._write_publication_phase(context, catalog.catalog_hash, "DATA_RENAMED")
            self._write_publication_record(context, catalog.catalog_hash, quality)
            self._write_publication_phase(context, catalog.catalog_hash, "PUBLISHED")
        except OSError as exc:
            phase = "after DATA_RENAMED" if published.is_dir() else "before DATA_RENAMED"
            raise InterruptedError(f"publication I/O interruption {phase} is recoverable") from exc

    def _write_publication_record(
        self,
        context: RuntimeV2Context,
        catalog_hash: str,
        quality: PublicationQualityReport,
    ) -> None:
        record = PublicationRecord.seal(
            {
                "run_id": context.run_id,
                "snapshot_id": context.manifest.snapshot_id,
                "manifest_hash": context.manifest.manifest_hash,
                "catalog_hash": catalog_hash,
                "quality_report_hash": quality.report_hash,
                "operation": "SAME_VOLUME_ATOMIC_RENAME",
                "publication_state": (
                    "PUBLISHED_WITH_RESOURCE_ANOMALIES"
                    if quality.resource_anomaly_count
                    else "PUBLISHED"
                ),
            }
        )
        write_once_model(_publication_path(context.run_root), record)

    @staticmethod
    def _write_publication_phase(
        context: RuntimeV2Context,
        catalog_hash: str,
        phase: Literal["CATALOG_SEALED", "DATA_RENAMED", "PUBLISHED"],
    ) -> None:
        record = PublicationPhaseRecord.seal(
            {
                "run_id": context.run_id,
                "snapshot_id": context.manifest.snapshot_id,
                "manifest_hash": context.manifest.manifest_hash,
                "catalog_hash": catalog_hash,
                "phase": phase,
            }
        )
        write_once_model(_publication_phase_path(context.run_root, phase), record)

    def _iter_complete_evidence(self, context: RuntimeV2Context) -> Iterator[TaskAggregateEvidence]:
        for task_id in FULL_TASK_MATRIX:
            evidence = _read_task_evidence(_task_evidence_path(context.run_root, task_id))
            self._assert_task_evidence_authority(context, task_id, evidence)
            yield evidence

    def _assert_task_evidence_authority(
        self,
        context: RuntimeV2Context,
        task_id: str,
        evidence: TaskAggregateEvidence,
    ) -> None:
        if (
            evidence.task_id != task_id
            or evidence.snapshot_id != context.manifest.snapshot_id
            or evidence.manifest_hash != context.manifest.manifest_hash
        ):
            raise ProductionBackendError("task evidence authority mismatch")
        self._assert_task_scope(task_id, evidence.receipts)

    def _assert_context(self, context: RuntimeV2Context) -> None:
        if context.manifest.manifest_hash != context.manifest.computed_hash():
            raise ProductionBackendError("Manifest hash cannot be reproduced")
        if context.manifest.stage1_data_run_id != STAGE1_DATA_RUN_ID:
            raise ProductionBackendError("Manifest Stage 1 Data Run ID changed")
        if context.manifest.code_tree_sha256 != context.migration.v2_code_tree_hash:
            raise ProductionBackendError("Manifest/migration code tree mismatch")
        authorities = {item.name: item.sha256 for item in context.manifest.stage1_authorities}
        expected_source_manifests = dict(self.freeze_source_authority_bindings(context))
        if any(
            authorities.get(name) != digest for name, digest in expected_source_manifests.items()
        ):
            raise ProductionBackendError(
                "Runtime Manifest omits a sealed resolved source authority"
            )
        # The former 200-object layout budget is an execution-performance
        # observation under CR-2026-013, not a semantic preflight gate.

    @staticmethod
    def _assert_capacity_plan() -> None:
        foundation = planned_packed_object_count(
            start=FORMAL_START,
            end_exclusive=FORMAL_END_EXCLUSIVE,
            instrument_count=2,
        )
        del foundation

    @staticmethod
    def _assert_task_prefix(context: RuntimeV2Context, task_id: str) -> None:
        if task_id not in FULL_TASK_MATRIX:
            raise ProductionBackendError(f"unapproved production task: {task_id}")
        position = FULL_TASK_MATRIX.index(task_id)
        for prior in FULL_TASK_MATRIX[:position]:
            if not _task_evidence_path(context.run_root, prior).is_file():
                raise ProductionBackendError(f"task order violation; missing {prior}")
        for later in FULL_TASK_MATRIX[position + 1 :]:
            if _task_evidence_path(context.run_root, later).exists():
                raise ProductionBackendError(f"task order violation; premature {later}")

    @staticmethod
    def _assert_task_scope(task_id: str, receipts: Sequence[Receipt]) -> None:
        parts = task_id.split(":")
        instrument = parts[1]
        if any(item.partition.instrument != instrument for item in receipts):
            raise ProductionBackendError("task evidence mixes instruments")
        if task_id in FOUNDATION_TASKS:
            if any(item.legacy_hash_algorithm != "NOT_APPLICABLE" for item in receipts):
                raise ProductionBackendError("Foundation task contains Group-1 receipts")
        else:
            variant = parts[2]
            if any(item.partition.variant != variant for item in receipts):
                raise ProductionBackendError("Group-1 task evidence mixes variants")
            if any(
                item.legacy_hash_algorithm != V2_RECEIPT_LEGACY_HASH_ALGORITHM for item in receipts
            ):
                raise ProductionBackendError("Group-1 task lacks V1 compatibility receipts")

    def _build_production_task(
        self,
        context: RuntimeV2Context,
        task_id: str,
    ) -> PipelineTaskResult:
        if task_id in FOUNDATION_TASKS:
            return self._foundation_task_builder(context, cast(Instrument, task_id.split(":")[1]))
        return self._build_group1_task(
            context,
            cast(Instrument, task_id.split(":")[1]),
            task_id.split(":")[2],
            task_id,
        )

    def _build_foundation_production_task(
        self,
        context: RuntimeV2Context,
        instrument: Instrument,
    ) -> PipelineTaskResult:
        trades, prices = self._load_source_indexes(context)
        pipeline = FeatureFoundationPipeline(
            config=FoundationPipelineConfig(run_root=context.run_root),
            snapshot_id=context.manifest.snapshot_id,
            trades_index=trades,
            contract_price_index=prices,
        )
        result: FoundationPipelineResult = pipeline.build(
            instruments=(instrument,),
            start=FORMAL_START,
            end_exclusive=FORMAL_END_EXCLUSIVE,
        )
        expected_days = (FORMAL_END_EXCLUSIVE - FORMAL_START).days
        verification_series = {
            "contract_price_sha256_verifications_per_partition": (
                result.contract_price_sha256_verification_counts
            ),
            "stage1_trades_sha256_verifications_per_partition": (
                result.trade_sha256_verification_counts
            ),
            "stage1_trades_decodes_per_partition": result.trade_decode_counts,
        }
        for name, counts in verification_series.items():
            if (
                len(counts) > expected_days
                or len({(item[0], item[1]) for item in counts}) != len(counts)
                or any(item[2] != 1 for item in counts)
            ):
                raise ProductionBackendError(f"{name} was not exactly one at first consumption")
        supporting = tuple(
            _foundation_checkpoint_binding(context.run_root, item) for item in result.checkpoints
        )
        return PipelineTaskResult(
            artifacts=result.artifacts,
            receipts=result.receipts,
            fragments=result.fragments,
            seals=result.seals,
            supporting_evidence=supporting,
            global_distributions={
                name: {
                    "verified_once_current_invocation": len(counts),
                    "reused_from_sealed_checkpoint": expected_days - len(counts),
                }
                for name, counts in verification_series.items()
            },
            max_inflight_bytes_observed=result.max_inflight_bytes_observed,
        )

    def _build_group1_task(
        self,
        context: RuntimeV2Context,
        instrument: Instrument,
        variant: str,
        task_id: str,
    ) -> PipelineTaskResult:
        aggregate = self._ensure_group1_aggregate(context)
        binding = next((item for item in aggregate.components if item.task_id == task_id), None)
        if binding is None:
            raise ProductionBackendError(f"Group-1 aggregate omits component {task_id}")
        path = _bound_path(context.run_root, binding.relative_path)
        if sha256_file(path) != binding.physical_sha256:
            raise ProductionBackendError("Group-1 component bytes changed")
        component = _read_model(path, Group1TaskComponent)
        if (
            component.task_id != task_id
            or component.snapshot_id != context.manifest.snapshot_id
            or component.manifest_hash != context.manifest.manifest_hash
            or component.component_hash != binding.component_hash
        ):
            raise ProductionBackendError("Group-1 component authority mismatch")
        if any(
            item.partition.instrument != instrument or item.partition.variant != variant
            for item in component.receipts
        ):
            raise ProductionBackendError("Group-1 component scope changed")
        distributions = (
            {
                item.name: {entry.value: entry.count for entry in item.counts}
                for item in aggregate.global_distributions
            }
            if (instrument, variant) == ("ETHUSDT", "V1_FLOW")
            else {}
        )
        return PipelineTaskResult(
            artifacts=component.artifacts,
            receipts=component.receipts,
            fragments=component.fragments,
            seals=component.seals,
            global_distributions=distributions,
            max_inflight_bytes_observed=aggregate.max_inflight_bytes_observed,
        )

    def _ensure_group1_aggregate(self, context: RuntimeV2Context) -> Group1ProductionAggregate:
        path = _group1_aggregate_path(context.run_root)
        if path.exists():
            aggregate = _read_model(path, Group1ProductionAggregate)
            if (
                aggregate.snapshot_id != context.manifest.snapshot_id
                or aggregate.manifest_hash != context.manifest.manifest_hash
            ):
                raise ProductionBackendError("Group-1 aggregate authority mismatch")
            return aggregate
        if not _task_evidence_path(context.run_root, FOUNDATION_TASKS[-1]).is_file():
            raise ProductionBackendError("Group-1 aggregate requires both Foundation tasks")
        if self._uses_default_group1_builder:
            return self._build_group1_streaming_production_aggregate(context)
        result = self._group1_aggregate_builder(context)
        bindings: list[Group1ComponentBinding] = []
        for task_id in GROUP1_TASKS:
            _prefix, instrument, variant = task_id.split(":")
            receipts = tuple(
                sorted(
                    (
                        item
                        for item in result.receipts
                        if item.partition.instrument == instrument
                        and item.partition.variant == variant
                    ),
                    key=lambda item: item.partition.semantic_order_key(),
                )
            )
            fragment_ids = {value for item in receipts for value in item.fragment_hashes}
            fragments = tuple(
                sorted(
                    (item for item in result.fragments if item.fragment_hash in fragment_ids),
                    key=lambda item: item.fragment_hash,
                )
            )
            object_ids = {item.artifact.object_sha256 for item in fragments}
            artifacts = tuple(
                sorted(
                    (item for item in result.artifacts if item.object_sha256 in object_ids),
                    key=lambda item: item.object_sha256,
                )
            )
            shard_ids = {item.shard_id for item in receipts}
            seals = tuple(
                sorted(
                    (item for item in result.seals if item.shard_id in shard_ids),
                    key=lambda item: item.seal_hash,
                )
            )
            component = Group1TaskComponent.seal(
                {
                    "task_id": task_id,
                    "snapshot_id": context.manifest.snapshot_id,
                    "manifest_hash": context.manifest.manifest_hash,
                    "generator_commit": RUN_A_GENERATOR_COMMIT,
                    "artifacts": artifacts,
                    "receipts": receipts,
                    "fragments": fragments,
                    "seals": seals,
                }
            )
            component_path = _group1_component_path(context.run_root, task_id)
            write_once_model(component_path, component)
            bindings.append(
                Group1ComponentBinding(
                    task_id=task_id,
                    relative_path=component_path.relative_to(context.run_root).as_posix(),
                    physical_sha256=sha256_file(component_path),
                    component_hash=component.component_hash,
                )
            )
        peak_rss = self._memory_budget.check("Group-1 component sealing").peak_rss_bytes
        aggregate = Group1ProductionAggregate.seal(
            {
                "snapshot_id": context.manifest.snapshot_id,
                "manifest_hash": context.manifest.manifest_hash,
                "generator_commit": RUN_A_GENERATOR_COMMIT,
                "components": tuple(sorted(bindings, key=lambda item: item.task_id)),
                "global_distributions": _normalize_distributions(result.global_distributions or {}),
                "max_inflight_bytes_observed": result.max_inflight_bytes_observed,
                "peak_process_rss_bytes": peak_rss,
                "quality_status": "PASS",
            }
        )
        write_once_model(path, aggregate)
        return aggregate

    def _build_group1_streaming_production_aggregate(
        self, context: RuntimeV2Context
    ) -> Group1ProductionAggregate:
        """Persist each task component before the next metadata graph exists."""

        foundation_checkpoints = self._load_foundation_checkpoints(context)
        lineage = {
            current: Group1Lineage(
                data_run_id=STAGE1_DATA_RUN_ID,
                dataset_logical_hash=STAGE1_LOGICAL_HASHES[current],
                config_hash=context.manifest.config_sha256,
                code_version=RUN_A_GENERATOR_COMMIT,
            )
            for current in cast(tuple[Instrument, ...], ("BTCUSDT", "ETHUSDT"))
        }
        pipeline = Group1FeaturePipeline(
            config=Group1PipelineConfig(
                run_root=context.run_root,
                foundation_catalog_root=_staging_snapshot_root(context),
            ),
            snapshot_id=context.manifest.snapshot_id,
            foundation_checkpoints=foundation_checkpoints,
            lineage_by_instrument=lineage,
        )
        bindings: list[Group1ComponentBinding] = []

        def persist(component: Group1PackedTaskComponent) -> None:
            task_id = f"GROUP1:{component.instrument}:{component.variant}"
            if task_id not in GROUP1_TASKS:
                raise ProductionBackendError("streamed Group-1 component escaped the matrix")
            model = Group1TaskComponent.seal(
                {
                    "task_id": task_id,
                    "snapshot_id": context.manifest.snapshot_id,
                    "manifest_hash": context.manifest.manifest_hash,
                    "generator_commit": RUN_A_GENERATOR_COMMIT,
                    "artifacts": component.artifacts,
                    "receipts": component.receipts,
                    "fragments": component.fragments,
                    "seals": component.seals,
                }
            )
            component_path = _group1_component_path(context.run_root, task_id)
            write_once_model(component_path, model)
            bindings.append(
                Group1ComponentBinding(
                    task_id=task_id,
                    relative_path=component_path.relative_to(context.run_root).as_posix(),
                    physical_sha256=sha256_file(component_path),
                    component_hash=model.component_hash,
                )
            )

        result: Group1StreamingPipelineResult = pipeline.build_streaming_components(
            instruments=("BTCUSDT", "ETHUSDT"),
            start=FORMAL_START,
            end_exclusive=FORMAL_END_EXCLUSIVE,
            component_sink=persist,
        )
        if tuple(sorted(item.task_id for item in bindings)) != tuple(sorted(GROUP1_TASKS)):
            raise ProductionBackendError("streamed Group-1 build omitted a task component")
        peak_rss = max(
            self._memory_budget.check("Group-1 streaming build").peak_rss_bytes,
            result.max_process_rss_bytes_observed,
        )
        distribution_map: dict[str, dict[str, int]] = {}
        for item in result.distributions:
            distribution_map.setdefault(item.name, {})[item.value] = item.count
        aggregate = Group1ProductionAggregate.seal(
            {
                "snapshot_id": context.manifest.snapshot_id,
                "manifest_hash": context.manifest.manifest_hash,
                "generator_commit": RUN_A_GENERATOR_COMMIT,
                "components": tuple(sorted(bindings, key=lambda item: item.task_id)),
                "global_distributions": _normalize_distributions(distribution_map),
                "max_inflight_bytes_observed": result.max_inflight_bytes_observed,
                "peak_process_rss_bytes": peak_rss,
                "quality_status": "PASS",
            }
        )
        write_once_model(_group1_aggregate_path(context.run_root), aggregate)
        return aggregate

    def _build_group1_production_aggregate(self, context: RuntimeV2Context) -> PipelineTaskResult:
        foundation_checkpoints = self._load_foundation_checkpoints(context)
        lineage = {
            current: Group1Lineage(
                data_run_id=STAGE1_DATA_RUN_ID,
                dataset_logical_hash=STAGE1_LOGICAL_HASHES[current],
                config_hash=context.manifest.config_sha256,
                # Event identities and legacy payloads bind the frozen Run A
                # generator.  V2 code-tree authority remains in Manifest and
                # receipts and must never leak into event semantics.
                code_version=RUN_A_GENERATOR_COMMIT,
            )
            for current in cast(tuple[Instrument, ...], ("BTCUSDT", "ETHUSDT"))
        }
        pipeline = Group1FeaturePipeline(
            config=Group1PipelineConfig(
                run_root=context.run_root,
                foundation_catalog_root=_staging_snapshot_root(context),
            ),
            snapshot_id=context.manifest.snapshot_id,
            foundation_checkpoints=foundation_checkpoints,
            lineage_by_instrument=lineage,
        )
        raw: Group1PipelineResult = pipeline.build(
            instruments=("BTCUSDT", "ETHUSDT"),
            start=FORMAL_START,
            end_exclusive=FORMAL_END_EXCLUSIVE,
        )
        distributions: dict[str, dict[str, int]] = {}
        for item in raw.distributions:
            distributions.setdefault(item.name, {})[item.value] = item.count
        return PipelineTaskResult(
            artifacts=raw.artifacts,
            receipts=raw.receipts,
            fragments=raw.fragments,
            seals=raw.seals,
            global_distributions=distributions,
            max_inflight_bytes_observed=raw.max_inflight_bytes_observed,
        )

    def _load_source_indexes(
        self, context: RuntimeV2Context
    ) -> tuple[Stage1TradesCatalogIndex, ContractPriceInventoryIndex]:
        authority_key = (
            context.migration.contract_price_inventory_manifest_hash,
            context.migration.stage1_resolved_source_index_manifest_hash,
        )
        if self._source_indexes is not None:
            if self._source_index_authority_key != authority_key:
                raise ProductionBackendError("cached source indexes belong to another authority")
            return self._source_indexes
        self._source_indexes = self._source_index_loader(context)
        self._source_index_authority_key = authority_key
        return self._source_indexes

    @staticmethod
    def _load_authoritative_source_indexes(
        context: RuntimeV2Context,
    ) -> tuple[Stage1TradesCatalogIndex, ContractPriceInventoryIndex]:
        price_path = Path(context.migration.contract_price_inventory_manifest_path)
        trades_path = Path(context.migration.stage1_resolved_source_index_path)
        if sha256_file(price_path) != context.migration.contract_price_inventory_source_sha256:
            raise ProductionBackendError("Contract Price source Manifest bytes changed")
        if sha256_file(trades_path) != (
            context.migration.stage1_resolved_source_index_source_sha256
        ):
            raise ProductionBackendError("Stage 1 resolved source index bytes changed")
        price_manifest = load_sealed_source_manifest(price_path, ContractPriceInventoryManifestV2)
        trades_manifest = load_sealed_source_manifest(trades_path, Stage1ResolvedSourceIndexV2)
        if price_manifest.manifest_hash != (
            context.migration.contract_price_inventory_manifest_hash
        ):
            raise ProductionBackendError("Contract Price source Manifest authority changed")
        if trades_manifest.manifest_hash != (
            context.migration.stage1_resolved_source_index_manifest_hash
        ):
            raise ProductionBackendError("Stage 1 resolved source index authority changed")
        if (
            price_manifest.legacy_inventory_sha256 != CONTRACT_PRICE_INVENTORY_SHA256
            or trades_manifest.data_run_id != STAGE1_DATA_RUN_ID
            or trades_manifest.dataset_version != "stage1-trades-v2"
            or trades_manifest.canonical_manifest_sha256 != STAGE1_CANONICAL_MANIFEST_SHA256
            or trades_manifest.physical_manifest_sha256 != STAGE1_PHYSICAL_MANIFEST_SHA256
            or trades_manifest.catalog_sha256s != STAGE1_CATALOG_SHA256S
            or trades_manifest.instrument_logical_hashes != STAGE1_LOGICAL_HASHES
        ):
            raise ProductionBackendError("sealed Stage 1 source authority changed")
        trades = trades_manifest.to_index(published_root=STAGE1_PUBLISHED_ROOT)
        prices = price_manifest.to_index(root=CONTRACT_PRICE_ROOT)
        return trades, prices

    @staticmethod
    def freeze_source_authority_bindings(
        context: RuntimeV2Context,
    ) -> tuple[tuple[str, str], ...]:
        """Expose the two semantic bindings required in Manifest snapshot identity."""

        return (
            (
                CONTRACT_PRICE_MANIFEST_AUTHORITY,
                context.migration.contract_price_inventory_manifest_hash,
            ),
            (
                TRADES_RESOLVED_INDEX_AUTHORITY,
                context.migration.stage1_resolved_source_index_manifest_hash,
            ),
        )

    @staticmethod
    def _load_foundation_checkpoints(
        context: RuntimeV2Context,
    ) -> tuple[FoundationShardCheckpoint, ...]:
        checkpoints: list[FoundationShardCheckpoint] = []
        for task_id in FOUNDATION_TASKS:
            evidence = _read_task_evidence(_task_evidence_path(context.run_root, task_id))
            for binding in evidence.supporting_evidence:
                path = _bound_path(context.run_root, binding.relative_path)
                if sha256_file(path) != binding.physical_sha256:
                    raise ProductionBackendError("Foundation supporting evidence bytes changed")
                if binding.relative_path.startswith("staging/evidence/resource-anomalies/"):
                    report = ResourceAnomalyReportV1.model_validate_json(path.read_bytes())
                    if (
                        report.run_id != context.run_id
                        or report.task_id != task_id
                        or report.snapshot_id != context.manifest.snapshot_id
                        or report.manifest_hash != context.manifest.manifest_hash
                        or report.semantic_impact != "NONE"
                        or report.integrity_impact != "NONE"
                    ):
                        raise ProductionBackendError(
                            "Foundation resource anomaly evidence authority changed"
                        )
                    continue
                if not binding.relative_path.startswith("staging/foundation/packed-checkpoints/"):
                    raise ProductionBackendError(
                        "Foundation task binds unsupported supporting evidence"
                    )
                checkpoint = FoundationShardCheckpoint.model_validate_json(path.read_bytes())
                if checkpoint.storage_role != "PACKED_FINAL":
                    raise ProductionBackendError("Group-1 received a non-final Foundation shard")
                checkpoints.append(checkpoint)
        return tuple(
            sorted(
                checkpoints,
                key=lambda item: (item.instrument, item.dataset_name, item.shard_key),
            )
        )


def _normalize_distributions(
    value: Mapping[str, Mapping[str, int]],
) -> tuple[EvidenceDistribution, ...]:
    return tuple(
        EvidenceDistribution(
            name=name,
            counts=tuple(
                DistributionCategory(value=category, count=count)
                for category, count in sorted(counts.items())
            ),
        )
        for name, counts in sorted(value.items())
    )


def _merge_evidence_distributions(
    evidences: Sequence[TaskAggregateEvidence] | Any,
) -> dict[str, dict[str, int]]:
    merged: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for evidence in evidences:
        for distribution in evidence.global_distributions:
            for item in distribution.counts:
                merged[distribution.name][item.value] += item.count
    return {name: dict(sorted(counts.items())) for name, counts in sorted(merged.items())}


def _foundation_checkpoint_binding(
    run_root: Path,
    checkpoint: FoundationShardCheckpoint,
) -> EvidenceFileBinding:
    path = (
        run_root
        / "staging"
        / "foundation"
        / "packed-checkpoints"
        / f"instrument={checkpoint.instrument}"
        / f"feature={checkpoint.dataset_name}"
        / f"shard={checkpoint.shard_key}.json"
    )
    if not path.is_file() or path.is_symlink():
        raise ProductionBackendError("packed Foundation checkpoint is missing")
    return EvidenceFileBinding(
        relative_path=path.relative_to(run_root).as_posix(),
        physical_sha256=sha256_file(path),
    )


def _read_task_evidence(path: Path) -> TaskAggregateEvidence:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"task evidence is missing: {path}")
    return TaskAggregateEvidence.model_validate_json(path.read_bytes())


def _read_model[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    return model.model_validate_json(path.read_bytes())


def _read_json_object(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ProductionBackendError(f"JSON authority is not an object: {path}")
    return cast(Mapping[str, object], value)


def _write_once_payload(path: Path, payload: Mapping[str, object]) -> str:
    data = (canonical_json(payload) + "\n").encode("utf-8")
    if path.exists():
        if path.is_symlink() or path.read_bytes() != data:
            raise FileExistsError(f"append-only report differs: {path}")
        return hashlib.sha256(data).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_directory(path.parent)
    return hashlib.sha256(data).hexdigest()


def _task_evidence_path(run_root: Path, task_id: str) -> Path:
    safe = task_id.lower().replace(":", "-")
    return run_root / "staging" / "backend-evidence" / f"{safe}.json"


def _staging_snapshot_root(context: RuntimeV2Context) -> Path:
    return context.run_root / "staging" / "snapshot"


def _published_snapshot_root(context: RuntimeV2Context) -> Path:
    return context.run_root / "published" / "snapshots" / context.manifest.snapshot_id


def _active_snapshot_root(context: RuntimeV2Context) -> Path:
    published = _published_snapshot_root(context)
    staging = _staging_snapshot_root(context)
    if published.is_dir() and not staging.exists():
        return published
    if staging.is_dir() and not published.exists():
        return staging
    raise ProductionBackendError("snapshot has no unambiguous active root")


def _object_path(root: Path, artifact: ArtifactRef) -> Path:
    relative = PurePosixPath(artifact.relative_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ProductionBackendError("ArtifactRef path is unsafe")
    path = root.joinpath(*relative.parts)
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file() or path.is_symlink():
        raise ProductionBackendError("ArtifactRef object is missing or escapes snapshot")
    return path


def _bound_path(run_root: Path, relative_path: str) -> Path:
    relative = PurePosixPath(relative_path)
    path = run_root.joinpath(*relative.parts)
    if not path.resolve().is_relative_to(run_root.resolve()) or not path.is_file():
        raise ProductionBackendError("supporting evidence is missing or unsafe")
    return path


def _quality_path(run_root: Path) -> Path:
    return run_root / "reports" / "v2-quality-report.json"


def _publication_path(run_root: Path) -> Path:
    return run_root / "reports" / "v2-publication-record.json"


def _comparison_path(run_root: Path) -> Path:
    return run_root / "reports" / "v2-run-a-comparison.json"


def _group1_aggregate_path(run_root: Path) -> Path:
    return run_root / "staging" / "group1" / "production-aggregate.json"


def _group1_component_path(run_root: Path, task_id: str) -> Path:
    safe = task_id.lower().replace(":", "-")
    return run_root / "staging" / "evidence" / "group1-components" / f"{safe}.json"


def _publication_phase_path(
    run_root: Path,
    phase: Literal["CATALOG_SEALED", "DATA_RENAMED", "PUBLISHED"],
) -> Path:
    ordinal = {"CATALOG_SEALED": "01", "DATA_RENAMED": "02", "PUBLISHED": "03"}[phase]
    return run_root / "reports" / "publication-journal" / f"{ordinal}-{phase.lower()}.json"


def _jsonable(value: object) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value):
        return _jsonable(asdict(cast(Any, value)))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _require_sorted_unique[T](values: Sequence[T], key: Callable[[T], str]) -> None:
    keys = tuple(key(item) for item in values)
    if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
        raise ValueError("evidence components must be unique and sorted")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
