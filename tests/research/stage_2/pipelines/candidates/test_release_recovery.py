from __future__ import annotations

import hashlib
import json
from pathlib import Path

import polars as pl
import pytest

from era100x.research.stage_2.manifests.models import (
    ReleaseShardBinding,
    Stage2ReleaseSupplementManifest,
    Stage2ShardAdoptionManifest,
    canonical_json,
)
from era100x.research.stage_2.pipelines.candidates.io import catalog_tree, write_partition
from era100x.research.stage_2.pipelines.candidates.release import FLOW_DATASETS, PRICE_DATASETS
from era100x.research.stage_2.pipelines.candidates.release_recovery import (
    ReleaseRecovery,
    _single_writer_lock,
    sha256_file,
    single_scan_release,
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
    # exFAT may also synthesize an AppleDouble file whose name still matches
    # the finalization-report glob.  It is execution metadata, never JSON
    # research evidence, and must not enter the release analysis.
    finalizer = next((run_root / "reports").glob("*-V1_*-candidate-finalization.json"))
    (finalizer.parent / f"._{finalizer.name}").write_bytes(b"\x00\x05\x16\x07\xb0metadata")
    single_scan_release(
        data,
        run_root=run_root,
        expected_partition_count=1,
        checkpoint=checkpoint,
        manifest_hash="d" * 64,
        progress_path=run_root / "logs/release-progress.json",
        shard_root=run_root / "tmp/shards",
    )


def _hardened_recovery(tmp_path: Path) -> tuple[Path, Path, Path]:
    run_root = tmp_path / "run-a"
    _tree(run_root)
    completed = [f"task-{index:04d}" for index in range(9508)]
    checkpoint = {
        "planned": completed,
        "completed": completed,
        "failed": [],
        "status": "IN_PROGRESS",
    }
    checkpoint_path = run_root / "checkpoint.json"
    checkpoint_path.write_text(json.dumps(checkpoint, sort_keys=True))
    execution_path = run_root / "manifests/execution.json"
    execution_path.parent.mkdir(parents=True, exist_ok=True)
    execution_path.write_text('{"immutable":"execution"}\n')

    previous_supplement_hash = "e" * 64
    shard_root = run_root / "tmp/release-sealed-shards" / previous_supplement_hash
    single_scan_release(
        run_root / "staging/data",
        run_root=run_root,
        expected_partition_count=1,
        checkpoint=checkpoint,
        manifest_hash="d" * 64,
        progress_path=run_root / "logs/release-progress.json",
        shard_root=shard_root,
        update_every_files=1,
    )
    bindings: list[ReleaseShardBinding] = []
    for shard_path in sorted(shard_root.glob("*.json")):
        shard = json.loads(shard_path.read_text())
        bindings.append(
            ReleaseShardBinding(
                relative_path=str(shard_path.relative_to(run_root)),
                physical_sha256=sha256_file(shard_path),
                inventory_fingerprint=shard["inventory_fingerprint"],
                instrument=shard["instrument"],
                variant=shard["variant"],
                dataset=shard["dataset"],
                entry_count=len(shard["entries"]),
            )
        )
    aggregate = hashlib.sha256()
    for item in bindings:
        aggregate.update(item.relative_path.encode())
        aggregate.update(b"\0")
        aggregate.update(bytes.fromhex(item.physical_sha256))
    adoption = Stage2ShardAdoptionManifest.seal(
        {
            "schema_name": "stage2-release-shard-adoption-v1",
            "manifest_version": "1.0",
            "change_request": "CR-2026-009",
            "source_run_id": run_root.name,
            "source_checkpoint_hash": sha256_file(checkpoint_path),
            "previous_release_supplement_hash": previous_supplement_hash,
            "previous_release_tool_commit": "a" * 40,
            "adoption_tool_commit": "b" * 40,
            "shard_root_relative_path": str(shard_root.relative_to(run_root)),
            "shards": tuple(bindings),
            "aggregate_sha256": aggregate.hexdigest(),
            "prohibited_actions": ("MODIFY_ADOPTED_SHARDS",),
        }
    )
    adoption_path = run_root / "manifests/adoption.json"
    adoption_path.write_text(canonical_json(adoption.model_dump(mode="python")) + "\n")
    finalizers = {}
    for instrument in ("BTCUSDT", "ETHUSDT"):
        for variant in ("V1_PRICE", "V1_FLOW"):
            key = f"{instrument}/{variant}"
            finalizers[key] = sha256_file(
                run_root / "reports" / f"{instrument}-{variant}-candidate-finalization.json"
            )
    supplement = Stage2ReleaseSupplementManifest.seal(
        {
            "schema_name": "stage2-group1-release-supplement",
            "manifest_version": "1.1",
            "operation": "RELEASE_EXISTING_STAGING",
            "change_request": "CR-2026-009",
            "source_run_id": run_root.name,
            "source_execution_manifest_hash": "d" * 64,
            "source_execution_manifest_physical_sha256": sha256_file(execution_path),
            "source_execution_manifest_path": str(execution_path),
            "generator_commit": "c" * 40,
            "generator_tree_hash": "1" * 64,
            "release_tool_commit": "b" * 40,
            "release_tool_tree_hash": "2" * 64,
            "quality_gate_evidence_hash": "3" * 64,
            "stage1_data_run_id": "stage1",
            "stage1_logical_hashes": {"BTCUSDT": "4" * 64, "ETHUSDT": "5" * 64},
            "preregistration_manifest_hash": "6" * 64,
            "config_hash": "7" * 64,
            "source_checkpoint_hash": sha256_file(checkpoint_path),
            "planned_count": 9508,
            "completed_count": 9508,
            "failed_count": 0,
            "finalization_report_hashes": finalizers,
            "release_progress_path": "logs/release-progress.json",
            "prohibited_actions": ("REGENERATE_SOURCE_EVENTS",),
            "previous_release_supplement_hash": previous_supplement_hash,
            "shard_adoption_manifest_hash": adoption.manifest_hash,
            "shard_adoption_manifest_physical_sha256": sha256_file(adoption_path),
            "shard_adoption_manifest_path": str(adoption_path),
        }
    )
    supplement_path = run_root / "manifests/supplement.json"
    supplement_path.write_text(canonical_json(supplement.model_dump(mode="python")) + "\n")
    return run_root, supplement_path, shard_root


def test_hardened_release_publishes_with_durable_journal(tmp_path: Path) -> None:
    run_root, supplement_path, _ = _hardened_recovery(tmp_path)
    result = ReleaseRecovery(run_root, supplement_path).release(expected_partition_count=1)
    assert result["entries"] == 26
    assert (run_root / "published/data").is_dir()
    assert not (run_root / "staging/data").exists()
    assert json.loads((run_root / "checkpoint.json").read_text())["status"] == "PUBLISHED"
    state = json.loads((run_root / "logs/release-state.json").read_text())
    assert state["phase"] == "PUBLISHED"
    journal = run_root / "reports/release-recovery"
    phases = {path.stem for path in journal.rglob("*.json")}
    assert {"ARTIFACTS_SEALED", "RENAME_INTENT_WRITTEN", "DATA_RENAMED", "PUBLISHED"} <= phases


def test_hardened_release_recovers_after_rename_before_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_root, supplement_path, _ = _hardened_recovery(tmp_path)
    recovery = ReleaseRecovery(run_root, supplement_path)
    original = recovery._persist_state

    def interrupt(phase: str) -> None:
        if phase == "DATA_RENAMED":
            raise OSError("fault after rename")
        original(phase)  # type: ignore[arg-type]

    monkeypatch.setattr(recovery, "_persist_state", interrupt)
    with pytest.raises(OSError, match="fault after rename"):
        recovery.release(expected_partition_count=1)
    assert (run_root / "published/data").is_dir()
    assert json.loads((run_root / "logs/release-state.json").read_text())["phase"] == (
        "RENAME_INTENT_WRITTEN"
    )
    result = ReleaseRecovery(run_root, supplement_path).release(expected_partition_count=1)
    assert result["entries"] == 26
    assert json.loads((run_root / "checkpoint.json").read_text())["status"] == "PUBLISHED"


def test_hardened_release_rejects_shard_tampering(tmp_path: Path) -> None:
    run_root, supplement_path, shard_root = _hardened_recovery(tmp_path)
    shard = next(shard_root.glob("*.json"))
    payload = json.loads(shard.read_text())
    payload["unknown_count"] = 1
    shard.write_text(json.dumps(payload, sort_keys=True))
    with pytest.raises(ValueError, match="adopted shard changed"):
        ReleaseRecovery(run_root, supplement_path).release(expected_partition_count=1)
    assert not (run_root / "published/data").exists()


def test_hardened_release_rejects_concurrent_writer(tmp_path: Path) -> None:
    run_root, supplement_path, _ = _hardened_recovery(tmp_path)
    lock_path = run_root / "logs/release-recovery.lock"
    with _single_writer_lock(lock_path):
        with pytest.raises(RuntimeError, match="active writer"):
            ReleaseRecovery(run_root, supplement_path).release(expected_partition_count=1)
    assert not (run_root / "published/data").exists()
