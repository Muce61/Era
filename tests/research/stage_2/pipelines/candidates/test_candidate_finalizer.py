from __future__ import annotations

from copy import deepcopy

import pytest

from era100x.research.stage_2.pipelines.candidates.candidate_finalizer import (
    CandidateIdentityConflict,
    finalize_candidate_attempts,
    owner_partition,
    partition_bounds,
)

DAY_START = 1_577_836_800_000_000_000


def attempt(
    *,
    canonical_id: str = "1" * 64,
    payload_hash: str = "2" * 64,
    source_partition: str = "2020-01-01",
    ordinal: int = 0,
    available_at_ts: int = DAY_START + 10,
    instrument: str = "BTCUSDT",
    timing: str = "T2",
    parameter: str = "G1-PRIMARY-V1",
) -> dict[str, object]:
    return {
        "instrument": instrument,
        "data_run_id": "stage1",
        "dataset_logical_hash": "a" * 64,
        "config_hash": "b" * 64,
        "code_version": "abcdef0",
        "parameter_set_id": parameter,
        "available_at_ts": available_at_ts,
        "market_episode_id": "c" * 64,
        "canonical_candidate_id": canonical_id,
        "candidate_version_id": canonical_id,
        "canonical_payload_hash": payload_hash,
        "venue": "BINANCE_USDM",
        "direction": "LONG",
        "canonical_key_level_id": "d" * 64,
        "sweep_id": "e" * 64,
        "reclaim_id": "f" * 64,
        "hold_id": "0" * 64,
        "trigger_id": "3" * 64,
        "flow_feature_set_id": None,
        "variant": "V1_PRICE",
        "time_combination_id": timing,
        "sweep_start_ns": DAY_START,
        "episode_status": "CANDIDATE",
        "consumed": False,
        "consumed_by_intent_id": None,
        "rearm_eligible_at_ns": None,
        "event_parameter_set_id": parameter,
        "trigger_available_at_ts": available_at_ts,
        "window_start_ts": available_at_ts - 5_000_000_000,
        "window_end_ts": available_at_ts,
        "source_processing_partition": source_partition,
        "source_row_ordinal": ordinal,
        "source_file_logical_path": (
            f"instrument={instrument}/variant=V1_PRICE/candidate_attempts/"
            f"date={source_partition}/part-000.parquet"
        ),
    }


def test_exact_duplicate_selects_one_canonical_and_audits_exclusion() -> None:
    later = attempt(ordinal=9)
    earlier = attempt(ordinal=1)

    result = finalize_candidate_attempts([later, earlier])

    assert result.summary["canonical_count"] == 1
    assert result.summary["exact_duplicate_excluded_count"] == 1
    assert len(result.market_episodes_by_date["2020-01-01"]) == 1
    assert sum(bool(row["included"]) for row in result.audit_records) == 1
    excluded = next(row for row in result.audit_records if not row["included"])
    assert excluded["duplicate_of_candidate_id"] == "1" * 64
    assert excluded["excluded_reason"] == "EXACT_DUPLICATE_EXCLUDED"


def test_same_identity_different_payload_is_a_hard_conflict() -> None:
    conflict = attempt(payload_hash="9" * 64, ordinal=1)
    with pytest.raises(CandidateIdentityConflict) as raised:
        finalize_candidate_attempts([attempt(), conflict])
    assert raised.value.conflicts[0]["attempt_count"] == 2


def test_input_and_worker_order_do_not_change_output_or_audit_hash() -> None:
    records = [attempt(canonical_id=f"{number:064x}", ordinal=number) for number in range(6)]
    forward = finalize_candidate_attempts(records)
    reverse = finalize_candidate_attempts(list(reversed(records)))
    assert forward == reverse
    assert forward.summary["audit_logical_hash"] == reverse.summary["audit_logical_hash"]


def test_out_of_partition_context_is_rehomed_to_available_date() -> None:
    record = attempt(source_partition="2019-12-31")
    result = finalize_candidate_attempts([record])

    assert len(result.market_episodes_by_date["2020-01-01"]) == 1
    assert result.summary["out_of_partition_context_count"] == 1
    assert any(
        row["reason_code"] == "OUT_OF_PARTITION_CONTEXT" and not row["included"]
        for row in result.audit_records
    )
    assert any(
        row["reason_code"] == "CANONICAL_REHOMED_TO_OWNER" and row["included"]
        for row in result.audit_records
    )


def test_cross_month_context_is_owned_by_february_partition() -> None:
    february_start = 1_580_515_200_000_000_000
    record = attempt(
        source_partition="2020-01-31",
        available_at_ts=february_start,
    )
    result = finalize_candidate_attempts([record])
    assert list(result.market_episodes_by_date) == ["2020-02-01"]
    assert result.summary["out_of_partition_context_count"] == 1


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        (DAY_START - 1, "2019-12-31"),
        (DAY_START, "2020-01-01"),
        (DAY_START + 86_400_000_000_000 - 1, "2020-01-01"),
        (DAY_START + 86_400_000_000_000, "2020-01-02"),
    ],
)
def test_partition_boundary_is_left_closed_right_open(timestamp: int, expected: str) -> None:
    assert owner_partition(timestamp) == expected
    start, end = partition_bounds(expected)
    assert start <= timestamp < end


def test_btc_eth_and_timing_are_isolated_by_canonical_identity() -> None:
    btc = attempt()
    eth = attempt(instrument="ETHUSDT", canonical_id="4" * 64)
    timing = attempt(timing="T1", parameter="G1-TIMING_T1-V1", canonical_id="5" * 64)
    result = finalize_candidate_attempts([btc, eth, timing])
    assert result.summary["canonical_count"] == 3


def test_canonical_input_is_not_mutated() -> None:
    record = attempt()
    original = deepcopy(record)
    finalize_candidate_attempts([record])
    assert record == original
