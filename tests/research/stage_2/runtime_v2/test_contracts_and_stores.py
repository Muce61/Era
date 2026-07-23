from __future__ import annotations

from datetime import date
from decimal import Decimal

import pyarrow as pa
import pytest

from era100x.research.stage_2.runtime_v2.contracts import (
    EventFactWriteReceipt,
    FeatureBatch,
    FeatureReadRequest,
    HalfOpenTimeWindow,
    TradeRowGroupQuery,
    TradeRowGroupRef,
    TradeSecondPrimitive,
    arrow_record_batch_hash,
    arrow_schema_hash,
)
from era100x.research.stage_2.runtime_v2.stores import (
    EventFactStore,
    PriceFeatureStore,
    TradePrimitiveStore,
    TradeRowGroupIndex,
    validate_event_fact_receipt,
    validate_store_batch,
    validate_trade_row_groups,
)


def _records(event_ts_ns: int, available_at_ns: int) -> pa.RecordBatch:
    return pa.RecordBatch.from_arrays(
        [
            pa.array([event_ts_ns], type=pa.int64()),
            pa.array([available_at_ns], type=pa.int64()),
        ],
        names=["event_ts_ns", "available_at_ns"],
    )


def _feature_batch(
    *,
    window: HalfOpenTimeWindow | None = None,
    event_ts_ns: int = 10,
    available_at_ns: int = 20,
    row_available_at_ns: int | None = None,
    definition_hash: str = "a" * 64,
    capability: str = "H1",
) -> FeatureBatch:
    actual_window = window or HalfOpenTimeWindow(10, 20)
    records = _records(
        event_ts_ns,
        available_at_ns if row_available_at_ns is None else row_available_at_ns,
    )
    return FeatureBatch(
        definition_id="PRICE_CLOSE_V1",
        definition_version="1.0",
        definition_hash=definition_hash,
        snapshot_id="b" * 64,
        instrument="BTCUSDT",
        evidence_capability=capability,  # type: ignore[arg-type]
        owner_date=date(1970, 1, 1),
        window=actual_window,
        available_at_ns=available_at_ns,
        schema_hash=arrow_schema_hash(records.schema),
        source_logical_hashes=("c" * 64,),
        content_hash=arrow_record_batch_hash(records),
        records=records,
    )


def test_half_open_trade_primitive_and_batch_availability_are_causal() -> None:
    window = HalfOpenTimeWindow(10, 20)
    assert window.contains(10)
    assert window.contains(19)
    assert not window.contains(20)

    second = TradeSecondPrimitive(
        instrument="BTCUSDT",
        second_start_ns=10_000_000_000,
        second_end_ns=11_000_000_000,
        available_at_ns=11_000_000_000,
        trade_count=3,
        aggressor_buy_count=2,
        aggressor_sell_count=1,
        aggressor_buy_qty=Decimal("5.5"),
        aggressor_sell_qty=Decimal("2.0"),
        signed_qty=Decimal("3.5"),
        source_logical_hash="d" * 64,
    )
    assert second.contains(second.second_start_ns)
    assert not second.contains(second.second_end_ns)
    with pytest.raises(ValueError, match="unavailable"):
        TradeSecondPrimitive(
            instrument="BTCUSDT",
            second_start_ns=10_000_000_000,
            second_end_ns=11_000_000_000,
            available_at_ns=10_999_999_999,
            trade_count=0,
            aggressor_buy_count=0,
            aggressor_sell_count=0,
            aggressor_buy_qty=Decimal("0"),
            aggressor_sell_qty=Decimal("0"),
            signed_qty=Decimal("0"),
            source_logical_hash="d" * 64,
        )

    batch = _feature_batch()
    batch.require_available_as_of(20)
    with pytest.raises(ValueError, match="not causally available"):
        batch.require_available_as_of(19)
    with pytest.raises(ValueError, match="outside its half-open window"):
        _feature_batch(event_ts_ns=20)
    with pytest.raises(ValueError, match="available before its source event"):
        _feature_batch(event_ts_ns=15, row_available_at_ns=14)


