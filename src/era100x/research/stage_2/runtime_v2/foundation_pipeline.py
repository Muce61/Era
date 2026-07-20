"""Recoverable production builder for the immutable V2 Feature Foundation.

The pipeline deliberately keeps source discovery outside the build loop.  It
accepts only the two authoritative Stage 1 indexes, processes one UTC month at
a time, and writes one content-addressed object per non-empty
feature/instrument/month.  A source Trades day is decoded at most once in an
invocation; row-group routing reads footer metadata only.

The implementation is intentionally independent from the Group-1 adapter and
the Runtime V2 orchestrator.  It returns sealed catalog components for the
caller to publish after every expected month has reached a terminal checkpoint.
"""

from __future__ import annotations

import hashlib
import gc
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, Field, model_validator

from era100x.research.stage_2.manifests.models import canonical_json
from era100x.research.stage_2.pipelines.candidates.stage1_catalog import (
    Stage1TradesCatalogIndex,
    Stage1TradesPartition,
    sha256_file,
)

from .catalog import SealReducerV2
from .errors import ContractViolation, PublicationConflict
from .foundation_build import (
    aggregate_price_bars,
    aggregate_trade_seconds,
    normalize_contract_price_day,
)
from .foundation_sources import (
    ContractPriceInventoryIndex,
    ContractPricePartition,
    Instrument,
    trade_row_group_index,
)
from .foundation_specs import feature_foundation_dataset_specs
from .hashing import (
    canonical_arrow_schema,
    canonical_projection_hash,
    canonical_semantic_hash,
    normalize_table,
)
from .manifest_factory import (
    FOUNDATION_CONTEXT_ID,
    FOUNDATION_SETUP_ID,
    FOUNDATION_VARIANTS,
)
from .memory import ProcessMemoryBudget
from .models import (
    MAX_PROCESS_CURRENT_RSS_BYTES,
    MAX_PROCESS_RSS_DELTA_BYTES,
    SHA256_PATTERN,
    ZERO_SHA256,
    ArtifactRef,
    DatasetSpec,
    FragmentV2,
    FrozenModel,
    LogicalPartitionKey,
    QualityFact,
    Receipt,
    ShardSealV2,
    metadata_sha256,
)

DEFAULT_EXTERNAL_ROOT = Path("/Volumes/FuckingLife/era100x_stage2")
SINGLE_SOURCE_READER = 1
COMPUTE_WORKERS = 3
SINGLE_DETERMINISTIC_WRITER = 1
MAX_INFLIGHT_BYTES = 1 << 30
PACKED_LARGE_SHARD_DAYS = 60
ROW_GROUP_SIZE = 262_144
FEATURE_DATASET_NAMES = (
    "contract_price_1s",
    "causal_price_bars",
    "trade_second_primitives",
    "trade_row_group_index",
)
_PRICE_FEATURES = frozenset({"contract_price_1s", "causal_price_bars"})
_TRADE_FEATURES = frozenset({"trade_second_primitives", "trade_row_group_index"})
_LARGE_FEATURES = frozenset({"contract_price_1s", "trade_second_primitives"})
_SMALL_FEATURES = frozenset({"causal_price_bars", "trade_row_group_index"})
_DAY_NS = 86_400_000_000_000


class FoundationPipelineConfig(FrozenModel):
    """Fixed resource and output-root contract for the production builder."""

    run_root: Path
    approved_external_root: Path = DEFAULT_EXTERNAL_ROOT
    source_reader_count: Literal[1] = 1
    compute_worker_count: Literal[3] = 3
    deterministic_writer_count: Literal[1] = 1
    max_inflight_bytes: Literal[1_073_741_824] = 1_073_741_824
    max_process_current_rss_bytes: Literal[3_221_225_472] = MAX_PROCESS_CURRENT_RSS_BYTES
    max_process_rss_delta_bytes: Literal[1_073_741_824] = MAX_PROCESS_RSS_DELTA_BYTES
    row_group_size: Literal[262_144] = 262_144
    month_object_count_observation_threshold: Literal[79] = 79

    @model_validator(mode="after")
    def validate_external_root(self) -> Self:
        external = self.approved_external_root.resolve()
        run_root = self.run_root.resolve()
        if not external.is_dir():
            raise ValueError(f"approved Stage 2 external root is unavailable: {external}")
        if not run_root.is_relative_to(external):
            raise ValueError(
                "Feature Foundation run_root must remain on the approved external root"
            )
        if run_root == external:
            raise ValueError("Feature Foundation run_root must be a run-specific child directory")
        return self

    @property
    def catalog_root(self) -> Path:
        # Final packed Foundation and Group-1 objects share one
        # content-addressed snapshot root.  Intermediate monthly recovery
        # objects remain isolated below ``foundation/monthly-catalog`` and are
        # never referenced by the formal Catalog.
        return self.run_root / "staging" / "snapshot"

    @property
    def monthly_catalog_root(self) -> Path:
        """Intermediate sealed month objects; never exposed by the final Catalog."""

        return self.run_root / "staging" / "foundation" / "monthly-catalog"

    @property
    def checkpoint_root(self) -> Path:
        return self.run_root / "staging" / "foundation" / "checkpoints"

    @property
    def packed_checkpoint_root(self) -> Path:
        return self.run_root / "staging" / "foundation" / "packed-checkpoints"

    @property
    def seal_root(self) -> Path:
        return self.run_root / "staging" / "foundation" / "seals"

    @property
    def packed_seal_root(self) -> Path:
        return self.run_root / "staging" / "foundation" / "packed-seals"

    @property
    def partial_root(self) -> Path:
        return self.run_root / "staging" / "foundation" / "partials"


class FoundationSourceBinding(FrozenModel):
    owner_date: date
    source_kind: Literal["CONTRACT_PRICE", "STAGE1_TRADES"]
    relative_path: str = Field(min_length=1)
    byte_sha256: str = Field(pattern=SHA256_PATTERN)
    logical_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_source_kind(self) -> Self:
        if self.source_kind == "STAGE1_TRADES" and self.logical_sha256 is None:
            raise ValueError("Stage 1 Trades bindings require the Catalog logical hash")
        if self.source_kind == "CONTRACT_PRICE" and self.logical_sha256 is not None:
            raise ValueError("Contract Price bindings must not fabricate a logical hash")
        relative = PurePosixPath(self.relative_path)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("source binding path must be safe and relative")
        return self


