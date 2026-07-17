"""Fail-closed registry tests for the Stage 2 V2 runtime."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pyarrow as pa
import pytest

from era100x.research.stage_2.runtime_v2.contracts import (
    FeatureBatch,
    HalfOpenTimeWindow,
    arrow_record_batch_hash,
    arrow_schema_hash,
)
from era100x.research.stage_2.runtime_v2.plugins import (
    FeatureRequirement,
    PluginInvocation,
    RuntimePluginApproval,
    RuntimePluginDescriptor,
    RuntimeVariantApproval,
)
from era100x.research.stage_2.runtime_v2.registry import (
    ApprovedRuntimeRegistry,
    RuntimeApprovalError,
)


def _records(available_at_ns: int = 20) -> pa.RecordBatch:
    return pa.RecordBatch.from_arrays(
        [
            pa.array([10], type=pa.int64()),
            pa.array([available_at_ns], type=pa.int64()),
        ],
        names=["event_ts_ns", "available_at_ns"],
    )


def _batch(
    definition_id: str,
    definition_hash: str,
    *,
    capability: str = "H1",
) -> FeatureBatch:
    records = _records()
    return FeatureBatch(
        definition_id=definition_id,
        definition_version="1.0",
        definition_hash=definition_hash,
        snapshot_id="9" * 64,
        instrument="BTCUSDT",
        evidence_capability=capability,  # type: ignore[arg-type]
        owner_date=date(1970, 1, 1),
        window=HalfOpenTimeWindow(10, 20),
        available_at_ns=20,
        schema_hash=arrow_schema_hash(records.schema),
        source_logical_hashes=("8" * 64,),
        content_hash=arrow_record_batch_hash(records),
        records=records,
    )


def _descriptors() -> tuple[RuntimePluginDescriptor, RuntimePluginDescriptor]:
    output_schema_hash = arrow_schema_hash(_records().schema)
    setup = RuntimePluginDescriptor(
        plugin_kind="SETUP",
        plugin_id="KEY_LOW_SWEEP_RECLAIM_HOLD_V1",
        plugin_version="1.0",
        implementation_tree_hash="1" * 64,
        output_schema_hash=output_schema_hash,
        required_features=(
            FeatureRequirement(
                definition_id="SETUP_PRICE_V1",
                definition_version="1.0",
                definition_hash="a" * 64,
                source="PRICE_FEATURE",
                required_capability="H1",
            ),
        ),
    )
    context = RuntimePluginDescriptor(
        plugin_kind="CONTEXT",
        plugin_id="CAUSAL_EMA20_1H",
        plugin_version="1.0",
        implementation_tree_hash="2" * 64,
        output_schema_hash=output_schema_hash,
        required_features=(
            FeatureRequirement(
                definition_id="CONTEXT_PRICE_V1",
                definition_version="1.0",
                definition_hash="b" * 64,
                source="PRICE_FEATURE",
                required_capability="H1",
            ),
        ),
    )
    return setup, context


class _Setup:
    def __init__(self, descriptor: RuntimePluginDescriptor) -> None:
        self._descriptor = descriptor

    @property
    def descriptor(self) -> RuntimePluginDescriptor:
        return self._descriptor

    def evaluate_setup(self, invocation: PluginInvocation, context: FeatureBatch) -> FeatureBatch:
        return _batch("SETUP_OUTPUT_V1", "d" * 64)


class _Context:
    def __init__(self, descriptor: RuntimePluginDescriptor) -> None:
        self._descriptor = descriptor

    @property
    def descriptor(self) -> RuntimePluginDescriptor:
        return self._descriptor

    def evaluate_context(self, invocation: PluginInvocation) -> FeatureBatch:
        return _batch("CONTEXT_OUTPUT_V1", "e" * 64)


def _registry() -> tuple[ApprovedRuntimeRegistry, _Setup, _Context]:
    setup_descriptor, context_descriptor = _descriptors()
    variants = (
        RuntimeVariantApproval(
            variant_id="V1_PRICE",
            variant_version="1.0",
            required_capability="H1",
            required_feature_hashes=("a" * 64, "b" * 64),
        ),
        RuntimeVariantApproval(
            variant_id="V1_FLOW",
            variant_version="1.0",
            required_capability="H2",
            required_feature_hashes=("a" * 64, "b" * 64, "c" * 64),
        ),
    )
    registry = ApprovedRuntimeRegistry.for_group1(
        plugin_approvals=(
            RuntimePluginApproval.from_descriptor(setup_descriptor),
            RuntimePluginApproval.from_descriptor(context_descriptor),
        ),
        variant_approvals=variants,
    )
    return registry, _Setup(setup_descriptor), _Context(context_descriptor)


def test_group1_registry_is_explicit_fail_closed_and_capability_aware() -> None:
    registry, setup, context = _registry()
    registry.bind_setup(setup)
    registry.bind_context(context)

    price = registry.resolve(
        setup_id="KEY_LOW_SWEEP_RECLAIM_HOLD_V1",
        setup_version="1.0",
        context_id="CAUSAL_EMA20_1H",
        context_version="1.0",
        variant_id="V1_PRICE",
        variant_version="1.0",
        evidence_capability="H1",
    )
    assert price.required_feature_hashes == ("a" * 64, "b" * 64)

    with pytest.raises(RuntimeApprovalError, match="insufficient evidence"):
        registry.resolve(
            setup_id="KEY_LOW_SWEEP_RECLAIM_HOLD_V1",
            setup_version="1.0",
            context_id="CAUSAL_EMA20_1H",
            context_version="1.0",
            variant_id="V1_FLOW",
            variant_version="1.0",
            evidence_capability="H1",
        )
    flow = registry.resolve(
        setup_id="KEY_LOW_SWEEP_RECLAIM_HOLD_V1",
        setup_version="1.0",
        context_id="CAUSAL_EMA20_1H",
        context_version="1.0",
        variant_id="V1_FLOW",
        variant_version="1.0",
        evidence_capability="H2",
    )
    assert flow.required_feature_hashes == ("a" * 64, "b" * 64, "c" * 64)

    with pytest.raises(RuntimeApprovalError, match="unknown or unapproved"):
        registry.require_variant("TEST_ONLY", "1.0", "H2")


def test_registry_executes_plugins_only_with_exact_authorized_feature_batches() -> None:
    registry, setup, context = _registry()
    registry.bind_setup(setup)
    registry.bind_context(context)
    invocation = PluginInvocation(
        instrument="BTCUSDT",
        owner_window=HalfOpenTimeWindow(10, 20),
        as_of_ns=20,
        config_hash="7" * 64,
        parameter_set_id="P0",
        batches=(_batch("CONTEXT_PRICE_V1", "b" * 64),),
    )
    result = registry.execute_context("CAUSAL_EMA20_1H", "1.0", invocation)
    assert result.definition_id == "CONTEXT_OUTPUT_V1"

    wrong_identity = PluginInvocation(
        instrument="BTCUSDT",
        owner_window=HalfOpenTimeWindow(10, 20),
        as_of_ns=20,
        config_hash="7" * 64,
        parameter_set_id="P0",
        batches=(_batch("WRONG_ID", "b" * 64),),
    )
    with pytest.raises(RuntimeApprovalError, match="identity"):
        registry.execute_context("CAUSAL_EMA20_1H", "1.0", wrong_identity)


def test_changed_unapproved_or_external_access_plugins_fail_closed() -> None:
    registry, setup, _ = _registry()
    setup_descriptor, _ = _descriptors()
    changed = RuntimePluginDescriptor(
        plugin_kind="SETUP",
        plugin_id=setup_descriptor.plugin_id,
        plugin_version=setup_descriptor.plugin_version,
        implementation_tree_hash="6" * 64,
        output_schema_hash=setup_descriptor.output_schema_hash,
        required_features=setup_descriptor.required_features,
    )
    with pytest.raises(RuntimeApprovalError, match="descriptor differs"):
        registry.bind_setup(_Setup(changed))

    class _ExternalSetup(_Setup):
        file_path = Path("/tmp/forbidden")

    with pytest.raises(RuntimeApprovalError, match="forbidden runtime dependencies"):
        registry.bind_setup(_ExternalSetup(setup_descriptor))

    registry.bind_setup(setup)
    with pytest.raises(RuntimeApprovalError, match="already bound"):
        registry.bind_setup(setup)

    test_descriptor = RuntimePluginDescriptor(
        plugin_kind="SETUP",
        plugin_id="TEST_ONLY",
        plugin_version="1.0",
        implementation_tree_hash="5" * 64,
        output_schema_hash=setup_descriptor.output_schema_hash,
        required_features=setup_descriptor.required_features,
    )
    with pytest.raises(RuntimeApprovalError, match="exactly the approved setup"):
        ApprovedRuntimeRegistry.for_group1(
            plugin_approvals=(
                RuntimePluginApproval.from_descriptor(setup_descriptor),
                RuntimePluginApproval.from_descriptor(test_descriptor),
            ),
            variant_approvals=(
                RuntimeVariantApproval(
                    variant_id="V1_PRICE",
                    variant_version="1.0",
                    required_capability="H1",
                    required_feature_hashes=("a" * 64,),
                ),
                RuntimeVariantApproval(
                    variant_id="V1_FLOW",
                    variant_version="1.0",
                    required_capability="H2",
                    required_feature_hashes=("a" * 64,),
                ),
            ),
        )


def test_plugin_invocation_has_no_path_or_store_escape_hatch() -> None:
    assert "path" not in PluginInvocation.__dataclass_fields__
    assert "store" not in PluginInvocation.__dataclass_fields__
    with pytest.raises(TypeError, match="scalar research values"):
        PluginInvocation(
            instrument="BTCUSDT",
            owner_window=HalfOpenTimeWindow(10, 20),
            as_of_ns=20,
            config_hash="7" * 64,
            parameter_set_id="P0",
            batches=(_batch("CONTEXT_PRICE_V1", "b" * 64),),
            parameters={"path": Path("/tmp/forbidden")},  # type: ignore[dict-item]
        )
