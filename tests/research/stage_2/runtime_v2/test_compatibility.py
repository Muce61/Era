from __future__ import annotations

import hashlib
from dataclasses import fields
from datetime import date, timedelta
from typing import Any

import pytest

from era100x.research.stage_2.manifests.models import canonical_json
from era100x.research.stage_2.runtime_v2.compatibility import (
    FORMAL_PERIOD_END_EXCLUSIVE,
    FORMAL_PERIOD_START,
    FORMAL_RUN_A_CATALOG_ENTRY_COUNT,
    LEGACY_HASH_ALGORITHM,
    PAYLOAD_AND_DISTRIBUTION_PROOF,
    CompatibilityMismatch,
    DailySemanticKey,
    DailySemanticRecord,
    GlobalDistribution,
    RunACompatibilityAuthority,
    RunAProjection,
    assert_run_a_v2_compatible,
    compare_run_a_to_v2,
    compare_run_a_to_v2_sorted_stream,
    project_formal_run_a,
    project_v2_receipts,
)
from era100x.research.stage_2.runtime_v2.errors import ContractViolation
from era100x.research.stage_2.runtime_v2.models import (
    LogicalPartitionKey,
    QualityFact,
    Receipt,
)

H1 = "a" * 64
H2 = "b" * 64
H3 = "c" * 64
H4 = "d" * 64
H5 = "e" * 64
H6 = "f" * 64

PRICE_DATASETS = (
    "arbitration",
    "candidate_inclusion",
    "canonical_key_levels",
    "flow_windows",
    "holds",
    "market_episodes",
    "price_triggers",
    "raw_key_levels",
    "reclaims",
    "sweeps",
)
FLOW_DATASETS = ("candidate_inclusion", "flow_features", "market_episodes")


def _global_distributions(*, primary: int = 1) -> dict[str, dict[str, int]]:
    return {
        "ownership_status": {"OWNED": primary},
        "parameter_set_id": {"G1-PRIMARY-V1": primary},
        "reason_code": {"CANONICAL_INCLUDED": primary},
        "research_role": {"PRIMARY": primary},
        "time_combination_id": {"T2": primary},
    }


def _normalized_distributions(*, primary: int = 1) -> tuple[GlobalDistribution, ...]:
    return tuple(
        GlobalDistribution(name=name, counts=tuple(sorted(values.items())))
        for name, values in sorted(_global_distributions(primary=primary).items())
    )


def _projection(
    *,
    owner_date: date = date(2020, 1, 1),
    logical_hash: str = H1,
    id_set_hash: str | None = None,
    row_count: int = 1,
) -> RunAProjection:
    return RunAProjection(
        source_run_id="formal-run-a",
        legacy_hash_algorithm=LEGACY_HASH_ALGORITHM,
        records=(
            DailySemanticRecord(
                key=DailySemanticKey(
                    instrument="BTCUSDT",
                    variant="V1_PRICE",
                    dataset="market_episodes",
                    owner_date=owner_date,
                ),
                row_count=row_count,
                empty=row_count == 0,
                legacy_logical_sha256=logical_hash,
                legacy_id_set_sha256=id_set_hash,
            ),
        ),
        global_distributions=_normalized_distributions(),
    )


def _receipt(
    *,
    owner_date: date = date(2020, 1, 1),
    logical_hash: str = H1,
    id_set_hash: str | None = None,
    row_count: int = 1,
    snapshot_id: str = H2,
) -> Receipt:
    quality_facts = (
        ()
        if id_set_hash is None
        else (QualityFact(name="legacy_id_set_sha256", value=id_set_hash),)
    )
    return Receipt.seal(
        {
            "snapshot_id": snapshot_id,
            "shard_id": "compatibility-test-shard",
            "partition": LogicalPartitionKey(
                snapshot_id=snapshot_id,
                dataset_name="market_episodes",
                dataset_version="1.0",
                dataset_spec_hash=H3,
                setup_id="KEY_LOW_SWEEP_RECLAIM_HOLD_V1",
                context_id="CAUSAL_EMA20_1H",
                instrument="BTCUSDT",
                variant="V1_PRICE",
                owner_date=owner_date,
            ),
            "terminal_state": "EMPTY" if row_count == 0 else "PRESENT",
            "row_count": row_count,
            "legacy_hash_algorithm": "ERA_CANONICAL_JSON_ROW_V1",
            "legacy_logical_sha256": logical_hash,
            "semantic_sha256": H4,
            "identity_multiset_sha256": H5,
            "payload_association_sha256": H6,
            "distributions": (),
            "quality_facts": quality_facts,
            "fragment_hashes": () if row_count == 0 else (H4,),
        }
    )