class FoundationShardCheckpoint(FrozenModel):
    """Write-once terminal evidence for one feature/instrument/UTC month."""

    schema_name: Literal["stage2-v2-foundation-shard-checkpoint"] = (
        "stage2-v2-foundation-shard-checkpoint"
    )
    checkpoint_version: Literal["1.0"] = "1.0"
    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    dataset_name: str
    dataset_spec_hash: str = Field(pattern=SHA256_PATTERN)
    instrument: Instrument
    shard_key: str = Field(
        pattern=r"^[0-9]{4}-[0-9]{2}(?:-[0-9]{2})?(?:_[0-9]{4}-[0-9]{2}-[0-9]{2})?$"
    )
    storage_role: Literal["MONTHLY_INTERMEDIATE", "PACKED_FINAL"]
    window_start_date: date
    window_end_date_exclusive: date
    source_bindings: tuple[FoundationSourceBinding, ...] = Field(min_length=1)
    artifact: ArtifactRef | None
    receipts: tuple[Receipt, ...] = Field(min_length=1)
    fragments: tuple[FragmentV2, ...]
    seal: ShardSealV2
    seal_relative_path: str
    seal_file_sha256: str = Field(pattern=SHA256_PATTERN)
    source_reader_count: Literal[1] = 1
    compute_worker_count: Literal[3] = 3
    deterministic_writer_count: Literal[1] = 1
    max_inflight_bytes: Literal[1_073_741_824] = 1_073_741_824
    terminal_state: Literal["SEALED"] = "SEALED"
    checkpoint_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return metadata_sha256(self.model_dump(mode="json", exclude={"checkpoint_hash"}))

    @model_validator(mode="after")
    def validate_checkpoint(self) -> Self:
        if self.window_end_date_exclusive <= self.window_start_date:
            raise ValueError("foundation checkpoint window must be ordered")
        expected_dates = tuple(_dates(self.window_start_date, self.window_end_date_exclusive))
        binding_dates = tuple(item.owner_date for item in self.source_bindings)
        if binding_dates != expected_dates:
            raise ValueError("foundation source bindings must cover every owner day in order")
        receipt_dates = tuple(item.partition.owner_date for item in self.receipts)
        if receipt_dates != expected_dates:
            raise ValueError("foundation receipts must cover every owner day in order")
        if any(item.snapshot_id != self.snapshot_id for item in self.receipts):
            raise ValueError("foundation checkpoint mixes receipt snapshots")
        if any(
            item.partition.dataset_spec_hash != self.dataset_spec_hash for item in self.receipts
        ):
            raise ValueError("foundation checkpoint mixes dataset specifications")
        if any(item.partition.instrument != self.instrument for item in self.receipts):
            raise ValueError("foundation checkpoint mixes instruments")
        if self.artifact is None:
            if self.fragments or any(item.row_count for item in self.receipts):
                raise ValueError("artifact-free checkpoint must contain only empty receipts")
        else:
            if self.artifact.snapshot_id != self.snapshot_id:
                raise ValueError("foundation artifact snapshot mismatch")
            if self.artifact.dataset_spec_hash != self.dataset_spec_hash:
                raise ValueError("foundation artifact dataset mismatch")
            if sum(item.row_count for item in self.receipts) != self.artifact.row_count:
                raise ValueError("foundation artifact row count mismatch")
        if self.seal.snapshot_id != self.snapshot_id:
            raise ValueError("foundation seal snapshot mismatch")
        if self.seal.dataset_spec_hash != self.dataset_spec_hash:
            raise ValueError("foundation seal dataset mismatch")
        if self.seal.partition_count != len(self.receipts):
            raise ValueError("foundation seal does not cover every receipt")
        if self.checkpoint_hash != ZERO_SHA256 and self.checkpoint_hash != self.computed_hash():
            raise ValueError("foundation checkpoint hash mismatch")
        return self

    @classmethod
    def seal_checkpoint(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "checkpoint_hash": ZERO_SHA256})
        return provisional.model_copy(update={"checkpoint_hash": provisional.computed_hash()})


@dataclass(frozen=True, slots=True)
class FoundationPipelineResult:
    snapshot_id: str
    checkpoints: tuple[FoundationShardCheckpoint, ...]
    artifacts: tuple[ArtifactRef, ...]
    receipts: tuple[Receipt, ...]
    fragments: tuple[FragmentV2, ...]
    seals: tuple[ShardSealV2, ...]
    max_inflight_bytes_observed: int
    max_process_rss_bytes_observed: int
    contract_price_sha256_verification_counts: tuple[tuple[Instrument, date, int], ...]
    trade_decode_counts: tuple[tuple[Instrument, date, int], ...]
    trade_sha256_verification_counts: tuple[tuple[Instrument, date, int], ...]

    def object_count(self, dataset_name: str, instrument: Instrument) -> int:
        return sum(
            item.dataset_name == dataset_name
            and item.instrument == instrument
            and item.artifact is not None
            for item in self.checkpoints
        )


@dataclass(frozen=True, slots=True)
class _PreparedDay:
    key: LogicalPartitionKey
    table: pa.Table
    semantic_sha256: str
    identity_sha256: str
    payload_sha256: str


@dataclass(frozen=True, slots=True)
class _DayDigest:
    key: LogicalPartitionKey
    row_count: int
    row_offset: int
    semantic_sha256: str
    identity_sha256: str
    payload_sha256: str


class _InflightBudget:
    def __init__(
        self,
        limit: int,
        *,
        process_memory: ProcessMemoryBudget | None = None,
    ) -> None:
        self.limit = limit
        self.observed = 0
        self.process_memory = process_memory or ProcessMemoryBudget()

    def check(self, tables: tuple[pa.Table, ...]) -> None:
        current = sum(table.nbytes for table in tables)
        self.observed = max(self.observed, current)
        self.process_memory.check("Feature Foundation", arrow_inflight_bytes=current)

    @property
    def rss_observed(self) -> int:
        return self.process_memory.max_peak_rss_bytes_observed


