"""Recoverable Group-1 production pipeline over the sealed Feature Foundation.

The pipeline is deliberately downstream-only: it accepts explicit packed
Feature Foundation checkpoints, reads their immutable objects, and never has a
Stage 1 path or discovery capability.  UTC months are the recovery boundary;
formal packed shards are deterministic contiguous owner-date ranges sized from
the already-written monthly object bytes.

The seven upstream PRICE facts retain their approved processing-date
partitions through :mod:`group1_feature_builder`.  Candidate datasets are
finalized by ``available_at_ts`` before they reach the adapter.  Every formal
owner day is passed through ``prepare_group1_partition`` so the V1 daily legacy
hash remains part of the receipt.
"""

from __future__ import annotations

import hashlib
import heapq
import fcntl
import json
import multiprocessing
import os
import threading
import uuid
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import Executor, Future, ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import Field, model_validator

from era100x.research.stage_2.manifests.configuration import parameter_sets
from era100x.research.stage_2.pipelines.candidates.candidate_finalizer import (
    finalize_candidate_attempts,
)
from era100x.research.stage_2.pipelines.candidates.io import (
    legacy_sorted_record_bytes,
)

from .catalog import CompactionResult, SealReducerV2
from .dataset_specs import (
    FLOW_DATASETS,
    PRICE_DATASETS,
    Group1DatasetBinding,
    group1_dataset_binding,
)
from .errors import ContractViolation, PublicationConflict
from .foundation_pipeline import FoundationShardCheckpoint
from .foundation_specs import feature_foundation_dataset_specs
from .group1_adapter import (
    PreparedGroup1Partition,
    normalize_group1_record_batch,
    prepare_group1_arrow_partition,
    prepare_group1_partition,
)
from .group1_feature_builder import (
    Group1Lineage,
    SourceDayStatus,
    _contract_bars,
    _contract_prices,
    _trade_seconds,
    build_flow_owner_day_from_primitives,
    build_price_processing_day_from_features,
)
from .hashing import (
    canonical_arrow_schema,
    canonical_semantic_hash,
    normalize_table,
)
from .models import (
    MAX_PROCESS_CURRENT_RSS_BYTES,
    MAX_PROCESS_RSS_DELTA_BYTES,
    SHA256_PATTERN,
    ZERO_SHA256,
    ArtifactRef,
    DistributionDigest,
    FragmentV2,
    FrozenModel,
    LogicalPartitionKey,
    QualityFact,
    Receipt,
    ShardSealV2,
    canonical_metadata_bytes,
    metadata_sha256,
)
from .memory import ProcessMemoryBudget, process_peak_rss_bytes
from .progress import WorkerProgressV2, utc_now_text

Instrument = Literal["BTCUSDT", "ETHUSDT"]

DEFAULT_EXTERNAL_ROOT = Path("/Volumes/FuckingLife/era100x_stage2")
SOURCE_READER_COUNT = 1
COMPUTE_WORKER_COUNT = 3
DETERMINISTIC_WRITER_COUNT = 1
MAX_INFLIGHT_BYTES = 1 << 30
PACKED_TARGET_BYTES = 256 << 20
PACKED_MIN_BYTES = 128 << 20
PACKED_MAX_BYTES = 512 << 20
MAX_GROUP1_PACKED_OBJECTS = 200
ROW_GROUP_SIZE = 262_144
DAY_NS = 86_400_000_000_000

GROUP1_BINDINGS: tuple[tuple[str, str], ...] = tuple(
    [("V1_PRICE", item) for item in PRICE_DATASETS] + [("V1_FLOW", item) for item in FLOW_DATASETS]
)
FOUNDATION_INPUTS = (
    "contract_price_1s",
    "causal_price_bars",
    "trade_second_primitives",
)
_RELEASE_DISTRIBUTION_FIELDS = (
    "ownership_status",
    "research_role",
    "time_combination_id",
    "parameter_set_id",
    "reason_code",
)


class Group1PipelineConfig(FrozenModel):
    """Fixed resource and append-only output contract for S2-T10 v1.8."""

    run_root: Path
    foundation_catalog_root: Path
    approved_external_root: Path = DEFAULT_EXTERNAL_ROOT
    source_reader_count: Literal[1] = 1
    compute_worker_count: Literal[3] = 3
    deterministic_writer_count: Literal[1] = 1
    max_inflight_bytes: Literal[1_073_741_824] = 1_073_741_824
    max_process_current_rss_bytes: Literal[3_221_225_472] = MAX_PROCESS_CURRENT_RSS_BYTES
    max_process_rss_delta_bytes: Literal[1_073_741_824] = MAX_PROCESS_RSS_DELTA_BYTES
    packed_target_bytes: Literal[268_435_456] = 268_435_456
    packed_min_bytes: Literal[134_217_728] = 134_217_728
    packed_max_bytes: Literal[536_870_912] = 536_870_912
    max_group1_packed_objects: Literal[200] = 200

    @model_validator(mode="after")
    def approved_roots_only(self) -> Self:
        external = self.approved_external_root.resolve()
        run_root = self.run_root.resolve()
        foundation_root = self.foundation_catalog_root.resolve()
        if not external.is_dir():
            raise ValueError(f"approved Stage 2 external root is unavailable: {external}")
        if not run_root.is_relative_to(external) or run_root == external:
            raise ValueError("Group-1 run_root must be a run-specific approved external child")
        if not foundation_root.is_relative_to(run_root):
            raise ValueError("Feature Foundation objects must belong to this V2 run")
        if self.packed_min_bytes > self.packed_target_bytes:
            raise ValueError("packed minimum cannot exceed target")
        if self.packed_target_bytes > self.packed_max_bytes:
            raise ValueError("packed target cannot exceed maximum")
        return self

    @property
    def monthly_catalog_root(self) -> Path:
        return self.run_root / "staging" / "group1" / "monthly-catalog"

    @property
    def monthly_checkpoint_root(self) -> Path:
        return self.run_root / "staging" / "group1" / "monthly-checkpoints"

    @property
    def monthly_dataset_checkpoint_root(self) -> Path:
        """Bounded metadata shards used by the production packer.

        The compatibility month checkpoint deliberately remains intact.  The
        split files prevent the formal pack step from retaining every month
        and every final Receipt/Fragment graph at the same time.
        """

        return self.run_root / "staging" / "group1" / "monthly-dataset-checkpoints"

    @property
    def monthly_seal_root(self) -> Path:
        return self.run_root / "staging" / "group1" / "monthly-seals"

    @property
    def snapshot_catalog_root(self) -> Path:
        """Shared final object root used by Foundation and Group-1 Catalog rows."""

        return self.run_root / "staging" / "snapshot"

    @property
    def packed_seal_root(self) -> Path:
        return self.run_root / "staging" / "group1" / "packed-seals"

    @property
    def partial_root(self) -> Path:
        return self.run_root / "staging" / "group1" / "partials"

    @property
    def processing_day_cache_root(self) -> Path:
        return self.run_root / "staging" / "group1" / "processing-day-cache"

    @property
    def worker_progress_root(self) -> Path:
        return self.run_root / "logs" / "worker-progress"

    @property
    def packed_aggregate_path(self) -> Path:
        return self.run_root / "staging" / "group1" / "packed-aggregate.json"


class GlobalDistributionCount(FrozenModel):
    name: str
    value: str
    count: int = Field(ge=0)


class Group1MonthlyDatasetSeal(FrozenModel):
    variant: Literal["V1_PRICE", "V1_FLOW"]
    dataset: str
    dataset_spec_hash: str = Field(pattern=SHA256_PATTERN)
    artifact: ArtifactRef | None
    receipts: tuple[Receipt, ...] = Field(min_length=1)
    fragments: tuple[FragmentV2, ...]
    seal: ShardSealV2
    seal_relative_path: str
    seal_file_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def consistent_graph(self) -> Self:
        binding = group1_dataset_binding(self.variant, self.dataset)
        if binding.spec.spec_hash != self.dataset_spec_hash:
            raise ValueError("monthly Group-1 dataset spec changed")
        if any(
            item.partition.dataset_spec_hash != self.dataset_spec_hash for item in self.receipts
        ):
            raise ValueError("monthly Group-1 receipts mix DatasetSpecs")
        if self.artifact is None:
            if self.fragments or any(item.row_count for item in self.receipts):
                raise ValueError("artifact-free monthly dataset must be entirely empty")
        elif sum(item.row_count for item in self.receipts) != self.artifact.row_count:
            raise ValueError("monthly artifact row count differs from receipts")
        if self.seal.dataset_spec_hash != self.dataset_spec_hash:
            raise ValueError("monthly Group-1 seal uses another DatasetSpec")
        return self


class Group1MonthCheckpoint(FrozenModel):
    schema_name: Literal["stage2-v2-group1-month-checkpoint"] = "stage2-v2-group1-month-checkpoint"
    checkpoint_version: Literal["1.0"] = "1.0"
    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    instrument: Instrument
    utc_month: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}$")
    owner_start: date
    owner_end_exclusive: date
    foundation_authority_members: tuple[str, ...] = Field(min_length=1)
    foundation_authority_sha256: str = Field(pattern=SHA256_PATTERN)
    datasets: tuple[Group1MonthlyDatasetSeal, ...] = Field(min_length=13, max_length=13)
    distributions: tuple[GlobalDistributionCount, ...]
    source_reader_count: Literal[1] = 1
    compute_worker_count: Literal[3] = 3
    deterministic_writer_count: Literal[1] = 1
    max_inflight_bytes: Literal[1_073_741_824] = 1_073_741_824
    max_process_rss_bytes_observed: int = Field(ge=0)
    terminal_state: Literal["SEALED"] = "SEALED"
    checkpoint_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"checkpoint_hash"}))

    @model_validator(mode="after")
    def validate_checkpoint(self) -> Self:
        if self.owner_end_exclusive <= self.owner_start:
            raise ValueError("Group-1 month range must be non-empty")
        if self.utc_month != self.owner_start.strftime("%Y-%m"):
            raise ValueError("Group-1 month key differs from owner range")
        if self.foundation_authority_members != tuple(
            sorted(set(self.foundation_authority_members))
        ):
            raise ValueError("foundation source authority must be sorted and unique")
        if self.foundation_authority_sha256 != metadata_sha256(self.foundation_authority_members):
            raise ValueError("foundation authority digest mismatch")
        keys = tuple((item.variant, item.dataset) for item in self.datasets)
        if keys != GROUP1_BINDINGS:
            raise ValueError("month checkpoint must contain all thirteen bindings in order")
        expected_dates = tuple(_dates(self.owner_start, self.owner_end_exclusive))
        for dataset in self.datasets:
            dates = tuple(item.partition.owner_date for item in dataset.receipts)
            if dates != expected_dates:
                raise ValueError("monthly Group-1 receipts must cover every owner day")
            if any(item.partition.instrument != self.instrument for item in dataset.receipts):
                raise ValueError("monthly Group-1 checkpoint mixes instruments")
        if self.distributions != tuple(
            sorted(self.distributions, key=lambda item: (item.name, item.value))
        ):
            raise ValueError("global distribution counts must be deterministically sorted")
        if self.checkpoint_hash != ZERO_SHA256 and self.checkpoint_hash != self.computed_hash():
            raise ValueError("Group-1 month checkpoint hash mismatch")
        return self

    @classmethod
    def seal_checkpoint(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "checkpoint_hash": ZERO_SHA256})
        return provisional.model_copy(update={"checkpoint_hash": provisional.computed_hash()})


class ProcessingDayCacheReceiptV1(FrozenModel):
    """Write-once execution cache for candidate attempts from one processing day."""

    schema_name: Literal["stage2-v2-processing-day-cache"] = "stage2-v2-processing-day-cache"
    cache_version: Literal["1.0"] = "1.0"
    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    instrument: Instrument
    processing_date: date
    attempt_count: int = Field(ge=0)
    attempts_relative_path: str
    attempts_physical_sha256: str = Field(pattern=SHA256_PATTERN)
    attempts_semantic_sha256: str = Field(pattern=SHA256_PATTERN)
    foundation_authority_sha256: str = Field(pattern=SHA256_PATTERN)
    lineage_sha256: str = Field(pattern=SHA256_PATTERN)
    receipt_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"receipt_hash"}))

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        path = PurePosixPath(self.attempts_relative_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("processing-day cache path must be safe and relative")
        if self.receipt_hash != ZERO_SHA256 and self.receipt_hash != self.computed_hash():
            raise ValueError("processing-day cache receipt hash mismatch")
        return self

    @classmethod
    def seal_receipt(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "receipt_hash": ZERO_SHA256})
        return provisional.model_copy(update={"receipt_hash": provisional.computed_hash()})


class Group1BindingObjectCount(FrozenModel):
    instrument: Instrument
    variant: Literal["V1_PRICE", "V1_FLOW"]
    dataset: str
    object_count: int = Field(ge=0)


