from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from era100x.research.stage_2.labels.ambiguity import full_run
from era100x.research.stage_2.labels.first_passage import full_run as first_passage


S = 1_000_000_000
START = 10 * S


def _matrix_row() -> dict:
    state = first_passage._PassageState(
        episode={
            "instrument": "BTCUSDT",
            "market_episode_id": "a" * 64,
            "canonical_candidate_id": "b" * 64,
            "candidate_version_id": "c" * 64,
            "canonical_payload_hash": "d" * 64,
            "parameter_set_id": "G1-TIMING_T1-V1",
            "variant_id": "V1_PRICE",
            "research_role": "SENSITIVITY",
            "primary_eligible": False,
            "time_combination_id": "T1",
            "window_start_ns": START,
            "requested_window_end_ns": START + 60 * S,
            "window_end_ns": START + 60 * S,
            "window_truncated": False,
        },
        quality={
            "h1_missing_seconds": 0,
            "h2_source_partition_gap_count": 0,
            "ambiguity_codes": [],
        },
        lineage={"source_snapshot_id": "e" * 64, "stage1_data_run_id": "stage1"},
        reference_price=Decimal("100"),
        evidence_level="H1",
    )
    return state.output(
        {
            "source_s2t11_manifest_hash": "f" * 64,
            "source_s2t11_catalog_hash": "0" * 64,
        }
    )


def _write_source(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist([row], schema=first_passage.FIRST_PASSAGE_SCHEMA), path)


def test_rate_retains_exact_fraction_and_zero_denominator() -> None:
    assert full_run._rate(1, 4) == "0.25"
    assert full_run._rate(1, 3) == format(Decimal(1) / Decimal(3), "f")
    assert full_run._rate(0, 0) is None


def test_aggregate_source_accounts_for_matrix_once_and_keeps_30_groups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _matrix_row()
    source_path = tmp_path / "first_passage.parquet"
    _write_source(source_path, row)
    label_counts = dict(sorted(Counter(row["labels"]).items()))
    reason_counts = dict(sorted(Counter(row["label_reasons"]).items()))
    monkeypatch.setattr(full_run, "_source_path", lambda _instrument: source_path)
    monkeypatch.setattr(
        full_run,
        "_source_contract",
        lambda: {
            "source_instruments": {
                "BTCUSDT": {
                    "path_rows": 1,
                    "classification_count": 30,
                    "sha256": "1" * 64,
                    "label_counts": label_counts,
                    "label_reason_counts": reason_counts,
                }
            }
        },
    )

    output, summary = full_run._aggregate_source("BTCUSDT")

    assert output["path_rows"] == 1
    assert output["classification_count"] == 30
    assert output["distribution_count"] == 30
    assert output["label_counts"] == label_counts
    assert output["output_hash"] == full_run._json_hash(
        {key: value for key, value in output.items() if key != "output_hash"}
    )
    assert summary["ambiguous_count"] == 30
    assert summary["conditional_denominator"] == 0
    assert {item["evidence_level"] for item in output["distributions"]} == {"H1"}
    assert all(item["raw_ambiguous_preserved"] is True for item in output["distributions"])


def test_aggregate_source_rejects_h2_same_event_ambiguity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _matrix_row()
    row["evidence_level"] = "H2"
    row["labels"] = ["AMBIGUOUS"] * 30
    row["label_reasons"] = ["H1_SAME_EVENT_TARGET_AND_STOP"] * 30
    row["classification_row_hash"] = first_passage._json_hash(
        {key: value for key, value in row.items() if key != "classification_row_hash"}
    )
    source_path = tmp_path / "first_passage.parquet"
    _write_source(source_path, row)
    monkeypatch.setattr(full_run, "_source_path", lambda _instrument: source_path)
    monkeypatch.setattr(
        full_run,
        "_source_contract",
        lambda: {
            "source_instruments": {
                "BTCUSDT": {
                    "path_rows": 1,
                    "classification_count": 30,
                    "sha256": "1" * 64,
                    "label_counts": dict(Counter(row["labels"])),
                    "label_reason_counts": dict(Counter(row["label_reasons"])),
                }
            }
        },
    )

    with pytest.raises(ValueError, match="H2 cannot contain"):
        full_run._aggregate_source("BTCUSDT")


def test_preflight_is_self_hashed_and_creates_no_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority_root = tmp_path / "authorities/S2-T14"
    monkeypatch.setattr(full_run, "AUTHORITY_ROOT", authority_root)
    monkeypatch.setattr(full_run, "current_code_commit", lambda: "abc123")
    monkeypatch.setattr(
        full_run,
        "_source_contract",
        lambda: {
            "source_s2t13_run_id": "source-run",
            "combination_order": list(first_passage.COMBINATION_ORDER),
            "parameter_set_ids": ["G1-PRIMARY-V1"],
            "parameter_set_timing_pairs": [
                {"parameter_set_id": "G1-PRIMARY-V1", "timing_id": "T2"}
            ],
            "timing_ids": ["T2"],
            "evidence_levels": ["H1", "H2"],
            "expected_distribution_count_per_instrument": 60,
        },
    )

    authority, path = full_run.create_preflight_manifest(code_commit="abc123")

    assert authority["expected_classification_count"] == 31_962_480
    assert authority["expected_distribution_count"] == 2_280
    assert "run_id" not in authority
    assert json.loads(path.read_text())["authority_hash"] == authority["authority_hash"]
    assert not (tmp_path / "runs").exists()


def test_write_distribution_is_byte_bound_and_failed_run_cannot_resume(
    tmp_path: Path,
) -> None:
    output = {"task_id": "S2-T14", "output_hash": "a" * 64}
    summary = {"instrument": "BTCUSDT", "distribution_count": 1}
    path = tmp_path / "staging/BTCUSDT/ambiguity_distributions.json"

    result = full_run._write_distribution(path, output, summary)

    assert result["byte_size"] == path.stat().st_size
    assert result["sha256"] == full_run.sha256_file(path)
    run_root = tmp_path / "stage2-s2t14-ambiguity-bounds-20260721T000000Z-abcdef123456"
    (run_root / "reports").mkdir(parents=True)
    (run_root / "reports/failure.json").write_text("{}")
    with pytest.raises(ValueError, match="immutable"):
        full_run.resume_run(run_root)