@pytest.fixture(scope="module")
def formal_run_a_documents() -> tuple[dict[str, Any], dict[str, Any], RunACompatibilityAuthority]:
    date_count = (FORMAL_PERIOD_END_EXCLUSIVE - FORMAL_PERIOD_START).days
    dates = tuple(
        (FORMAL_PERIOD_START + timedelta(days=offset)).isoformat() for offset in range(date_count)
    )
    groups = tuple(
        sorted(
            (instrument, variant, dataset)
            for instrument in ("BTCUSDT", "ETHUSDT")
            for variant, datasets in (
                ("V1_PRICE", PRICE_DATASETS),
                ("V1_FLOW", FLOW_DATASETS),
            )
            for dataset in datasets
        )
    )
    entries: list[dict[str, Any]] = []
    datasets: dict[str, Any] = {}
    for instrument, variant, dataset in groups:
        partition_hashes = {day: H1 for day in dates}
        datasets[f"{instrument}/{variant}/{dataset}"] = {
            "rows": 0,
            "partition_count": len(dates),
            "partition_logical_hashes": partition_hashes,
            "partition_id_set_hashes": {},
        }
        entries.extend(
            {
                "relative_path": (
                    f"instrument={instrument}/variant={variant}/{dataset}/"
                    f"date={day}/part-000.parquet"
                ),
                "rows": 0,
                "bytes": 123,
                "byte_sha256": H2,
                "logical_sha256": H1,
            }
            for day in dates
        )
    entries.sort(key=lambda item: str(item["relative_path"]))
    aggregate = hashlib.sha256()
    for entry in entries:
        aggregate.update(
            canonical_json(
                {
                    "relative_path": entry["relative_path"],
                    "rows": entry["rows"],
                    "logical_sha256": entry["logical_sha256"],
                }
            ).encode("utf-8")
        )
    logical_hash = aggregate.hexdigest()
    catalog = {
        "entries": entries,
        "logical_hash": logical_hash,
        "physical_hash": H6,
    }
    analysis = {
        "schema_name": "stage2-group1-release-analysis-v1",
        "catalog_logical_hash": logical_hash,
        "catalog_physical_hash": H5,
        "datasets": datasets,
        "distributions": _global_distributions(primary=0),
        "quality": {"status": "PASS"},
    }
    authority = RunACompatibilityAuthority(
        source_run_id="stage2-g1-full-a-formal",
        catalog_logical_hash=logical_hash,
        legacy_hash_algorithm=LEGACY_HASH_ALGORITHM,
    )
    assert len(entries) == FORMAL_RUN_A_CATALOG_ENTRY_COUNT
    return catalog, analysis, authority


def test_formal_run_a_projection_requires_all_daily_hashes_and_excludes_physical_facts(
    formal_run_a_documents: tuple[dict[str, Any], dict[str, Any], RunACompatibilityAuthority],
) -> None:
    catalog, analysis, authority = formal_run_a_documents

    projection = project_formal_run_a(catalog, analysis, authority=authority)

    assert len(projection.records) == FORMAL_RUN_A_CATALOG_ENTRY_COUNT
    assert projection.payload_and_distribution_proof == PAYLOAD_AND_DISTRIBUTION_PROOF
    field_names = {item.name for item in fields(DailySemanticRecord)}
    assert not field_names.intersection(
        {"snapshot_id", "relative_path", "physical_hash", "byte_sha256", "fragment_hash"}
    )


def test_formal_run_a_projection_fails_closed_on_incomplete_catalog() -> None:
    authority = RunACompatibilityAuthority(
        source_run_id="stage2-g1-full-a-formal",
        catalog_logical_hash=H1,
        legacy_hash_algorithm=LEGACY_HASH_ALGORITHM,
    )
    with pytest.raises(ContractViolation, match="61,776"):
        project_formal_run_a(
            {"entries": [], "logical_hash": H1},
            {},
            authority=authority,
        )


def test_formal_run_a_projection_requires_quality_pass(
    formal_run_a_documents: tuple[dict[str, Any], dict[str, Any], RunACompatibilityAuthority],
) -> None:
    catalog, analysis, authority = formal_run_a_documents
    failed_analysis = {**analysis, "quality": {"status": "FAIL", "unknown_count": 1}}

    with pytest.raises(ContractViolation, match="Quality is not PASS"):
        project_formal_run_a(catalog, failed_analysis, authority=authority)


