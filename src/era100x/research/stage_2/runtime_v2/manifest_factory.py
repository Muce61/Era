"""Deterministic authority factory for the S2-T10 v1.8 full V2 matrix."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Final

from .dataset_specs import (
    GROUP1_CONTEXT_ID,
    GROUP1_DATASET_BINDINGS,
    GROUP1_SETUP_ID,
)
from .foundation_specs import feature_foundation_dataset_specs
from .models import (
    DatasetPlan,
    DatasetSpec,
    DigestBinding,
    LogicalPartitionKey,
    ManifestV2,
    metadata_sha256,
)
from .source_authority import (
    CONTRACT_PRICE_MANIFEST_AUTHORITY,
    TRADES_RESOLVED_INDEX_AUTHORITY,
)

START: Final = date(2020, 1, 1)
END_EXCLUSIVE: Final = date(2026, 7, 4)
INSTRUMENTS: Final = ("BTCUSDT", "ETHUSDT")
FOUNDATION_SETUP_ID: Final = "FEATURE_FOUNDATION"
FOUNDATION_CONTEXT_ID: Final = "FROZEN_STAGE1"
FOUNDATION_VARIANTS: Final = {
    "contract_price_1s": "FOUNDATION",
    "causal_price_bars": "FOUNDATION",
    "trade_second_primitives": "FOUNDATION",
    "trade_row_group_index": "FOUNDATION",
}
EXPECTED_LOGICAL_PARTITIONS: Final = 80_784


def build_runtime_v2_manifest(
    *,
    stage1_data_run_id: str,
    stage1_authorities: tuple[DigestBinding, ...],
    preregistration_manifest_sha256: str,
    config_sha256: str,
    code_tree_sha256: str,
) -> ManifestV2:
    """Freeze the complete Foundation plus Group-1 owner-day matrix."""

    source_authorities = {item.name: item.sha256 for item in stage1_authorities}
    required_resolved = {
        CONTRACT_PRICE_MANIFEST_AUTHORITY,
        TRADES_RESOLVED_INDEX_AUTHORITY,
    }
    if not required_resolved.issubset(source_authorities):
        raise ValueError("Runtime V2 requires both sealed resolved source authorities")

    specs = tuple(
        sorted(
            (*feature_foundation_dataset_specs(), *(item.spec for item in GROUP1_DATASET_BINDINGS)),
            key=lambda item: item.spec_hash,
        )
    )
    if len(specs) != 17 or len({item.spec_hash for item in specs}) != len(specs):
        raise ValueError("Runtime V2 requires exactly 17 unique DatasetSpec contracts")
    snapshot_id = _snapshot_id(
        stage1_data_run_id=stage1_data_run_id,
        stage1_authorities=stage1_authorities,
        preregistration_manifest_sha256=preregistration_manifest_sha256,
        config_sha256=config_sha256,
        code_tree_sha256=code_tree_sha256,
        specs=specs,
    )
    plans = _dataset_plans(snapshot_id=snapshot_id, specs=specs)
    if sum(len(item.expected_partition_ids) for item in plans) != EXPECTED_LOGICAL_PARTITIONS:
        raise AssertionError("Runtime V2 logical partition matrix is incomplete")
    return ManifestV2.seal(
        {
            "snapshot_id": snapshot_id,
            "stage1_data_run_id": stage1_data_run_id,
            "stage1_authorities": tuple(sorted(stage1_authorities, key=lambda item: item.name)),
            "preregistration_manifest_sha256": preregistration_manifest_sha256,
            "config_sha256": config_sha256,
            "code_tree_sha256": code_tree_sha256,
            "dataset_specs": specs,
            "dataset_plans": plans,
            "invalidation_conditions": (
                "Stage 1 Data Run, Manifest, Catalog, logical hash, or Contract Price "
                "inventory changes",
                "Feature formula, availability, schema, evidence capability, or code tree changes",
                "Group-1 event semantics, identity, ownership, parameter, or "
                "preregistration changes",
                "Canonical serialization, stable sort, multiplicity, or comparison "
                "protocol changes",
            ),
        }
    )


def _snapshot_id(
    *,
    stage1_data_run_id: str,
    stage1_authorities: tuple[DigestBinding, ...],
    preregistration_manifest_sha256: str,
    config_sha256: str,
    code_tree_sha256: str,
    specs: tuple[DatasetSpec, ...],
) -> str:
    return metadata_sha256(
        {
            "schema_name": "stage2-v2-semantic-snapshot-identity",
            "snapshot_version": "2.0",
            "task": "S2-T10-v1.8",
            "change_requests": ("CR-2026-007", "CR-2026-008"),
            "stage1_data_run_id": stage1_data_run_id,
            "stage1_authorities": [
                item.model_dump(mode="json")
                for item in sorted(stage1_authorities, key=lambda item: item.name)
            ],
            "preregistration_manifest_sha256": preregistration_manifest_sha256,
            "config_sha256": config_sha256,
            "code_tree_sha256": code_tree_sha256,
            "dataset_spec_hashes": tuple(item.spec_hash for item in specs),
            "period": (START.isoformat(), END_EXCLUSIVE.isoformat()),
        }
    )


def _dataset_plans(
    *,
    snapshot_id: str,
    specs: tuple[DatasetSpec, ...],
) -> tuple[DatasetPlan, ...]:
    foundation_by_name = {item.dataset_name: item for item in feature_foundation_dataset_specs()}
    group1_by_hash = {item.spec.spec_hash: item for item in GROUP1_DATASET_BINDINGS}
    plans: list[DatasetPlan] = []
    for spec in specs:
        partitions: list[str] = []
        foundation = foundation_by_name.get(spec.dataset_name)
        if foundation is not None and foundation.spec_hash == spec.spec_hash:
            variant = FOUNDATION_VARIANTS[spec.dataset_name]
            for instrument in INSTRUMENTS:
                partitions.extend(
                    _partition_ids(
                        snapshot_id=snapshot_id,
                        spec=spec,
                        setup_id=FOUNDATION_SETUP_ID,
                        context_id=FOUNDATION_CONTEXT_ID,
                        instrument=instrument,
                        variant=variant,
                    )
                )
        else:
            binding = group1_by_hash.get(spec.spec_hash)
            if binding is None:
                raise AssertionError(f"unbound Runtime V2 DatasetSpec: {spec.dataset_name}")
            for instrument in INSTRUMENTS:
                partitions.extend(
                    _partition_ids(
                        snapshot_id=snapshot_id,
                        spec=spec,
                        setup_id=GROUP1_SETUP_ID,
                        context_id=GROUP1_CONTEXT_ID,
                        instrument=instrument,
                        variant=binding.variant,
                    )
                )
        plans.append(
            DatasetPlan(
                dataset_spec_hash=spec.spec_hash,
                expected_partition_ids=tuple(sorted(partitions)),
            )
        )
    return tuple(sorted(plans, key=lambda item: item.dataset_spec_hash))


def _partition_ids(
    *,
    snapshot_id: str,
    spec: DatasetSpec,
    setup_id: str,
    context_id: str,
    instrument: str,
    variant: str,
) -> tuple[str, ...]:
    current = START
    result: list[str] = []
    while current < END_EXCLUSIVE:
        result.append(
            LogicalPartitionKey(
                snapshot_id=snapshot_id,
                dataset_name=spec.dataset_name,
                dataset_version=spec.dataset_version,
                dataset_spec_hash=spec.spec_hash,
                setup_id=setup_id,
                context_id=context_id,
                instrument=instrument,
                variant=variant,
                owner_date=current,
            ).partition_id
        )
        current += timedelta(days=1)
    return tuple(result)
