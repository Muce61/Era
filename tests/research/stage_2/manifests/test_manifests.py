from __future__ import annotations

from pathlib import Path

import pytest

from era100x.research.stage_2.manifests.configuration import config_hash, parameter_sets
from era100x.research.stage_2.manifests.models import Stage2ExecutionManifest
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


@pytest.mark.skipif(not OLD_EXECUTION_MANIFEST.exists(), reason="external audit manifest absent")
def test_failed_run_execution_manifest_remains_readable() -> None:
    manifest = Stage2ExecutionManifest.model_validate_json(OLD_EXECUTION_MANIFEST.read_bytes())
    assert manifest.recovery is None
    assert manifest.manifest_hash == manifest.computed_hash()