class FoundationSourceReader:
    """Single-threaded adapter over the two already-authorized source indexes."""

    def __init__(
        self,
        *,
        trades_index: Stage1TradesCatalogIndex,
        contract_price_index: ContractPriceInventoryIndex,
    ) -> None:
        self.trades_index = trades_index
        self.contract_price_index = contract_price_index
        self._owner_thread = threading.get_ident()
        self._trade_by_key: dict[tuple[Instrument, date], Stage1TradesPartition] = {}
        for partition in trades_index.partitions:
            key = (partition.instrument, partition.partition_date)
            if key in self._trade_by_key:
                raise ValueError(f"duplicate Stage 1 Trades authority: {key}")
            if not partition.path.is_absolute() or not partition.path.is_relative_to(
                trades_index.published_root
            ):
                raise ValueError("Stage 1 Trades authority escapes the frozen published root")
            self._trade_by_key[key] = partition
        self._trade_decode_counts: dict[tuple[Instrument, date], int] = {}
        self._price_sha256_verification_counts: dict[tuple[Instrument, date], int] = {}
        self._verified_price_partitions: set[tuple[Instrument, date]] = set()
        self._trade_sha256_verification_counts: dict[tuple[Instrument, date], int] = {}
        self._verified_trade_partitions: set[tuple[Instrument, date]] = set()

    @property
    def trade_decode_counts(self) -> tuple[tuple[Instrument, date, int], ...]:
        return tuple(
            (instrument, owner_date, count)
            for (instrument, owner_date), count in sorted(self._trade_decode_counts.items())
        )

    @property
    def contract_price_sha256_verification_counts(
        self,
    ) -> tuple[tuple[Instrument, date, int], ...]:
        return tuple(
            (instrument, owner_date, count)
            for (instrument, owner_date), count in sorted(
                self._price_sha256_verification_counts.items()
            )
        )

    @property
    def trade_sha256_verification_counts(self) -> tuple[tuple[Instrument, date, int], ...]:
        return tuple(
            (instrument, owner_date, count)
            for (instrument, owner_date), count in sorted(
                self._trade_sha256_verification_counts.items()
            )
        )

    def price_partition(self, instrument: Instrument, owner_date: date) -> ContractPricePartition:
        return self.contract_price_index.get(instrument, owner_date)

    def trade_partition(self, instrument: Instrument, owner_date: date) -> Stage1TradesPartition:
        try:
            return self._trade_by_key[(instrument, owner_date)]
        except KeyError as exc:
            raise FileNotFoundError(
                f"Stage 1 Trades coverage missing: {instrument} {owner_date.isoformat()}"
            ) from exc

    def read_price(self, instrument: Instrument, owner_date: date) -> pa.Table:
        self._assert_reader_thread()
        partition = self._verify_price_partition_once(instrument, owner_date)
        table = normalize_contract_price_day(
            path=partition.path,
            instrument=instrument,
            expected_source_sha256=partition.byte_sha256,
        )
        source_hashes = pc.unique(table["source_file_sha256"])
        if table.num_rows and (
            len(source_hashes) != 1 or source_hashes[0].as_py() != partition.byte_sha256
        ):
            raise ValueError("Contract Price bytes changed after inventory approval")
        return table

    def _verify_price_partition_once(
        self, instrument: Instrument, owner_date: date
    ) -> ContractPricePartition:
        key = (instrument, owner_date)
        partition = self.price_partition(instrument, owner_date)
        if key in self._verified_price_partitions:
            return partition
        verification_count = self._price_sha256_verification_counts.get(key, 0) + 1
        self._price_sha256_verification_counts[key] = verification_count
        if verification_count != 1:
            raise RuntimeError(f"Contract Price day SHA verified more than once: {key}")
        source = partition.path.resolve()
        if not source.is_relative_to(self.contract_price_index.root) or not source.is_file():
            raise ValueError("Contract Price path escapes the frozen inventory root")
        if source.stat().st_size != partition.byte_size or sha256_file(source) != (
            partition.byte_sha256
        ):
            raise ValueError("Contract Price bytes changed after inventory approval")
        self._verified_price_partitions.add(key)
        return partition

    def read_trade_seconds(self, instrument: Instrument, owner_date: date) -> pa.Table:
        self._assert_reader_thread()
        key = (instrument, owner_date)
        partition = self._verify_trade_partition_once(instrument, owner_date)
        count = self._trade_decode_counts.get(key, 0) + 1
        self._trade_decode_counts[key] = count
        if count != 1:
            raise RuntimeError(f"Stage 1 Trades day decoded more than once: {key}")
        return aggregate_trade_seconds(
            path=partition.path,
            instrument=instrument,
            source_logical_hash=partition.logical_sha256,
        )

    def read_trade_row_groups(self, instrument: Instrument, owner_date: date) -> pa.Table:
        self._assert_reader_thread()
        self._verify_trade_partition_once(instrument, owner_date)
        return trade_row_group_index(
            self.trade_partition(instrument, owner_date),
            published_root=self.trades_index.published_root,
        )

    def _verify_trade_partition_once(
        self, instrument: Instrument, owner_date: date
    ) -> Stage1TradesPartition:
        key = (instrument, owner_date)
        partition = self.trade_partition(instrument, owner_date)
        if key in self._verified_trade_partitions:
            return partition
        verification_count = self._trade_sha256_verification_counts.get(key, 0) + 1
        self._trade_sha256_verification_counts[key] = verification_count
        if verification_count != 1:
            raise RuntimeError(f"Stage 1 Trades day SHA verified more than once: {key}")
        # The Catalog byte SHA is checked immediately before the first footer
        # or row decode, so no unverified source can produce any sealed
        # primitive.  Polars does not expose a hash callback for its seekable
        # Parquet reader; this is two logical passes that may benefit from the
        # OS page cache, not a claimed single-pass physical read.
        if sha256_file(partition.path) != partition.byte_sha256:
            raise ValueError(f"Stage 1 Trades physical byte hash changed: {key}")
        self._verified_trade_partitions.add(key)
        return partition

    def _assert_reader_thread(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("Feature Foundation source reads require the single reader thread")


class _ShardObjectWriter:
    """Single-threaded, bounded-memory writer for one intermediate or final shard."""

    def __init__(
        self,
        *,
        config: FoundationPipelineConfig,
        spec: DatasetSpec,
        snapshot_id: str,
        instrument: Instrument,
        shard_key: str,
        window_start: date,
        window_end_exclusive: date,
        storage_role: Literal["MONTHLY_INTERMEDIATE", "PACKED_FINAL"],
    ) -> None:
        self.config = config
        self.spec = spec
        self.snapshot_id = snapshot_id
        self.instrument = instrument
        self.shard_key = shard_key
        self.window_start = window_start
        self.window_end_exclusive = window_end_exclusive
        self.storage_role = storage_role
        self.catalog_root = (
            config.monthly_catalog_root
            if storage_role == "MONTHLY_INTERMEDIATE"
            else config.catalog_root
        )
        self._owner_thread = threading.get_ident()
        self._writer: pq.ParquetWriter | None = None
        self._rows = 0
        self._days: list[_DayDigest] = []
        partial_directory = config.partial_root / instrument / spec.dataset_name
        partial_directory.mkdir(parents=True, exist_ok=True)
        self.partial_path = partial_directory / (f"{shard_key}.{uuid.uuid4().hex}.parquet.partial")

    def append(self, prepared: _PreparedDay) -> None:
        self._assert_writer_thread()
        if not self.window_start <= prepared.key.owner_date < self.window_end_exclusive:
            raise ValueError("prepared owner day does not belong to the active shard window")
        if prepared.key.instrument != self.instrument:
            raise ValueError("prepared day belongs to another instrument")
        if prepared.key.dataset_spec_hash != self.spec.spec_hash:
            raise ValueError("prepared day belongs to another DatasetSpec")
        row_offset = self._rows
        if prepared.table.num_rows:
            if self._writer is None:
                self._writer = pq.ParquetWriter(
                    self.partial_path,
                    canonical_arrow_schema(self.spec),
                    compression="zstd",
                    write_statistics=True,
                )
            self._writer.write_table(prepared.table, row_group_size=self.config.row_group_size)
            self._rows += prepared.table.num_rows
        self._days.append(
            _DayDigest(
                key=prepared.key,
                row_count=prepared.table.num_rows,
                row_offset=row_offset,
                semantic_sha256=prepared.semantic_sha256,
                identity_sha256=prepared.identity_sha256,
                payload_sha256=prepared.payload_sha256,
            )
        )

    def finalize(
        self,
        *,
        source_bindings: tuple[FoundationSourceBinding, ...],
        window_start: date,
        window_end_exclusive: date,
    ) -> FoundationShardCheckpoint:
        self._assert_writer_thread()
        if self._writer is not None:
            self._writer.close()
            self._writer = None
            with self.partial_path.open("rb") as stream:
                os.fsync(stream.fileno())
        expected_dates = tuple(_dates(window_start, window_end_exclusive))
        if tuple(item.key.owner_date for item in self._days) != expected_dates:
            raise ValueError("month writer did not receive every owner day in order")

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
                        "dataset_spec_hash": self.spec.spec_hash,
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

        shard_id = _shard_id(self.spec.dataset_name, self.instrument, self.shard_key)
        quality = (
            QualityFact(name="available_at_causal", value=True),
            QualityFact(name="source_authority_complete", value=True),
        )
        receipts: list[Receipt] = []
        for day in self._days:
            current_fragment = fragment_by_partition.get(day.key.partition_id)
            receipts.append(
                Receipt.seal(
                    {
                        "snapshot_id": self.snapshot_id,
                        "shard_id": shard_id,
                        "partition": day.key,
                        "terminal_state": "PRESENT" if day.row_count else "EMPTY",
                        "row_count": day.row_count,
                        "legacy_hash_algorithm": "NOT_APPLICABLE",
                        "legacy_logical_sha256": None,
                        "semantic_sha256": day.semantic_sha256,
                        "identity_multiset_sha256": day.identity_sha256,
                        "payload_association_sha256": day.payload_sha256,
                        "quality_facts": quality,
                        "fragment_hashes": ()
                        if current_fragment is None
                        else (current_fragment.fragment_hash,),
                    }
                )
            )
        seal = SealReducerV2.reduce(
            snapshot_id=self.snapshot_id,
            dataset_spec_hash=self.spec.spec_hash,
            shard_id=shard_id,
            receipts=receipts,
        )
        seal_relative_path = _seal_relative_path(
            self.spec.dataset_name,
            self.instrument,
            self.shard_key,
            storage_role=self.storage_role,
        )
        seal_path = self.config.run_root / seal_relative_path
        seal_file_sha256 = _write_once_model(seal_path, seal)
        checkpoint = FoundationShardCheckpoint.seal_checkpoint(
            {
                "snapshot_id": self.snapshot_id,
                "dataset_name": self.spec.dataset_name,
                "dataset_spec_hash": self.spec.spec_hash,
                "instrument": self.instrument,
                "shard_key": self.shard_key,
                "storage_role": self.storage_role,
                "window_start_date": window_start,
                "window_end_date_exclusive": window_end_exclusive,
                "source_bindings": source_bindings,
                "artifact": artifact,
                "receipts": tuple(receipts),
                "fragments": tuple(fragments),
                "seal": seal,
                "seal_relative_path": seal_relative_path,
                "seal_file_sha256": seal_file_sha256,
            }
        )
        checkpoint_path = _checkpoint_path(
            self.config,
            self.spec.dataset_name,
            self.instrument,
            self.shard_key,
            storage_role=self.storage_role,
        )
        _write_once_model(checkpoint_path, checkpoint)
        return checkpoint

    def close_after_failure(self) -> None:
        """Close the partial writer without deleting audit-relevant staging bytes."""

        if self._writer is not None:
            self._writer.close()
            self._writer = None

    def _publish_artifact(self) -> ArtifactRef | None:
        if not self._rows:
            return None
        if not self.partial_path.is_file():
            raise FileNotFoundError("non-empty Foundation shard is missing its partial object")
        physical_sha256 = _sha256_file(self.partial_path)
        byte_size = self.partial_path.stat().st_size
        relative_path = f"objects/{physical_sha256[:2]}/{physical_sha256}.parquet"
        target = self.catalog_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.stat().st_size != byte_size or _sha256_file(target) != physical_sha256:
                raise PublicationConflict(f"Foundation object conflict at {target}")
        else:
            os.replace(self.partial_path, target)
            _fsync_directory(target.parent)
        semantic_sha256 = metadata_sha256(
            {
                "domain": "stage2-v2-foundation-month-object",
                "members": tuple(
                    (item.key.partition_id, item.semantic_sha256)
                    for item in self._days
                    if item.row_count
                ),
            }
        )
        return ArtifactRef(
            snapshot_id=self.snapshot_id,
            dataset_spec_hash=self.spec.spec_hash,
            object_sha256=physical_sha256,
            relative_path=relative_path,
            byte_size=byte_size,
            row_count=self._rows,
            semantic_sha256=semantic_sha256,
        )

    def _assert_writer_thread(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("Foundation output requires the single deterministic writer thread")


class FeatureFoundationPipeline:
    """Build monthly recovery evidence, then expose only packed final shards."""

    def __init__(
        self,
        *,
        config: FoundationPipelineConfig,
        snapshot_id: str,
        trades_index: Stage1TradesCatalogIndex,
        contract_price_index: ContractPriceInventoryIndex,
        source_reader: FoundationSourceReader | None = None,
    ) -> None:
        if len(snapshot_id) != 64 or any(
            character not in "0123456789abcdef" for character in snapshot_id
        ):
            raise ValueError("snapshot_id must be lowercase SHA-256")
        self.config = config
        self.snapshot_id = snapshot_id
        self.specs = {spec.dataset_name: spec for spec in feature_foundation_dataset_specs()}
        if tuple(sorted(self.specs)) != tuple(sorted(FEATURE_DATASET_NAMES)):
            raise ValueError("Feature Foundation DatasetSpec registry is incomplete")
        self.reader = source_reader or FoundationSourceReader(
            trades_index=trades_index,
            contract_price_index=contract_price_index,
        )
        if self.reader.trades_index is not trades_index:
            raise ValueError("injected source reader is bound to another Trades index")
        if self.reader.contract_price_index is not contract_price_index:
            raise ValueError("injected source reader is bound to another Contract Price index")

    def build(
        self,
        *,
        instruments: tuple[Instrument, ...],
        start: date,
        end_exclusive: date,
    ) -> FoundationPipelineResult:
        if end_exclusive <= start:
            raise ValueError("Feature Foundation period must be non-empty")
        if not instruments or tuple(sorted(set(instruments))) != instruments:
            raise ValueError("instruments must be unique and deterministically ordered")
        if any(item not in {"BTCUSDT", "ETHUSDT"} for item in instruments):
            raise ValueError("Feature Foundation supports only BTCUSDT and ETHUSDT")
        months = tuple(_month_windows(start, end_exclusive))
        process_memory = ProcessMemoryBudget(
            current_limit_bytes=self.config.max_process_current_rss_bytes,
            delta_limit_bytes=self.config.max_process_rss_delta_bytes,
        )
        process_memory.observe_threshold(
            category="OBJECT_COUNT",
            phase="Feature Foundation planning",
            metric_name="MONTH_OBJECTS_PER_FEATURE_INSTRUMENT",
            threshold=self.config.month_object_count_observation_threshold,
            observed=len(months),
            unit="objects",
        )

        # These are authoritative coverage checks.  No filesystem discovery occurs here.
        for instrument in instruments:
            for owner_date in _dates(start, end_exclusive):
                self.reader.price_partition(instrument, owner_date)
                self.reader.trade_partition(instrument, owner_date)

        monthly_checkpoints: list[FoundationShardCheckpoint] = []
        budget = _InflightBudget(
            self.config.max_inflight_bytes,
            process_memory=process_memory,
        )
        with ThreadPoolExecutor(
            max_workers=self.config.compute_worker_count,
            thread_name_prefix="stage2-v2-foundation-compute",
        ) as compute_pool:
            for instrument in instruments:
                for month, month_start, month_end in months:
                    monthly_checkpoints.extend(
                        self._build_month(
                            instrument=instrument,
                            utc_month=month,
                            start=month_start,
                            end_exclusive=month_end,
                            compute_pool=compute_pool,
                            budget=budget,
                        )
                    )
            packed_checkpoints = self._pack_final_shards(
                instruments=instruments,
                start=start,
                end_exclusive=end_exclusive,
                monthly_checkpoints=tuple(monthly_checkpoints),
                compute_pool=compute_pool,
                budget=budget,
            )

        ordered = tuple(
            sorted(
                packed_checkpoints,
                key=lambda item: (item.instrument, item.dataset_name, item.shard_key),
            )
        )
        for dataset_name in FEATURE_DATASET_NAMES:
            for instrument in instruments:
                count = sum(
                    item.dataset_name == dataset_name
                    and item.instrument == instrument
                    and item.artifact is not None
                    for item in ordered
                )
                expected_cap = (
                    _ceil_days(start, end_exclusive, PACKED_LARGE_SHARD_DAYS)
                    if dataset_name in _LARGE_FEATURES
                    else 1
                )
                budget.process_memory.observe_threshold(
                    category="OBJECT_COUNT",
                    phase="Feature Foundation packing",
                    metric_name=f"{dataset_name}:{instrument}:PACKED_OBJECT_COUNT",
                    threshold=expected_cap,
                    observed=count,
                    unit="objects",
                )
        planned_cap = planned_packed_object_count(
            start=start,
            end_exclusive=end_exclusive,
            instrument_count=len(instruments),
        )
        budget.process_memory.observe_threshold(
            category="OBJECT_COUNT",
            phase="Feature Foundation packing",
            metric_name="FOUNDATION_PACKED_OBJECT_COUNT",
            threshold=planned_cap,
            observed=sum(item.artifact is not None for item in ordered),
            unit="objects",
        )
        budget.process_memory.observe_threshold(
            category="OBJECT_COUNT",
            phase="Feature Foundation capacity plan",
            metric_name="FOUNDATION_PLANNED_OBJECT_COUNT",
            threshold=164,
            observed=planned_cap,
            unit="objects",
        )
        artifacts_by_hash = {
            item.artifact.object_sha256: item.artifact
            for item in ordered
            if item.artifact is not None
        }
        return FoundationPipelineResult(
            snapshot_id=self.snapshot_id,
            checkpoints=ordered,
            artifacts=tuple(artifacts_by_hash[key] for key in sorted(artifacts_by_hash)),
            receipts=tuple(receipt for item in ordered for receipt in item.receipts),
            fragments=tuple(fragment for item in ordered for fragment in item.fragments),
            seals=tuple(sorted((item.seal for item in ordered), key=lambda item: item.seal_hash)),
            max_inflight_bytes_observed=budget.observed,
            max_process_rss_bytes_observed=budget.rss_observed,
            contract_price_sha256_verification_counts=(
                self.reader.contract_price_sha256_verification_counts
            ),
            trade_decode_counts=self.reader.trade_decode_counts,
            trade_sha256_verification_counts=self.reader.trade_sha256_verification_counts,
        )

    def _build_month(
        self,
        *,
        instrument: Instrument,
        utc_month: str,
        start: date,
        end_exclusive: date,
        compute_pool: ThreadPoolExecutor,
        budget: _InflightBudget,
    ) -> tuple[FoundationShardCheckpoint, ...]:
        bindings = {
            dataset_name: self._source_bindings(dataset_name, instrument, start, end_exclusive)
            for dataset_name in FEATURE_DATASET_NAMES
        }
        completed: dict[str, FoundationShardCheckpoint] = {}
        missing: list[str] = []
        for dataset_name in FEATURE_DATASET_NAMES:
            checkpoint_path = _checkpoint_path(
                self.config,
                dataset_name,
                instrument,
                utc_month,
                storage_role="MONTHLY_INTERMEDIATE",
            )
            if checkpoint_path.exists():
                completed[dataset_name] = self._read_and_verify_checkpoint(
                    path=checkpoint_path,
                    spec=self.specs[dataset_name],
                    instrument=instrument,
                    shard_key=utc_month,
                    storage_role="MONTHLY_INTERMEDIATE",
                    start=start,
                    end_exclusive=end_exclusive,
                    source_bindings=bindings[dataset_name],
                )
            else:
                missing.append(dataset_name)
        if not missing:
            return tuple(completed[name] for name in FEATURE_DATASET_NAMES)

        writers = {
            dataset_name: _ShardObjectWriter(
                config=self.config,
                spec=self.specs[dataset_name],
                snapshot_id=self.snapshot_id,
                instrument=instrument,
                shard_key=utc_month,
                window_start=start,
                window_end_exclusive=end_exclusive,
                storage_role="MONTHLY_INTERMEDIATE",
            )
            for dataset_name in missing
        }
        try:
            for owner_date in _dates(start, end_exclusive):
                if _PRICE_FEATURES.intersection(missing):
                    prices = self.reader.read_price(instrument, owner_date)
                    budget.check((prices,))
                    if "contract_price_1s" in writers:
                        _prepare_and_append(
                            writer=writers["contract_price_1s"],
                            table=prices,
                            spec=self.specs["contract_price_1s"],
                            snapshot_id=self.snapshot_id,
                            instrument=instrument,
                            owner_date=owner_date,
                            compute_pool=compute_pool,
                            budget=budget,
                        )
                    if "causal_price_bars" in missing:
                        bars = compute_pool.submit(aggregate_price_bars, prices).result()
                        budget.check((prices, bars))
                        _prepare_and_append(
                            writer=writers["causal_price_bars"],
                            table=bars,
                            spec=self.specs["causal_price_bars"],
                            snapshot_id=self.snapshot_id,
                            instrument=instrument,
                            owner_date=owner_date,
                            compute_pool=compute_pool,
                            budget=budget,
                        )
                        del bars
                    del prices
                    _release_columnar_memory()
                if _TRADE_FEATURES.intersection(missing):
                    row_groups = self.reader.read_trade_row_groups(instrument, owner_date)
                    budget.check((row_groups,))
                    expected_rows = cast(int | None, pc.sum(row_groups["row_count"]).as_py())
                    if "trade_row_group_index" in writers:
                        _prepare_and_append(
                            writer=writers["trade_row_group_index"],
                            table=row_groups,
                            spec=self.specs["trade_row_group_index"],
                            snapshot_id=self.snapshot_id,
                            instrument=instrument,
                            owner_date=owner_date,
                            compute_pool=compute_pool,
                            budget=budget,
                        )
                    del row_groups
                    _release_columnar_memory()
                    if "trade_second_primitives" in missing:
                        trade_seconds = self.reader.read_trade_seconds(instrument, owner_date)
                        actual_rows = cast(int | None, pc.sum(trade_seconds["trade_count"]).as_py())
                        if (expected_rows or 0) != (actual_rows or 0):
                            raise ValueError("Trades decode row count differs from Parquet footer")
                        _prepare_and_append(
                            writer=writers["trade_second_primitives"],
                            table=trade_seconds,
                            spec=self.specs["trade_second_primitives"],
                            snapshot_id=self.snapshot_id,
                            instrument=instrument,
                            owner_date=owner_date,
                            compute_pool=compute_pool,
                            budget=budget,
                        )
                        del trade_seconds
                        _release_columnar_memory()

            for dataset_name in FEATURE_DATASET_NAMES:
                writer = writers.get(dataset_name)
                if writer is None:
                    continue
                completed[dataset_name] = writer.finalize(
                    source_bindings=bindings[dataset_name],
                    window_start=start,
                    window_end_exclusive=end_exclusive,
                )
        except BaseException:
            for writer in writers.values():
                writer.close_after_failure()
            raise
        return tuple(completed[name] for name in FEATURE_DATASET_NAMES)

    def _pack_final_shards(
        self,
        *,
        instruments: tuple[Instrument, ...],
        start: date,
        end_exclusive: date,
        monthly_checkpoints: tuple[FoundationShardCheckpoint, ...],
        compute_pool: ThreadPoolExecutor,
        budget: _InflightBudget,
    ) -> tuple[FoundationShardCheckpoint, ...]:
        by_dataset_instrument: dict[tuple[str, Instrument], list[FoundationShardCheckpoint]] = {}
        for checkpoint in monthly_checkpoints:
            if checkpoint.storage_role != "MONTHLY_INTERMEDIATE":
                raise ContractViolation("packed input must be a monthly intermediate checkpoint")
            key = (checkpoint.dataset_name, checkpoint.instrument)
            by_dataset_instrument.setdefault(key, []).append(checkpoint)

        packed: list[FoundationShardCheckpoint] = []
        for instrument in instruments:
            for dataset_name in FEATURE_DATASET_NAMES:
                monthly = tuple(
                    sorted(
                        by_dataset_instrument.get((dataset_name, instrument), []),
                        key=lambda item: item.window_start_date,
                    )
                )
                expected_months = tuple(_month_windows(start, end_exclusive))
                if (
                    tuple(
                        (
                            item.shard_key,
                            item.window_start_date,
                            item.window_end_date_exclusive,
                        )
                        for item in monthly
                    )
                    != expected_months
                ):
                    raise ContractViolation(
                        "monthly recovery evidence is incomplete before packing"
                    )
                packed.extend(
                    self._pack_dataset(
                        instrument=instrument,
                        dataset_name=dataset_name,
                        start=start,
                        end_exclusive=end_exclusive,
                        monthly=monthly,
                        compute_pool=compute_pool,
                        budget=budget,
                    )
                )
        return tuple(packed)

    def _pack_dataset(
        self,
        *,
        instrument: Instrument,
        dataset_name: str,
        start: date,
        end_exclusive: date,
        monthly: tuple[FoundationShardCheckpoint, ...],
        compute_pool: ThreadPoolExecutor,
        budget: _InflightBudget,
    ) -> tuple[FoundationShardCheckpoint, ...]:
        spec = self.specs[dataset_name]
        windows = (
            tuple(_fixed_day_windows(start, end_exclusive, PACKED_LARGE_SHARD_DAYS))
            if dataset_name in _LARGE_FEATURES
            else ((start, end_exclusive),)
        )
        completed: dict[str, FoundationShardCheckpoint] = {}
        writers: dict[str, _ShardObjectWriter] = {}
        window_by_date: dict[date, tuple[str, date, date]] = {}
        for window_start, window_end in windows:
            shard_key = _packed_shard_key(window_start, window_end)
            bindings = self._source_bindings(dataset_name, instrument, window_start, window_end)
            path = _checkpoint_path(
                self.config,
                dataset_name,
                instrument,
                shard_key,
                storage_role="PACKED_FINAL",
            )
            if path.exists():
                completed[shard_key] = self._read_and_verify_checkpoint(
                    path=path,
                    spec=spec,
                    instrument=instrument,
                    shard_key=shard_key,
                    storage_role="PACKED_FINAL",
                    start=window_start,
                    end_exclusive=window_end,
                    source_bindings=bindings,
                )
            else:
                writers[shard_key] = _ShardObjectWriter(
                    config=self.config,
                    spec=spec,
                    snapshot_id=self.snapshot_id,
                    instrument=instrument,
                    shard_key=shard_key,
                    window_start=window_start,
                    window_end_exclusive=window_end,
                    storage_role="PACKED_FINAL",
                )
            for owner_date in _dates(window_start, window_end):
                window_by_date[owner_date] = (shard_key, window_start, window_end)
        if not writers:
            return tuple(completed[_packed_shard_key(*window)] for window in windows)

        try:
            for checkpoint in monthly:
                monthly_table = self._read_intermediate_object(checkpoint, spec)
                budget.check((monthly_table,))
                fragments = {fragment.partition_id: fragment for fragment in checkpoint.fragments}
                for receipt in checkpoint.receipts:
                    owner_date = receipt.partition.owner_date
                    shard_key, _window_start, _window_end = window_by_date[owner_date]
                    if shard_key not in writers:
                        continue
                    fragment = fragments.get(receipt.partition.partition_id)
                    if fragment is None:
                        if receipt.row_count:
                            raise ContractViolation("monthly receipt lost its physical fragment")
                        table = _empty_table(spec)
                    else:
                        table = monthly_table.slice(fragment.row_offset, fragment.row_count)
                    prepared = compute_pool.submit(
                        _prepare_day,
                        table,
                        spec,
                        self.snapshot_id,
                        instrument,
                        owner_date,
                    ).result()
                    budget.check((monthly_table, prepared.table))
                    if (
                        prepared.semantic_sha256 != receipt.semantic_sha256
                        or prepared.identity_sha256 != receipt.identity_multiset_sha256
                        or prepared.payload_sha256 != receipt.payload_association_sha256
                        or prepared.table.num_rows != receipt.row_count
                    ):
                        raise ContractViolation(
                            "monthly recovery object changed before final packing"
                        )
                    shard_key, _window_start, _window_end = window_by_date[
                        receipt.partition.owner_date
                    ]
                    writers[shard_key].append(prepared)
                    del prepared, table
                del monthly_table
                _release_columnar_memory()

            for window_start, window_end in windows:
                shard_key = _packed_shard_key(window_start, window_end)
                writer = writers.get(shard_key)
                if writer is None:
                    continue
                completed[shard_key] = writer.finalize(
                    source_bindings=self._source_bindings(
                        dataset_name, instrument, window_start, window_end
                    ),
                    window_start=window_start,
                    window_end_exclusive=window_end,
                )
        except BaseException:
            for writer in writers.values():
                writer.close_after_failure()
            raise
        return tuple(completed[_packed_shard_key(*window)] for window in windows)

    def _read_intermediate_object(
        self,
        checkpoint: FoundationShardCheckpoint,
        spec: DatasetSpec,
    ) -> pa.Table:
        if checkpoint.artifact is None:
            return _empty_table(spec)
        path = self.config.monthly_catalog_root / checkpoint.artifact.relative_path
        table = pq.read_table(path)
        expected = canonical_arrow_schema(spec)
        if not table.schema.equals(expected, check_metadata=False):
            raise ContractViolation("monthly recovery object schema changed")
        if table.num_rows != checkpoint.artifact.row_count:
            raise ContractViolation("monthly recovery object row count changed")
        return table.combine_chunks()

    def _source_bindings(
        self,
        dataset_name: str,
        instrument: Instrument,
        start: date,
        end_exclusive: date,
    ) -> tuple[FoundationSourceBinding, ...]:
        bindings: list[FoundationSourceBinding] = []
        for owner_date in _dates(start, end_exclusive):
            if dataset_name in _PRICE_FEATURES:
                price_partition = self.reader.price_partition(instrument, owner_date)
                relative_path = price_partition.path.relative_to(
                    self.reader.contract_price_index.root
                ).as_posix()
                bindings.append(
                    FoundationSourceBinding(
                        owner_date=owner_date,
                        source_kind="CONTRACT_PRICE",
                        relative_path=relative_path,
                        byte_sha256=price_partition.byte_sha256,
                        logical_sha256=None,
                    )
                )
            elif dataset_name in _TRADE_FEATURES:
                trade_partition = self.reader.trade_partition(instrument, owner_date)
                relative_path = trade_partition.path.relative_to(
                    self.reader.trades_index.published_root
                ).as_posix()
                bindings.append(
                    FoundationSourceBinding(
                        owner_date=owner_date,
                        source_kind="STAGE1_TRADES",
                        relative_path=relative_path,
                        byte_sha256=trade_partition.byte_sha256,
                        logical_sha256=trade_partition.logical_sha256,
                    )
                )
            else:
                raise ValueError(f"unknown Feature Foundation dataset: {dataset_name}")
        return tuple(bindings)

    def _read_and_verify_checkpoint(
        self,
        *,
        path: Path,
        spec: DatasetSpec,
        instrument: Instrument,
        shard_key: str,
        storage_role: Literal["MONTHLY_INTERMEDIATE", "PACKED_FINAL"],
        start: date,
        end_exclusive: date,
        source_bindings: tuple[FoundationSourceBinding, ...],
    ) -> FoundationShardCheckpoint:
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"Foundation checkpoint is unavailable: {path}")
        checkpoint = FoundationShardCheckpoint.model_validate_json(path.read_bytes())
        if (
            checkpoint.snapshot_id != self.snapshot_id
            or checkpoint.dataset_name != spec.dataset_name
            or checkpoint.dataset_spec_hash != spec.spec_hash
            or checkpoint.instrument != instrument
            or checkpoint.shard_key != shard_key
            or checkpoint.storage_role != storage_role
            or checkpoint.window_start_date != start
            or checkpoint.window_end_date_exclusive != end_exclusive
            or checkpoint.source_bindings != source_bindings
        ):
            raise ContractViolation("Foundation checkpoint authority changed; resume is forbidden")
        seal_path = self.config.run_root / checkpoint.seal_relative_path
        if not seal_path.is_file() or seal_path.is_symlink():
            raise FileNotFoundError("Foundation checkpoint seal evidence is missing")
        seal_bytes = seal_path.read_bytes()
        if hashlib.sha256(seal_bytes).hexdigest() != checkpoint.seal_file_sha256:
            raise ContractViolation("Foundation checkpoint seal bytes changed")
        if ShardSealV2.model_validate_json(seal_bytes) != checkpoint.seal:
            raise ContractViolation("Foundation checkpoint seal payload changed")
        recomputed_seal = SealReducerV2.reduce(
            snapshot_id=self.snapshot_id,
            dataset_spec_hash=spec.spec_hash,
            shard_id=checkpoint.seal.shard_id,
            receipts=checkpoint.receipts,
        )
        if recomputed_seal != checkpoint.seal:
            raise ContractViolation("Foundation checkpoint seal reduction changed")
        artifact = checkpoint.artifact
        if artifact is not None:
            artifact_root = (
                self.config.monthly_catalog_root
                if storage_role == "MONTHLY_INTERMEDIATE"
                else self.config.catalog_root
            )
            object_path = artifact_root / artifact.relative_path
            if (
                not object_path.is_file()
                or object_path.is_symlink()
                or object_path.stat().st_size != artifact.byte_size
                or _sha256_file(object_path) != artifact.object_sha256
            ):
                raise ContractViolation("sealed Foundation object changed before resume")
        for fragment in checkpoint.fragments:
            if artifact is None or fragment.artifact != artifact:
                raise ContractViolation("Foundation checkpoint fragment/artifact mismatch")
        return checkpoint


def _prepare_day(
    table: pa.Table,
    spec: DatasetSpec,
    snapshot_id: str,
    instrument: Instrument,
    owner_date: date,
) -> _PreparedDay:
    normalized = normalize_table(table, spec)
    _validate_day_ownership(normalized, spec, owner_date)
    key = LogicalPartitionKey(
        snapshot_id=snapshot_id,
        dataset_name=spec.dataset_name,
        dataset_version=spec.dataset_version,
        dataset_spec_hash=spec.spec_hash,
        setup_id=FOUNDATION_SETUP_ID,
        context_id=FOUNDATION_CONTEXT_ID,
        instrument=instrument,
        variant=FOUNDATION_VARIANTS[spec.dataset_name],
        owner_date=owner_date,
    )
    return _PreparedDay(
        key=key,
        table=normalized,
        semantic_sha256=canonical_semantic_hash(normalized, spec),
        identity_sha256=canonical_projection_hash(
            normalized,
            spec,
            projection_fields=spec.identity_fields,
            sort_fields=spec.identity_fields,
            domain="identity-multiset",
            require_unique=False,
        ),
        payload_sha256=canonical_projection_hash(
            normalized,
            spec,
            projection_fields=spec.payload_association_fields,
            sort_fields=spec.stable_sort_keys,
            domain="identity-payload-association",
            require_unique=True,
        ),
    )


def _prepare_and_append(
    *,
    writer: _ShardObjectWriter,
    table: pa.Table,
    spec: DatasetSpec,
    snapshot_id: str,
    instrument: Instrument,
    owner_date: date,
    compute_pool: ThreadPoolExecutor,
    budget: _InflightBudget,
) -> None:
    budget.check((table,))
    prepared = compute_pool.submit(
        _prepare_day,
        table,
        spec,
        snapshot_id,
        instrument,
        owner_date,
    ).result()
    budget.check((table, prepared.table))
    writer.append(prepared)
    del prepared


def _release_columnar_memory() -> None:
    """Release completed source buffers before the next feature is decoded."""

    gc.collect()
    pa.default_memory_pool().release_unused()


def _validate_day_ownership(table: pa.Table, spec: DatasetSpec, owner_date: date) -> None:
    if not table.num_rows:
        return
    if spec.ownership_mode == "DATE_FIELD":
        if spec.owner_date_field is None:
            raise ContractViolation("DATE_FIELD spec lacks its owner field")
        matches = pc.equal(table[spec.owner_date_field], pa.scalar(owner_date, type=pa.date32()))
    elif spec.ownership_mode == "TIMESTAMP_NS_FIELD":
        if spec.owner_timestamp_ns_field is None:
            raise ContractViolation("TIMESTAMP_NS_FIELD spec lacks its owner field")
        start_ns = (owner_date - date(1970, 1, 1)).days * _DAY_NS
        timestamps = table[spec.owner_timestamp_ns_field]
        matches = pc.and_(
            pc.greater_equal(timestamps, start_ns),
            pc.less(timestamps, start_ns + _DAY_NS),
        )
    else:
        return
    if pc.all(matches).as_py() is not True:
        raise ContractViolation("Feature Foundation rows escape their UTC owner day")


def _month_windows(start: date, end_exclusive: date) -> list[tuple[str, date, date]]:
    windows: list[tuple[str, date, date]] = []
    current = start
    while current < end_exclusive:
        next_month = (
            date(current.year + 1, 1, 1)
            if current.month == 12
            else date(current.year, current.month + 1, 1)
        )
        month_end = min(next_month, end_exclusive)
        windows.append((current.strftime("%Y-%m"), current, month_end))
        current = month_end
    return windows


def _dates(start: date, end_exclusive: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end_exclusive - start).days)]


