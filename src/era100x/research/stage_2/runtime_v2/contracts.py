"""Immutable in-memory contracts for the Stage 2 Runtime V2 boundary.

The runtime owns all source access.  Plugins only receive :class:`FeatureBatch`
instances, which makes causal availability and evidence capability explicit at
the call boundary.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, TypeAlias

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]

Instrument: TypeAlias = Literal["BTCUSDT", "ETHUSDT"]  # noqa: UP040
EvidenceCapability: TypeAlias = Literal["H1", "H2"]  # noqa: UP040
FeatureSource: TypeAlias = Literal[  # noqa: UP040
    "PRICE_FEATURE",
    "TRADE_PRIMITIVE",
    "EXACT_TRADE_ROWS",
    "EVENT_FACT",
]

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ONE_SECOND_NS = 1_000_000_000
_INSTRUMENTS = {"BTCUSDT", "ETHUSDT"}
_CAPABILITIES = {"H1", "H2"}


def require_sha256(value: str, field_name: str) -> None:
    if not SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def arrow_schema_hash(schema: pa.Schema) -> str:
    """Return the deterministic integrity hash used by ``FeatureBatch``."""

    return hashlib.sha256(schema.serialize().to_pybytes()).hexdigest()


def arrow_record_batch_hash(batch: pa.RecordBatch) -> str:
    """Hash one Arrow batch without converting its rows to Python objects."""

    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as writer:
        writer.write_batch(batch)
    return hashlib.sha256(sink.getvalue().to_pybytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class HalfOpenTimeWindow:
    """Nanosecond window with the only supported ``[start, end)`` semantics."""

    start_ns: int
    end_ns: int

    def __post_init__(self) -> None:
        if self.start_ns < 0:
            raise ValueError("window start_ns must be non-negative")
        if self.end_ns <= self.start_ns:
            raise ValueError("window must be non-empty and left-closed/right-open")

    def contains(self, event_ts_ns: int) -> bool:
        return self.start_ns <= event_ts_ns < self.end_ns

    def overlaps(self, other: HalfOpenTimeWindow) -> bool:
        return self.start_ns < other.end_ns and other.start_ns < self.end_ns

    def touches_or_overlaps(self, other: HalfOpenTimeWindow) -> bool:
        return self.start_ns <= other.end_ns and other.start_ns <= self.end_ns

    def expand_lookback(self, lookback_ns: int) -> HalfOpenTimeWindow:
        if lookback_ns < 0:
            raise ValueError("lookback_ns must be non-negative")
        return HalfOpenTimeWindow(max(0, self.start_ns - lookback_ns), self.end_ns)


@dataclass(frozen=True, slots=True)
class FeatureBatch:
    """A causal, immutable Arrow batch supplied to research plugins.

    Every row carries ``available_at_ns``.  A plugin invocation may consume the
    batch only when its ``as_of_ns`` is at least the batch-level availability.
    If ``event_ts_ns`` is present, every event must belong to ``window``.
    """

    definition_id: str
    definition_version: str
    definition_hash: str
    snapshot_id: str
    instrument: Instrument
    evidence_capability: EvidenceCapability
    owner_date: date
    window: HalfOpenTimeWindow
    available_at_ns: int
    schema_hash: str
    source_logical_hashes: tuple[str, ...]
    content_hash: str
    records: pa.RecordBatch

    def __post_init__(self) -> None:
        if not self.definition_id or not self.definition_version:
            raise ValueError("feature definition id and version are required")
        for field_name, value in (
            ("definition_hash", self.definition_hash),
            ("snapshot_id", self.snapshot_id),
            ("schema_hash", self.schema_hash),
            ("content_hash", self.content_hash),
        ):
            require_sha256(value, field_name)
        if self.instrument not in _INSTRUMENTS:
            raise ValueError("FeatureBatch instrument is not approved")
        if self.evidence_capability not in _CAPABILITIES:
            raise ValueError("FeatureBatch evidence capability is not approved")
        if self.available_at_ns < 0:
            raise ValueError("FeatureBatch available_at_ns must be non-negative")
        if not self.source_logical_hashes:
            raise ValueError("FeatureBatch requires source logical hashes")
        for digest in self.source_logical_hashes:
            require_sha256(digest, "source_logical_hash")
        canonical_sources = tuple(sorted(set(self.source_logical_hashes)))
        object.__setattr__(self, "source_logical_hashes", canonical_sources)
        if not isinstance(self.records, pa.RecordBatch):
            raise TypeError("FeatureBatch records must be a pyarrow.RecordBatch")
        if self.schema_hash != arrow_schema_hash(self.records.schema):
            raise ValueError("FeatureBatch schema hash mismatch")
        if self.content_hash != arrow_record_batch_hash(self.records):
            raise ValueError("FeatureBatch content hash mismatch")
        if self.available_at_ns < self.window.end_ns:
            raise ValueError("FeatureBatch cannot be available before its window closes")
        self._validate_availability_column()
        self._validate_event_times()

    @property
    def row_count(self) -> int:
        return int(self.records.num_rows)

    def require_available_as_of(self, as_of_ns: int) -> None:
        if as_of_ns < self.available_at_ns:
            raise ValueError("FeatureBatch is not causally available as of the request")

    def _validate_availability_column(self) -> None:
        index = self.records.schema.get_field_index("available_at_ns")
        if index < 0:
            raise ValueError("FeatureBatch requires an available_at_ns column")
        column = self.records.column(index)
        if not pa.types.is_integer(column.type) or column.null_count:
            raise ValueError("available_at_ns must be a non-null integer column")
        if len(column):
            invalid = pc.or_(
                pc.less(column, 0),
                pc.greater(column, self.available_at_ns),
            )
            if bool(pc.any(invalid).as_py()):
                raise ValueError("row availability exceeds the FeatureBatch availability")

    def _validate_event_times(self) -> None:
        index = self.records.schema.get_field_index("event_ts_ns")
        if index < 0:
            return
        column = self.records.column(index)
        if not pa.types.is_integer(column.type) or column.null_count:
            raise ValueError("event_ts_ns must be a non-null integer column")
        if not len(column):
            return
        outside = pc.or_(
            pc.less(column, self.window.start_ns),
            pc.greater_equal(column, self.window.end_ns),
        )
        if bool(pc.any(outside).as_py()):
            raise ValueError("FeatureBatch event lies outside its half-open window")
        availability = self.records.column(self.records.schema.get_field_index("available_at_ns"))
        if bool(pc.any(pc.less(availability, column)).as_py()):
            raise ValueError("FeatureBatch row is available before its source event")


@dataclass(frozen=True, slots=True)
class TradeSecondPrimitive:
    """Causal one-second H2 aggregate over ``[second_start_ns, second_end_ns)``."""

    instrument: Instrument
    second_start_ns: int
    second_end_ns: int
    available_at_ns: int
    trade_count: int
    aggressor_buy_count: int
    aggressor_sell_count: int
    aggressor_buy_qty: Decimal
    aggressor_sell_qty: Decimal
    signed_qty: Decimal
    source_logical_hash: str

    def __post_init__(self) -> None:
        if self.instrument not in _INSTRUMENTS:
            raise ValueError("trade primitive instrument is not approved")
        if self.second_start_ns < 0 or self.second_start_ns % ONE_SECOND_NS:
            raise ValueError("trade primitive start must align to a UTC second")
        if self.second_end_ns != self.second_start_ns + ONE_SECOND_NS:
            raise ValueError("trade primitive must cover exactly one half-open second")
        if self.available_at_ns < self.second_end_ns:
            raise ValueError("trade primitive is unavailable until the second closes")
        counts = (self.trade_count, self.aggressor_buy_count, self.aggressor_sell_count)
        if any(value < 0 for value in counts):
            raise ValueError("trade primitive counts must be non-negative")
        if self.aggressor_buy_count + self.aggressor_sell_count != self.trade_count:
            raise ValueError("aggressor counts must sum to trade_count")
        quantities = (
            self.aggressor_buy_qty,
            self.aggressor_sell_qty,
            self.signed_qty,
        )
        if any(not isinstance(value, Decimal) for value in quantities):
            raise TypeError("trade primitive quantities must be Decimals")
        if any(not value.is_finite() for value in quantities):
            raise ValueError("trade primitive quantities must be finite Decimals")
        if self.aggressor_buy_qty < 0 or self.aggressor_sell_qty < 0:
            raise ValueError("trade primitive quantities must be non-negative")
        if self.signed_qty != self.aggressor_buy_qty - self.aggressor_sell_qty:
            raise ValueError("signed_qty must equal aggressor buy quantity minus sell quantity")
        require_sha256(self.source_logical_hash, "source_logical_hash")

    @property
    def window(self) -> HalfOpenTimeWindow:
        return HalfOpenTimeWindow(self.second_start_ns, self.second_end_ns)

    def contains(self, trade_ts_ns: int) -> bool:
        return self.second_start_ns <= trade_ts_ns < self.second_end_ns


@dataclass(frozen=True, slots=True)
class FeatureReadRequest:
    definition_hash: str
    snapshot_id: str
    instrument: Instrument
    window: HalfOpenTimeWindow
    as_of_ns: int
    source_logical_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        require_sha256(self.definition_hash, "definition_hash")
        require_sha256(self.snapshot_id, "snapshot_id")
        if self.instrument not in _INSTRUMENTS:
            raise ValueError("feature request instrument is not approved")
        if self.as_of_ns < self.window.end_ns:
            raise ValueError("feature request as_of_ns predates the closed source window")
        if not self.source_logical_hashes:
            raise ValueError("feature request requires locked source logical hashes")
        for digest in self.source_logical_hashes:
            require_sha256(digest, "source_logical_hash")
        object.__setattr__(
            self,
            "source_logical_hashes",
            tuple(sorted(set(self.source_logical_hashes))),
        )


@dataclass(frozen=True, slots=True)
class TradeRowGroupQuery:
    instrument: Instrument
    window: HalfOpenTimeWindow
    as_of_ns: int
    source_logical_hash: str

    def __post_init__(self) -> None:
        if self.instrument not in _INSTRUMENTS:
            raise ValueError("trade row-group instrument is not approved")
        if self.as_of_ns < self.window.end_ns:
            raise ValueError("trade row-group query precedes its half-open window end")
        require_sha256(self.source_logical_hash, "source_logical_hash")


@dataclass(frozen=True, slots=True)
class TradeRowGroupRef:
    object_id: str
    row_group_ordinal: int
    instrument: Instrument
    event_window: HalfOpenTimeWindow
    available_at_ns: int
    row_count: int
    source_logical_hash: str

    def __post_init__(self) -> None:
        require_sha256(self.object_id, "object_id")
        require_sha256(self.source_logical_hash, "source_logical_hash")
        if self.instrument not in _INSTRUMENTS:
            raise ValueError("trade row-group instrument is not approved")
        if self.row_group_ordinal < 0 or self.row_count < 0:
            raise ValueError("row-group ordinal and row count must be non-negative")
        if self.available_at_ns < self.event_window.end_ns:
            raise ValueError("trade row group cannot be available before its event window closes")


@dataclass(frozen=True, slots=True)
class EventFactWriteReceipt:
    node_key: str
    instrument: Instrument
    owner_date: date
    row_count: int
    semantic_hash: str
    terminal_state: Literal["SEALED"] = "SEALED"

    def __post_init__(self) -> None:
        require_sha256(self.node_key, "node_key")
        require_sha256(self.semantic_hash, "semantic_hash")
        if self.row_count < 0:
            raise ValueError("event fact receipt row_count must be non-negative")
        if self.instrument not in _INSTRUMENTS:
            raise ValueError("event fact receipt instrument is not approved")
        if self.terminal_state != "SEALED":
            raise ValueError("event fact receipt must be terminal SEALED")
