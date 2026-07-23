from __future__ import annotations

from dataclasses import replace

import pytest

from era100x.research.stage_2.runtime_v2.contracts import HalfOpenTimeWindow
from era100x.research.stage_2.runtime_v2.dag import ContentAddressedDAGNodeKey
from era100x.research.stage_2.runtime_v2.plugins import FeatureRequirement
from era100x.research.stage_2.runtime_v2.scan_plan import ScanPlanBuilder


def _node(**changes: object) -> ContentAddressedDAGNodeKey:
    payload = {
        "node_kind": "PRICE_FEATURE",
        "definition_id": "PRICE_CLOSE_V1",
        "definition_version": "1.0",
        "definition_hash": "a" * 64,
        "implementation_tree_hash": "b" * 64,
        "config_hash": "c" * 64,
        "schema_hash": "d" * 64,
        "instrument": "BTCUSDT",
        "logical_utc_partition": "2026-07-17",
        "evidence_capability": "H1",
        "availability_rule": "BAR_CLOSE_UTC",
        "source_logical_hashes": ("e" * 64, "f" * 64),
        "dependency_node_keys": ("1" * 64, "2" * 64),
    }
    payload.update(changes)
    return ContentAddressedDAGNodeKey(**payload)  # type: ignore[arg-type]


def test_dag_node_key_is_order_independent_and_invalidates_dependents() -> None:
    first = _node()
    reordered = _node(
        source_logical_hashes=tuple(reversed(first.source_logical_hashes)),
        dependency_node_keys=tuple(reversed(first.dependency_node_keys)),
    )
    assert first.value == reordered.value
    assert replace(first, config_hash="3" * 64).value != first.value
    assert replace(first, dependency_node_keys=("4" * 64,)).value != first.value
    assert replace(first, source_logical_hashes=("5" * 64,)).value != first.value
    assert replace(first, instrument="ETHUSDT").value != first.value


def test_scan_plan_coalesces_reusable_sources_and_preserves_capabilities() -> None:
    price_a = FeatureRequirement(
        definition_id="EMA20_1H",
        definition_version="1.0",
        definition_hash="a" * 64,
        source="PRICE_FEATURE",
        required_capability="H1",
        lookback_ns=5,
    )
    price_b = FeatureRequirement(
        definition_id="KEY_LEVEL_V1",
        definition_version="1.0",
        definition_hash="b" * 64,
        source="PRICE_FEATURE",
        required_capability="H1",
        lookback_ns=2,
    )
    trades = FeatureRequirement(
        definition_id="SIGNED_FLOW_1S_V1",
        definition_version="1.0",
        definition_hash="c" * 64,
        source="TRADE_PRIMITIVE",
        required_capability="H2",
    )
    windows = (HalfOpenTimeWindow(10, 20), HalfOpenTimeWindow(20, 30))
    builder = ScanPlanBuilder()
    first = builder.build(
        instrument="BTCUSDT",
        owner_windows=windows,
        requirements=(trades, price_b, price_a),
        as_of_ns=30,
    )
    second = builder.build(
        instrument="BTCUSDT",
        owner_windows=tuple(reversed(windows)),
        requirements=(price_a, trades, price_b),
        as_of_ns=30,
    )
    assert first.plan_key == second.plan_key
    assert len(first.segments) == 2

    price_segment = next(item for item in first.segments if item.source == "PRICE_FEATURE")
    assert price_segment.window == HalfOpenTimeWindow(5, 30)
    assert price_segment.required_capability == "H1"
    assert price_segment.required_definition_hashes == ("a" * 64, "b" * 64)

    trade_segment = next(item for item in first.segments if item.source == "TRADE_PRIMITIVE")
    assert trade_segment.window == HalfOpenTimeWindow(10, 30)
    assert trade_segment.required_capability == "H2"


def test_scan_plan_rejects_future_overlap_and_conflicting_definition_authority() -> None:
    feature = FeatureRequirement(
        definition_id="PRICE_V1",
        definition_version="1.0",
        definition_hash="a" * 64,
        source="PRICE_FEATURE",
        required_capability="H1",
    )
    builder = ScanPlanBuilder()
    with pytest.raises(ValueError, match="predates"):
        builder.build(
            instrument="BTCUSDT",
            owner_windows=(HalfOpenTimeWindow(10, 20),),
            requirements=(feature,),
            as_of_ns=19,
        )
    with pytest.raises(ValueError, match="must not overlap"):
        builder.build(
            instrument="BTCUSDT",
            owner_windows=(HalfOpenTimeWindow(10, 20), HalfOpenTimeWindow(19, 30)),
            requirements=(feature,),
            as_of_ns=30,
        )

    conflicting = replace(feature, lookback_ns=1)
    with pytest.raises(ValueError, match="conflicting"):
        builder.build(
            instrument="BTCUSDT",
            owner_windows=(HalfOpenTimeWindow(10, 20),),
            requirements=(feature, conflicting),
            as_of_ns=20,
        )

    with pytest.raises(ValueError, match="H2"):
        FeatureRequirement(
            definition_id="BAD_TRADES",
            definition_version="1.0",
            definition_hash="b" * 64,
            source="EXACT_TRADE_ROWS",
            required_capability="H1",
        )
