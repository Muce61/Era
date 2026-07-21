from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pyarrow as pa

from era100x.research.stage_2.labels.first_passage import full_run

S = 1_000_000_000
START = 10 * S


def _episode() -> dict:
    return {
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
    }


def _quality() -> dict:
    return {
        "h1_missing_seconds": 0,
        "h2_source_partition_gap_count": 0,
        "ambiguity_codes": [],
    }


def _lineage() -> dict:
    return {"source_snapshot_id": "e" * 64, "stage1_data_run_id": "stage1-baseline"}


def _source() -> dict[str, str]:
    return {
        "source_s2t11_manifest_hash": "f" * 64,
        "source_s2t11_catalog_hash": "0" * 64,
    }


def _h1_state() -> full_run._PassageState:
    return full_run._PassageState(
        episode=_episode(),
        quality=_quality(),
        lineage=_lineage(),
        reference_price=Decimal("100"),
        evidence_level="H1",
    )


def _decimal(values: list[str]) -> pa.Array:
    return pa.array([Decimal(value) for value in values], type=full_run.DECIMAL_TYPE)


def test_full_matrix_uses_each_episode_frozen_timing_and_all_target_stop_pairs() -> None:
    state = _h1_state()
    timestamps = [START + index * S for index in range(60)]
    highs = ["100"] * 60
    lows = ["100"] * 60
    highs[10] = "100.20"
    lows[20] = "99.85"
    state.update_h1(timestamps, _decimal(highs), _decimal(lows))

    row = state.output(_source())

    assert row["timing_id"] == "T1"
    assert row["horizon_seconds"] == 60
    assert row["classification_count"] == 30
    assert row["combination_order"] == list(full_run.COMBINATION_ORDER)
    assert row["labels"][0] == "TARGET_FIRST"
    assert row["strict_target_first"][0] is True
    assert row["classification_row_hash"] == full_run._json_hash(
        {key: value for key, value in row.items() if key != "classification_row_hash"}
    )


def test_h1_same_event_is_ambiguous_and_gap_after_decision_does_not_rewrite() -> None:
    same = _h1_state()
    same.update_h1(
        [START],
        _decimal(["100.20"]),
        _decimal(["99.85"]),
    )
    same_row = same.output(_source())
    assert same_row["labels"][0] == "AMBIGUOUS"
    assert same_row["label_reasons"][0] == "H1_SAME_EVENT_TARGET_AND_STOP"
    assert same_row["conservative_main_labels"][0] == "STOP_FIRST"

    after = _h1_state()
    after.update_h1(
        [START, START + S],
        _decimal(["100", "100.20"]),
        _decimal(["100", "100"]),
    )
    after.update_h1(
        [START + 3 * S],
        _decimal(["100"]),
        _decimal(["100"]),
    )
    after_row = after.output(_source())
    assert after_row["labels"][0] == "TARGET_FIRST"
    assert after_row["source_gap_codes"] == ["H1_MISSING_SECONDS"]


def test_h2_gap_before_touch_fails_closed_but_stable_order_is_preserved() -> None:
    state = full_run._PassageState(
        episode=_episode(),
        quality={**_quality(), "h2_source_partition_gap_count": 1},
        lineage=_lineage(),
        reference_price=Decimal("100"),
        evidence_level="H2",
    )
    state.update_h2(
        [START, START + S],
        pa.array([100, 102], type=pa.int64()),
        _decimal(["100", "100.20"]),
    )

    row = state.output(_source())

    assert row["labels"][0] == "AMBIGUOUS"
    assert row["label_reasons"][0] == "SOURCE_GAP_BEFORE_DECISION"
    assert row["stable_order"] == ["ts_event_ns", "venue_trade_id", "canonical_trade_id"]
    assert row["observed_uncertainty_before_order"] == 1


def test_preflight_is_self_hashed_and_creates_no_run_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    stage2_root = tmp_path / "stage2"
    authority_root = stage2_root / "authorities/S2-T13"
    stage2_root.mkdir()
    monkeypatch.setattr(full_run, "STAGE2_ROOT", stage2_root)
    monkeypatch.setattr(full_run, "AUTHORITY_ROOT", authority_root)
    monkeypatch.setattr(full_run, "current_code_commit", lambda: "abc123")
    monkeypatch.setattr(
        full_run,
        "_episode_counts_and_timings",
        lambda: (
            {"BTCUSDT": 10, "ETHUSDT": 12},
            {"T1": 1, "T2": 19, "T3": 1, "T4": 1},
        ),
    )
    monkeypatch.setattr(full_run, "_source_binding", lambda: {"source": "frozen"})

    authority, path = full_run.create_preflight_manifest(code_commit="abc123")

    assert authority["expected_path_rows"] == 44
    assert authority["expected_classification_count"] == 1320
    assert "run_id" not in authority
    assert json.loads(path.read_text())["authority_hash"] == authority["authority_hash"]
    assert not (stage2_root / "runs").exists()


def test_parquet_round_trip_preserves_row_hash_and_matrix_contract(tmp_path: Path) -> None:
    state = _h1_state()
    timestamps = [START + index * S for index in range(60)]
    state.update_h1(timestamps, _decimal(["100"] * 60), _decimal(["100"] * 60))
    row = state.output(_source())
    path = tmp_path / "first_passage.parquet"
    writer = full_run._Writer(path)
    writer.append(row)
    writer.close()
    summary = {
        "byte_size": path.stat().st_size,
        "sha256": full_run.sha256_file(path),
        "first_passage": writer.summary(),
    }

    verified = full_run._verify_output(path, "BTCUSDT", summary)

    assert verified["row_count"] == 1
    assert verified["classification_count"] == 30


def test_failed_run_is_not_resumable(tmp_path: Path, monkeypatch) -> None:
    run_root = tmp_path / "stage2-s2t13-first-passage-20260721T000000Z-abcdef123456"
    (run_root / "reports").mkdir(parents=True)
    (run_root / "manifests").mkdir()
    (run_root / "reports/failure.json").write_text("{}")
    monkeypatch.setattr(full_run, "RUNS_ROOT", tmp_path)

    try:
        full_run.resume_run(run_root)
    except ValueError as exc:
        assert "immutable" in str(exc)
    else:
        raise AssertionError("failed run unexpectedly resumed")
