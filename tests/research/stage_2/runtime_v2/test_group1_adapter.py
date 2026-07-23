from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from era100x.research.stage_2.manifests.configuration import (
    parameter_sets,
    research_classification,
)
from era100x.research.stage_2.pipelines.candidates.io import records_logical_hash
from era100x.research.stage_2.runtime_v2.catalog import ArtifactStoreV2, CatalogCompactorV2
from era100x.research.stage_2.runtime_v2.dataset_specs import (
    FLOW_DATASETS,
    PRICE_DATASETS,
    GROUP1_DATASET_BINDINGS,
    Group1DatasetBinding,
    group1_dataset_binding,
    group1_dataset_specs,
)
from era100x.research.stage_2.runtime_v2.errors import ContractViolation
from era100x.research.stage_2.runtime_v2.group1_adapter import prepare_group1_partition
from era100x.research.stage_2.runtime_v2.hashing import canonical_arrow_schema

SNAPSHOT = "a" * 64
OWNER_DATE = date(2020, 1, 1)
DAY_START_NS = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp()) * 1_000_000_000


def _sample(binding: Group1DatasetBinding, *, ordinal: int = 1) -> dict[str, Any]:
    fields = binding.spec.fields
    values: dict[str, Any] = {}
    for field in fields:
        if field.nullable:
            values[field.name] = None
        elif field.data_type == "utf8":
            values[field.name] = f"value-{ordinal}"
        elif field.data_type == "int64":
            values[field.name] = DAY_START_NS + ordinal
        elif field.data_type == "bool":
            values[field.name] = False
        elif field.data_type in {"list", "large_list"}:
            values[field.name] = [f"member-{ordinal}"]
        elif field.data_type == "struct":
            values[field.name] = {
                child.name: (ordinal if child.data_type == "int64" else f"metadata-{ordinal}")
                for child in field.children
            }
        else:  # pragma: no cover - the approved Group-1 registry is intentionally small
            raise AssertionError(field.data_type)

    id_text = f"{ordinal:064x}"
    values.update(
        {
            name: id_text
            for name in values
            if name.endswith("_id")
            and name not in {"parameter_set_id", "time_combination_id"}
            and values[name] is not None
        }
    )
    for name in ("dataset_logical_hash", "config_hash", "canonical_payload_hash"):
        if name in values:
            values[name] = id_text
    if "instrument" in values:
        values["instrument"] = "BTCUSDT"
    if "data_run_id" in values:
        values["data_run_id"] = "stage1-v1.0"
    if "code_version" in values:
        values["code_version"] = "abcdef0"
    if "parameter_set_id" in values:
        values["parameter_set_id"] = (
            "G1-PRIMARY-V1"
            if "time_combination_id" in values or binding.dataset == "flow_windows"
            else "KEYLEVEL-BASE-V1"
        )
    if "event_parameter_set_id" in values:
        values["event_parameter_set_id"] = "G1-PRIMARY-V1"
    if "time_combination_id" in values:
        values["time_combination_id"] = "T2"
    if "research_role" in values:
        values["research_role"] = "PRIMARY"
    if "primary_eligible" in values:
        values["primary_eligible"] = True
    for name in ("variant", "variant_id"):
        if name in values:
            values[name] = binding.variant
    if "canonical_candidate_id" in values:
        values["canonical_candidate_id"] = id_text
    if "candidate_version_id" in values:
        values["candidate_version_id"] = id_text
    if "owner_partition" in values:
        values["owner_partition"] = OWNER_DATE.isoformat()
    for name in (
        "available_at_ts",
        "window_end_ts",
        "trigger_available_at_ts",
        "detection_ts",
        "sweep_detection_ts",
    ):
        if name in values:
            values[name] = DAY_START_NS + 10_000_000_000 + ordinal
    if "window_start_ts" in values:
        values["window_start_ts"] = DAY_START_NS + 5_000_000_000 + ordinal
    if "source_start_ts" in values:
        values["source_start_ts"] = DAY_START_NS + ordinal
    if "source_end_ts" in values:
        values["source_end_ts"] = DAY_START_NS + 1_000_000_000 + ordinal
    if "formed_at_ns" in values:
        values["formed_at_ns"] = DAY_START_NS + 1_000_000_000 + ordinal
    if "expires_at_ns" in values:
        values["expires_at_ns"] = DAY_START_NS + 60_000_000_000 + ordinal
    if "owner_partition" in values:
        values["owner_partition"] = OWNER_DATE.isoformat()
    if "included" in values:
        values["included"] = True
    if "ownership_status" in values:
        values["ownership_status"] = "OWNED"
    if "consumed" in values:
        values["consumed"] = False
    if "flow_feature_set_id" in values:
        values["flow_feature_set_id"] = id_text if binding.variant == "V1_FLOW" else None
    return values


