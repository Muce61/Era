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