class Group1PackedAggregate(FrozenModel):
    schema_name: Literal["stage2-v2-group1-packed-aggregate"] = "stage2-v2-group1-packed-aggregate"
    aggregate_version: Literal["1.0"] = "1.0"
    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    owner_start: date
    owner_end_exclusive: date
    instruments: tuple[Instrument, ...]
    object_counts: tuple[Group1BindingObjectCount, ...]
    total_object_count: int = Field(ge=0)
    receipt_count: int = Field(gt=0)
    receipt_root_sha256: str = Field(pattern=SHA256_PATTERN)
    seal_hashes: tuple[str, ...]
    distributions: tuple[GlobalDistributionCount, ...]
    aggregate_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"aggregate_hash"}))

    @model_validator(mode="after")
    def validate_aggregate(self) -> Self:
        if self.owner_end_exclusive <= self.owner_start:
            raise ValueError("packed aggregate owner range must be non-empty")
        if self.total_object_count != sum(item.object_count for item in self.object_counts):
            raise ValueError("packed aggregate object count mismatch")
        if self.object_counts != tuple(
            sorted(
                self.object_counts,
                key=lambda item: (item.instrument, item.variant, item.dataset),
            )
        ):
            raise ValueError("packed object counts must be sorted")
        if self.seal_hashes != tuple(sorted(set(self.seal_hashes))):
            raise ValueError("packed seal hashes must be sorted and unique")
        if self.distributions != tuple(
            sorted(self.distributions, key=lambda item: (item.name, item.value))
        ):
            raise ValueError("packed distributions must be sorted")
        if self.aggregate_hash != ZERO_SHA256 and self.aggregate_hash != self.computed_hash():
            raise ValueError("packed aggregate hash mismatch")
        return self

    @classmethod
    def seal_aggregate(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "aggregate_hash": ZERO_SHA256})
        return provisional.model_copy(update={"aggregate_hash": provisional.computed_hash()})


@dataclass(frozen=True, slots=True)
class FoundationFeatureWindow:
    instrument: Instrument
    owner_start: date
    owner_end_exclusive: date
    contract_price_1s: pa.Table
    causal_price_bars: pa.Table
    trade_second_primitives: pa.Table
    trade_source_day_status: Mapping[date | str, SourceDayStatus]
    foundation_authority_members: tuple[str, ...]
    max_inflight_bytes_observed: int


@dataclass(frozen=True, slots=True)
class Group1PipelineResult:
    snapshot_id: str
    monthly_checkpoints: tuple[Group1MonthCheckpoint, ...]
    artifacts: tuple[ArtifactRef, ...]
    receipts: tuple[Receipt, ...]
    fragments: tuple[FragmentV2, ...]
    seals: tuple[ShardSealV2, ...]
    object_counts: tuple[Group1BindingObjectCount, ...]
    distributions: tuple[GlobalDistributionCount, ...]
    packed_aggregate: Group1PackedAggregate
    max_inflight_bytes_observed: int
    max_process_rss_bytes_observed: int

    def object_count(self, instrument: Instrument, variant: str, dataset: str) -> int:
        for item in self.object_counts:
            if (item.instrument, item.variant, item.dataset) == (instrument, variant, dataset):
                return item.object_count
        raise KeyError((instrument, variant, dataset))


@dataclass(frozen=True, slots=True)
class Group1MonthlyDatasetBinding:
    instrument: Instrument
    utc_month: str
    owner_start: date
    owner_end_exclusive: date
    variant: Literal["V1_PRICE", "V1_FLOW"]
    dataset: str
    relative_path: str
    physical_sha256: str
    artifact_byte_size: int


@dataclass(frozen=True, slots=True)
class Group1PackedTaskComponent:
    instrument: Instrument
    variant: Literal["V1_PRICE", "V1_FLOW"]
    artifacts: tuple[ArtifactRef, ...]
    receipts: tuple[Receipt, ...]
    fragments: tuple[FragmentV2, ...]
    seals: tuple[ShardSealV2, ...]


@dataclass(frozen=True, slots=True)
class Group1StreamingPipelineResult:
    """Small production result; full partition graphs leave through the sink."""

    snapshot_id: str
    object_counts: tuple[Group1BindingObjectCount, ...]
    distributions: tuple[GlobalDistributionCount, ...]
    packed_aggregate: Group1PackedAggregate
    max_inflight_bytes_observed: int
    max_process_rss_bytes_observed: int


@dataclass(frozen=True, slots=True)
class Group1MonthWorkItemV1:
    """Spawn-safe, month-owned execution unit with no shared formal writer."""

    instrument: Instrument
    utc_month: str
    owner_start: date
    owner_end_exclusive: date


@dataclass(frozen=True, slots=True)
class Group1MonthResultV1:
    checkpoint: Group1MonthCheckpoint
    max_inflight_bytes_observed: int
    foundation_fragment_reads: int
    foundation_cache_hits: int
    processing_day_executions: int
    legacy_runs_generated: int
    bytes_written: int


_GROUP1_WORKER_PIPELINE: Group1FeaturePipeline | None = None


def _initialize_group1_month_worker(
    config: Group1PipelineConfig,
    snapshot_id: str,
    foundation_checkpoints: tuple[FoundationShardCheckpoint, ...],
    lineage_by_instrument: Mapping[Instrument, Group1Lineage],
) -> None:
    """Initialize immutable Foundation authority once per spawn worker."""

    import signal

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    global _GROUP1_WORKER_PIPELINE
    _GROUP1_WORKER_PIPELINE = Group1FeaturePipeline(
        config=config,
        snapshot_id=snapshot_id,
        foundation_checkpoints=foundation_checkpoints,
        lineage_by_instrument=lineage_by_instrument,
        _allow_process_workers=False,
    )


def _execute_group1_month_worker(work: Group1MonthWorkItemV1) -> Group1MonthResultV1:
    """Build one owner month in a spawn child; SIGINT belongs to the parent."""

    pipeline = _GROUP1_WORKER_PIPELINE
    if pipeline is None:
        raise RuntimeError("Group-1 month worker lacks its frozen initializer authority")
    config = pipeline.config
    worker_id = f"{work.instrument}-{work.utc_month}"

    def report(
        owner_date: date | None,
        minute: int,
        status: Literal["RUNNING", "SEALED", "FAILED"],
        *,
        processing_day_executions: int = 0,
        legacy_runs_generated: int = 0,
        bytes_written: int = 0,
    ) -> None:
        _write_worker_progress(
            config,
            WorkerProgressV2(
                worker_id=worker_id,
                pid=os.getpid(),
                status=status,
                instrument=work.instrument,
                variant="V1_PRICE",
                current_month=work.utc_month,
                current_owner_date=(None if owner_date is None else owner_date.isoformat()),
                current_processing_minute=minute,
                foundation_fragment_reads=sum(pipeline.reader.read_counts.values()),
                foundation_cache_hits=sum(pipeline.reader.cache_hits.values()),
                processing_day_executions=processing_day_executions,
                legacy_runs_generated=legacy_runs_generated,
                bytes_written=bytes_written,
                updated_at=utc_now_text(),
            ),
        )

    report(None, 0, "RUNNING")
    owner_dates = tuple(_dates(work.owner_start, work.owner_end_exclusive))
    cache_receipts_before = {
        owner_date
        for owner_date in owner_dates
        if _processing_day_cache_paths(config, work.instrument, owner_date)[1].exists()
    }
    prior_date = work.owner_start - timedelta(days=1)
    prior_was_cached = _processing_day_cache_paths(config, work.instrument, prior_date)[1].exists()
    try:
        checkpoint, observed = pipeline._build_or_resume_month(
            instrument=work.instrument,
            utc_month=work.utc_month,
            start=work.owner_start,
            end_exclusive=work.owner_end_exclusive,
            compute_pool=None,
            progress_sink=lambda owner, minute: report(owner, minute, "RUNNING"),
        )
    except BaseException:
        report(None, 0, "FAILED")
        raise
    cache_receipts_after = {
        owner_date
        for owner_date in owner_dates
        if _processing_day_cache_paths(config, work.instrument, owner_date)[1].exists()
    }
    processing_day_executions = len(cache_receipts_after - cache_receipts_before) + int(
        not prior_was_cached
    )
    legacy_runs_generated = _checkpoint_legacy_run_count(checkpoint)
    bytes_written = sum(
        0 if dataset.artifact is None else dataset.artifact.byte_size
        for dataset in checkpoint.datasets
    )
    report(
        work.owner_end_exclusive - timedelta(days=1),
        1440,
        "SEALED",
        processing_day_executions=processing_day_executions,
        legacy_runs_generated=legacy_runs_generated,
        bytes_written=bytes_written,
    )
    return Group1MonthResultV1(
        checkpoint=checkpoint,
        max_inflight_bytes_observed=observed,
        foundation_fragment_reads=sum(pipeline.reader.read_counts.values()),
        foundation_cache_hits=sum(pipeline.reader.cache_hits.values()),
        processing_day_executions=processing_day_executions,
        legacy_runs_generated=legacy_runs_generated,
        bytes_written=bytes_written,
    )


def _checkpoint_legacy_run_count(checkpoint: Group1MonthCheckpoint) -> int:
    upstream = set(PRICE_DATASETS[:7])
    return sum(
        (receipt.row_count + _DailyRecordSpool.BUFFER_ROWS - 1) // _DailyRecordSpool.BUFFER_ROWS
        for dataset in checkpoint.datasets
        if dataset.variant == "V1_PRICE" and dataset.dataset in upstream
        for receipt in dataset.receipts
        if receipt.row_count
    )


