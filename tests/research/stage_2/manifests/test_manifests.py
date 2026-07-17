from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from era100x.research.stage_2.manifests.configuration import config_hash, parameter_sets
from era100x.research.stage_2.manifests.models import (
    Stage2ExecutionManifest,
    Stage2ReleaseSupplementManifest,
    Stage2ShardAdoptionManifest,
)
from era100x.research.stage_2.manifests.preflight import estimate_peak_bytes
from era100x.research.stage_2.manifests.repository import AppendOnlyManifestRepository


def test_parameter_family_is_exact_ofat() -> None:
    sets = parameter_sets()
    assert len(sets) == 20
    primary = sets[0]
    assert primary.parameter_set_id == "G1-PRIMARY-V1"
    assert primary.status == "BASELINE"
    for item in sets[1:]:
        differences = {
            name
            for name in (
                "timing_id",
                "merge_tolerance_bps",
                "minimum_episode_gap_seconds",
                "rearm_above_level_seconds",
                "sweep_confirmation_bps",
                "reclaim_buffer_bps",
                "hold_failure_buffer_bps",
            )
            if getattr(item, name) != getattr(primary, name)
        }
        assert differences == {item.changed_axis}


def test_config_hash_is_stable() -> None:
    assert config_hash() == config_hash()
    assert len(config_hash()) == 64


def test_execution_manifest_hash_and_append_only(tmp_path: Path) -> None:
    payload = {
        "schema_name": "stage2-group1-execution",
        "manifest_version": "1.0",
        "preregistration_manifest_hash": "1" * 64,
        "code_commit": "a" * 40,
        "fixture_logical_hash": "2" * 64,
        "small_sample_validation_hash": "3" * 64,
        "config_hash": "4" * 64,
        "stage1_data_run_id": "stage1-run",
        "stage1_logical_hashes": {"BTCUSDT": "5" * 64, "ETHUSDT": "6" * 64},
        "full_run_cli": (
            "uv run python scripts/run_stage2_group1_candidates.py {preflight,run,resume,verify}"
        ),
        "invalidation_conditions": ("hash drift",),
    }
    manifest = Stage2ExecutionManifest.seal(payload)
    assert manifest.manifest_hash == manifest.computed_hash()
    repository = AppendOnlyManifestRepository(tmp_path)
    path = repository.publish(manifest)
    assert repository.publish(manifest) == path
    path.write_text("replacement", encoding="utf-8")
    with pytest.raises(FileExistsError):
        repository.publish(manifest)


def test_space_estimate_uses_two_publications_and_staging() -> None:
    assert estimate_peak_bytes(days=1, schema_max_record_bytes=1) == 86_400 // 60 * 20 * 2 * 2 * 3


def test_recovery_manifest_binds_fix_commit_and_forbids_price_reuse() -> None:
    payload = {
        "schema_name": "stage2-group1-execution",
        "manifest_version": "1.1-recovery",
        "preregistration_manifest_hash": "1" * 64,
        "code_commit": "a" * 40,
        "fixture_logical_hash": "2" * 64,
        "small_sample_validation_hash": "3" * 64,
        "config_hash": "4" * 64,
        "stage1_data_run_id": "stage1-run",
        "stage1_logical_hashes": {"BTCUSDT": "5" * 64, "ETHUSDT": "6" * 64},
        "full_run_cli": (
            "uv run python scripts/run_stage2_group1_candidates.py {preflight,run,resume,verify}"
        ),
        "invalidation_conditions": ("hash drift",),
        "quality_gate_evidence_hash": "7" * 64,
        "tool_versions": {
            "python": "3.12.7",
            "polars": "1.42.1",
            "pytest": "8.4.2",
            "ruff": "0.15.21",
            "mypy": "1.20.2",
        },
        "recovery": {
            "recovery_of_run_id": "failed-run",
            "supersedes_failed_run_id": "failed-run",
            "failure_reason": "archive path omitted",
            "change_request": "CR-2026-003",
            "identity_change_request": "CR-2026-004",
            "ownership_change_request": "CR-2026-005",
            "fix_code_commit": "a" * 40,
            "reused_price_staging": False,
        },
    }
    manifest = Stage2ExecutionManifest.seal(payload)
    assert manifest.recovery is not None
    assert manifest.recovery.reused_price_staging is False
    assert manifest.recovery.identity_change_request == "CR-2026-004"
    assert manifest.recovery.ownership_change_request == "CR-2026-005"
    assert manifest.quality_gate_evidence_hash == "7" * 64
    assert manifest.tool_versions["polars"] == "1.42.1"
    payload["recovery"]["fix_code_commit"] = "b" * 40  # type: ignore[index]
    with pytest.raises(ValueError, match="fix commit"):
        Stage2ExecutionManifest.seal(payload)


