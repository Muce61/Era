from __future__ import annotations

from era100x.research.stage_2.runtime_v2.manifest_factory import (
    EXPECTED_LOGICAL_PARTITIONS,
    FOUNDATION_CONTEXT_ID,
    FOUNDATION_SETUP_ID,
    build_runtime_v2_manifest,
)
from era100x.research.stage_2.runtime_v2.models import DigestBinding
from era100x.research.stage_2.runtime_v2.source_authority import (
    CONTRACT_PRICE_MANIFEST_AUTHORITY,
    TRADES_RESOLVED_INDEX_AUTHORITY,
)


def _manifest(*, code_tree_sha256: str = "5" * 64):
    return build_runtime_v2_manifest(
        stage1_data_run_id="stage1-v1.0-example",
        stage1_authorities=(
            DigestBinding(name="trades_eth_logical", sha256="2" * 64),
            DigestBinding(name="stage1_manifest", sha256="1" * 64),
            DigestBinding(name="trades_btc_logical", sha256="3" * 64),
            DigestBinding(name="contract_price_inventory", sha256="4" * 64),
            DigestBinding(name=CONTRACT_PRICE_MANIFEST_AUTHORITY, sha256="8" * 64),
            DigestBinding(name=TRADES_RESOLVED_INDEX_AUTHORITY, sha256="9" * 64),
        ),
        preregistration_manifest_sha256="6" * 64,
        config_sha256="7" * 64,
        code_tree_sha256=code_tree_sha256,
    )


def test_manifest_factory_freezes_complete_unique_matrix() -> None:
    manifest = _manifest()

    assert len(manifest.dataset_specs) == 17
    assert len(manifest.dataset_plans) == 17
    assert (
        sum(len(plan.expected_partition_ids) for plan in manifest.dataset_plans)
        == EXPECTED_LOGICAL_PARTITIONS
    )
    partition_ids = {
        partition_id
        for plan in manifest.dataset_plans
        for partition_id in plan.expected_partition_ids
    }
    assert len(partition_ids) == EXPECTED_LOGICAL_PARTITIONS
    assert tuple(item.name for item in manifest.stage1_authorities) == (
        "contract_price_inventory",
        CONTRACT_PRICE_MANIFEST_AUTHORITY,
        "stage1_manifest",
        TRADES_RESOLVED_INDEX_AUTHORITY,
        "trades_btc_logical",
        "trades_eth_logical",
    )
    assert manifest.manifest_hash == manifest.computed_hash()

    foundation_plan = next(
        plan
        for plan in manifest.dataset_plans
        if next(
            spec for spec in manifest.dataset_specs if spec.spec_hash == plan.dataset_spec_hash
        ).dataset_name
        == "contract_price_1s"
    )
    assert len(foundation_plan.expected_partition_ids) == 4_752
    assert FOUNDATION_SETUP_ID == "FEATURE_FOUNDATION"
    assert FOUNDATION_CONTEXT_ID == "FROZEN_STAGE1"


def test_manifest_factory_is_deterministic_and_invalidates_on_code_change() -> None:
    first = _manifest()
    second = _manifest()
    changed = _manifest(code_tree_sha256="8" * 64)

    assert first == second
    assert first.snapshot_id == second.snapshot_id
    assert first.manifest_hash == second.manifest_hash
    assert changed.snapshot_id != first.snapshot_id
    assert changed.manifest_hash != first.manifest_hash