def test_exact_comparison_passes_and_ignores_snapshot_and_physical_layout() -> None:
    run_a = _projection(id_set_hash=H2)
    receipt = _receipt(id_set_hash=H2, snapshot_id=H6)

    report = assert_run_a_v2_compatible(
        run_a,
        (receipt,),
        v2_legacy_hash_algorithm=LEGACY_HASH_ALGORITHM,
        v2_global_distributions=_global_distributions(),
    )

    assert report.status == "PASS"
    assert report.daily_row_hash_match_count == 1
    assert report.daily_id_set_checked_count == 1
    assert report.global_distributions_equal is True


def test_sorted_stream_comparison_matches_exact_result_and_rejects_reordering() -> None:
    records = tuple(_projection(owner_date=date(2020, 1, day)).records[0] for day in (1, 2))
    run_a = RunAProjection(
        source_run_id="run-a",
        legacy_hash_algorithm=LEGACY_HASH_ALGORITHM,
        records=records,
        global_distributions=_normalized_distributions(),
    )
    receipts = tuple(_receipt(owner_date=date(2020, 1, day)) for day in (1, 2))

    report = compare_run_a_to_v2_sorted_stream(
        run_a,
        receipts,
        v2_legacy_hash_algorithm=LEGACY_HASH_ALGORITHM,
        v2_global_distributions=_global_distributions(),
    )
    assert report.status == "PASS"
    assert report.matched_partition_count == 2
    with pytest.raises(ContractViolation, match="strictly sorted"):
        compare_run_a_to_v2_sorted_stream(
            run_a,
            tuple(reversed(receipts)),
            v2_legacy_hash_algorithm=LEGACY_HASH_ALGORITHM,
            v2_global_distributions=_global_distributions(),
        )


def test_row_hash_proves_payload_and_row_level_distributions_at_zero_tolerance() -> None:
    report = compare_run_a_to_v2(
        _projection(logical_hash=H1),
        (_receipt(logical_hash=H2),),
        v2_legacy_hash_algorithm=LEGACY_HASH_ALGORITHM,
        v2_global_distributions=_global_distributions(),
    )

    assert report.status == "FAIL"
    assert report.payload_and_distribution_proof == "CANONICAL_ROW_HASH_EQUALITY"
    assert {difference.field for difference in report.differences} == {"legacy_logical_sha256"}
    with pytest.raises(CompatibilityMismatch):
        report.require_pass()


def test_daily_id_set_is_compared_when_run_a_publishes_it() -> None:
    missing = compare_run_a_to_v2(
        _projection(id_set_hash=H2),
        (_receipt(id_set_hash=None),),
        v2_legacy_hash_algorithm=LEGACY_HASH_ALGORITHM,
        v2_global_distributions=_global_distributions(),
    )
    conflicting = compare_run_a_to_v2(
        _projection(id_set_hash=H2),
        (_receipt(id_set_hash=H3),),
        v2_legacy_hash_algorithm=LEGACY_HASH_ALGORITHM,
        v2_global_distributions=_global_distributions(),
    )

    assert missing.status == "FAIL"
    assert conflicting.status == "FAIL"
    assert {item.field for item in missing.differences} == {"legacy_id_set_sha256"}
    assert {item.field for item in conflicting.differences} == {"legacy_id_set_sha256"}


def test_missing_extra_and_duplicate_owner_days_fail() -> None:
    run_a = _projection(owner_date=date(2020, 1, 1))
    extra_receipt = _receipt(owner_date=date(2020, 1, 2))
    report = compare_run_a_to_v2(
        run_a,
        (extra_receipt,),
        v2_legacy_hash_algorithm=LEGACY_HASH_ALGORITHM,
        v2_global_distributions=_global_distributions(),
    )

    assert report.status == "FAIL"
    assert tuple(item.owner_date for item in report.missing_in_v2) == (date(2020, 1, 1),)
    assert tuple(item.owner_date for item in report.extra_in_v2) == (date(2020, 1, 2),)
    with pytest.raises(ContractViolation, match="conflicting V2 receipts"):
        project_v2_receipts(
            (_receipt(snapshot_id=H1), _receipt(snapshot_id=H2)),
            legacy_hash_algorithm=LEGACY_HASH_ALGORITHM,
        )


def test_global_distributions_are_compared_independently() -> None:
    report = compare_run_a_to_v2(
        _projection(),
        (_receipt(),),
        v2_legacy_hash_algorithm=LEGACY_HASH_ALGORITHM,
        v2_global_distributions=_global_distributions(primary=2),
    )

    assert report.status == "FAIL"
    assert report.global_distributions_equal is False
    assert {item.field for item in report.differences} == {"global_distributions"}


def test_unbound_or_wrong_legacy_hash_algorithm_fails_closed() -> None:
    with pytest.raises(ContractViolation, match="approved legacy hash algorithm"):
        project_v2_receipts((_receipt(),), legacy_hash_algorithm="unknown")
