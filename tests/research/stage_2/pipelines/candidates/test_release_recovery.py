from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from era100x.research.stage_2.pipelines.candidates.io import catalog_tree, write_partition
from era100x.research.stage_2.pipelines.candidates.release import FLOW_DATASETS, PRICE_DATASETS
from era100x.research.stage_2.pipelines.candidates.release_recovery import single_scan_release

DAY_START = 1_577_836_800_000_000_000


def _candidate(instrument: str, variant: str, identifier: str) -> dict[str, object]:
    return {
        "instrument": instrument,
        "data_run_id": "stage1",
        "dataset_logical_hash": "1" * 64,
        "config_hash": "2" * 64,
        "code_version": "a" * 40,
        "parameter_set_id": "G1-PRIMARY-V1",
        "available_at_ts": DAY_START + 1,
        "market_episode_id": "3" * 64,
        "canonical_candidate_id": identifier,
        "candidate_version_id": identifier,
        "canonical_payload_hash": "4" * 64,
        "venue": "BINANCE_USDM",
        "direction": "LONG",
        "canonical_key_level_id": "5" * 64,
        "sweep_id": "6" * 64,
        "reclaim_id": "7" * 64,
        "hold_id": "8" * 64,
        "trigger_id": "9" * 64,
        "flow_feature_set_id": None if variant == "V1_PRICE" else "b" * 64,
        "variant": variant,
        "variant_id": variant,
        "time_combination_id": "T2",
        "research_role": "PRIMARY",
        "primary_eligible": True,
        "sweep_start_ns": DAY_START,
        "episode_status": "CANDIDATE",
        "consumed": False,
        "consumed_by_intent_id": None,
        "rearm_eligible_at_ns": None,
        "event_parameter_set_id": "G1-PRIMARY-V1",
    }


def _inclusion(candidate: dict[str, object]) -> dict[str, object]:
    keep = (
        "instrument",
        "data_run_id",
        "dataset_logical_hash",
        "config_hash",
        "code_version",
        "parameter_set_id",
        "available_at_ts",
        "market_episode_id",
        "canonical_candidate_id",
        "candidate_version_id",
        "canonical_payload_hash",
        "variant_id",
        "time_combination_id",
        "research_role",
        "primary_eligible",
    )
    return {key: candidate[key] for key in keep} | {
        "inclusion_id": "c" * 64,
        "included": True,
        "reason_code": "CANONICAL_INCLUDED",
        "deduplication_key": candidate["canonical_candidate_id"],
        "ownership_status": "OWNED",
        "duplicate_of_candidate_id": None,
        "source_processing_partition": "2020-01-01",
        "source_row_ordinal": 0,
        "source_file_logical_path": "fixture",
        "excluded_reason": None,
        "owner_partition": "2020-01-01",
    }


def _tree(run_root: Path) -> dict[str, object]:
    data = run_root / "staging" / "data"
    completed: list[str] = []
    for instrument_index, instrument in enumerate(("BTCUSDT", "ETHUSDT"), 1):
        for variant_index, (variant, datasets) in enumerate(
            (("V1_PRICE", PRICE_DATASETS), ("V1_FLOW", FLOW_DATASETS)), 1
        ):
            candidate = _candidate(
                instrument, variant, f"{instrument_index}{variant_index}".ljust(64, "0")
            )
            for dataset in datasets:
                records: list[dict[str, object]] = []
                if dataset == "market_episodes":
                    records = [candidate]
                elif dataset == "candidate_inclusion":
                    records = [_inclusion(candidate)]
                write_partition(
                    data
                    / f"instrument={instrument}"
                    / f"variant={variant}"
                    / dataset
                    / "date=2020-01-01"
                    / "part-000.parquet",
                    records,
                    dataset,
                )
            report = {
                "instrument": instrument,
                "variant": variant,
                "attempt_count": 1,
                "canonical_count": 1,
                "exact_duplicate_excluded_count": 0,
                "identity_conflict_count": 0,
                "out_of_partition_context_count": 0,
                "out_of_period_count": 0,
            }
            path = run_root / "reports" / f"{instrument}-{variant}-candidate-finalization.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report))
            completed.extend(
                (f"{instrument}:{variant}:2020-01-01", f"{instrument}:{variant}:FINALIZE")
            )
    return {"planned": completed, "completed": completed, "failed": []}


def test_single_scan_matches_legacy_hashes_and_resumes_sealed_shards(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    checkpoint = _tree(run_root)
    data = run_root / "staging" / "data"
    legacy = catalog_tree(data)
    catalog, analysis = single_scan_release(
        data,
        run_root=run_root,
        expected_partition_count=1,
        checkpoint=checkpoint,
        manifest_hash="d" * 64,
        progress_path=run_root / "logs/release-progress.json",
        shard_root=run_root / "tmp/shards",
        update_every_files=1,
    )
    assert catalog["logical_hash"] == legacy["logical_hash"]
    assert catalog["physical_hash"] == legacy["physical_hash"]
    assert analysis["quality"]["status"] == "PASS"
    assert json.loads((run_root / "logs/release-progress.json").read_text())["phase"] == (
        "ARTIFACTS_SEALED"
    )

    original = pl.read_parquet

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("sealed shards must avoid Parquet rereads")

    pl.read_parquet = forbidden  # type: ignore[assignment]
    try:
        resumed_catalog, resumed_analysis = single_scan_release(
            data,
            run_root=run_root,
            expected_partition_count=1,
            checkpoint=checkpoint,
            manifest_hash="d" * 64,
            progress_path=run_root / "logs/release-progress.json",
            shard_root=run_root / "tmp/shards",
        )
    finally:
        pl.read_parquet = original  # type: ignore[assignment]
    assert resumed_catalog == catalog
    assert resumed_analysis == analysis


def test_scanner_ignores_appledouble_and_rejects_unregistered_dataset(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    checkpoint = _tree(run_root)
    data = run_root / "staging/data"
    first = next(data.rglob("part-000.parquet"))
    (first.parent / "._part-000.parquet").write_bytes(b"metadata")
    single_scan_release(
        data,
        run_root=run_root,
        expected_partition_count=1,
        checkpoint=checkpoint,
        manifest_hash="d" * 64,
        progress_path=run_root / "logs/release-progress.json",
        shard_root=run_root / "tmp/shards",
    )