def _write_worker_progress(config: Group1PipelineConfig, progress: WorkerProgressV2) -> None:
    path = config.worker_progress_root / f"{progress.worker_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = (
        json.JSONEncoder(sort_keys=True, separators=(",", ":")).encode(
            progress.model_dump(mode="json")
        )
        + "\n"
    ).encode("utf-8")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class PackedFoundationFeatureReader:
    """Explicit fragment reader for immutable PACKED_FINAL Foundation evidence."""

    def __init__(
        self,
        *,
        snapshot_id: str,
        catalog_root: Path,
        checkpoints: Sequence[FoundationShardCheckpoint],
        max_inflight_bytes: int = MAX_INFLIGHT_BYTES,
    ) -> None:
        if len(snapshot_id) != 64 or any(item not in "0123456789abcdef" for item in snapshot_id):
            raise ValueError("snapshot_id must be lowercase SHA-256")
        self.snapshot_id = snapshot_id
        self.catalog_root = Path(catalog_root).resolve()
        self.max_inflight_bytes = max_inflight_bytes
        self._owner_thread = threading.get_ident()
        self._specs = {item.dataset_name: item for item in feature_foundation_dataset_specs()}
        self._receipts: dict[
            tuple[str, Instrument, date], tuple[Receipt, FragmentV2 | None, str]
        ] = {}
        self._artifact_by_hash: dict[str, ArtifactRef] = {}
        self._verified_objects: set[str] = set()
        self._partition_cache: dict[tuple[str, Instrument, date], pa.Table] = {}
        self.read_counts: Counter[tuple[str, Instrument, date]] = Counter()
        self.cache_hits: Counter[tuple[str, Instrument, date]] = Counter()

        ordered = sorted(
            checkpoints,
            key=lambda item: (item.dataset_name, item.instrument, item.window_start_date),
        )
        for checkpoint in ordered:
            if checkpoint.storage_role != "PACKED_FINAL":
                raise ContractViolation("Group-1 may consume only PACKED_FINAL Foundation evidence")
            if checkpoint.snapshot_id != snapshot_id:
                raise ContractViolation("Feature Foundation snapshot differs from Group-1 snapshot")
            if checkpoint.dataset_name not in self._specs:
                raise ContractViolation("unknown Feature Foundation checkpoint dataset")
            recomputed = SealReducerV2.reduce(
                snapshot_id=snapshot_id,
                dataset_spec_hash=checkpoint.dataset_spec_hash,
                shard_id=checkpoint.seal.shard_id,
                receipts=checkpoint.receipts,
            )
            if recomputed != checkpoint.seal:
                raise ContractViolation("Feature Foundation packed seal changed")
            fragments = {item.fragment_hash: item for item in checkpoint.fragments}
            source_by_date = {item.owner_date: item for item in checkpoint.source_bindings}
            if checkpoint.artifact is not None:
                previous = self._artifact_by_hash.setdefault(
                    checkpoint.artifact.object_sha256, checkpoint.artifact
                )
                if previous != checkpoint.artifact:
                    raise ContractViolation(
                        "Foundation object hash is bound to conflicting metadata"
                    )
            for receipt in checkpoint.receipts:
                if not any(
                    item.name == "source_authority_complete" and item.value is True
                    for item in receipt.quality_facts
                ):
                    raise ContractViolation(
                        "Feature Foundation receipt lacks verified source authority"
                    )
                try:
                    source_binding = source_by_date[receipt.partition.owner_date]
                except KeyError as exc:
                    raise ContractViolation(
                        "Feature Foundation receipt lacks byte-SHA source lineage"
                    ) from exc
                fragment: FragmentV2 | None = None
                if receipt.fragment_hashes:
                    if len(receipt.fragment_hashes) != 1:
                        raise ContractViolation("Foundation owner day must use one packed fragment")
                    try:
                        fragment = fragments[receipt.fragment_hashes[0]]
                    except KeyError as exc:
                        raise ContractViolation("Foundation receipt lost its fragment") from exc
                key = (
                    checkpoint.dataset_name,
                    checkpoint.instrument,
                    receipt.partition.owner_date,
                )
                if key in self._receipts:
                    raise ContractViolation(f"duplicate Feature Foundation owner day: {key}")
                authority_member = metadata_sha256(
                    {
                        "receipt_hash": receipt.receipt_hash,
                        "source_checkpoint_hash": checkpoint.checkpoint_hash,
                        "source_binding": source_binding.model_dump(mode="json"),
                    }
                )
                self._receipts[key] = (receipt, fragment, authority_member)

        for instrument in ("BTCUSDT", "ETHUSDT"):
            present = {
                name
                for name in FOUNDATION_INPUTS
                if any(key[0] == name and key[1] == instrument for key in self._receipts)
            }
            if present and present != set(FOUNDATION_INPUTS):
                raise ContractViolation(f"incomplete Feature Foundation inputs for {instrument}")

    def authority_for_window(
        self, *, instrument: Instrument, owner_start: date, owner_end_exclusive: date
    ) -> tuple[str, ...]:
        keys = self._window_keys(instrument, owner_start, owner_end_exclusive)
        return tuple(sorted({self._receipts[key][2] for key in keys if key in self._receipts}))

    def read_window(
        self, *, instrument: Instrument, owner_start: date, owner_end_exclusive: date
    ) -> FoundationFeatureWindow:
        self._assert_reader_thread()
        keys = self._window_keys(instrument, owner_start, owner_end_exclusive)
        tables: dict[str, list[pa.Table]] = {name: [] for name in FOUNDATION_INPUTS}
        authority: set[str] = set()
        status: dict[date | str, SourceDayStatus] = {}
        for key in keys:
            dataset_name, _instrument, owner_date = key
            receipt_fragment = self._receipts.get(key)
            if receipt_fragment is None:
                if self._outside_authorized_coverage(dataset_name, instrument, owner_date):
                    continue
                raise ContractViolation(f"interior Feature Foundation owner day is missing: {key}")
            receipt, fragment, authority_member = receipt_fragment
            authority.add(authority_member)
            tables[dataset_name].append(
                self._read_partition(dataset_name, instrument, receipt, fragment)
            )
            if dataset_name == "trade_second_primitives":
                status[owner_date] = "COMPLETE"

        combined = {
            name: _concat_or_empty(items, self._specs[name]) for name, items in tables.items()
        }
        self._evict_partition_cache(instrument)
        observed = sum(item.nbytes for item in combined.values())
        return FoundationFeatureWindow(
            instrument=instrument,
            owner_start=owner_start,
            owner_end_exclusive=owner_end_exclusive,
            contract_price_1s=combined["contract_price_1s"],
            causal_price_bars=combined["causal_price_bars"],
            trade_second_primitives=combined["trade_second_primitives"],
            trade_source_day_status=status,
            foundation_authority_members=tuple(sorted(authority)),
            max_inflight_bytes_observed=observed,
        )

    def _window_keys(
        self, instrument: Instrument, owner_start: date, owner_end_exclusive: date
    ) -> tuple[tuple[str, Instrument, date], ...]:
        if owner_end_exclusive <= owner_start:
            raise ValueError("owner window must be non-empty")
        ranges = {
            "contract_price_1s": (
                owner_start - timedelta(days=2),
                owner_end_exclusive + timedelta(days=1),
            ),
            "causal_price_bars": (owner_start - timedelta(days=2), owner_end_exclusive),
            "trade_second_primitives": (owner_start - timedelta(days=1), owner_end_exclusive),
        }
        return tuple(
            (name, instrument, owner_date)
            for name in FOUNDATION_INPUTS
            for owner_date in _dates(*ranges[name])
        )

    def _outside_authorized_coverage(
        self, dataset_name: str, instrument: Instrument, owner_date: date
    ) -> bool:
        dates = [
            key[2] for key in self._receipts if key[0] == dataset_name and key[1] == instrument
        ]
        if not dates:
            raise ContractViolation(f"Feature Foundation lacks {dataset_name}/{instrument}")
        return owner_date < min(dates) or owner_date > max(dates)

    def _read_partition(
        self,
        dataset_name: str,
        instrument: Instrument,
        receipt: Receipt,
        fragment: FragmentV2 | None,
    ) -> pa.Table:
        cache_key = (dataset_name, instrument, receipt.partition.owner_date)
        cached = self._partition_cache.get(cache_key)
        if cached is not None:
            self.cache_hits[cache_key] += 1
            return cached
        self.read_counts[cache_key] += 1
        spec = self._specs[dataset_name]
        if fragment is None:
            if receipt.row_count:
                raise ContractViolation("non-empty Foundation receipt lacks a fragment")
            table = pa.Table.from_batches([], schema=canonical_arrow_schema(spec))
            self._partition_cache[cache_key] = table
            return table
        artifact = fragment.artifact
        path = _safe_object_path(self.catalog_root, artifact.relative_path)
        if artifact.object_sha256 not in self._verified_objects:
            if not path.is_file() or path.is_symlink():
                raise FileNotFoundError(f"Foundation object is unavailable: {path}")
            if (
                path.stat().st_size != artifact.byte_size
                or _sha256_file(path) != artifact.object_sha256
            ):
                raise ContractViolation("Feature Foundation packed object bytes changed")
            self._verified_objects.add(artifact.object_sha256)
        table = _read_fragment(path, fragment)
        expected = canonical_arrow_schema(spec)
        if not table.schema.equals(expected, check_metadata=False):
            raise ContractViolation("Feature Foundation fragment schema changed")
        table = normalize_table(table, spec)
        if table.num_rows != receipt.row_count:
            raise ContractViolation("Feature Foundation fragment row count changed")
        if canonical_semantic_hash(table, spec) != receipt.semantic_sha256:
            raise ContractViolation("Feature Foundation fragment semantics changed")
        self._partition_cache[cache_key] = table
        return table

    def _evict_partition_cache(self, instrument: Instrument) -> None:
        limits = {
            "contract_price_1s": 4,
            "causal_price_bars": 3,
            "trade_second_primitives": 2,
        }
        for dataset_name, limit in limits.items():
            keys = sorted(
                (
                    key
                    for key in self._partition_cache
                    if key[0] == dataset_name and key[1] == instrument
                ),
                key=lambda key: key[2],
            )
            for key in keys[:-limit]:
                del self._partition_cache[key]

    def _assert_reader_thread(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("Group-1 Foundation reads require the single reader thread")


class Group1FeaturePipeline:
    """Build monthly recovery artifacts and packed formal Group-1 shards."""

    def __init__(
        self,
        *,
        config: Group1PipelineConfig,
        snapshot_id: str,
        foundation_checkpoints: Sequence[FoundationShardCheckpoint],
        lineage_by_instrument: Mapping[Instrument, Group1Lineage],
        foundation_reader: PackedFoundationFeatureReader | None = None,
        _allow_process_workers: bool = True,
    ) -> None:
        self.config = config
        self.snapshot_id = snapshot_id
        if set(lineage_by_instrument) != {"BTCUSDT", "ETHUSDT"}:
            raise ValueError("Group-1 lineage must keep BTC and ETH separate and complete")
        self.lineage_by_instrument = dict(lineage_by_instrument)
        self._foundation_checkpoints = tuple(foundation_checkpoints)
        self._allow_process_workers = _allow_process_workers and foundation_reader is None
        foundation_artifacts = {
            item.artifact.object_sha256
            for item in foundation_checkpoints
            if item.storage_role == "PACKED_FINAL" and item.artifact is not None
        }
        self.foundation_object_count = len(foundation_artifacts)
        self.group1_object_budget = group1_object_budget(
            self.foundation_object_count,
            catalog_cap=self.config.max_group1_packed_objects,
        )
        self.reader = foundation_reader or PackedFoundationFeatureReader(
            snapshot_id=snapshot_id,
            catalog_root=config.foundation_catalog_root,
            checkpoints=foundation_checkpoints,
            max_inflight_bytes=config.max_inflight_bytes,
        )
        self._memory_budget = ProcessMemoryBudget(
            current_limit_bytes=config.max_process_current_rss_bytes,
            delta_limit_bytes=config.max_process_rss_delta_bytes,
        )

    def build(
        self,
        *,
        instruments: tuple[Instrument, ...],
        start: date,
        end_exclusive: date,
    ) -> Group1PipelineResult:
        if end_exclusive <= start:
            raise ValueError("Group-1 owner range must be non-empty")
        if not instruments or tuple(sorted(set(instruments))) != instruments:
            raise ValueError("instruments must be unique and deterministically sorted")
        if any(item not in {"BTCUSDT", "ETHUSDT"} for item in instruments):
            raise ValueError("Group-1 supports only BTCUSDT and ETHUSDT")

        monthly: list[Group1MonthCheckpoint] = []
        max_observed = 0
        # RSS is execution evidence sealed per newly-built month.  It is not a
        # semantic aggregate field and a resume must reuse the sealed values
        # instead of injecting the caller process's current high-water mark.
        max_rss_observed = 0
        for result in self._iter_month_results(instruments, start, end_exclusive):
            checkpoint = result.checkpoint
            monthly.append(checkpoint)
            max_observed = max(max_observed, result.max_inflight_bytes_observed)
            max_rss_observed = max(max_rss_observed, checkpoint.max_process_rss_bytes_observed)

        packed = self._pack_months(
            instruments=instruments,
            start=start,
            end_exclusive=end_exclusive,
            monthly=tuple(monthly),
        )
        max_observed = max(max_observed, packed[5])
        artifacts, receipts, fragments, seals, object_counts, _observed = packed
        distributions = _merge_distributions(item.distributions for item in monthly)
        aggregate = Group1PackedAggregate.seal_aggregate(
            {
                "snapshot_id": self.snapshot_id,
                "owner_start": start,
                "owner_end_exclusive": end_exclusive,
                "instruments": instruments,
                "object_counts": object_counts,
                "total_object_count": len(artifacts),
                "receipt_count": len(receipts),
                "receipt_root_sha256": metadata_sha256(
                    tuple(
                        (item.partition.semantic_order_key(), item.semantic_receipt_sha256)
                        for item in sorted(
                            receipts, key=lambda row: row.partition.semantic_order_key()
                        )
                    )
                ),
                "seal_hashes": tuple(sorted(item.seal_hash for item in seals)),
                "distributions": distributions,
            }
        )
        _write_once_model(self.config.packed_aggregate_path, aggregate)
        return Group1PipelineResult(
            snapshot_id=self.snapshot_id,
            monthly_checkpoints=tuple(monthly),
            artifacts=artifacts,
            receipts=receipts,
            fragments=fragments,
            seals=seals,
            object_counts=object_counts,
            distributions=distributions,
            packed_aggregate=aggregate,
            max_inflight_bytes_observed=max_observed,
            max_process_rss_bytes_observed=max_rss_observed,
        )

    def build_streaming_components(
        self,
        *,
        instruments: tuple[Instrument, ...],
        start: date,
        end_exclusive: date,
        component_sink: Callable[[Group1PackedTaskComponent], None],
    ) -> Group1StreamingPipelineResult:
        """Build the formal matrix without retaining two full metadata graphs.

        Month checkpoints remain the recovery authority.  Each of their
        thirteen dataset graphs is additionally sealed into a small immutable
        metadata shard.  Packing loads one dataset at a time and emits one
        instrument/variant component at a time.  The caller must persist the
        component before this method proceeds, so completed components are
        released before the next one is materialized.
        """

        if end_exclusive <= start:
            raise ValueError("Group-1 owner range must be non-empty")
        if not instruments or tuple(sorted(set(instruments))) != instruments:
            raise ValueError("instruments must be unique and deterministically sorted")
        if any(item not in {"BTCUSDT", "ETHUSDT"} for item in instruments):
            raise ValueError("Group-1 supports only BTCUSDT and ETHUSDT")

        bindings: list[Group1MonthlyDatasetBinding] = []
        distributions: Counter[tuple[str, str]] = Counter()
        max_observed = 0
        max_rss_observed = 0
        for result in self._iter_month_results(instruments, start, end_exclusive):
            checkpoint = result.checkpoint
            max_observed = max(max_observed, result.max_inflight_bytes_observed)
            max_rss_observed = max(
                max_rss_observed,
                checkpoint.max_process_rss_bytes_observed,
                process_peak_rss_bytes(),
            )
            distributions.update(
                {(item.name, item.value): item.count for item in checkpoint.distributions}
            )
            bindings.extend(self._seal_month_dataset_bindings(checkpoint))
            del checkpoint
            self._enforce_production_rss("monthly metadata sealing")

        packed = self._pack_streaming_components(
            instruments=instruments,
            start=start,
            end_exclusive=end_exclusive,
            bindings=tuple(bindings),
            distributions=_distribution_models(distributions),
            component_sink=component_sink,
        )
        max_observed = max(max_observed, packed.max_inflight_bytes_observed)
        max_rss_observed = max(
            max_rss_observed,
            packed.max_process_rss_bytes_observed,
            process_peak_rss_bytes(),
        )
        self._enforce_production_rss("formal component packing")
        return Group1StreamingPipelineResult(
            snapshot_id=self.snapshot_id,
            object_counts=packed.object_counts,
            distributions=packed.distributions,
            packed_aggregate=packed.packed_aggregate,
            max_inflight_bytes_observed=max_observed,
            max_process_rss_bytes_observed=max_rss_observed,
        )

    def _iter_month_results(
        self,
        instruments: tuple[Instrument, ...],
        start: date,
        end_exclusive: date,
    ) -> Iterator[Group1MonthResultV1]:
        plan = tuple(
            Group1MonthWorkItemV1(
                instrument=instrument,
                utc_month=utc_month,
                owner_start=month_start,
                owner_end_exclusive=month_end,
            )
            for utc_month, month_start, month_end in _month_windows(start, end_exclusive)
            for instrument in instruments
        )
        if not self._allow_process_workers or len(plan) == 1:
            for work in plan:
                checkpoint, observed = self._build_or_resume_month(
                    instrument=work.instrument,
                    utc_month=work.utc_month,
                    start=work.owner_start,
                    end_exclusive=work.owner_end_exclusive,
                    compute_pool=None,
                )
                yield Group1MonthResultV1(
                    checkpoint=checkpoint,
                    max_inflight_bytes_observed=observed,
                    foundation_fragment_reads=sum(self.reader.read_counts.values()),
                    foundation_cache_hits=sum(self.reader.cache_hits.values()),
                    processing_day_executions=len(
                        tuple(
                            (
                                self.config.processing_day_cache_root
                                / f"instrument={work.instrument}"
                            ).glob("date=*.receipt.json")
                        )
                    ),
                    legacy_runs_generated=_checkpoint_legacy_run_count(checkpoint),
                    bytes_written=sum(
                        0 if dataset.artifact is None else dataset.artifact.byte_size
                        for dataset in checkpoint.datasets
                    ),
                )
            return

        context = multiprocessing.get_context("spawn")
        pool = ProcessPoolExecutor(
            max_workers=self.config.compute_worker_count,
            mp_context=context,
            initializer=_initialize_group1_month_worker,
            initargs=(
                self.config,
                self.snapshot_id,
                self._foundation_checkpoints,
                self.lineage_by_instrument,
            ),
        )
        try:
            futures: dict[int, Future[Group1MonthResultV1]] = {}
            next_submit = 0
            while next_submit < min(len(plan), self.config.compute_worker_count):
                futures[next_submit] = pool.submit(_execute_group1_month_worker, plan[next_submit])
                next_submit += 1
            for index in range(len(plan)):
                result = futures.pop(index).result()
                if next_submit < len(plan):
                    futures[next_submit] = pool.submit(
                        _execute_group1_month_worker, plan[next_submit]
                    )
                    next_submit += 1
                yield result
        except BaseException:
            for future in futures.values():
                future.cancel()
            _terminate_process_pool(pool)
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            pool.shutdown(wait=True)

    def _seal_month_dataset_bindings(
        self, checkpoint: Group1MonthCheckpoint
    ) -> tuple[Group1MonthlyDatasetBinding, ...]:
        result: list[Group1MonthlyDatasetBinding] = []
        for dataset in checkpoint.datasets:
            path = _month_dataset_checkpoint_path(
                self.config,
                checkpoint.instrument,
                checkpoint.utc_month,
                dataset.variant,
                dataset.dataset,
            )
            physical_sha256 = _write_once_model(path, dataset)
            result.append(
                Group1MonthlyDatasetBinding(
                    instrument=checkpoint.instrument,
                    utc_month=checkpoint.utc_month,
                    owner_start=checkpoint.owner_start,
                    owner_end_exclusive=checkpoint.owner_end_exclusive,
                    variant=dataset.variant,
                    dataset=dataset.dataset,
                    relative_path=path.relative_to(self.config.run_root).as_posix(),
                    physical_sha256=physical_sha256,
                    artifact_byte_size=(
                        0 if dataset.artifact is None else dataset.artifact.byte_size
                    ),
                )
            )
        return tuple(result)

    def _load_month_dataset_binding(
        self, binding: Group1MonthlyDatasetBinding
    ) -> Group1MonthlyDatasetSeal:
        path = _safe_bound_metadata_path(self.config.run_root, binding.relative_path)
        if _sha256_file(path) != binding.physical_sha256:
            raise ContractViolation("Group-1 monthly dataset metadata changed")
        dataset = Group1MonthlyDatasetSeal.model_validate_json(path.read_bytes())
        if (
            dataset.variant != binding.variant
            or dataset.dataset != binding.dataset
            or (0 if dataset.artifact is None else dataset.artifact.byte_size)
            != binding.artifact_byte_size
        ):
            raise ContractViolation("Group-1 monthly dataset binding changed")
        expected_dates = tuple(_dates(binding.owner_start, binding.owner_end_exclusive))
        if tuple(item.partition.owner_date for item in dataset.receipts) != expected_dates:
            raise ContractViolation("Group-1 monthly dataset coverage changed")
        if any(item.partition.instrument != binding.instrument for item in dataset.receipts):
            raise ContractViolation("Group-1 monthly dataset instrument changed")
        return dataset

    def _pack_streaming_components(
        self,
        *,
        instruments: tuple[Instrument, ...],
        start: date,
        end_exclusive: date,
        bindings: tuple[Group1MonthlyDatasetBinding, ...],
        distributions: tuple[GlobalDistributionCount, ...],
        component_sink: Callable[[Group1PackedTaskComponent], None],
    ) -> Group1StreamingPipelineResult:
        expected_months = tuple(_month_windows(start, end_exclusive))
        by_key: dict[tuple[Instrument, str, str], tuple[Group1MonthlyDatasetBinding, ...]] = {}
        planned_objects = 0
        for instrument in instruments:
            for variant, dataset in GROUP1_BINDINGS:
                selected = tuple(
                    sorted(
                        (
                            item
                            for item in bindings
                            if item.instrument == instrument
                            and item.variant == variant
                            and item.dataset == dataset
                        ),
                        key=lambda item: item.owner_start,
                    )
                )
                actual = tuple(
                    (item.utc_month, item.owner_start, item.owner_end_exclusive)
                    for item in selected
                )
                if actual != expected_months:
                    raise ContractViolation("Group-1 dataset binding coverage is incomplete")
                by_key[(instrument, variant, dataset)] = selected
                planned_objects += len(
                    _packed_byte_windows(
                        tuple(item.artifact_byte_size for item in selected),
                        target_bytes=self.config.packed_target_bytes,
                        min_bytes=self.config.packed_min_bytes,
                        max_bytes=self.config.packed_max_bytes,
                    )
                )
        require_catalog_object_budget(
            foundation_object_count=self.foundation_object_count,
            group1_planned_object_count=planned_objects,
            catalog_cap=self.config.max_group1_packed_objects,
        )

        object_counts: list[Group1BindingObjectCount] = []
        aggregate_receipts: list[tuple[tuple[Any, ...], str]] = []
        aggregate_seal_hashes: list[str] = []
        total_object_count = 0
        receipt_count = 0
        max_observed = 0
        max_rss_observed = process_peak_rss_bytes()
        variants = tuple(dict.fromkeys(variant for variant, _dataset in GROUP1_BINDINGS))
        for instrument in instruments:
            for variant in variants:
                component_artifacts: list[ArtifactRef] = []
                component_receipts: list[Receipt] = []
                component_fragments: list[FragmentV2] = []
                component_seals: list[ShardSealV2] = []
                for current_variant, dataset in GROUP1_BINDINGS:
                    if current_variant != variant:
                        continue
                    month_inputs = tuple(
                        self._load_month_dataset_binding(item)
                        for item in by_key[(instrument, variant, dataset)]
                    )
                    windows = _packed_month_windows(
                        month_inputs,
                        target_bytes=self.config.packed_target_bytes,
                        min_bytes=self.config.packed_min_bytes,
                        max_bytes=self.config.packed_max_bytes,
                    )
                    binding_count = 0
                    for ordinal, window in enumerate(windows):
                        writer = _PackedBindingWriter(
                            config=self.config,
                            snapshot_id=self.snapshot_id,
                            instrument=instrument,
                            binding=group1_dataset_binding(variant, dataset),
                            shard_ordinal=ordinal,
                            owner_start=window[0].receipts[0].partition.owner_date,
                            owner_end_exclusive=window[-1].receipts[-1].partition.owner_date
                            + timedelta(days=1),
                        )
                        result, observed = writer.pack(window)
                        max_observed = max(max_observed, observed)
                        if result.artifact is not None:
                            component_artifacts.append(result.artifact)
                            binding_count += 1
                        component_receipts.extend(result.receipts)
                        component_fragments.extend(result.fragments)
                        component_seals.append(result.seal)
                    object_counts.append(
                        Group1BindingObjectCount(
                            instrument=instrument,
                            variant=cast(Literal["V1_PRICE", "V1_FLOW"], variant),
                            dataset=dataset,
                            object_count=binding_count,
                        )
                    )
                    del month_inputs, windows
                    self._enforce_production_rss("dataset packing")

                component = Group1PackedTaskComponent(
                    instrument=instrument,
                    variant=cast(Literal["V1_PRICE", "V1_FLOW"], variant),
                    artifacts=tuple(
                        sorted(
                            component_artifacts,
                            key=lambda item: (item.dataset_spec_hash, item.object_sha256),
                        )
                    ),
                    receipts=tuple(
                        sorted(
                            component_receipts,
                            key=lambda item: item.partition.semantic_order_key(),
                        )
                    ),
                    fragments=tuple(
                        sorted(component_fragments, key=lambda item: item.fragment_hash)
                    ),
                    seals=tuple(sorted(component_seals, key=lambda item: item.seal_hash)),
                )
                component_sink(component)
                total_object_count += len(component.artifacts)
                receipt_count += len(component.receipts)
                aggregate_receipts.extend(
                    (
                        item.partition.semantic_order_key(),
                        item.semantic_receipt_sha256,
                    )
                    for item in component.receipts
                )
                aggregate_seal_hashes.extend(item.seal_hash for item in component.seals)
                del component
                max_rss_observed = max(max_rss_observed, process_peak_rss_bytes())
                self._enforce_production_rss("component sealing")

        self._memory_budget.observe_threshold(
            category="OBJECT_COUNT",
            phase="Group-1 packing",
            metric_name="GROUP1_PACKED_OBJECT_COUNT",
            threshold=self.group1_object_budget,
            observed=total_object_count,
            unit="objects",
        )
        aggregate = Group1PackedAggregate.seal_aggregate(
            {
                "snapshot_id": self.snapshot_id,
                "owner_start": start,
                "owner_end_exclusive": end_exclusive,
                "instruments": instruments,
                "object_counts": tuple(
                    sorted(
                        object_counts,
                        key=lambda item: (item.instrument, item.variant, item.dataset),
                    )
                ),
                "total_object_count": total_object_count,
                "receipt_count": receipt_count,
                "receipt_root_sha256": metadata_sha256(
                    tuple(item for item in sorted(aggregate_receipts, key=lambda value: value[0]))
                ),
                "seal_hashes": tuple(sorted(set(aggregate_seal_hashes))),
                "distributions": distributions,
            }
        )
        _write_once_model(self.config.packed_aggregate_path, aggregate)
        max_rss_observed = max(max_rss_observed, process_peak_rss_bytes())
        return Group1StreamingPipelineResult(
            snapshot_id=self.snapshot_id,
            object_counts=aggregate.object_counts,
            distributions=distributions,
            packed_aggregate=aggregate,
            max_inflight_bytes_observed=max_observed,
            max_process_rss_bytes_observed=max_rss_observed,
        )

    def _enforce_production_rss(self, phase: str) -> None:
        self._memory_budget.check(f"Group-1 {phase}")

    def _build_or_resume_month(
        self,
        *,
        instrument: Instrument,
        utc_month: str,
        start: date,
        end_exclusive: date,
        compute_pool: Executor | None,
        progress_sink: Callable[[date, int], None] | None = None,
    ) -> tuple[Group1MonthCheckpoint, int]:
        authority = self.reader.authority_for_window(
            instrument=instrument, owner_start=start, owner_end_exclusive=end_exclusive
        )
        path = _month_checkpoint_path(self.config, instrument, utc_month)
        if path.exists():
            checkpoint = Group1MonthCheckpoint.model_validate_json(path.read_bytes())
            self._verify_month_checkpoint(
                checkpoint,
                instrument=instrument,
                utc_month=utc_month,
                start=start,
                end_exclusive=end_exclusive,
                authority=authority,
            )
            return checkpoint, 0

        owner_dates = tuple(_dates(start, end_exclusive))
        writers = {
            (variant, dataset): _MonthlyBindingWriter(
                config=self.config,
                snapshot_id=self.snapshot_id,
                instrument=instrument,
                binding=group1_dataset_binding(variant, dataset),
                utc_month=utc_month,
                owner_start=start,
                owner_end_exclusive=end_exclusive,
            )
            for variant, dataset in GROUP1_BINDINGS
        }
        distributions: Counter[tuple[str, str]] = Counter()
        observed_authority: set[str] = set()
        processing_day_cache: dict[date, tuple[dict[str, Any], ...]] = {}
        prior_date = start - timedelta(days=1)
        cached_prior = _load_processing_day_cache(
            config=self.config,
            snapshot_id=self.snapshot_id,
            instrument=instrument,
            processing_date=prior_date,
            expected_foundation_authority=self.reader.authority_for_window(
                instrument=instrument,
                owner_start=prior_date,
                owner_end_exclusive=prior_date + timedelta(days=1),
            ),
            lineage=self.lineage_by_instrument[instrument],
        )
        if cached_prior is not None:
            processing_day_cache[prior_date] = cached_prior
        max_observed = 0
        max_rss_observed = process_peak_rss_bytes()
        try:
            # A single dataset spool for one owner day is the maximum Python
            # record-state unit.  Seven PRICE facts stream directly out of the
            # event state machine; the month and the thirteen datasets are
            # never materialized together.
            for owner_date in owner_dates:
                window = self.reader.read_window(
                    instrument=instrument,
                    owner_start=owner_date,
                    owner_end_exclusive=owner_date + timedelta(days=1),
                )
                if not set(window.foundation_authority_members).issubset(set(authority)):
                    raise ContractViolation("Feature Foundation authority changed during day read")
                observed_authority.update(window.foundation_authority_members)
                max_observed = max(max_observed, window.max_inflight_bytes_observed)
                day_observed, day_rss = _stream_owner_day_to_writers(
                    config=self.config,
                    snapshot_id=self.snapshot_id,
                    instrument=instrument,
                    owner_date=owner_date,
                    window=window,
                    lineage=self.lineage_by_instrument[instrument],
                    writers=writers,
                    distributions=distributions,
                    compute_pool=compute_pool,
                    memory_budget=self._memory_budget,
                    processing_day_cache=processing_day_cache,
                    progress_sink=progress_sink,
                )
                _write_or_verify_processing_day_cache(
                    config=self.config,
                    snapshot_id=self.snapshot_id,
                    instrument=instrument,
                    processing_date=owner_date,
                    attempts=processing_day_cache[owner_date],
                    foundation_authority=window.foundation_authority_members,
                    lineage=self.lineage_by_instrument[instrument],
                )
                for cached_date in tuple(processing_day_cache):
                    if cached_date < owner_date - timedelta(days=1):
                        del processing_day_cache[cached_date]
                max_observed = max(max_observed, day_observed)
                max_rss_observed = max(max_rss_observed, day_rss)
            if tuple(sorted(observed_authority)) != authority:
                raise ContractViolation("Feature Foundation authority changed during month build")
            datasets = [writers[key].finalize() for key in GROUP1_BINDINGS]
        except BaseException:
            for writer in writers.values():
                writer.close_after_failure()
            raise
        checkpoint = Group1MonthCheckpoint.seal_checkpoint(
            {
                "snapshot_id": self.snapshot_id,
                "instrument": instrument,
                "utc_month": utc_month,
                "owner_start": start,
                "owner_end_exclusive": end_exclusive,
                "foundation_authority_members": authority,
                "foundation_authority_sha256": metadata_sha256(authority),
                "datasets": tuple(datasets),
                "distributions": _distribution_models(distributions),
                "max_process_rss_bytes_observed": max_rss_observed,
            }
        )
        _write_once_model(path, checkpoint)
        return checkpoint, max_observed

    def _verify_month_checkpoint(
        self,
        checkpoint: Group1MonthCheckpoint,
        *,
        instrument: Instrument,
        utc_month: str,
        start: date,
        end_exclusive: date,
        authority: tuple[str, ...],
    ) -> None:
        if (
            checkpoint.snapshot_id != self.snapshot_id
            or checkpoint.instrument != instrument
            or checkpoint.utc_month != utc_month
            or checkpoint.owner_start != start
            or checkpoint.owner_end_exclusive != end_exclusive
            or checkpoint.foundation_authority_members != authority
        ):
            raise ContractViolation("Group-1 month checkpoint authority changed; resume forbidden")
        for dataset in checkpoint.datasets:
            seal_path = self.config.run_root / dataset.seal_relative_path
            if (
                not seal_path.is_file()
                or seal_path.is_symlink()
                or _sha256_file(seal_path) != dataset.seal_file_sha256
                or ShardSealV2.model_validate_json(seal_path.read_bytes()) != dataset.seal
            ):
                raise ContractViolation("Group-1 monthly seal evidence changed")
            if (
                SealReducerV2.reduce(
                    snapshot_id=self.snapshot_id,
                    dataset_spec_hash=dataset.dataset_spec_hash,
                    shard_id=dataset.seal.shard_id,
                    receipts=dataset.receipts,
                )
                != dataset.seal
            ):
                raise ContractViolation("Group-1 monthly receipt reduction changed")
            if dataset.artifact is not None:
                artifact_path = _safe_object_path(
                    self.config.monthly_catalog_root, dataset.artifact.relative_path
                )
                if (
                    not artifact_path.is_file()
                    or artifact_path.is_symlink()
                    or artifact_path.stat().st_size != dataset.artifact.byte_size
                    or _sha256_file(artifact_path) != dataset.artifact.object_sha256
                ):
                    raise ContractViolation("Group-1 monthly artifact changed")

    def _pack_months(
        self,
        *,
        instruments: tuple[Instrument, ...],
        start: date,
        end_exclusive: date,
        monthly: tuple[Group1MonthCheckpoint, ...],
    ) -> tuple[
        tuple[ArtifactRef, ...],
        tuple[Receipt, ...],
        tuple[FragmentV2, ...],
        tuple[ShardSealV2, ...],
        tuple[Group1BindingObjectCount, ...],
        int,
    ]:
        by_instrument = {
            instrument: tuple(
                sorted(
                    (item for item in monthly if item.instrument == instrument),
                    key=lambda item: item.owner_start,
                )
            )
            for instrument in instruments
        }
        planned_windows: dict[
            tuple[Instrument, str, str],
            tuple[tuple[Group1MonthlyDatasetSeal, ...], ...],
        ] = {}
        planned_objects = 0
        for instrument in instruments:
            for variant, dataset in GROUP1_BINDINGS:
                inputs = tuple(
                    next(
                        item
                        for item in month.datasets
                        if item.variant == variant and item.dataset == dataset
                    )
                    for month in by_instrument[instrument]
                )
                windows = _packed_month_windows(
                    inputs,
                    target_bytes=self.config.packed_target_bytes,
                    min_bytes=self.config.packed_min_bytes,
                    max_bytes=self.config.packed_max_bytes,
                )
                planned_windows[(instrument, variant, dataset)] = windows
                planned_objects += sum(
                    any(item.artifact is not None for item in window) for window in windows
                )
        require_catalog_object_budget(
            foundation_object_count=self.foundation_object_count,
            group1_planned_object_count=planned_objects,
            catalog_cap=self.config.max_group1_packed_objects,
        )
        artifacts: list[ArtifactRef] = []
        receipts: list[Receipt] = []
        fragments: list[FragmentV2] = []
        seals: list[ShardSealV2] = []
        object_counts: list[Group1BindingObjectCount] = []
        max_observed = 0
        for instrument in instruments:
            months = by_instrument[instrument]
            expected = tuple(_month_windows(start, end_exclusive))
            actual = tuple(
                (item.utc_month, item.owner_start, item.owner_end_exclusive) for item in months
            )
            if actual != expected:
                raise ContractViolation("Group-1 month checkpoint coverage is incomplete")
            for variant, dataset in GROUP1_BINDINGS:
                windows = planned_windows[(instrument, variant, dataset)]
                binding_count = 0
                for ordinal, window in enumerate(windows):
                    writer = _PackedBindingWriter(
                        config=self.config,
                        snapshot_id=self.snapshot_id,
                        instrument=instrument,
                        binding=group1_dataset_binding(variant, dataset),
                        shard_ordinal=ordinal,
                        owner_start=window[0].receipts[0].partition.owner_date,
                        owner_end_exclusive=window[-1].receipts[-1].partition.owner_date
                        + timedelta(days=1),
                    )
                    result, observed = writer.pack(window)
                    max_observed = max(max_observed, observed)
                    if result.artifact is not None:
                        artifacts.append(result.artifact)
                        binding_count += 1
                    receipts.extend(result.receipts)
                    fragments.extend(result.fragments)
                    seals.append(result.seal)
                object_counts.append(
                    Group1BindingObjectCount(
                        instrument=instrument,
                        variant=cast(Literal["V1_PRICE", "V1_FLOW"], variant),
                        dataset=dataset,
                        object_count=binding_count,
                    )
                )
        self._memory_budget.observe_threshold(
            category="OBJECT_COUNT",
            phase="Group-1 packing",
            metric_name="GROUP1_PACKED_OBJECT_COUNT",
            threshold=self.group1_object_budget,
            observed=len(artifacts),
            unit="objects",
        )
        object_hashes = [item.object_sha256 for item in artifacts]
        if len(set(object_hashes)) != len(object_hashes):
            raise ContractViolation("distinct Group-1 packed shards produced one physical identity")
        return (
            tuple(sorted(artifacts, key=lambda item: (item.dataset_spec_hash, item.object_sha256))),
            tuple(sorted(receipts, key=lambda item: item.partition.semantic_order_key())),
            tuple(sorted(fragments, key=lambda item: item.fragment_hash)),
            tuple(sorted(seals, key=lambda item: item.seal_hash)),
            tuple(
                sorted(
                    object_counts,
                    key=lambda item: (item.instrument, item.variant, item.dataset),
                )
            ),
            max_observed,
        )


def _terminate_process_pool(pool: ProcessPoolExecutor) -> None:
    """Stop spawn children now; ``shutdown(wait=False)`` alone lets them run on."""

    processes = tuple(getattr(pool, "_processes", {}).values())
    for process in processes:
        if process.is_alive():
            process.terminate()
    for process in processes:
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)


