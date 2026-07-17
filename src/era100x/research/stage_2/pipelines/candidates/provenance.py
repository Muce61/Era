"""Git-tree provenance for generator/release-tool version separation."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

GENERATOR_PATHS = (
    "src/era100x/research/stage_2/contracts",
    "src/era100x/research/stage_2/episodes",
    "src/era100x/research/stage_2/gates",
    "src/era100x/research/stage_2/key_levels",
    "src/era100x/research/stage_2/registry",
    "src/era100x/research/stage_2/manifests/configuration.py",
    "src/era100x/research/stage_2/pipelines/candidates/candidate_diagnostics.py",
    "src/era100x/research/stage_2/pipelines/candidates/candidate_finalizer.py",
    "src/era100x/research/stage_2/pipelines/candidates/flow_phase.py",
    "src/era100x/research/stage_2/pipelines/candidates/io.py",
    "src/era100x/research/stage_2/pipelines/candidates/price_phase.py",
    "src/era100x/research/stage_2/pipelines/candidates/stage1_catalog.py",
)

RELEASE_TOOL_PATHS = (
    "scripts/freeze_stage2_group1_execution_manifest.py",
    "scripts/prepare_stage2_release_supplement.py",
    "scripts/record_stage2_group1_quality_evidence.py",
    "scripts/run_stage2_group1_cr006_pipeline.py",
    "scripts/run_stage2_group1_candidates.py",
    "src/era100x/research/stage_2/manifests/models.py",
    "src/era100x/research/stage_2/manifests/repository.py",
    "src/era100x/research/stage_2/pipelines/candidates/provenance.py",
    "src/era100x/research/stage_2/pipelines/candidates/release_recovery.py",
    "src/era100x/research/stage_2/pipelines/candidates/runner.py",
)


def git_tree_entries(root: Path, commit: str, paths: tuple[str, ...]) -> list[dict[str, str]]:
    output = subprocess.check_output(
        ["git", "ls-tree", "-r", "--full-tree", commit, "--", *paths],
        cwd=root,
        text=True,
    ).strip()
    entries = []
    for line in output.splitlines():
        metadata, path = line.split("\t", 1)
        mode, object_type, object_id = metadata.split()
        entries.append({"mode": mode, "type": object_type, "object_id": object_id, "path": path})
    return sorted(entries, key=lambda item: item["path"])


def git_tree_hash(entries: list[dict[str, str]]) -> str:
    raw = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def assert_generator_tree(root: Path, generator_commit: str, expected_hash: str) -> None:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    generator = git_tree_entries(root, generator_commit, GENERATOR_PATHS)
    current = git_tree_entries(root, head, GENERATOR_PATHS)
    if generator != current:
        raise ValueError("event generator semantic tree changed")
    if git_tree_hash(generator) != expected_hash:
        raise ValueError("event generator tree hash mismatch")