def _prepare(binding: Group1DatasetBinding, records: list[dict[str, Any]]):
    return prepare_group1_partition(
        snapshot_id=SNAPSHOT,
        instrument="BTCUSDT",
        variant=binding.variant,
        dataset=binding.dataset,
        owner_date=OWNER_DATE,
        records=records,
    )


def test_registry_freezes_exactly_ten_price_and_three_flow_specs() -> None:
    assert (
        tuple(
            binding.dataset for binding in GROUP1_DATASET_BINDINGS if binding.variant == "V1_PRICE"
        )
        == PRICE_DATASETS
    )
    assert (
        tuple(
            binding.dataset for binding in GROUP1_DATASET_BINDINGS if binding.variant == "V1_FLOW"
        )
        == FLOW_DATASETS
    )
    assert len(group1_dataset_specs()) == 13
    assert len({spec.spec_hash for spec in group1_dataset_specs()}) == 13


def test_unknown_dataset_or_variant_fails_closed() -> None:
    with pytest.raises(ValueError, match="unapproved"):
        group1_dataset_binding("V1_PRICE", "new_event")
    with pytest.raises(ContractViolation, match="unapproved"):
        prepare_group1_partition(
            snapshot_id=SNAPSHOT,
            instrument="BTCUSDT",
            variant="V2_UNKNOWN",
            dataset="market_episodes",
            owner_date=OWNER_DATE,
            records=[],
        )


def test_all_thirteen_approved_outputs_prepare_without_run_a_artifact_reads() -> None:
    for binding in GROUP1_DATASET_BINDINGS:
        prepared = _prepare(binding, [_sample(binding)])
        assert prepared.row_count == 1
        assert prepared.batch.key.variant == binding.variant
        assert prepared.batch.key.dataset_name == binding.dataset
        assert prepared.batch.table.schema.equals(
            canonical_arrow_schema(binding.spec), check_metadata=False
        )


def test_nested_list_and_struct_are_canonical_arrow_fields() -> None:
    binding = group1_dataset_binding("V1_PRICE", "canonical_key_levels")
    record = _sample(binding)
    prepared = _prepare(binding, [record])

    assert (
        prepared.batch.table["member_key_level_ids"].type
        == canonical_arrow_schema(binding.spec).field("member_key_level_ids").type
    )
    assert (
        prepared.batch.table["metadata"].type
        == canonical_arrow_schema(binding.spec).field("metadata").type
    )


def test_legacy_and_v2_hashes_are_computed_from_generation_records() -> None:
    binding = group1_dataset_binding("V1_PRICE", "market_episodes")
    first = _sample(binding, ordinal=1)
    second = _sample(binding, ordinal=2)

    forward = _prepare(binding, [first, second])
    reverse = _prepare(binding, [second, first])

    assert forward.legacy_logical_sha256 == records_logical_hash([first, second], "market_episodes")
    assert forward.legacy_logical_sha256 == reverse.legacy_logical_sha256
    assert forward.v2_semantic_sha256 == reverse.v2_semantic_sha256


def test_empty_owner_day_generates_receipt_without_empty_parquet(tmp_path: Path) -> None:
    binding = group1_dataset_binding("V1_PRICE", "arbitration")
    prepared = _prepare(binding, [])
    result = CatalogCompactorV2(ArtifactStoreV2(tmp_path)).compact(
        spec=binding.spec,
        snapshot_id=SNAPSHOT,
        shard_id="btc-price-arbitration-2020-01",
        partitions=(prepared.batch,),
    )

    assert prepared.legacy_logical_sha256 == records_logical_hash([], "arbitration")
    assert result.artifact is None
    assert result.fragments == ()
    assert result.receipts[0].terminal_state == "EMPTY"
    assert result.receipts[0].row_count == 0
    assert not tuple(tmp_path.rglob("*.parquet"))


def test_nonempty_nested_partition_feeds_catalog_compactor(tmp_path: Path) -> None:
    binding = group1_dataset_binding("V1_PRICE", "canonical_key_levels")
    prepared = _prepare(binding, [_sample(binding)])
    result = CatalogCompactorV2(ArtifactStoreV2(tmp_path)).compact(
        spec=binding.spec,
        snapshot_id=SNAPSHOT,
        shard_id="btc-price-canonical-2020-01",
        partitions=(prepared.batch,),
    )

    assert result.artifact is not None
    assert result.receipts[0].terminal_state == "PRESENT"
    assert result.receipts[0].legacy_logical_sha256 == prepared.legacy_logical_sha256
    assert result.receipts[0].semantic_sha256 == prepared.v2_semantic_sha256
    expected_id_hash = hashlib.sha256(f"{1:064x}".encode()).hexdigest()
    facts = {item.name: item.value for item in result.receipts[0].quality_facts}
    assert facts["legacy_id_set_sha256"] == expected_id_hash