def _processing_day_cache_paths(
    config: Group1PipelineConfig,
    instrument: Instrument,
    processing_date: date,
) -> tuple[Path, Path]:
    root = config.processing_day_cache_root / f"instrument={instrument}"
    stem = f"date={processing_date.isoformat()}"
    return root / f"{stem}.attempts.json", root / f"{stem}.receipt.json"


def _lineage_sha256(lineage: Group1Lineage) -> str:
    return metadata_sha256(
        {
            "data_run_id": lineage.data_run_id,
            "dataset_logical_hash": lineage.dataset_logical_hash,
            "config_hash": lineage.config_hash,
            "code_version": lineage.code_version,
        }
    )


def _attempts_bytes(attempts: Sequence[Mapping[str, Any]]) -> bytes:
    return (
        json.JSONEncoder(
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        .encode([dict(item) for item in attempts])
        .encode("utf-8")
        + b"\n"
    )


def _write_or_verify_processing_day_cache(
    *,
    config: Group1PipelineConfig,
    snapshot_id: str,
    instrument: Instrument,
    processing_date: date,
    attempts: Sequence[Mapping[str, Any]],
    foundation_authority: tuple[str, ...],
    lineage: Group1Lineage,
) -> ProcessingDayCacheReceiptV1:
    attempts_path, receipt_path = _processing_day_cache_paths(config, instrument, processing_date)
    payload = _attempts_bytes(attempts)
    physical = hashlib.sha256(payload).hexdigest()
    semantic = metadata_sha256(tuple(dict(item) for item in attempts))
    receipt = ProcessingDayCacheReceiptV1.seal_receipt(
        {
            "snapshot_id": snapshot_id,
            "instrument": instrument,
            "processing_date": processing_date,
            "attempt_count": len(attempts),
            "attempts_relative_path": attempts_path.relative_to(config.run_root).as_posix(),
            "attempts_physical_sha256": physical,
            "attempts_semantic_sha256": semantic,
            "foundation_authority_sha256": metadata_sha256(tuple(sorted(foundation_authority))),
            "lineage_sha256": _lineage_sha256(lineage),
        }
    )
    attempts_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = receipt_path.with_suffix(".lock")
    with _processing_cache_lock(lock_path):
        if attempts_path.exists() or receipt_path.exists():
            existing = _load_processing_day_cache(
                config=config,
                snapshot_id=snapshot_id,
                instrument=instrument,
                processing_date=processing_date,
                expected_foundation_authority=foundation_authority,
                lineage=lineage,
            )
            if existing is None or tuple(dict(item) for item in attempts) != existing:
                raise ContractViolation("processing-day cache changed during deterministic replay")
            current = ProcessingDayCacheReceiptV1.model_validate_json(receipt_path.read_bytes())
            if current != receipt:
                raise ContractViolation("processing-day cache receipt changed")
            return current
        temporary = attempts_path.with_name(
            f".{attempts_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, attempts_path)
            _write_once_model(receipt_path, receipt)
        finally:
            temporary.unlink(missing_ok=True)
        return receipt


@contextmanager
def _processing_cache_lock(path: Path) -> Iterator[None]:
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _load_processing_day_cache(
    *,
    config: Group1PipelineConfig,
    snapshot_id: str,
    instrument: Instrument,
    processing_date: date,
    expected_foundation_authority: tuple[str, ...],
    lineage: Group1Lineage,
) -> tuple[dict[str, Any], ...] | None:
    attempts_path, receipt_path = _processing_day_cache_paths(config, instrument, processing_date)
    if not attempts_path.exists() and not receipt_path.exists():
        return None
    if not attempts_path.is_file() or not receipt_path.is_file():
        raise ContractViolation("processing-day cache is incomplete")
    receipt = ProcessingDayCacheReceiptV1.model_validate_json(receipt_path.read_bytes())
    if (
        receipt.snapshot_id != snapshot_id
        or receipt.instrument != instrument
        or receipt.processing_date != processing_date
        or receipt.attempts_relative_path != attempts_path.relative_to(config.run_root).as_posix()
        or receipt.foundation_authority_sha256
        != metadata_sha256(tuple(sorted(expected_foundation_authority)))
        or receipt.lineage_sha256 != _lineage_sha256(lineage)
    ):
        raise ContractViolation("processing-day cache authority changed")
    payload = attempts_path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != receipt.attempts_physical_sha256:
        raise ContractViolation("processing-day cache bytes changed")
    raw = json.loads(payload)
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise ContractViolation("processing-day cache payload is not a record list")
    attempts = tuple(cast(dict[str, Any], item) for item in raw)
    if (
        len(attempts) != receipt.attempt_count
        or metadata_sha256(attempts) != receipt.attempts_semantic_sha256
    ):
        raise ContractViolation("processing-day cache semantics changed")
    return attempts


def _stream_owner_day_to_writers(
    *,
    config: Group1PipelineConfig,
    snapshot_id: str,
    instrument: Instrument,
    owner_date: date,
    window: FoundationFeatureWindow,
    lineage: Group1Lineage,
    writers: Mapping[tuple[str, str], _MonthlyBindingWriter],
    distributions: Counter[tuple[str, str]],
    compute_pool: Executor | None,
    memory_budget: ProcessMemoryBudget,
    processing_day_cache: dict[date, tuple[dict[str, Any], ...]] | None = None,
    progress_sink: Callable[[date, int], None] | None = None,
) -> tuple[int, int]:
    """Stream one owner day without a monolithic thirteen-dataset result."""

    bars = _contract_bars(window.causal_price_bars, instrument)
    spools = {
        dataset: _DailyRecordSpool(
            config=config,
            snapshot_id=snapshot_id,
            instrument=instrument,
            dataset=dataset,
            owner_date=owner_date,
            memory_budget=memory_budget,
        )
        for dataset in PRICE_DATASETS[:7]
    }
    max_arrow = window.max_inflight_bytes_observed

    def sink(dataset: str, record: Mapping[str, Any]) -> None:
        try:
            spool = spools[dataset]
        except KeyError as exc:
            raise ContractViolation(
                f"unapproved streamed upstream PRICE dataset: {dataset}"
            ) from exc
        _count_release_distributions(
            distributions,
            (record,),
            dataset=dataset,
            variant="V1_PRICE",
        )
        spool.add(record)

    try:
        owner_start_ns = _day_start_ns(owner_date)
        previous_date = owner_date - timedelta(days=1)
        previous_attempts = (
            None if processing_day_cache is None else processing_day_cache.get(previous_date)
        )
        if previous_attempts is None:
            previous_prices = _contract_prices(
                _slice_event_time(
                    window.contract_price_1s,
                    owner_start_ns - DAY_NS - 5_000_000_000,
                    owner_start_ns + 180_000_000_000,
                ),
                instrument,
            )
            previous = build_price_processing_day_from_features(
                instrument=instrument,
                processing_date=previous_date,
                contract_prices=previous_prices,
                causal_bars=bars,
                lineage=lineage,
                record_sink=lambda _dataset, _record: None,
                retained_outputs=frozenset({"candidate_attempts"}),
                progress_sink=(
                    None
                    if progress_sink is None
                    else lambda minute: progress_sink(previous_date, minute)
                ),
            )
            previous_attempts = tuple(previous["candidate_attempts"])
            if processing_day_cache is not None:
                processing_day_cache[previous_date] = previous_attempts
            del previous_prices, previous
        current_prices = _contract_prices(
            _slice_event_time(
                window.contract_price_1s,
                owner_start_ns - 5_000_000_000,
                owner_start_ns + DAY_NS + 180_000_000_000,
            ),
            instrument,
        )
        current = build_price_processing_day_from_features(
            instrument=instrument,
            processing_date=owner_date,
            contract_prices=current_prices,
            causal_bars=bars,
            lineage=lineage,
            record_sink=sink,
            retained_outputs=frozenset({"candidate_attempts"}),
            progress_sink=(
                None if progress_sink is None else lambda minute: progress_sink(owner_date, minute)
            ),
        )
        current_attempts = tuple(current["candidate_attempts"])
        if processing_day_cache is not None:
            processing_day_cache[owner_date] = current_attempts
        price_attempts = [
            *previous_attempts,
            *current_attempts,
        ]
        # ContractPrice/ContractBar Pydantic rows are the dominant non-Arrow
        # context during canonical spooling.  Candidate attempts are the only
        # retained cross-processing-day state, so release the contexts before
        # reconstructing one daily dataset at a time.
        del current, current_prices, bars
        for dataset in PRICE_DATASETS[:7]:
            prepared = spools[dataset].finish()
            max_arrow = max(
                max_arrow,
                window.max_inflight_bytes_observed + prepared.batch.table.nbytes,
            )
            memory_budget.observe_threshold(
                category="ARROW_INFLIGHT",
                phase=f"Group-1 {instrument} {owner_date.isoformat()} PRICE streaming",
                metric_name="ARROW_INFLIGHT_BYTES",
                threshold=config.max_inflight_bytes,
                observed=max_arrow,
            )
            writers[("V1_PRICE", dataset)].append(prepared)

        price_finalized = finalize_candidate_attempts(price_attempts)
        owner_key = owner_date.isoformat()
        flow_windows = tuple(price_finalized.flow_windows_by_date.get(owner_key, ()))
        price_formal: tuple[tuple[str, Sequence[Mapping[str, Any]]], ...] = (
            (
                "market_episodes",
                price_finalized.market_episodes_by_date.get(owner_key, ()),
            ),
            (
                "candidate_inclusion",
                price_finalized.inclusion_by_date.get(owner_key, ()),
            ),
            ("flow_windows", flow_windows),
        )
        for dataset, records in price_formal:
            prepared = _prepare_formal_records(
                compute_pool=compute_pool,
                snapshot_id=snapshot_id,
                instrument=instrument,
                variant="V1_PRICE",
                dataset=dataset,
                owner_date=owner_date,
                records=records,
                distributions=distributions,
            )
            max_arrow = max(
                max_arrow,
                window.max_inflight_bytes_observed + prepared.batch.table.nbytes,
            )
            writers[("V1_PRICE", dataset)].append(prepared)
        # The finalizer owns several redundant maps and audit lists.  Keep only
        # the immutable FLOW-window facts needed by G4 before materializing the
        # large per-second Trade primitive context.
        del price_attempts, price_finalized, price_formal, records, prepared

        # Trades primitives are deliberately materialized only after all large
        # PRICE facts have been spooled and prepared.
        trade_seconds = _trade_seconds(window.trade_second_primitives, instrument)
        trade_quality = {
            key: value
            for key, value in window.trade_source_day_status.items()
            if isinstance(key, date)
        }
        flow_output = build_flow_owner_day_from_primitives(
            instrument=instrument,
            owner_date=owner_date,
            windows=flow_windows,
            trade_seconds=trade_seconds,
            trade_source_day_status=trade_quality,
        )
        flow_finalized = finalize_candidate_attempts(
            flow_output["candidate_attempts"], include_flow_windows=False
        )
        flow_formal: tuple[tuple[str, Sequence[Mapping[str, Any]]], ...] = (
            ("flow_features", flow_output["flow_features"]),
            (
                "market_episodes",
                flow_finalized.market_episodes_by_date.get(owner_key, ()),
            ),
            (
                "candidate_inclusion",
                flow_finalized.inclusion_by_date.get(owner_key, ()),
            ),
        )
        for dataset, records in flow_formal:
            prepared = _prepare_formal_records(
                compute_pool=compute_pool,
                snapshot_id=snapshot_id,
                instrument=instrument,
                variant="V1_FLOW",
                dataset=dataset,
                owner_date=owner_date,
                records=records,
                distributions=distributions,
            )
            max_arrow = max(
                max_arrow,
                window.max_inflight_bytes_observed + prepared.batch.table.nbytes,
            )
            writers[("V1_FLOW", dataset)].append(prepared)
        memory_budget.observe_threshold(
            category="ARROW_INFLIGHT",
            phase=f"Group-1 {instrument} {owner_date.isoformat()} FLOW streaming",
            metric_name="ARROW_INFLIGHT_BYTES",
            threshold=config.max_inflight_bytes,
            observed=max_arrow,
        )
        return max_arrow, _require_rss_within_limit(
            config,
            memory_budget,
            phase=f"Group-1 {instrument} {owner_date.isoformat()} owner day",
            arrow_inflight_bytes=max_arrow,
        )
    except BaseException:
        for spool in spools.values():
            spool.close_after_failure()
        raise


def _prepare_formal_records(
    *,
    compute_pool: Executor | None,
    snapshot_id: str,
    instrument: Instrument,
    variant: Literal["V1_PRICE", "V1_FLOW"],
    dataset: str,
    owner_date: date,
    records: Sequence[Mapping[str, Any]],
    distributions: Counter[tuple[str, str]],
) -> PreparedGroup1Partition:
    _count_release_distributions(
        distributions,
        records,
        dataset=dataset,
        variant=variant,
    )
    if compute_pool is None:
        return prepare_group1_partition(
            snapshot_id=snapshot_id,
            instrument=instrument,
            variant=variant,
            dataset=dataset,
            owner_date=owner_date,
            records=records,
        )
    future: Future[PreparedGroup1Partition] = compute_pool.submit(
        prepare_group1_partition,
        snapshot_id=snapshot_id,
        instrument=instrument,
        variant=variant,
        dataset=dataset,
        owner_date=owner_date,
        records=records,
    )
    return future.result()


@dataclass(frozen=True, slots=True)
class _MonthlyDayDigest:
    key: LogicalPartitionKey
    row_count: int
    row_offset: int
    legacy_hash_algorithm: str
    legacy_logical_sha256: str | None
    semantic_sha256: str
    identity_sha256: str
    payload_sha256: str
    distributions: tuple[DistributionDigest, ...]
    quality_facts: tuple[QualityFact, ...]


class _DailyRecordSpool:
    """Bounded upstream-record spool for one dataset and processing day."""

    BUFFER_ROWS = 32_768

    def __init__(
        self,
        *,
        config: Group1PipelineConfig,
        snapshot_id: str,
        instrument: Instrument,
        dataset: str,
        owner_date: date,
        memory_budget: ProcessMemoryBudget,
    ) -> None:
        self.config = config
        self.snapshot_id = snapshot_id
        self.instrument = instrument
        self.dataset = dataset
        self.owner_date = owner_date
        self.memory_budget = memory_budget
        self.binding = group1_dataset_binding("V1_PRICE", dataset)
        self._buffer: list[Mapping[str, Any]] = []
        self._tables: list[pa.Table] = []
        self._row_count = 0
        self._legacy_runs: list[_LegacyHashRun] = []

    def add(self, record: Mapping[str, Any]) -> None:
        self._buffer.append(record)
        if len(self._buffer) >= self.BUFFER_ROWS:
            self._flush()

    def finish(self) -> PreparedGroup1Partition:
        self._flush()
        if self._row_count == 0:
            return prepare_group1_partition(
                snapshot_id=self.snapshot_id,
                instrument=self.instrument,
                variant="V1_PRICE",
                dataset=self.dataset,
                owner_date=self.owner_date,
                records=(),
            )
        table = pa.concat_tables(self._tables).combine_chunks()
        if table.num_rows != self._row_count:
            raise ContractViolation("daily Group-1 spool row count changed")
        legacy_digest = _merge_legacy_hash_runs(
            self._legacy_runs,
            expected_row_count=self._row_count,
        )
        prepared = prepare_group1_arrow_partition(
            snapshot_id=self.snapshot_id,
            instrument=self.instrument,
            variant="V1_PRICE",
            dataset=self.dataset,
            owner_date=self.owner_date,
            table=table,
            source_record_count=self._row_count,
            legacy_logical_sha256=legacy_digest,
        )
        _require_rss_within_limit(
            self.config,
            self.memory_budget,
            phase=f"Group-1 {self.instrument} {self.owner_date.isoformat()} spool finish",
            arrow_inflight_bytes=table.nbytes,
        )
        self._tables.clear()
        self._legacy_runs.clear()
        return prepared

    def close_after_failure(self) -> None:
        self._tables.clear()
        self._legacy_runs.clear()
        self._buffer.clear()

    def _flush(self) -> None:
        if not self._buffer:
            return
        _binding, table = normalize_group1_record_batch(
            instrument=self.instrument,
            variant="V1_PRICE",
            dataset=self.dataset,
            owner_date=self.owner_date,
            records=self._buffer,
        )
        legacy_rows = legacy_sorted_record_bytes(self._buffer)
        self._legacy_runs.append(_LegacyHashRun(rows=legacy_rows))
        if table.num_rows:
            self._tables.append(table)
            self._row_count += table.num_rows
        self._buffer.clear()
        _require_rss_within_limit(
            self.config,
            self.memory_budget,
            phase=f"Group-1 {self.instrument} {self.owner_date.isoformat()} spool flush",
            arrow_inflight_bytes=table.nbytes,
        )


@dataclass(frozen=True, slots=True)
class _LegacyHashRun:
    rows: tuple[bytes, ...]

    @property
    def row_count(self) -> int:
        return len(self.rows)


def _merge_legacy_hash_runs(
    runs: Sequence[_LegacyHashRun],
    *,
    expected_row_count: int,
) -> str:
    """Externally merge bounded V1 serialization runs into the exact day hash."""

    if not runs:
        raise ContractViolation("non-empty Group-1 spool has no legacy hash runs")
    if sum(item.row_count for item in runs) != expected_row_count:
        raise ContractViolation("legacy compatibility run row count changed")
    rows = heapq.merge(*(iter(run.rows) for run in runs))
    digest = hashlib.sha256()
    first = True
    count = 0
    for row in rows:
        if not first:
            digest.update(b"\n")
        digest.update(row)
        first = False
        count += 1
    if count != expected_row_count:
        raise ContractViolation("legacy compatibility merge row count changed")
    return digest.hexdigest()


class _MonthlyBindingWriter:
    """Append one prepared owner day at a time; never retain month event rows."""

    def __init__(
        self,
        *,
        config: Group1PipelineConfig,
        snapshot_id: str,
        instrument: Instrument,
        binding: Group1DatasetBinding,
        utc_month: str,
        owner_start: date,
        owner_end_exclusive: date,
    ) -> None:
        self.config = config
        self.snapshot_id = snapshot_id
        self.instrument = instrument
        self.binding = binding
        self.utc_month = utc_month
        self.owner_start = owner_start
        self.owner_end_exclusive = owner_end_exclusive
        self._owner_thread = threading.get_ident()
        self._writer: pq.ParquetWriter | None = None
        self._rows = 0
        self._days: list[_MonthlyDayDigest] = []
        directory = config.partial_root / instrument / binding.variant / binding.dataset / "monthly"
        directory.mkdir(parents=True, exist_ok=True)
        self.partial = directory / f"{utc_month}.{uuid.uuid4().hex}.parquet.partial"

    def append(self, prepared: PreparedGroup1Partition) -> None:
        self._assert_writer_thread()
        batch = prepared.batch
        if batch.key.snapshot_id != self.snapshot_id:
            raise ContractViolation("monthly Group-1 writer received another snapshot")
        if batch.key.instrument != self.instrument or batch.key.variant != self.binding.variant:
            raise ContractViolation("monthly Group-1 writer received another physical group")
        if batch.key.dataset_spec_hash != self.binding.spec.spec_hash:
            raise ContractViolation("monthly Group-1 writer received another DatasetSpec")
        if not self.owner_start <= batch.key.owner_date < self.owner_end_exclusive:
            raise ContractViolation("monthly Group-1 writer received an out-of-range owner day")
        expected_date = self.owner_start + timedelta(days=len(self._days))
        if batch.key.owner_date != expected_date:
            raise ContractViolation("monthly Group-1 owner days must arrive once in UTC order")
        table = batch.table
        semantic = prepared.v2_semantic_sha256
        identity = prepared.identity_multiset_sha256
        payload = prepared.payload_association_sha256
        row_offset = self._rows
        if table.num_rows:
            if self._writer is None:
                self._writer = pq.ParquetWriter(
                    self.partial,
                    canonical_arrow_schema(self.binding.spec),
                    compression="zstd",
                    write_statistics=True,
                )
            self._writer.write_table(table, row_group_size=ROW_GROUP_SIZE)
            self._rows += table.num_rows
        self._days.append(
            _MonthlyDayDigest(
                key=batch.key,
                row_count=table.num_rows,
                row_offset=row_offset,
                legacy_hash_algorithm=batch.legacy_hash_algorithm,
                legacy_logical_sha256=batch.legacy_logical_sha256,
                semantic_sha256=semantic,
                identity_sha256=identity,
                payload_sha256=payload,
                distributions=batch.distributions,
                quality_facts=batch.quality_facts,
            )
        )

    def finalize(self) -> Group1MonthlyDatasetSeal:
        self._assert_writer_thread()
        expected_dates = tuple(_dates(self.owner_start, self.owner_end_exclusive))
        if tuple(item.key.owner_date for item in self._days) != expected_dates:
            raise ContractViolation("monthly Group-1 writer did not receive every owner day")
        if self._writer is not None:
            self._writer.close()
            self._writer = None
            with self.partial.open("rb") as handle:
                os.fsync(handle.fileno())
        artifact = self._publish_artifact()
        fragments: list[FragmentV2] = []
        fragment_by_partition: dict[str, FragmentV2] = {}
        if artifact is not None:
            for day in self._days:
                if not day.row_count:
                    continue
                fragment = FragmentV2.seal(
                    {
                        "snapshot_id": self.snapshot_id,
                        "dataset_spec_hash": self.binding.spec.spec_hash,
                        "partition_id": day.key.partition_id,
                        "artifact": artifact,
                        "fragment_ordinal": 0,
                        "row_offset": day.row_offset,
                        "row_count": day.row_count,
                        "semantic_sha256": day.semantic_sha256,
                    }
                )
                fragments.append(fragment)
                fragment_by_partition[day.key.partition_id] = fragment
        shard_id = _monthly_shard_id(
            self.instrument,
            self.binding.variant,
            self.binding.dataset,
            self.utc_month,
        )
        receipts: list[Receipt] = []
        for day in self._days:
            selected_fragment = fragment_by_partition.get(day.key.partition_id)
            receipts.append(
                Receipt.seal(
                    {
                        "snapshot_id": self.snapshot_id,
                        "shard_id": shard_id,
                        "partition": day.key,
                        "terminal_state": "PRESENT" if day.row_count else "EMPTY",
                        "row_count": day.row_count,
                        "legacy_hash_algorithm": day.legacy_hash_algorithm,
                        "legacy_logical_sha256": day.legacy_logical_sha256,
                        "semantic_sha256": day.semantic_sha256,
                        "identity_multiset_sha256": day.identity_sha256,
                        "payload_association_sha256": day.payload_sha256,
                        "distributions": day.distributions,
                        "quality_facts": day.quality_facts,
                        "fragment_hashes": ()
                        if selected_fragment is None
                        else (selected_fragment.fragment_hash,),
                    }
                )
            )
        seal = SealReducerV2.reduce(
            snapshot_id=self.snapshot_id,
            dataset_spec_hash=self.binding.spec.spec_hash,
            shard_id=shard_id,
            receipts=receipts,
        )
        seal_relative_path = (
            "staging/group1/monthly-seals/"
            f"instrument={self.instrument}/month={self.utc_month}/"
            f"{self.binding.variant.lower()}--{self.binding.dataset}.json"
        )
        seal_sha = _write_once_model(self.config.run_root / seal_relative_path, seal)
        return Group1MonthlyDatasetSeal(
            variant=self.binding.variant,
            dataset=self.binding.dataset,
            dataset_spec_hash=self.binding.spec.spec_hash,
            artifact=artifact,
            receipts=tuple(receipts),
            fragments=tuple(fragments),
            seal=seal,
            seal_relative_path=seal_relative_path,
            seal_file_sha256=seal_sha,
        )

    def close_after_failure(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None

    def _publish_artifact(self) -> ArtifactRef | None:
        if self._rows == 0:
            self.partial.unlink(missing_ok=True)
            return None
        physical = _sha256_file(self.partial)
        byte_size = self.partial.stat().st_size
        relative = f"objects/{physical[:2]}/{physical}.parquet"
        target = self.config.monthly_catalog_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.stat().st_size != byte_size or _sha256_file(target) != physical:
                raise PublicationConflict(f"Group-1 monthly object conflict at {target}")
        else:
            os.replace(self.partial, target)
            _fsync_directory(target.parent)
        return ArtifactRef(
            snapshot_id=self.snapshot_id,
            dataset_spec_hash=self.binding.spec.spec_hash,
            object_sha256=physical,
            relative_path=relative,
            byte_size=byte_size,
            row_count=self._rows,
            semantic_sha256=metadata_sha256(
                {
                    "domain": "stage2-v2-group1-month-object",
                    "members": tuple(
                        (item.key.partition_id, item.semantic_sha256)
                        for item in self._days
                        if item.row_count
                    ),
                }
            ),
        )

    def _assert_writer_thread(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("monthly Group-1 output requires one deterministic writer")


class _PackedBindingWriter:
    """Stream monthly recovery objects into one bounded formal packed shard."""

    def __init__(
        self,
        *,
        config: Group1PipelineConfig,
        snapshot_id: str,
        instrument: Instrument,
        binding: Group1DatasetBinding,
        shard_ordinal: int,
        owner_start: date,
        owner_end_exclusive: date,
    ) -> None:
        self.config = config
        self.snapshot_id = snapshot_id
        self.instrument = instrument
        self.binding = binding
        self.shard_ordinal = shard_ordinal
        self.owner_start = owner_start
        self.owner_end_exclusive = owner_end_exclusive
        self._owner_thread = threading.get_ident()

    def pack(self, monthly: Sequence[Group1MonthlyDatasetSeal]) -> tuple[CompactionResult, int]:
        self._assert_writer_thread()
        partial_dir = (
            self.config.partial_root / self.instrument / self.binding.variant / self.binding.dataset
        )
        partial_dir.mkdir(parents=True, exist_ok=True)
        partial = (
            partial_dir / f"packed-{self.shard_ordinal:03d}.{uuid.uuid4().hex}.parquet.partial"
        )
        writer: pq.ParquetWriter | None = None
        rows = 0
        source_receipts: list[Receipt] = []
        day_offsets: list[tuple[Receipt, int]] = []
        max_observed = 0
        try:
            for item in monthly:
                if (item.variant, item.dataset) != (
                    self.binding.variant,
                    self.binding.dataset,
                ):
                    raise ContractViolation("packed Group-1 shard mixes bindings")
                table = self._read_month_artifact(item)
                max_observed = max(max_observed, table.nbytes)
                fragment_by_hash = {fragment.fragment_hash: fragment for fragment in item.fragments}
                for receipt in item.receipts:
                    owner_date = receipt.partition.owner_date
                    if not self.owner_start <= owner_date < self.owner_end_exclusive:
                        raise ContractViolation("packed receipt escapes deterministic shard range")
                    day = _slice_receipt(table, receipt, fragment_by_hash)
                    day = normalize_table(day, self.binding.spec)
                    if canonical_semantic_hash(day, self.binding.spec) != receipt.semantic_sha256:
                        raise ContractViolation("monthly Group-1 semantics changed before packing")
                    day_offsets.append((receipt, rows))
                    source_receipts.append(receipt)
                    if day.num_rows:
                        if writer is None:
                            writer = pq.ParquetWriter(
                                partial,
                                canonical_arrow_schema(self.binding.spec),
                                compression="zstd",
                                write_statistics=True,
                            )
                        writer.write_table(day, row_group_size=ROW_GROUP_SIZE)
                        rows += day.num_rows
            if writer is not None:
                writer.close()
                writer = None
                with partial.open("rb") as handle:
                    os.fsync(handle.fileno())
            expected_dates = tuple(_dates(self.owner_start, self.owner_end_exclusive))
            if tuple(item.partition.owner_date for item in source_receipts) != expected_dates:
                raise ContractViolation("packed Group-1 shard lost an owner day")
            artifact = self._publish_artifact(partial, rows, source_receipts)
            fragments: list[FragmentV2] = []
            fragment_by_partition: dict[str, FragmentV2] = {}
            if artifact is not None:
                for receipt, row_offset in day_offsets:
                    if receipt.row_count == 0:
                        continue
                    fragment = FragmentV2.seal(
                        {
                            "snapshot_id": self.snapshot_id,
                            "dataset_spec_hash": self.binding.spec.spec_hash,
                            "partition_id": receipt.partition.partition_id,
                            "artifact": artifact,
                            "fragment_ordinal": 0,
                            "row_offset": row_offset,
                            "row_count": receipt.row_count,
                            "semantic_sha256": receipt.semantic_sha256,
                        }
                    )
                    fragments.append(fragment)
                    fragment_by_partition[receipt.partition.partition_id] = fragment
            shard_id = _packed_shard_id(
                self.instrument,
                self.binding.variant,
                self.binding.dataset,
                self.owner_start,
                self.owner_end_exclusive,
            )
            final_receipts: list[Receipt] = []
            for source in source_receipts:
                selected_fragment = fragment_by_partition.get(source.partition.partition_id)
                final_receipts.append(
                    Receipt.seal(
                        {
                            "snapshot_id": self.snapshot_id,
                            "shard_id": shard_id,
                            "partition": source.partition,
                            "terminal_state": source.terminal_state,
                            "row_count": source.row_count,
                            "legacy_hash_algorithm": source.legacy_hash_algorithm,
                            "legacy_logical_sha256": source.legacy_logical_sha256,
                            "semantic_sha256": source.semantic_sha256,
                            "identity_multiset_sha256": source.identity_multiset_sha256,
                            "payload_association_sha256": source.payload_association_sha256,
                            "distributions": source.distributions,
                            "quality_facts": tuple(
                                sorted(
                                    (
                                        *source.quality_facts,
                                        QualityFact(name="packed_from_month_seal", value=True),
                                    ),
                                    key=lambda fact: fact.name,
                                )
                            ),
                            "fragment_hashes": ()
                            if selected_fragment is None
                            else (selected_fragment.fragment_hash,),
                        }
                    )
                )
            seal = SealReducerV2.reduce(
                snapshot_id=self.snapshot_id,
                dataset_spec_hash=self.binding.spec.spec_hash,
                shard_id=shard_id,
                receipts=final_receipts,
            )
            seal_path = (
                self.config.packed_seal_root
                / f"instrument={self.instrument}"
                / f"variant={self.binding.variant}"
                / f"dataset={self.binding.dataset}"
                / f"{self.owner_start.isoformat()}_{self.owner_end_exclusive.isoformat()}.json"
            )
            _write_once_model(seal_path, seal)
            return (
                CompactionResult(
                    artifact=artifact,
                    receipts=tuple(final_receipts),
                    fragments=tuple(fragments),
                    seal=seal,
                ),
                max_observed,
            )
        except BaseException:
            if writer is not None:
                writer.close()
            raise

    def _read_month_artifact(self, item: Group1MonthlyDatasetSeal) -> pa.Table:
        if item.artifact is None:
            return pa.Table.from_batches([], schema=canonical_arrow_schema(self.binding.spec))
        path = _safe_object_path(self.config.monthly_catalog_root, item.artifact.relative_path)
        if (
            not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != item.artifact.byte_size
            or _sha256_file(path) != item.artifact.object_sha256
        ):
            raise ContractViolation("Group-1 monthly artifact bytes changed before packing")
        table = pq.read_table(path).combine_chunks()
        if not table.schema.equals(canonical_arrow_schema(self.binding.spec), check_metadata=False):
            raise ContractViolation("Group-1 monthly artifact schema changed")
        if table.num_rows != item.artifact.row_count:
            raise ContractViolation("Group-1 monthly artifact row count changed")
        return table

    def _publish_artifact(
        self, partial: Path, rows: int, source_receipts: Sequence[Receipt]
    ) -> ArtifactRef | None:
        if rows == 0:
            partial.unlink(missing_ok=True)
            return None
        physical = _sha256_file(partial)
        byte_size = partial.stat().st_size
        relative = f"objects/{physical[:2]}/{physical}.parquet"
        target = self.config.snapshot_catalog_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.stat().st_size != byte_size or _sha256_file(target) != physical:
                raise PublicationConflict(f"Group-1 packed object conflict at {target}")
        else:
            os.replace(partial, target)
            _fsync_directory(target.parent)
        return ArtifactRef(
            snapshot_id=self.snapshot_id,
            dataset_spec_hash=self.binding.spec.spec_hash,
            object_sha256=physical,
            relative_path=relative,
            byte_size=byte_size,
            row_count=rows,
            semantic_sha256=metadata_sha256(
                {
                    "domain": "stage2-v2-group1-packed-object",
                    "members": tuple(
                        (item.partition.partition_id, item.semantic_sha256)
                        for item in source_receipts
                        if item.row_count
                    ),
                }
            ),
        )

    def _assert_writer_thread(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("Group-1 packed output requires the deterministic writer thread")


def _packed_month_windows(
    inputs: Sequence[Group1MonthlyDatasetSeal],
    *,
    target_bytes: int,
    min_bytes: int,
    max_bytes: int,
) -> tuple[tuple[Group1MonthlyDatasetSeal, ...], ...]:
    """Form deterministic contiguous shards from sealed monthly byte sizes."""

    if not inputs:
        raise ValueError("packed Group-1 planning requires monthly inputs")
    slices = _packed_byte_windows(
        tuple(0 if item.artifact is None else item.artifact.byte_size for item in inputs),
        target_bytes=target_bytes,
        min_bytes=min_bytes,
        max_bytes=max_bytes,
    )
    return tuple(tuple(inputs[start:end]) for start, end in slices)


def _packed_byte_windows(
    item_sizes: Sequence[int],
    *,
    target_bytes: int,
    min_bytes: int,
    max_bytes: int,
) -> tuple[tuple[int, int], ...]:
    """Return the exact packed slices without retaining monthly metadata."""

    if not item_sizes:
        raise ValueError("packed Group-1 planning requires monthly inputs")
    windows: list[tuple[int, int]] = []
    current_start = 0
    current_bytes = 0
    for index, item_bytes in enumerate(item_sizes):
        # CR-2026-013 makes the maximum an observational packing target.  An
        # already larger indivisible monthly object is emitted alone and is
        # recorded as a SHARD_SIZE anomaly when the task evidence is sealed.
        if index > current_start and current_bytes + item_bytes > max_bytes:
            windows.append((current_start, index))
            current_start = index
            current_bytes = 0
        current_bytes += item_bytes
        if current_bytes >= target_bytes:
            windows.append((current_start, index + 1))
            current_start = index + 1
            current_bytes = 0
    if current_start < len(item_sizes):
        if windows:
            previous_start, previous_end = windows[-1]
            previous_bytes = sum(item_sizes[previous_start:previous_end])
            if current_bytes < min_bytes and previous_bytes + current_bytes <= max_bytes:
                windows[-1] = (previous_start, len(item_sizes))
            else:
                windows.append((current_start, len(item_sizes)))
        else:
            windows.append((current_start, len(item_sizes)))
    return tuple(windows)


def group1_object_budget(foundation_object_count: int, *, catalog_cap: int = 200) -> int:
    if foundation_object_count < 0 or catalog_cap <= 0:
        raise ValueError("Catalog object counts must be non-negative with a positive cap")
    budget = catalog_cap - foundation_object_count
    return max(0, budget)


def require_catalog_object_budget(
    *,
    foundation_object_count: int,
    group1_planned_object_count: int,
    catalog_cap: int = 200,
) -> None:
    if group1_planned_object_count < 0:
        raise ValueError("Group-1 planned object count cannot be negative")
    budget = group1_object_budget(foundation_object_count, catalog_cap=catalog_cap)
    del budget


def _slice_receipt(
    table: pa.Table,
    receipt: Receipt,
    fragments: Mapping[str, FragmentV2],
) -> pa.Table:
    if not receipt.fragment_hashes:
        if receipt.row_count:
            raise ContractViolation("non-empty monthly receipt lost its fragment")
        return table.slice(0, 0)
    if len(receipt.fragment_hashes) != 1:
        raise ContractViolation("monthly Group-1 receipt must use one fragment")
    try:
        fragment = fragments[receipt.fragment_hashes[0]]
    except KeyError as exc:
        raise ContractViolation("monthly Group-1 fragment is missing") from exc
    return table.slice(fragment.row_offset, fragment.row_count)


def _read_fragment(path: Path, fragment: FragmentV2) -> pa.Table:
    parquet = pq.ParquetFile(path)
    offsets: list[tuple[int, int, int]] = []
    row_offset = 0
    target_end = fragment.row_offset + fragment.row_count
    for ordinal in range(parquet.metadata.num_row_groups):
        count = parquet.metadata.row_group(ordinal).num_rows
        group_end = row_offset + count
        if row_offset < target_end and group_end > fragment.row_offset:
            offsets.append((ordinal, row_offset, group_end))
        row_offset = group_end
    if not offsets:
        raise ContractViolation("Foundation fragment does not overlap a Parquet row group")
    table = parquet.read_row_groups([item[0] for item in offsets]).combine_chunks()
    relative_start = fragment.row_offset - offsets[0][1]
    return table.slice(relative_start, fragment.row_count)


def _count_release_distributions(
    target: Counter[tuple[str, str]],
    records: Sequence[Mapping[str, Any]],
    *,
    dataset: str,
    variant: str,
) -> None:
    """Use the same key/value normalization as V1 ``release._inspect_rows``."""

    for row in records:
        for field in ("time_combination_id", "research_role", "reason_code", "ownership_status"):
            if field in row:
                target[(field, str(row[field]))] += 1
        parameter = row.get("parameter_set_id", row.get("event_parameter_set_id"))
        if parameter is not None:
            target[("parameter_set_id", str(parameter))] += 1
        if "primary_eligible" in row:
            target[("primary_eligible", str(bool(row["primary_eligible"])).lower())] += 1
        if dataset == "market_episodes":
            target[("candidate_variant_id", variant)] += 1
            target[("candidate_time_combination_id", str(row["time_combination_id"]))] += 1
            target[("candidate_parameter_set_id", str(parameter))] += 1
            target[("candidate_research_role", str(row["research_role"]))] += 1


def _distribution_models(
    values: Mapping[tuple[str, str], int],
) -> tuple[GlobalDistributionCount, ...]:
    return tuple(
        GlobalDistributionCount(name=name, value=value, count=count)
        for (name, value), count in sorted(values.items())
    )


def _merge_distributions(
    groups: Sequence[Sequence[GlobalDistributionCount]] | Any,
) -> tuple[GlobalDistributionCount, ...]:
    counter: Counter[tuple[str, str]] = Counter()
    for group in groups:
        for item in group:
            counter[(item.name, item.value)] += item.count
    return _distribution_models(counter)


def _concat_or_empty(tables: Sequence[pa.Table], spec: Any) -> pa.Table:
    if not tables:
        return pa.Table.from_batches([], schema=canonical_arrow_schema(spec))
    return pa.concat_tables(tables).combine_chunks()


def _safe_object_path(root: Path, relative_path: str) -> Path:
    relative = PurePosixPath(relative_path)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or len(relative.parts) != 3
        or relative.parts[0] != "objects"
    ):
        raise ContractViolation(f"unsafe packed object path: {relative_path}")
    path = root.joinpath(*relative.parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ContractViolation("packed object path escapes its catalog root")
    return path


def _monthly_shard_id(instrument: str, variant: str, dataset: str, utc_month: str) -> str:
    return f"g1m-{instrument.lower()}-{variant.lower()}-{dataset.replace('_', '-')}-{utc_month}"


def _packed_shard_id(
    instrument: str,
    variant: str,
    dataset: str,
    start: date,
    end_exclusive: date,
) -> str:
    return (
        f"g1p-{instrument.lower()}-{variant.lower()}-{dataset.replace('_', '-')}-"
        f"{start.isoformat()}-{end_exclusive.isoformat()}"
    )


def _month_checkpoint_path(
    config: Group1PipelineConfig, instrument: Instrument, utc_month: str
) -> Path:
    return config.monthly_checkpoint_root / f"instrument={instrument}" / f"{utc_month}.json"


def _month_dataset_checkpoint_path(
    config: Group1PipelineConfig,
    instrument: Instrument,
    utc_month: str,
    variant: str,
    dataset: str,
) -> Path:
    if (variant, dataset) not in GROUP1_BINDINGS:
        raise ContractViolation("unapproved Group-1 monthly dataset binding")
    return (
        config.monthly_dataset_checkpoint_root
        / f"instrument={instrument}"
        / f"utc_month={utc_month}"
        / f"variant={variant}"
        / f"dataset={dataset}.json"
    )


def _safe_bound_metadata_path(root: Path, relative_path: str) -> Path:
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ContractViolation("unsafe Group-1 metadata binding path")
    if relative.parts[:3] != ("staging", "group1", "monthly-dataset-checkpoints"):
        raise ContractViolation("Group-1 metadata binding is outside its approved root")
    path = root.joinpath(*relative.parts)
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file() or path.is_symlink():
        raise ContractViolation("Group-1 metadata binding is unavailable or unsafe")
    return path


def _month_windows(start: date, end_exclusive: date) -> list[tuple[str, date, date]]:
    windows: list[tuple[str, date, date]] = []
    cursor = start
    while cursor < end_exclusive:
        next_month = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )
        window_end = min(next_month, end_exclusive)
        windows.append((cursor.strftime("%Y-%m"), cursor, window_end))
        cursor = window_end
    return windows


def _dates(start: date, end_exclusive: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end_exclusive - start).days)]


def _write_once_model(path: Path, model: Any) -> str:
    payload = canonical_metadata_bytes(model) + b"\n"
    digest = hashlib.sha256(payload).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != payload:
            raise PublicationConflict(f"append-only evidence conflict at {path}")
        return digest
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
    return digest


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _require_rss_within_limit(
    config: Group1PipelineConfig,
    memory_budget: ProcessMemoryBudget,
    *,
    phase: str,
    arrow_inflight_bytes: int = 0,
) -> int:
    sample = memory_budget.check(phase, arrow_inflight_bytes=arrow_inflight_bytes)
    return sample.peak_rss_bytes


def _day_start_ns(owner_date: date) -> int:
    start = datetime(owner_date.year, owner_date.month, owner_date.day, tzinfo=UTC)
    return int(start.timestamp()) * 10**9


def _slice_event_time(table: pa.Table, start_ns: int, end_ns: int) -> pa.Table:
    if end_ns <= start_ns:
        raise ValueError("event-time slice must be non-empty")
    timestamps = table["event_ts_ns"]
    mask = pc.and_(pc.greater_equal(timestamps, start_ns), pc.less(timestamps, end_ns))
    return table.filter(mask)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


# Freeze the parameter registry at import time so an accidental later dynamic
# extension cannot silently alter the approved 20-set Group-1 matrix.
if len(parameter_sets()) != 20:  # pragma: no cover - governance tripwire
    raise RuntimeError("approved Group-1 parameter registry must contain exactly 20 sets")
