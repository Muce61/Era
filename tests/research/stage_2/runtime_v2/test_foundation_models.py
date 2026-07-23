from __future__ import annotations

import pytest

from era100x.research.stage_2.runtime_v2.foundation_models import (
    FeatureDefinition,
    FeatureFoundationManifest,
    FeatureSnapshot,
    Stage2V2ExecutionManifest,
)
from era100x.research.stage_2.runtime_v2.models import DigestBinding

H = "a" * 64
E = "b" * 64


def _definition(source: str, capability: str, identifier: str) -> FeatureDefinition:
    return FeatureDefinition.seal(
        {
            "definition_version": "1.0",
            "definition_id": identifier,
            "source_kind": source,
            "evidence_capability": capability,
            "formula_id": f"{identifier}-FORMULA-V1",
            "availability_rule": "available_at_ns=window_end_ns",
            "schema_sha256": H,
            "implementation_tree_sha256": E,
            "config_sha256": H,
            "required_source_columns": ("aggressor_side", "quantity", "ts_event_ns")
            if capability == "H2"
            else ("close", "high", "low", "open", "ts_event_ns"),
            "prohibited_capabilities": ("BID", "ASK", "L2", "TS_RECV"),
        }
    )


def _snapshot(definition: FeatureDefinition, instrument: str) -> FeatureSnapshot:
    return FeatureSnapshot.seal(
        {
            "definition_hash": definition.definition_hash,
            "instrument": instrument,
            "utc_partition": "2020-01",
            "window_start_ns": 1,
            "window_end_ns": 2,
            "available_at_ns": 2,
            "node_key": H,
            "source_logical_hashes": (H,),
            "artifact_object_hashes": (E,),
            "logical_receipt_hashes": (H,),
            "row_count": 1,
            "quality_status": "PASS",
        }
    )


def test_foundation_manifest_is_stable_and_keeps_instruments_separate() -> None:
    price = _definition("CONTRACT_PRICE_1S", "H1", "CONTRACT_PRICE_1S")
    trades = _definition("TRADES_1S_PRIMITIVE", "H2", "TRADES_1S_PRIMITIVE")
    definitions = tuple(sorted((price, trades), key=lambda item: item.definition_hash))
    snapshots = tuple(
        sorted(
            (
                _snapshot(definition, instrument)
                for definition in definitions
                for instrument in ("BTCUSDT", "ETHUSDT")
            ),
            key=lambda item: (item.definition_hash, item.instrument, item.utc_partition),
        )
    )
    manifest = FeatureFoundationManifest.seal(
        {
            "change_requests": ("CR-2026-007", "CR-2026-008"),
            "stage1_data_run_id": "stage1-run",
            "stage1_authorities": (
                DigestBinding(name="btc_trades", sha256=H),
                DigestBinding(name="eth_trades", sha256=E),
            ),
            "contract_price_inventory_sha256": H,
            "preregistration_manifest_sha256": E,
            "config_sha256": H,
            "code_commit": "c" * 40,
            "code_tree_sha256": E,
            "external_root": "/Volumes/FuckingLife/era100x_stage2",
            "definitions": definitions,
            "snapshots": snapshots,
            "instruments": ("BTCUSDT", "ETHUSDT"),
            "prohibited_capabilities": ("ASK", "BID", "L2"),
            "invalidation_conditions": ("SOURCE_HASH_CHANGED",),
        }
    )
    assert manifest.computed_hash() == manifest.manifest_hash


def test_trades_definition_cannot_claim_h1() -> None:
    with pytest.raises(ValueError, match="require H2"):
        _definition("TRADES_1S_PRIMITIVE", "H1", "BAD")

    with pytest.raises(ValueError, match="require H2"):
        _definition("EXACT_TRADE_ROW_GROUP_INDEX", "H1", "BAD-ROW-GROUP-INDEX")


def test_execution_manifest_is_bound_to_approved_group1_only() -> None:
    manifest = Stage2V2ExecutionManifest.seal(
        {
            "run_id": "stage2-g1-v2-b",
            "source_run_a_protection_hash": H,
            "migration_manifest_hash": E,
            "feature_foundation_manifest_hash": H,
            "preregistration_manifest_sha256": E,
            "config_sha256": H,
            "code_commit": "c" * 40,
            "code_tree_sha256": E,
            "approved_setup_id": "KEY_LOW_SWEEP_RECLAIM_HOLD_V1",
            "approved_context_id": "CAUSAL_EMA20_1H",
            "approved_variants": ("V1_PRICE", "V1_FLOW"),
            "instruments": ("BTCUSDT", "ETHUSDT"),
            "no_run_a_artifact_reuse": True,
            "full_period_start": "2020-01-01",
            "full_period_end_exclusive": "2026-07-04",
            "invalidation_conditions": ("HASH_CHANGED",),
        }
    )
    assert manifest.computed_hash() == manifest.manifest_hash
