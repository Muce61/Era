"""Storage-agnostic Runtime V2 interfaces owned by the orchestrator.

These stores never cross the plugin boundary.  Implementations may use local
artifacts, a catalog or another approved backend, but callers see only logical
hashes, causal windows and immutable Arrow batches.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from era100x.research.stage_2.runtime_v2.contracts import (
    EventFactWriteReceipt,
    EvidenceCapability,
    FeatureBatch,
    FeatureReadRequest,
    TradeRowGroupQuery,
    TradeRowGroupRef,
)

_CAPABILITY_RANK: dict[EvidenceCapability, int] = {"H1": 1, "H2": 2}


@runtime_checkable
class PriceFeatureStore(Protocol):
    """Read immutable price-derived Feature Snapshots by logical contract."""

    def read_price_features(self, request: FeatureReadRequest) -> FeatureBatch: ...


@runtime_checkable
class TradePrimitiveStore(Protocol):
    """Read approved H2 second primitives, never fabricated execution facts."""

    def read_trade_primitives(self, request: FeatureReadRequest) -> FeatureBatch: ...


@runtime_checkable
class TradeRowGroupIndex(Protocol):
    """Resolve exact Trades row groups that overlap one half-open query."""

    def lookup_trade_row_groups(
        self, query: TradeRowGroupQuery
    ) -> tuple[TradeRowGroupRef, ...]: ...


@runtime_checkable
class EventFactStore(Protocol):
    """Read and append immutable, content-addressed event facts."""

    def read_event_facts(self, request: FeatureReadRequest) -> FeatureBatch: ...

    def append_event_facts(self, node_key: str, batch: FeatureBatch) -> EventFactWriteReceipt: ...


def validate_store_batch(
    request: FeatureReadRequest,
    batch: FeatureBatch,
    *,
    required_capability: EvidenceCapability,
) -> None:
    """Fail closed if a store returns a different or unavailable logical slice."""

    if batch.definition_hash != request.definition_hash:
        raise ValueError("store returned an unrequested Feature Definition")
    if batch.snapshot_id != request.snapshot_id:
        raise ValueError("store returned an unrequested Feature Snapshot")
    if batch.source_logical_hashes != request.source_logical_hashes:
        raise ValueError("store returned different source logical authorities")
    if batch.instrument != request.instrument:
        raise ValueError("store returned a different instrument")
    if batch.window != request.window:
        raise ValueError("store returned a different half-open time window")
    if _CAPABILITY_RANK[batch.evidence_capability] < _CAPABILITY_RANK[required_capability]:
        raise ValueError("store batch has insufficient evidence capability")
    batch.require_available_as_of(request.as_of_ns)


def validate_trade_row_groups(
    query: TradeRowGroupQuery, refs: tuple[TradeRowGroupRef, ...]
) -> tuple[TradeRowGroupRef, ...]:
    """Validate and deterministically order row-group index results."""

    identities: set[tuple[str, int]] = set()
    for ref in refs:
        identity = (ref.object_id, ref.row_group_ordinal)
        if identity in identities:
            raise ValueError("trade row-group index returned a duplicate reference")
        identities.add(identity)
        if ref.instrument != query.instrument:
            raise ValueError("trade row-group index mixed instruments")
        if ref.source_logical_hash != query.source_logical_hash:
            raise ValueError("trade row-group source authority mismatch")
        if not ref.event_window.overlaps(query.window):
            raise ValueError("trade row-group does not overlap the half-open query")
        if ref.available_at_ns > query.as_of_ns:
            raise ValueError("trade row-group is not causally available as of the query")
    return tuple(
        sorted(
            refs,
            key=lambda item: (
                item.event_window.start_ns,
                item.event_window.end_ns,
                item.object_id,
                item.row_group_ordinal,
            ),
        )
    )


def validate_event_fact_receipt(
    node_key: str, batch: FeatureBatch, receipt: EventFactWriteReceipt
) -> None:
    """Bind a sealed write receipt back to the requested logical event batch."""

    if receipt.node_key != node_key:
        raise ValueError("event-fact receipt node key mismatch")
    if receipt.instrument != batch.instrument or receipt.owner_date != batch.owner_date:
        raise ValueError("event-fact receipt ownership mismatch")
    if receipt.row_count != batch.row_count:
        raise ValueError("event-fact receipt row count mismatch")