def _shard_id(dataset_name: str, instrument: Instrument, shard_key: str) -> str:
    return f"foundation-{instrument}-{dataset_name}-{shard_key}"


def _seal_relative_path(
    dataset_name: str,
    instrument: Instrument,
    shard_key: str,
    *,
    storage_role: Literal["MONTHLY_INTERMEDIATE", "PACKED_FINAL"],
) -> str:
    directory = "seals" if storage_role == "MONTHLY_INTERMEDIATE" else "packed-seals"
    return (
        f"staging/foundation/{directory}/instrument={instrument}/"
        f"feature={dataset_name}/shard={shard_key}.json"
    )


def _checkpoint_path(
    config: FoundationPipelineConfig,
    dataset_name: str,
    instrument: Instrument,
    shard_key: str,
    *,
    storage_role: Literal["MONTHLY_INTERMEDIATE", "PACKED_FINAL"],
) -> Path:
    root = (
        config.checkpoint_root
        if storage_role == "MONTHLY_INTERMEDIATE"
        else config.packed_checkpoint_root
    )
    return root / f"instrument={instrument}" / f"feature={dataset_name}" / f"shard={shard_key}.json"


def _packed_shard_key(window_start: date, window_end_exclusive: date) -> str:
    return f"{window_start.isoformat()}_{window_end_exclusive.isoformat()}"