OLD_EXECUTION_MANIFEST = Path(
    "/Volumes/FuckingLife/era100x_stage2/runs/stage2-g1-preregistration-v1.0/manifests/"
    "84f6fcdd2d4710fd98112dc7a39d798d0f488accb6e7b2a7962f98ba589e3b74.json"
)


def test_release_supplement_is_stable_and_binds_all_finalizers() -> None:
    payload = {
        "schema_name": "stage2-group1-release-supplement",
        "manifest_version": "1.0",
        "operation": "RELEASE_EXISTING_STAGING",
        "change_request": "CR-2026-006",
        "source_run_id": "run-a",
        "source_execution_manifest_hash": "1" * 64,
        "source_execution_manifest_physical_sha256": "f" * 64,
        "source_execution_manifest_path": "/immutable/execution.json",
        "generator_commit": "a" * 40,
        "generator_tree_hash": "2" * 64,
        "release_tool_commit": "b" * 40,
        "release_tool_tree_hash": "3" * 64,
        "quality_gate_evidence_hash": "4" * 64,
        "stage1_data_run_id": "stage1",
        "stage1_logical_hashes": {"BTCUSDT": "5" * 64, "ETHUSDT": "6" * 64},
        "preregistration_manifest_hash": "7" * 64,
        "config_hash": "8" * 64,
        "source_checkpoint_hash": "9" * 64,
        "planned_count": 9508,
        "completed_count": 9508,
        "failed_count": 0,
        "finalization_report_hashes": {
            "BTCUSDT/V1_PRICE": "a" * 64,
            "BTCUSDT/V1_FLOW": "b" * 64,
            "ETHUSDT/V1_PRICE": "c" * 64,
            "ETHUSDT/V1_FLOW": "d" * 64,
        },
        "release_progress_path": "logs/release-progress.json",
        "prohibited_actions": ("REGENERATE_SOURCE_EVENTS",),
    }
    left = Stage2ReleaseSupplementManifest.seal(payload)
    right = Stage2ReleaseSupplementManifest.seal(dict(reversed(list(payload.items()))))
    assert left.manifest_hash == right.manifest_hash
    with pytest.raises(ValueError, match="four finalization"):
        Stage2ReleaseSupplementManifest.seal(
            {**payload, "finalization_report_hashes": {"BTCUSDT/V1_PRICE": "a" * 64}}
        )


