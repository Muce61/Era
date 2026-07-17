"""Freeze the append-only CR-2026-006 release supplement for the completed Run A."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import cast

from era100x.research.stage_2.manifests.models import (
    ReleaseShardBinding,
    Stage2ExecutionManifest,
    Stage2ReleaseSupplementManifest,
    Stage2ShardAdoptionManifest,
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
    result.add_argument(
        "--change-request", choices=("CR-2026-006", "CR-2026-009"), default="CR-2026-006"
    )
    result.add_argument("--previous-supplement", type=Path)
    return result


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _adopted_shard_bindings(
    *,
    run_root: Path,
    previous: Stage2ReleaseSupplementManifest,
) -> tuple[str, tuple[ReleaseShardBinding, ...]]:
    """Verify and inherit immutable shards across supplement generations."""

    if previous.manifest_version == "1.1":
        adoption_path = Path(cast(str, previous.shard_adoption_manifest_path))
        if not adoption_path.resolve().is_relative_to(
            (run_root / "manifests").resolve()
        ) or sha256_file(adoption_path) != cast(
            str, previous.shard_adoption_manifest_physical_sha256
        ):
            raise ValueError("previous shard adoption authority changed")
        prior = Stage2ShardAdoptionManifest.model_validate_json(adoption_path.read_bytes())
        if (
            prior.manifest_hash != previous.shard_adoption_manifest_hash
            or prior.manifest_hash != prior.computed_hash()
            or prior.source_run_id != run_root.name
        ):
            raise ValueError("previous shard adoption Manifest is invalid")
        bindings = prior.shards
        shard_root_relative = prior.shard_root_relative_path
    else:
        shard_root = run_root / "tmp" / "release-sealed-shards" / previous.manifest_hash
        shard_paths = sorted(
            path for path in shard_root.glob("*.json") if not path.name.startswith("._")
        )
        bindings = tuple(
            ReleaseShardBinding(
                relative_path=str(shard_path.relative_to(run_root)),
                physical_sha256=sha256_file(shard_path),
                inventory_fingerprint=shard["inventory_fingerprint"],
                instrument=shard["instrument"],
                variant=shard["variant"],
                dataset=shard["dataset"],
                entry_count=len(shard["entries"]),
            )
            for shard_path in shard_paths
            for shard in (json.loads(shard_path.read_text()),)
        )
        shard_root_relative = str(shard_root.relative_to(run_root))
    for binding in bindings:
        shard_path = run_root / binding.relative_path
        if (
            not shard_path.resolve().is_relative_to(run_root.resolve())
            or sha256_file(shard_path) != binding.physical_sha256
        ):
            raise ValueError(f"adopted release shard changed: {binding.relative_path}")
    return shard_root_relative, bindings


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
    supplement_payload = {
        "schema_name": "stage2-group1-release-supplement",
        "manifest_version": "1.1" if args.change_request == "CR-2026-009" else "1.0",
        "operation": "RELEASE_EXISTING_STAGING",
        "change_request": args.change_request,
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
    adoption_path: Path | None = None
    adoption: Stage2ShardAdoptionManifest | None = None
    if args.change_request == "CR-2026-009":
        if args.previous_supplement is None:
            raise ValueError("CR-2026-009 requires --previous-supplement")
        previous = Stage2ReleaseSupplementManifest.model_validate_json(
            args.previous_supplement.read_bytes()
        )
        if previous.manifest_hash != previous.computed_hash():
            raise ValueError("previous release supplement changed")
        if previous.source_run_id != args.run_id:
            raise ValueError("previous release supplement belongs to another run")
        shard_root_relative, bindings = _adopted_shard_bindings(
            run_root=run_root,
            previous=previous,
        )
        aggregate = hashlib.sha256()
        for binding in bindings:
            aggregate.update(binding.relative_path.encode())
            aggregate.update(b"\0")
            aggregate.update(bytes.fromhex(binding.physical_sha256))
        adoption = Stage2ShardAdoptionManifest.seal(
            {
                "schema_name": "stage2-release-shard-adoption-v1",
                "manifest_version": "1.0",
                "change_request": "CR-2026-009",
                "source_run_id": args.run_id,
                "source_checkpoint_hash": sha256_file(checkpoint_path),
                "previous_release_supplement_hash": previous.manifest_hash,
                "previous_release_tool_commit": previous.release_tool_commit,
                "adoption_tool_commit": head,
                "shard_root_relative_path": shard_root_relative,
                "shards": bindings,
                "aggregate_sha256": aggregate.hexdigest(),
                "prohibited_actions": (
                    "MODIFY_ADOPTED_SHARDS",
                    "REGENERATE_SOURCE_EVENTS",
                    "MODIFY_STAGE1",
                ),
            }
        )
        adoption_path = AppendOnlyManifestRepository(run_root / "manifests").publish(adoption)
        supplement_payload.update(
            {
                "previous_release_supplement_hash": previous.manifest_hash,
                "shard_adoption_manifest_hash": adoption.manifest_hash,
                "shard_adoption_manifest_physical_sha256": sha256_file(adoption_path),
                "shard_adoption_manifest_path": str(adoption_path),
            }
        )
    supplement = Stage2ReleaseSupplementManifest.seal(supplement_payload)
    path = AppendOnlyManifestRepository(run_root / "manifests").publish(supplement)
    print(
        json.dumps(
            {
                "manifest_hash": supplement.manifest_hash,
                "path": str(path),
                "generator_tree_hash": generator_tree_hash,
                "release_tool_tree_hash": release_tool_tree_hash,
                "shard_adoption_manifest_hash": (
                    adoption.manifest_hash if adoption is not None else None
                ),
                "shard_adoption_manifest_path": str(adoption_path) if adoption_path else None,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
