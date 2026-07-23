from __future__ import annotations

from pathlib import Path

import pytest

from era100x.research.stage_2.pipelines.candidates import candidate_diagnostics
from era100x.research.stage_2.pipelines.candidates.candidate_diagnostics import (
    assert_code_commit_matches_head,
    classify_legacy_price_records,
)


def record(*, legacy_id: str, parameter: str, trigger_id: str, ordinal: int) -> dict[str, object]:
    return {
        "candidate_version_id": legacy_id,
        "event_parameter_set_id": parameter,
        "instrument": "BTCUSDT",
        "canonical_key_level_id": "1" * 64,
        "sweep_id": "2" * 64,
        "reclaim_id": "3" * 64,
        "hold_id": "4" * 64,
        "trigger_id": trigger_id,
        "available_at_ts": 1_577_836_800_000_000_001,
        "data_run_id": "stage1",
        "dataset_logical_hash": "5" * 64,
        "config_hash": "6" * 64,
        "market_episode_id": "7" * 64,
        "venue": "BINANCE_USDM",
        "sweep_start_ns": 1_577_836_790_000_000_000,
        "episode_status": "CANDIDATE",
        "source_processing_partition": "2020-01-01",
        "source_row_ordinal": ordinal,
        "source_file_logical_path": "date=2020-01-01/part-000.parquet",
    }


def test_legacy_conflict_splits_into_distinct_canonical_candidates() -> None:
    rows = [
        record(
            legacy_id="a",
            parameter="G1-PRIMARY-V1",
            trigger_id="8" * 64,
            ordinal=0,
        ),
        record(
            legacy_id="a",
            parameter="G1-TIMING_T1-V1",
            trigger_id="9" * 64,
            ordinal=1,
        ),
    ]
    result = classify_legacy_price_records(rows, {"G1-PRIMARY-V1": "T2", "G1-TIMING_T1-V1": "T1"})
    assert result.summary["case_c_group_count"] == 1
    assert result.summary["case_c_row_count"] == 2
    assert result.summary["legacy_excess_count"] == 1
    assert result.summary["canonical_candidate_count"] == 2
    assert result.summary["canonical_identity_conflict_count"] == 0
    assert all(
        row["classification"] == "LEGACY_IDENTITY_CONFLICT_SPLIT_APPROVED"
        for row in result.classifications
    )


def test_diagnosis_is_input_order_independent() -> None:
    rows = [
        record(
            legacy_id=str(index),
            parameter="G1-PRIMARY-V1",
            trigger_id=f"{index:064x}",
            ordinal=index,
        )
        for index in range(5)
    ]
    timing = {"G1-PRIMARY-V1": "T2"}
    assert classify_legacy_price_records(rows, timing) == classify_legacy_price_records(
        list(reversed(rows)), timing
    )


def test_diagnostic_evidence_rejects_a_code_commit_other_than_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        candidate_diagnostics.subprocess,
        "check_output",
        lambda *args, **kwargs: "a" * 40 + "\n",
    )
    with pytest.raises(ValueError, match="current HEAD"):
        assert_code_commit_matches_head("b" * 40)
    assert not (tmp_path / "evidence").exists()