def test_arbitration_exact_duplicate_multiplicity_is_preserved(tmp_path: Path) -> None:
    binding = group1_dataset_binding("V1_PRICE", "arbitration")
    record = _sample(binding)
    prepared = _prepare(binding, [record, deepcopy(record)])
    result = CatalogCompactorV2(ArtifactStoreV2(tmp_path)).compact(
        spec=binding.spec,
        snapshot_id=SNAPSHOT,
        shard_id="btc-price-arbitration-multiset",
        partitions=(prepared.batch,),
    )

    assert binding.spec.row_multiplicity == "MULTISET_STABLE"
    assert prepared.row_count == 2
    assert prepared.legacy_logical_sha256 == records_logical_hash([record, record], "arbitration")
    assert result.receipts[0].row_count == 2


def test_canonical_snapshots_share_identity_but_preserve_distinct_expiry(tmp_path: Path) -> None:
    binding = group1_dataset_binding("V1_PRICE", "canonical_key_levels")
    first = _sample(binding)
    second = deepcopy(first)
    second["expires_at_ns"] = int(first["expires_at_ns"]) + 60_000_000_000
    prepared = _prepare(binding, [second, first])
    result = CatalogCompactorV2(ArtifactStoreV2(tmp_path)).compact(
        spec=binding.spec,
        snapshot_id=SNAPSHOT,
        shard_id="btc-price-canonical-snapshots",
        partitions=(prepared.batch,),
    )

    assert prepared.row_count == 2
    assert result.receipts[0].row_count == 2
    assert result.receipts[0].identity_multiset_sha256


def test_same_stable_key_with_different_nested_payload_fails_closed() -> None:
    binding = group1_dataset_binding("V1_PRICE", "arbitration")
    first = _sample(binding)
    conflicting = deepcopy(first)
    conflicting["member_key_level_ids"] = ["different-member"]

    with pytest.raises(ContractViolation, match="stable multiset key"):
        _prepare(binding, [first, conflicting])


def test_primary_exploratory_and_variant_mismatches_fail_closed() -> None:
    binding = group1_dataset_binding("V1_PRICE", "market_episodes")
    role_mismatch = _sample(binding)
    role_mismatch["research_role"] = "EXPLORATORY"
    with pytest.raises(ContractViolation, match="role mismatch"):
        _prepare(binding, [role_mismatch])

    variant_mismatch = _sample(binding)
    variant_mismatch["variant_id"] = "V1_FLOW"
    with pytest.raises(ContractViolation, match="variant_id"):
        _prepare(binding, [variant_mismatch])


@pytest.mark.parametrize("registered", parameter_sets(), ids=lambda item: item.parameter_set_id)
def test_all_twenty_parameter_sets_preserve_registered_research_role(registered: Any) -> None:
    binding = group1_dataset_binding("V1_PRICE", "market_episodes")
    record = _sample(binding)
    role, eligible = research_classification(registered.parameter_set_id, registered.timing_id)
    record["parameter_set_id"] = registered.parameter_set_id
    record["time_combination_id"] = registered.timing_id
    record["research_role"] = role
    record["primary_eligible"] = eligible

    prepared = _prepare(binding, [record])

    assert prepared.batch.table["parameter_set_id"][0].as_py() == registered.parameter_set_id
    assert prepared.batch.table["research_role"][0].as_py() == role


def test_owner_day_is_left_closed_right_open_and_outside_rows_fail() -> None:
    binding = group1_dataset_binding("V1_PRICE", "market_episodes")
    at_start = _sample(binding)
    at_start["available_at_ts"] = DAY_START_NS
    _prepare(binding, [at_start])

    at_end = _sample(binding)
    at_end["available_at_ts"] = DAY_START_NS + 86_400_000_000_000
    with pytest.raises(ContractViolation, match="outside"):
        _prepare(binding, [at_end])


@pytest.mark.parametrize(
    "dataset",
    (
        "raw_key_levels",
        "canonical_key_levels",
        "arbitration",
        "sweeps",
        "reclaims",
        "holds",
        "price_triggers",
    ),
)
def test_legacy_price_facts_preserve_processing_partition_across_midnight(
    dataset: str,
) -> None:
    binding = group1_dataset_binding("V1_PRICE", dataset)
    record = _sample(binding)
    if "available_at_ts" in record:
        record["available_at_ts"] = DAY_START_NS + 86_400_000_000_000

    prepared = _prepare(binding, [record])

    assert prepared.batch.key.owner_date == date(2020, 1, 1)
    assert binding.spec.ownership_mode == "PARTITION_KEY_ONLY"


def test_binary_float_and_execution_metadata_are_rejected() -> None:
    binding = group1_dataset_binding("V1_PRICE", "sweeps")
    binary_float = _sample(binding)
    binary_float["metadata"] = {"confirmation_bps": 2.0}
    with pytest.raises(ContractViolation, match="binary floats"):
        _prepare(binding, [binary_float])

    run_bound = _sample(binding)
    run_bound["run_id"] = "forbidden-execution-metadata"
    with pytest.raises(ContractViolation, match="extra"):
        _prepare(binding, [run_bound])