def _fixed_day_windows(
    start: date,
    end_exclusive: date,
    width_days: int,
) -> list[tuple[date, date]]:
    if width_days <= 0:
        raise ValueError("packed shard width must be positive")
    result: list[tuple[date, date]] = []
    current = start
    while current < end_exclusive:
        next_boundary = min(current + timedelta(days=width_days), end_exclusive)
        result.append((current, next_boundary))
        current = next_boundary
    return result


def _ceil_days(start: date, end_exclusive: date, width_days: int) -> int:
    days = (end_exclusive - start).days
    return (days + width_days - 1) // width_days


def planned_packed_object_count(
    *,
    start: date,
    end_exclusive: date,
    instrument_count: int,
) -> int:
    """Return the hard upper bound exposed to the single global V2 Catalog."""

    if end_exclusive <= start or instrument_count <= 0:
        raise ValueError("packed object planning inputs must be positive")
    large = len(_LARGE_FEATURES) * _ceil_days(start, end_exclusive, PACKED_LARGE_SHARD_DAYS)
    small = len(_SMALL_FEATURES)
    return instrument_count * (large + small)


def _empty_table(spec: DatasetSpec) -> pa.Table:
    schema = canonical_arrow_schema(spec)
    return pa.Table.from_arrays([pa.array([], type=field.type) for field in schema], schema=schema)


def _write_once_model(path: Path, model: BaseModel) -> str:
    payload = (canonical_json(model.model_dump(mode="json")) + "\n").encode("utf-8")
    if path.exists():
        if path.is_symlink() or path.read_bytes() != payload:
            raise FileExistsError(f"append-only Foundation evidence differs: {path}")
        return hashlib.sha256(payload).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_directory(path.parent)
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
