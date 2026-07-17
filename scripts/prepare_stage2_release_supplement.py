"""Freeze the append-only CR-2026-006 release supplement for the completed Run A."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from era100x.research.stage_2.manifests.models import (
    Stage2ExecutionManifest,
    Stage2ReleaseSupplementManifest,
)
from era100x.research.stage_2.manifests.repository import AppendOnlyManifestRepository
from era100x.research.stage_2.pipelines.candidates.release_recovery import sha256_file
from era100x.research.stage_2.pipelines.candidates.provenance import (
    GENERATOR_PATHS,
    RELEASE_TOOL_PATHS,
    git_tree_entries,
    git_tree_hash,
)

ROOT = Path(__file__).resolve().parents[1]
STAGE2_ROOT = Path("/Volumes/FuckingLife/era100x_stage2")
SOURCE_RUN_ID = "stage2-g1-full-a-20260716T144233Z-366a541b7956"
GENERATOR_COMMIT = "366a541b7956030d1a0ea2b5c67b4b30e2154c76"
EXECUTION_HASH = "71385c11e38b0e76b198e3a2ba510665a3301d052f770a8407797795e5312a4b"
PREREGISTRATION_HASH = "6b0f66e4007b86e08b58a9b366170eeee952199baa203d7f174b2ca69478c1f9"
CONFIG_HASH = "adb6295e210de66d1e69aa008e6161e8fef1e1fd72001ff812b68597f8c72e3f"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--quality-evidence-hash", required=True)
    result.add_argument("--run-id", default=SOURCE_RUN_ID)
    result.add_argument("--execution-manifest", type=Path)
    return result


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> int:
    args = parser().parse_args()
    head = _git("rev-parse", "HEAD")
    if _git("status", "--porcelain"):
        raise ValueError("release supplement requires a clean worktree")
    old_generator = git_tree_entries(ROOT, GENERATOR_COMMIT, GENERATOR_PATHS)
    current_generator = git_tree_entries(ROOT, head, GENERATOR_PATHS)
    if old_generator != current_generator:
        raise ValueError("event generator tree changed after Run A generation")
    generator_tree_hash = git_tree_hash(old_generator)
    release_tool_tree_hash = git_tree_hash(git_tree_entries(ROOT, head, RELEASE_TOOL_PATHS))

    run_root = STAGE2_ROOT / "runs" / args.run_id
    manifest_path = args.execution_manifest or run_root / "manifests" / f"{EXECUTION_HASH}.json"
    execution = Stage2ExecutionManifest.model_validate_json(manifest_path.read_bytes())
    execution_hash = execution.manifest_hash
    if execution.computed_hash() != execution_hash:
        raise ValueError("source Execution Manifest/hash changed")
    if (execution.generator_code_commit or GENERATOR_COMMIT) != GENERATOR_COMMIT:
        raise ValueError("release source does not bind the approved generator commit")
    execution_physical_hash = sha256_file(manifest_path)
    checkpoint_path = run_root / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text())
    if (
        len(checkpoint["planned"]) != 9508
        or len(checkpoint["completed"]) != 9508
        or checkpoint["failed"]
        or (run_root / "published" / "data").exists()
    ):
        raise ValueError("source Run A is not eligible for release-only recovery")

    finalizers = {}
    for instrument in ("BTCUSDT", "ETHUSDT"):
        for variant in ("V1_PRICE", "V1_FLOW"):
            path = run_root / "reports" / f"{instrument}-{variant}-candidate-finalization.json"
            finalizers[f"{instrument}/{variant}"] = sha256_file(path)
    supplement = Stage2ReleaseSupplementManifest.seal(
        {
            "schema_name": "stage2-group1-release-supplement",
            "manifest_version": "1.0",
            "operation": "RELEASE_EXISTING_STAGING",
            "change_request": "CR-2026-006",
            "source_run_id": args.run_id,
            "source_execution_manifest_hash": execution_hash,
            "source_execution_manifest_physical_sha256": execution_physical_hash,
            "source_execution_manifest_path": str(manifest_path),
            "generator_commit": GENERATOR_COMMIT,
            "generator_tree_hash": generator_tree_hash,
            "release_tool_commit": head,
            "release_tool_tree_hash": release_tool_tree_hash,
            "quality_gate_evidence_hash": args.quality_evidence_hash,
            "stage1_data_run_id": execution.stage1_data_run_id,
            "stage1_logical_hashes": execution.stage1_logical_hashes,
            "preregistration_manifest_hash": PREREGISTRATION_HASH,
            "config_hash": CONFIG_HASH,
            "source_checkpoint_hash": sha256_file(checkpoint_path),
            "planned_count": 9508,
            "completed_count": 9508,
            "failed_count": 0,
            "finalization_report_hashes": finalizers,
            "release_progress_path": "logs/release-progress.json",
            "prohibited_actions": (
                "REGENERATE_SOURCE_EVENTS",
                "MODIFY_SOURCE_EXECUTION_MANIFEST",
                "MODIFY_STAGE1",
                "EXECUTE_S2_T11_THROUGH_S2_T20",
            ),
        }
    )
    path = AppendOnlyManifestRepository(run_root / "manifests").publish(supplement)
    print(
        json.dumps(
            {
                "manifest_hash": supplement.manifest_hash,
                "path": str(path),
                "generator_tree_hash": generator_tree_hash,
                "release_tool_tree_hash": release_tool_tree_hash,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