def test_cr009_release_requires_stable_shard_adoption() -> None:
    shard = {
        "relative_path": "tmp/release-sealed-shards/old/BTCUSDT-V1_PRICE-sweeps.json",
        "physical_sha256": "1" * 64,
        "inventory_fingerprint": "2" * 64,
        "instrument": "BTCUSDT",
        "variant": "V1_PRICE",
        "dataset": "sweeps",
        "entry_count": 2376,
    }
    aggregate = hashlib.sha256()
    shards = []
    for index in range(26):
        item = {
            **shard,
            "relative_path": f"tmp/release-sealed-shards/old/{index:02d}.json",
            "physical_sha256": f"{index + 1:064x}",
        }
        shards.append(item)
        aggregate.update(item["relative_path"].encode())
        aggregate.update(b"\0")
        aggregate.update(bytes.fromhex(item["physical_sha256"]))
    adoption = Stage2ShardAdoptionManifest.seal(
        {
            "schema_name": "stage2-release-shard-adoption-v1",
            "manifest_version": "1.0",
            "change_request": "CR-2026-009",
            "source_run_id": "run-a",
            "source_checkpoint_hash": "3" * 64,
            "previous_release_supplement_hash": "4" * 64,
            "previous_release_tool_commit": "a" * 40,
            "adoption_tool_commit": "b" * 40,
            "shard_root_relative_path": "tmp/release-sealed-shards/old",
            "shards": tuple(shards),
            "aggregate_sha256": aggregate.hexdigest(),
            "prohibited_actions": ("MODIFY_ADOPTED_SHARDS",),
        }
    )
    assert adoption.manifest_hash == adoption.computed_hash()

    payload = {
        "schema_name": "stage2-group1-release-supplement",
        "manifest_version": "1.1",
        "operation": "RELEASE_EXISTING_STAGING",
        "change_request": "CR-2026-009",
        "source_run_id": "run-a",
        "source_execution_manifest_hash": "5" * 64,
        "source_execution_manifest_physical_sha256": "6" * 64,
        "source_execution_manifest_path": "/immutable/execution.json",
        "generator_commit": "c" * 40,
        "generator_tree_hash": "7" * 64,
        "release_tool_commit": "d" * 40,
        "release_tool_tree_hash": "8" * 64,
        "quality_gate_evidence_hash": "9" * 64,
        "stage1_data_run_id": "stage1",
        "stage1_logical_hashes": {"BTCUSDT": "a" * 64, "ETHUSDT": "b" * 64},
        "preregistration_manifest_hash": "c" * 64,
        "config_hash": "d" * 64,
        "source_checkpoint_hash": "3" * 64,
        "planned_count": 9508,
        "completed_count": 9508,
        "failed_count": 0,
        "finalization_report_hashes": {
            "BTCUSDT/V1_PRICE": "e" * 64,
            "BTCUSDT/V1_FLOW": "f" * 64,
            "ETHUSDT/V1_PRICE": "1" * 64,
            "ETHUSDT/V1_FLOW": "2" * 64,
        },
        "release_progress_path": "logs/release-progress.json",
        "prohibited_actions": ("REGENERATE_SOURCE_EVENTS",),
        "previous_release_supplement_hash": "4" * 64,
        "shard_adoption_manifest_hash": adoption.manifest_hash,
        "shard_adoption_manifest_physical_sha256": "e" * 64,
        "shard_adoption_manifest_path": "/immutable/adoption.json",
    }
    supplement = Stage2ReleaseSupplementManifest.seal(payload)
    assert supplement.manifest_hash == supplement.computed_hash()
    with pytest.raises(ValueError, match="shard-adoption"):
        Stage2ReleaseSupplementManifest.seal({**payload, "shard_adoption_manifest_path": None})


def test_version_separated_execution_requires_both_tree_hashes() -> None:
    payload = {
        "schema_name": "stage2-group1-execution",
        "manifest_version": "test-separated",
        "preregistration_manifest_hash": "1" * 64,
        "code_commit": "a" * 40,
        "generator_code_commit": "b" * 40,
        "generator_tree_hash": "2" * 64,
        "release_tool_tree_hash": "3" * 64,
        "publication_mode": "RELEASE_SUPPLEMENT_REQUIRED",
        "fixture_logical_hash": "4" * 64,
        "small_sample_validation_hash": "5" * 64,
        "config_hash": "6" * 64,
        "stage1_data_run_id": "stage1",
        "stage1_logical_hashes": {"BTCUSDT": "7" * 64, "ETHUSDT": "8" * 64},
        "full_run_cli": "fixture",
        "invalidation_conditions": ("fixture",),
    }
    manifest = Stage2ExecutionManifest.seal(payload)
    assert manifest.generator_code_commit == "b" * 40
    with pytest.raises(ValueError, match="generator/release provenance"):
        Stage2ExecutionManifest.seal({**payload, "generator_tree_hash": None})


@pytest.mark.skipif(not OLD_EXECUTION_MANIFEST.exists(), reason="external audit manifest absent")
def test_failed_run_execution_manifest_remains_readable() -> None:
    manifest = Stage2ExecutionManifest.model_validate_json(OLD_EXECUTION_MANIFEST.read_bytes())
    assert manifest.recovery is None
    assert manifest.manifest_hash == manifest.computed_hash()