class _Stores:
    def __init__(self, batch: FeatureBatch) -> None:
        self.batch = batch

    def read_price_features(self, request: FeatureReadRequest) -> FeatureBatch:
        return self.batch

    def read_trade_primitives(self, request: FeatureReadRequest) -> FeatureBatch:
        return self.batch

    def lookup_trade_row_groups(self, query: TradeRowGroupQuery) -> tuple[TradeRowGroupRef, ...]:
        return ()

    def read_event_facts(self, request: FeatureReadRequest) -> FeatureBatch:
        return self.batch

    def append_event_facts(self, node_key: str, batch: FeatureBatch) -> EventFactWriteReceipt:
        return EventFactWriteReceipt(
            node_key=node_key,
            instrument=batch.instrument,
            owner_date=batch.owner_date,
            row_count=batch.row_count,
            semantic_hash=batch.content_hash,
        )


def test_store_contracts_validate_logical_identity_capability_and_receipts() -> None:
    batch = _feature_batch(capability="H2")
    stores = _Stores(batch)
    assert isinstance(stores, PriceFeatureStore)
    assert isinstance(stores, TradePrimitiveStore)
    assert isinstance(stores, TradeRowGroupIndex)
    assert isinstance(stores, EventFactStore)

    request = FeatureReadRequest(
        definition_hash=batch.definition_hash,
        snapshot_id=batch.snapshot_id,
        instrument="BTCUSDT",
        window=batch.window,
        as_of_ns=20,
        source_logical_hashes=batch.source_logical_hashes,
    )
    validate_store_batch(request, batch, required_capability="H2")
    node_key = "e" * 64
    receipt = stores.append_event_facts(node_key, batch)
    validate_event_fact_receipt(node_key, batch, receipt)

    wrong_request = FeatureReadRequest(
        definition_hash="f" * 64,
        snapshot_id=batch.snapshot_id,
        instrument="BTCUSDT",
        window=batch.window,
        as_of_ns=20,
        source_logical_hashes=batch.source_logical_hashes,
    )
    with pytest.raises(ValueError, match="unrequested"):
        validate_store_batch(wrong_request, batch, required_capability="H1")

    wrong_snapshot = FeatureReadRequest(
        definition_hash=batch.definition_hash,
        snapshot_id="0" * 64,
        instrument="BTCUSDT",
        window=batch.window,
        as_of_ns=20,
        source_logical_hashes=batch.source_logical_hashes,
    )
    with pytest.raises(ValueError, match="Feature Snapshot"):
        validate_store_batch(wrong_snapshot, batch, required_capability="H1")


def test_trade_row_group_index_respects_half_open_overlap_and_available_at() -> None:
    query = TradeRowGroupQuery(
        instrument="BTCUSDT",
        window=HalfOpenTimeWindow(10, 20),
        as_of_ns=30,
        source_logical_hash="a" * 64,
    )
    later = TradeRowGroupRef(
        object_id="b" * 64,
        row_group_ordinal=1,
        instrument="BTCUSDT",
        event_window=HalfOpenTimeWindow(15, 25),
        available_at_ns=25,
        row_count=10,
        source_logical_hash="a" * 64,
    )
    earlier = TradeRowGroupRef(
        object_id="c" * 64,
        row_group_ordinal=0,
        instrument="BTCUSDT",
        event_window=HalfOpenTimeWindow(5, 15),
        available_at_ns=15,
        row_count=8,
        source_logical_hash="a" * 64,
    )
    assert validate_trade_row_groups(query, (later, earlier)) == (earlier, later)

    touches_only = TradeRowGroupRef(
        object_id="d" * 64,
        row_group_ordinal=0,
        instrument="BTCUSDT",
        event_window=HalfOpenTimeWindow(0, 10),
        available_at_ns=10,
        row_count=4,
        source_logical_hash="a" * 64,
    )
    with pytest.raises(ValueError, match="does not overlap"):
        validate_trade_row_groups(query, (touches_only,))

    wrong_instrument = TradeRowGroupRef(
        object_id="f" * 64,
        row_group_ordinal=0,
        instrument="ETHUSDT",
        event_window=HalfOpenTimeWindow(15, 25),
        available_at_ns=25,
        row_count=4,
        source_logical_hash="a" * 64,
    )
    with pytest.raises(ValueError, match="mixed instruments"):
        validate_trade_row_groups(query, (wrong_instrument,))

    unavailable = TradeRowGroupRef(
        object_id="e" * 64,
        row_group_ordinal=0,
        instrument="BTCUSDT",
        event_window=HalfOpenTimeWindow(15, 25),
        available_at_ns=31,
        row_count=4,
        source_logical_hash="a" * 64,
    )
    with pytest.raises(ValueError, match="not causally available"):
        validate_trade_row_groups(query, (unavailable,))
