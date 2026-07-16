from __future__ import annotations

from pathlib import Path

from era100x.research.stage_2.pipelines.candidates.io import (
    catalog_tree,
    records_logical_hash,
    write_partition,
)
from era100x.research.stage_2.pipelines.candidates.release import (
    FLOW_DATASETS,
    PRICE_DATASETS,
    analyze_release,
    semantic_comparison,
)

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
    return {
        key: candidate[key]
        for key in (
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
    } | {
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


def _release_tree(root: Path) -> dict[str, object]:
    completed = []
    for instrument_index, instrument in enumerate(("BTCUSDT", "ETHUSDT"), start=1):
        for variant_index, (variant, datasets) in enumerate(
            (("V1_PRICE", PRICE_DATASETS), ("V1_FLOW", FLOW_DATASETS)), start=1
        ):
            identifier = f"{instrument_index}{variant_index}".ljust(64, "0")
            candidate = _candidate(instrument, variant, identifier)
            for dataset in datasets:
                records = []
                if dataset == "market_episodes":
                    records = [candidate]
                elif dataset == "candidate_inclusion":
                    records = [_inclusion(candidate)]
                path = (
                    root
                    / f"instrument={instrument}"
                    / f"variant={variant}"
                    / dataset
                    / "date=2020-01-01"
                    / "part-000.parquet"
                )
                write_partition(path, records, dataset)
            completed.extend(
                (f"{instrument}:{variant}:2020-01-01", f"{instrument}:{variant}:FINALIZE")
            )
    return {"planned": completed, "completed": completed, "failed": []}


def test_release_analysis_separates_physical_and_semantic_hashes(tmp_path: Path) -> None:
    checkpoint = _release_tree(tmp_path / "data")
    report = analyze_release(
        tmp_path / "data",
        expected_partition_count=1,
        checkpoint=checkpoint,
        manifest_hash="d" * 64,
        require_finalization_reports=False,
    )
    assert report["quality"]["status"] == "PASS"
    assert report["catalog_logical_hash"] != report["catalog_physical_hash"]
    assert report["distributions"]["research_role"] == {"PRIMARY": 8}
    assert semantic_comparison(report, report)["status"] == "PASS"


def test_record_hash_is_input_order_independent_and_catalog_ignores_appledouble(
    tmp_path: Path,
) -> None:
    rows = [{"id": "b"}, {"id": "a"}]
    assert records_logical_hash(rows, "test") == records_logical_hash(list(reversed(rows)), "test")
    path = tmp_path / "dataset/date=2020-01-01/part-000.parquet"
    write_partition(path, rows, "dataset")
    (path.parent / "._part-000.parquet").write_bytes(b"metadata")
    catalog = catalog_tree(tmp_path)
    assert len(catalog["entries"]) == 1
    assert catalog["entries"][0]["logical_sha256"]
    assert catalog["physical_hash"]
