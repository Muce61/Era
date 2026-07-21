#!/usr/bin/env python3
"""Release, verify and compare the fixed CR-2026-018 sealed Run only."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from era100x.research.stage_2.manifests.models import canonical_json
from era100x.research.stage_2.runtime_v2.orchestrator import (
    RuntimeComparison,
    RuntimeVerification,
    Stage2V2Orchestrator,
    _LoadedAuthorities,
    compute_v2_code_tree_sha256,
)
from era100x.research.stage_2.runtime_v2.checkpoint import RuntimeV2Checkpoint
from era100x.research.stage_2.runtime_v2.production_backend import (
    ProductionRuntimeV2Backend,
)
from era100x.research.stage_2.runtime_v2.progress import PipelineProgressStore
from era100x.research.stage_2.runtime_v2.transition import sha256_file

ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = Path("/Volumes/FuckingLife/era100x_stage2/runs")
BASELINE_COMMIT = "9c4b7c423a0479e3d1eb8b6f6423c2d09f2f2813"
BASELINE_CODE_TREE_SHA256 = "b605ab38f693ebb227bfea7def80a690d04d7c33ada470d0001494f2520226b4"
RELEASE_BRANCH = "codex/stage2-cr018-release-only"
TARGET_RUN_ID = "stage2-g1-v2-b-20260720T111704Z-9c4b7c423a04"
SUPERSEDED_RUN_ID = "stage2-g1-v2-b-20260720T143327Z-de804cf61e81"
AUTHORITY_RUN_ID = "stage2-g1-v2-authority-20260720T111704Z-9c4b7c423a04"
RUNTIME_MANIFEST_HASH = "7c4c40c482b309108ae821cdd8185d6f5674721a71411bae4163fd4184cddb53"
RUN_A_PROTECTION_HASH = "330b7cddea33f42fff4d7638cf54a3067073ad052f33e2dac9273aee1842f7da"
MIGRATION_MANIFEST_HASH = "c89cd57b1de7110c7f853cb2e2ebda45619819be1c37193ef8ad90ed35e52259"
EXPECTED_TARGET_REVISION = 12
EXPECTED_SUPERSEDED_REVISION = 8
EXPECTED_SUPERSEDED_PACKED_SEALS = 2
EXPECTED_PARTITIONS = 80_784
EXPECTED_GROUP1_PARTITIONS = 61_776
EXPECTED_FRAGMENTS = 77_265
EXPECTED_OBJECTS = 208
EXPECTED_SEALS = 208
EXPECTED_FOUNDATION_OBJECTS = 164
EXPECTED_GROUP1_OBJECTS = 44
EXPECTED_INPUT_SET_SHA256 = "ed861c67c3401b11117bbd1da3bd94c6773ca63766bfed57b9742325fde6f3d8"
EXPECTED_DISABLEMENT_SHA256 = "b6e0236c1634c0d29cf131dab12968196673c8428c4e5bf1d5d95ec51bcd4a05"
CATALOG_PATH = "src/era100x/research/stage_2/runtime_v2/catalog.py"
EXPECTED_TASKS = (
    "FOUNDATION:BTCUSDT",
    "FOUNDATION:ETHUSDT",
    "GROUP1:BTCUSDT:V1_PRICE",
    "GROUP1:BTCUSDT:V1_FLOW",
    "GROUP1:ETHUSDT:V1_PRICE",
    "GROUP1:ETHUSDT:V1_FLOW",
)
ALLOWED_COMMANDS = ("release", "verify", "compare")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("action", choices=("authorize", "preflight", *ALLOWED_COMMANDS))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    action = parser().parse_args(argv).action
    if action == "authorize":
        output: dict[str, Any] = _authorize()
    elif action == "preflight":
        output = _preflight()
    else:
        output = _execute(cast(str, action))
    print(canonical_json(output))
    return 0


class ReleaseOnlyOrchestrator(Stage2V2Orchestrator):
    """Retain old generation authority while accepting one release-only code overlay."""

    def _assert_repository_authority(self, authorities: _LoadedAuthorities) -> None:
        amendment = _validated_amendment()
        if authorities.manifest.code_tree_sha256 != BASELINE_CODE_TREE_SHA256:
            raise ValueError("target Run generation code tree changed")
        if authorities.migration.v2_code_commit != BASELINE_COMMIT:
            raise ValueError("target Run generation commit changed")
        if amendment["release_code_commit"] != _git("rev-parse", "HEAD"):
            raise ValueError("release-only amendment commit differs from HEAD")
        if amendment["release_code_tree_sha256"] != compute_v2_code_tree_sha256(ROOT):
            raise ValueError("release-only amendment code tree differs")


def _authorize() -> dict[str, Any]:
    release_commit, release_tree = _assert_release_code_authority(require_clean=True)
    target = _validate_target_run()
    superseded = _validate_superseded_run()
    disablement_path = _target_root() / "reports/disablement-cr-2026-017.json"
    if sha256_file(disablement_path) != EXPECTED_DISABLEMENT_SHA256:
        raise ValueError("CR-2026-017 disablement evidence changed")
    disablement = _read_object(disablement_path)
    if (
        disablement.get("resume_allowed") is not False
        or disablement.get("reuse_allowed") is not False
        or disablement.get("delete_allowed") is not False
    ):
        raise ValueError("CR-2026-017 disablement boundary changed")
    amendment = {
        "schema_name": "stage2-v2-release-only-authority-amendment",
        "amendment_version": "1.0",
        "status": "AUTHORIZED_RELEASE_ONLY",
        "change_request": "CR-2026-018",
        "approved_by": "Muce",
        "approved_at": "2026-07-20",
        "target_run_id": TARGET_RUN_ID,
        "baseline_generation_commit": BASELINE_COMMIT,
        "baseline_generation_code_tree_sha256": BASELINE_CODE_TREE_SHA256,
        "release_code_commit": release_commit,
        "release_code_tree_sha256": release_tree,
        "checkpoint_sha256": target["checkpoint_sha256"],
        "runtime_manifest_hash": RUNTIME_MANIFEST_HASH,
        "run_a_protection_hash": RUN_A_PROTECTION_HASH,
        "migration_manifest_hash": MIGRATION_MANIFEST_HASH,
        "sealed_input_set_sha256": target["sealed_input_set_sha256"],
        "partition_count": EXPECTED_PARTITIONS,
        "group1_partition_count": EXPECTED_GROUP1_PARTITIONS,
        "fragment_count": EXPECTED_FRAGMENTS,
        "object_count": EXPECTED_OBJECTS,
        "seal_count": EXPECTED_SEALS,
        "foundation_object_count": EXPECTED_FOUNDATION_OBJECTS,
        "group1_object_count": EXPECTED_GROUP1_OBJECTS,
        "allowed_commands": list(ALLOWED_COMMANDS),
        "generation_allowed": False,
        "resume_allowed": False,
        "repacking_allowed": False,
        "adoption_allowed": False,
        "input_mutation_allowed": False,
        "delete_allowed": False,
        "source_disablement_sha256": EXPECTED_DISABLEMENT_SHA256,
        "superseded_run_id": SUPERSEDED_RUN_ID,
        "superseded_run_checkpoint_sha256": superseded["checkpoint_sha256"],
    }
    supersession = {
        "schema_name": "stage2-v2-incomplete-run-supersession",
        "supersession_version": "1.0",
        "status": "SUPERSEDED_INCOMPLETE_NO_REUSE",
        "change_request": "CR-2026-018",
        "run_id": SUPERSEDED_RUN_ID,
        "checkpoint_sha256": superseded["checkpoint_sha256"],
        "prior_status": "INTERRUPTED_RECOVERABLE",
        "completed_tasks": 2,
        "packed_seals": EXPECTED_SUPERSEDED_PACKED_SEALS,
        "partial_files": 3,
        "published_files": 0,
        "resume_allowed": False,
        "reuse_allowed": False,
        "delete_allowed": False,
        "replacement_run_allowed": False,
        "release_target_run_id": TARGET_RUN_ID,
        "release_code_commit": release_commit,
    }
    amendment_path = _amendment_path()
    supersession_path = _superseded_root() / "reports/supersession-cr-2026-018.json"
    _write_once(amendment_path, amendment)
    _write_once(supersession_path, supersession)
    return {
        "status": amendment["status"],
        "target_run_id": TARGET_RUN_ID,
        "amendment_path": str(amendment_path),
        "amendment_sha256": sha256_file(amendment_path),
        "superseded_run_id": SUPERSEDED_RUN_ID,
        "supersession_path": str(supersession_path),
        "supersession_sha256": sha256_file(supersession_path),
    }


def _preflight() -> dict[str, Any]:
    amendment = _validated_amendment()
    target = _validate_target_run()
    _require_no_publication()
    orchestrator = ReleaseOnlyOrchestrator(ProductionRuntimeV2Backend())
    context, checkpoint = orchestrator._load_run(  # noqa: SLF001 - bounded authority adapter
        TARGET_RUN_ID,
        _runtime_manifest_path(),
        _snapshot_id(),
        _protection_path(),
        _migration_path(),
        mutating=False,
    )
    if checkpoint.status != "GROUP1_COMPLETE":
        raise ValueError("release-only preflight requires GROUP1_COMPLETE")
    orchestrator._verify_completed(context, checkpoint)  # noqa: SLF001
    report = {
        "schema_name": "stage2-v2-release-only-preflight",
        "preflight_version": "1.0",
        "status": "PASS",
        "change_request": "CR-2026-018",
        "target_run_id": TARGET_RUN_ID,
        "release_authority_sha256": sha256_file(_amendment_path()),
        "release_code_commit": amendment["release_code_commit"],
        "checkpoint_sha256": target["checkpoint_sha256"],
        "sealed_input_set_sha256": EXPECTED_INPUT_SET_SHA256,
        "checked_task_count": len(EXPECTED_TASKS),
        "checked_partition_count": EXPECTED_PARTITIONS,
        "checked_object_count": EXPECTED_OBJECTS,
        "checked_seal_count": EXPECTED_SEALS,
        "physical_object_hash_verification": "PASS",
        "publication_absent": True,
    }
    path = _preflight_path()
    _write_once(path, report)
    return {"status": "PASS", "path": str(path), "physical_sha256": sha256_file(path)}


def _execute(action: str) -> dict[str, Any]:
    if action not in ALLOWED_COMMANDS:
        raise ValueError("release-only command is not allowed")
    _validated_amendment()
    _validated_preflight()
    _validate_target_run()
    orchestrator = ReleaseOnlyOrchestrator(ProductionRuntimeV2Backend())
    runtime_manifest = _runtime_manifest_path()
    snapshot_id = _snapshot_id()
    protection = _protection_path()
    migration = _migration_path()
    subflow = {"release": "RELEASE", "verify": "VERIFY", "compare": "RUN_A_RUN_B_COMPARE"}[action]
    progress = PipelineProgressStore(_target_root())
    progress.update(
        name=subflow,
        status="RUNNING",
        current_item=action,
        message=f"CR-2026-018 release-only {action} started",
    )
    result: RuntimeV2Checkpoint | RuntimeVerification | RuntimeComparison
    try:
        if action == "release":
            result = orchestrator.release(
                run_id=TARGET_RUN_ID,
                manifest_path=runtime_manifest,
                snapshot_id=snapshot_id,
                protection_path=protection,
                migration_path=migration,
            )
        elif action == "verify":
            result = orchestrator.verify(
                run_id=TARGET_RUN_ID,
                manifest_path=runtime_manifest,
                snapshot_id=snapshot_id,
                protection_path=protection,
                migration_path=migration,
            )
        else:
            result = orchestrator.compare(
                run_id=TARGET_RUN_ID,
                manifest_path=runtime_manifest,
                snapshot_id=snapshot_id,
                protection_path=protection,
                migration_path=migration,
            )
    except Exception as exc:
        progress.update(
            name=subflow,
            status="FAILED",
            current_item=action,
            message=f"CR-2026-018 {action} failed: {type(exc).__name__}: {exc}",
            level="ERROR",
        )
        raise
    progress.update(
        name=subflow,
        status="PASS",
        done=1,
        total=1,
        current_item=action,
        message=f"CR-2026-018 release-only {action} completed",
    )
    payload = result.model_dump(mode="json")
    if isinstance(result, RuntimeVerification):
        if (
            result.checked_task_count != len(EXPECTED_TASKS)
            or result.checked_partition_count != EXPECTED_PARTITIONS
            or result.unknown_count != 0
            or result.error_count != 0
        ):
            raise ValueError("release-only verification coverage changed")
    if isinstance(result, RuntimeComparison):
        if (
            result.matched_partition_count != EXPECTED_GROUP1_PARTITIONS
            or result.difference_count != 0
        ):
            raise ValueError("release-only exact comparison differs")
    return payload


def _validated_amendment() -> dict[str, Any]:
    release_commit, release_tree = _assert_release_code_authority(require_clean=True)
    amendment = _read_object(_amendment_path())
    target = _validate_target_run()
    if (
        amendment.get("status") != "AUTHORIZED_RELEASE_ONLY"
        or amendment.get("change_request") != "CR-2026-018"
        or amendment.get("target_run_id") != TARGET_RUN_ID
        or amendment.get("release_code_commit") != release_commit
        or amendment.get("release_code_tree_sha256") != release_tree
        or amendment.get("checkpoint_sha256") != target["checkpoint_sha256"]
        or amendment.get("sealed_input_set_sha256") != EXPECTED_INPUT_SET_SHA256
        or amendment.get("allowed_commands") != list(ALLOWED_COMMANDS)
        or amendment.get("generation_allowed") is not False
        or amendment.get("resume_allowed") is not False
        or amendment.get("repacking_allowed") is not False
        or amendment.get("input_mutation_allowed") is not False
        or amendment.get("delete_allowed") is not False
    ):
        raise ValueError("release-only Authority amendment changed")
    supersession = _read_object(_superseded_root() / "reports/supersession-cr-2026-018.json")
    if (
        supersession.get("status") != "SUPERSEDED_INCOMPLETE_NO_REUSE"
        or supersession.get("run_id") != SUPERSEDED_RUN_ID
        or supersession.get("release_target_run_id") != TARGET_RUN_ID
        or supersession.get("resume_allowed") is not False
        or supersession.get("reuse_allowed") is not False
        or supersession.get("delete_allowed") is not False
    ):
        raise ValueError("superseded successor boundary changed")
    return amendment


def _validated_preflight() -> dict[str, Any]:
    report = _read_object(_preflight_path())
    if (
        report.get("status") != "PASS"
        or report.get("target_run_id") != TARGET_RUN_ID
        or report.get("release_authority_sha256") != sha256_file(_amendment_path())
        or report.get("sealed_input_set_sha256") != EXPECTED_INPUT_SET_SHA256
        or report.get("checked_partition_count") != EXPECTED_PARTITIONS
        or report.get("checked_object_count") != EXPECTED_OBJECTS
        or report.get("checked_seal_count") != EXPECTED_SEALS
        or report.get("physical_object_hash_verification") != "PASS"
    ):
        raise ValueError("release-only preflight evidence changed")
    return report


def _assert_release_code_authority(*, require_clean: bool) -> tuple[str, str]:
    if _git("branch", "--show-current") != RELEASE_BRANCH:
        raise ValueError(f"release-only execution requires {RELEASE_BRANCH}")
    if require_clean and _git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("release-only execution requires a clean worktree")
    changed = tuple(
        item
        for item in _git(
            "diff",
            "--name-only",
            BASELINE_COMMIT,
            "HEAD",
            "--",
            "scripts/run_stage2_research.py",
            "src/era100x/data/schema/models.py",
            "src/era100x/research/stage_2/contracts",
            "src/era100x/research/stage_2/episodes",
            "src/era100x/research/stage_2/features/foundation",
            "src/era100x/research/stage_2/gates",
            "src/era100x/research/stage_2/key_levels",
            "src/era100x/research/stage_2/manifests/configuration.py",
            "src/era100x/research/stage_2/manifests/models.py",
            "src/era100x/research/stage_2/pipelines/candidates",
            "src/era100x/research/stage_2/pipelines/v2",
            "src/era100x/research/stage_2/runtime_v2",
        ).splitlines()
        if item
    )
    if changed != (CATALOG_PATH,):
        raise ValueError(f"release-only Runtime V2 code scope changed: {changed}")
    baseline = _git("show", f"{BASELINE_COMMIT}:{CATALOG_PATH}")
    current = (ROOT / CATALOG_PATH).read_text(encoding="utf-8")
    removed_catalog_gate_lines = tuple(
        line.strip()
        for line in baseline.splitlines()
        if 'raise CatalogIntegrityError("catalog object/seal summaries' in line
    )
    if len(removed_catalog_gate_lines) != 1 or removed_catalog_gate_lines[0] in current:
        raise ValueError("release-only Catalog correction differs")
    return _git("rev-parse", "HEAD"), compute_v2_code_tree_sha256(ROOT)


def _validate_target_run() -> dict[str, Any]:
    root = _target_root()
    _assert_run_idle(root)
    checkpoint_path = root / "checkpoint-v2.json"
    checkpoint = _read_object(checkpoint_path)
    tasks = tuple(
        item.get("task_id")
        for item in checkpoint.get("completed_tasks", [])
        if isinstance(item, dict)
    )
    if (
        checkpoint.get("run_id") != TARGET_RUN_ID
        or checkpoint.get("status") != "GROUP1_COMPLETE"
        or checkpoint.get("phase") != "GROUP1"
        or checkpoint.get("revision") != EXPECTED_TARGET_REVISION
        or checkpoint.get("active_task") is not None
        or checkpoint.get("failure") is not None
        or checkpoint.get("resource_pause") is not None
        or tasks != EXPECTED_TASKS
    ):
        raise ValueError("target release-only checkpoint changed")
    if _formal_files(root / "staging/group1/partials"):
        raise ValueError("target release-only Run contains partial files")
    if len(_json_files_recursive(root / "staging/group1/packed-seals")) != EXPECTED_GROUP1_OBJECTS:
        raise ValueError("target Group-1 packed Seal coverage changed")
    if len(_json_files(root / "staging/evidence/group1-components")) != 4:
        raise ValueError("target Group-1 component coverage changed")
    summary = _sealed_input_summary(root)
    if (
        summary["partition_count"] != EXPECTED_PARTITIONS
        or summary["fragment_count"] != EXPECTED_FRAGMENTS
        or summary["object_count"] != EXPECTED_OBJECTS
        or summary["seal_count"] != EXPECTED_SEALS
        or summary["foundation_object_count"] != EXPECTED_FOUNDATION_OBJECTS
        or summary["group1_object_count"] != EXPECTED_GROUP1_OBJECTS
        or summary["sealed_input_set_sha256"] != EXPECTED_INPUT_SET_SHA256
    ):
        raise ValueError("target 208-item sealed input set changed")
    return {
        **summary,
        "checkpoint_sha256": sha256_file(checkpoint_path),
    }


def _validate_superseded_run() -> dict[str, Any]:
    root = _superseded_root()
    _assert_run_idle(root)
    checkpoint_path = root / "checkpoint-v2.json"
    checkpoint = _read_object(checkpoint_path)
    tasks = tuple(
        item.get("task_id")
        for item in checkpoint.get("completed_tasks", [])
        if isinstance(item, dict)
    )
    if (
        checkpoint.get("run_id") != SUPERSEDED_RUN_ID
        or checkpoint.get("status") != "INTERRUPTED_RECOVERABLE"
        or checkpoint.get("phase") != "GROUP1"
        or checkpoint.get("revision") != EXPECTED_SUPERSEDED_REVISION
        or checkpoint.get("active_task") != "GROUP1:BTCUSDT:V1_PRICE"
        or checkpoint.get("failure") is not None
        or checkpoint.get("resource_pause") is not None
        or tasks != EXPECTED_TASKS[:2]
        or len(_json_files_recursive(root / "staging/group1/packed-seals"))
        != EXPECTED_SUPERSEDED_PACKED_SEALS
        or len(_formal_files(root / "staging/group1/partials")) != 3
        or _formal_files(root / "published")
    ):
        raise ValueError("superseded successor state changed")
    return {"checkpoint_sha256": sha256_file(checkpoint_path)}


def _sealed_input_summary(root: Path) -> dict[str, Any]:
    evidence_paths = _json_files(root / "staging/backend-evidence")
    if len(evidence_paths) != len(EXPECTED_TASKS):
        raise ValueError("target backend evidence matrix changed")
    object_ids: dict[str, dict[str, Any]] = {}
    seal_ids: dict[str, dict[str, Any]] = {}
    task_ids: list[str] = []
    partition_count = 0
    fragment_count = 0
    foundation_objects = 0
    group1_objects = 0
    for path in evidence_paths:
        value = _read_object(path)
        task_id = value.get("task_id")
        if not isinstance(task_id, str):
            raise ValueError("backend evidence task_id is missing")
        task_ids.append(task_id)
        artifacts = value.get("artifacts")
        receipts = value.get("receipts")
        fragments = value.get("fragments")
        seals = value.get("seals")
        if not all(isinstance(item, list) for item in (artifacts, receipts, fragments, seals)):
            raise ValueError("backend evidence collection is invalid")
        typed_artifacts = cast(list[dict[str, Any]], artifacts)
        typed_seals = cast(list[dict[str, Any]], seals)
        partition_count += len(cast(list[Any], receipts))
        fragment_count += len(cast(list[Any], fragments))
        if task_id.startswith("FOUNDATION:"):
            foundation_objects += len(typed_artifacts)
        else:
            group1_objects += len(typed_artifacts)
        for artifact in typed_artifacts:
            object_id = artifact.get("object_sha256")
            if not isinstance(object_id, str):
                raise ValueError("ArtifactRef object hash is missing")
            existing = object_ids.setdefault(object_id, artifact)
            if existing != artifact:
                raise ValueError("conflicting ArtifactRef identity")
        for seal in typed_seals:
            shard_id = seal.get("shard_id")
            if not isinstance(shard_id, str):
                raise ValueError("ShardSeal shard_id is missing")
            existing = seal_ids.setdefault(shard_id, seal)
            if existing != seal:
                raise ValueError("conflicting ShardSeal identity")
    if set(task_ids) != set(EXPECTED_TASKS):
        raise ValueError("target backend evidence tasks changed")
    basis = {
        "tasks": sorted(task_ids),
        "partition_count": partition_count,
        "fragment_count": fragment_count,
        "object_count": len(object_ids),
        "seal_count": len(seal_ids),
        "object_sha256s": sorted(object_ids),
        "seal_hashes": sorted(cast(str, seal["seal_hash"]) for seal in seal_ids.values()),
    }
    digest = hashlib.sha256(canonical_json(basis).encode()).hexdigest()
    return {
        "partition_count": partition_count,
        "fragment_count": fragment_count,
        "object_count": len(object_ids),
        "seal_count": len(seal_ids),
        "foundation_object_count": foundation_objects,
        "group1_object_count": group1_objects,
        "sealed_input_set_sha256": digest,
    }


def _require_no_publication() -> None:
    root = _target_root()
    if (
        _formal_files(root / "published")
        or (root / "reports/v2-publication-record.json").exists()
        or (root / "reports/v2-run-a-comparison.json").exists()
    ):
        raise ValueError("release-only preflight requires an unpublished target")


def _assert_run_idle(root: Path) -> None:
    path = root / "orchestration-v2.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(f"Runtime V2 command is active for {root.name}") from exc
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _runtime_manifest_path() -> Path:
    return _authority_root() / "manifests" / f"{RUNTIME_MANIFEST_HASH}.json"


def _protection_path() -> Path:
    return _authority_root() / "manifests" / f"{RUN_A_PROTECTION_HASH}.json"


def _migration_path() -> Path:
    return _authority_root() / "manifests" / f"{MIGRATION_MANIFEST_HASH}.json"


def _snapshot_id() -> str:
    value = _read_object(_runtime_manifest_path()).get("snapshot_id")
    if not isinstance(value, str):
        raise ValueError("Runtime V2 snapshot_id is missing")
    return value


def _target_root() -> Path:
    return _bounded_root(TARGET_RUN_ID)


def _superseded_root() -> Path:
    return _bounded_root(SUPERSEDED_RUN_ID)


def _authority_root() -> Path:
    return _bounded_root(AUTHORITY_RUN_ID)


def _bounded_root(run_id: str) -> Path:
    root = (RUNS_ROOT / run_id).resolve()
    if not root.is_dir() or root.is_symlink() or not root.is_relative_to(RUNS_ROOT.resolve()):
        raise FileNotFoundError(root)
    return root


def _amendment_path() -> Path:
    return _target_root() / "reports/release-only-authority-cr-2026-018.json"


def _preflight_path() -> Path:
    return _target_root() / "reports/release-only-preflight-cr-2026-018.json"


def _json_files(root: Path) -> tuple[Path, ...]:
    if not root.is_dir() or root.is_symlink():
        return ()
    return tuple(
        path
        for path in sorted(root.glob("*.json"))
        if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
    )


def _json_files_recursive(root: Path) -> tuple[Path, ...]:
    if not root.is_dir() or root.is_symlink():
        return ()
    return tuple(
        path
        for path in sorted(root.rglob("*.json"))
        if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
    )


def _formal_files(root: Path) -> tuple[Path, ...]:
    if not root.exists():
        return ()
    return tuple(
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
    )


def _read_object(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return cast(dict[str, Any], value)


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    encoded = (canonical_json(payload) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != encoded:
            raise FileExistsError(f"append-only CR-2026-018 evidence differs: {path}")
        return
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


if __name__ == "__main__":
    raise SystemExit(main())
