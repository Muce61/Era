#!/usr/bin/env python3
"""Authorize and run only the CR-2026-019 exact Run-A comparison."""

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
    Stage2V2Orchestrator,
    _LoadedAuthorities,
    compute_v2_code_tree_sha256,
)
from era100x.research.stage_2.runtime_v2.production_backend import (
    ProductionRuntimeV2Backend,
)
from era100x.research.stage_2.runtime_v2.progress import PipelineProgressStore
from era100x.research.stage_2.runtime_v2.transition import sha256_file

ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = Path("/Volumes/FuckingLife/era100x_stage2/runs")
COMPARE_BRANCH = "codex/stage2-cr019-compare-only"
RELEASE_COMMIT = "9857bd83c73c0b0e103e5600e41f89d3e698ae41"
BASELINE_COMMIT = "9c4b7c423a0479e3d1eb8b6f6423c2d09f2f2813"
BASELINE_CODE_TREE_SHA256 = "b605ab38f693ebb227bfea7def80a690d04d7c33ada470d0001494f2520226b4"
TARGET_RUN_ID = "stage2-g1-v2-b-20260720T111704Z-9c4b7c423a04"
AUTHORITY_RUN_ID = "stage2-g1-v2-authority-20260720T111704Z-9c4b7c423a04"
RUNTIME_MANIFEST_HASH = "7c4c40c482b309108ae821cdd8185d6f5674721a71411bae4163fd4184cddb53"
RUN_A_PROTECTION_HASH = "330b7cddea33f42fff4d7638cf54a3067073ad052f33e2dac9273aee1842f7da"
MIGRATION_MANIFEST_HASH = "c89cd57b1de7110c7f853cb2e2ebda45619819be1c37193ef8ad90ed35e52259"
EXPECTED_TARGET_REVISION = 12
EXPECTED_PARTITIONS = 80_784
EXPECTED_GROUP1_PARTITIONS = 61_776
EXPECTED_FRAGMENTS = 77_265
EXPECTED_OBJECTS = 208
EXPECTED_SEALS = 208
EXPECTED_FOUNDATION_OBJECTS = 164
EXPECTED_GROUP1_OBJECTS = 44
EXPECTED_INPUT_SET_SHA256 = "ed861c67c3401b11117bbd1da3bd94c6773ca63766bfed57b9742325fde6f3d8"
EXPECTED_TASKS = (
    "FOUNDATION:BTCUSDT",
    "FOUNDATION:ETHUSDT",
    "GROUP1:BTCUSDT:V1_PRICE",
    "GROUP1:BTCUSDT:V1_FLOW",
    "GROUP1:ETHUSDT:V1_PRICE",
    "GROUP1:ETHUSDT:V1_FLOW",
)
PRODUCTION_BACKEND_PATH = "src/era100x/research/stage_2/runtime_v2/production_backend.py"
EXPECTED_RELEASE_AUTHORITY_SHA256 = (
    "c1fcc17d9d365d385f71ca3fb59b8d70724e387b996be8f568e34af323687a89"
)
EXPECTED_RELEASE_PREFLIGHT_SHA256 = (
    "485f5bdc710866d25d75a5f5669283478af478f3d3e790f50ca20aee50c21351"
)
EXPECTED_PUBLICATION_RECORD_SHA256 = (
    "aab429f8e1d3ed50ffce65befabb19e98a80b974521ddd216d4ddfc7c98d6a36"
)
EXPECTED_QUALITY_REPORT_SHA256 = "eb0aec8246dbe2dfd51b512e0bc92549f05a85e90f0a2369af5af765910dda55"
EXPECTED_PUBLISHED_CATALOG_SHA256 = (
    "95332819f6abf30b017f6e8376b47c88b766784b964bfbadb17f5b8ef64766b9"
)
EXPECTED_CATALOG_HASH = "cf56286d09c88f8976bc7eb298db3da38686ae3892d00f9efefb6a7b467912aa"
EXPECTED_QUALITY_REPORT_HASH = "902bb29a50f21535b7d0f464e72204ee37be673afae80ac369f838da52b88549"
EXPECTED_PUBLICATION_RECORD_HASH = (
    "3b758bb1181a44173c6214d095b61026513570ae93c5e52887b3d75680e7e5a8"
)
EXPECTED_SNAPSHOT_ID = "df15b9cbb208a6f921b3a68bee24be44f77e83eb2c8ac1582ef942b108708d33"
ALLOWED_COMMANDS = ("compare",)

_CODE_SURFACES = (
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
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("action", choices=("authorize", *ALLOWED_COMMANDS))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    action = parser().parse_args(argv).action
    output = _authorize() if action == "authorize" else _execute_compare()
    print(canonical_json(output))
    return 0


class CompareOnlyOrchestrator(Stage2V2Orchestrator):
    """Retain generation authority while accepting one compare-only overlay."""

    def _assert_repository_authority(self, authorities: _LoadedAuthorities) -> None:
        amendment = _validated_amendment()
        if authorities.manifest.code_tree_sha256 != BASELINE_CODE_TREE_SHA256:
            raise ValueError("target Run generation code tree changed")
        if authorities.migration.v2_code_commit != BASELINE_COMMIT:
            raise ValueError("target Run generation commit changed")
        if amendment["compare_code_commit"] != _git("rev-parse", "HEAD"):
            raise ValueError("compare-only amendment commit differs from HEAD")
        if amendment["compare_code_tree_sha256"] != compute_v2_code_tree_sha256(ROOT):
            raise ValueError("compare-only amendment code tree differs")


def _authorize() -> dict[str, Any]:
    compare_commit, compare_tree = _assert_compare_code_authority(require_clean=True)
    target = _validate_target_run()
    publication = _validate_published_state()
    _validate_release_evidence()
    _require_no_comparison()
    amendment = {
        "schema_name": "stage2-v2-compare-only-authority-amendment",
        "amendment_version": "1.0",
        "status": "AUTHORIZED_COMPARE_ONLY",
        "change_request": "CR-2026-019",
        "approved_by": "Muce",
        "approved_at": "2026-07-21",
        "target_run_id": TARGET_RUN_ID,
        "baseline_generation_commit": BASELINE_COMMIT,
        "baseline_generation_code_tree_sha256": BASELINE_CODE_TREE_SHA256,
        "release_code_commit": RELEASE_COMMIT,
        "release_authority_sha256": EXPECTED_RELEASE_AUTHORITY_SHA256,
        "release_preflight_sha256": EXPECTED_RELEASE_PREFLIGHT_SHA256,
        "compare_code_commit": compare_commit,
        "compare_code_tree_sha256": compare_tree,
        "checkpoint_sha256": target["checkpoint_sha256"],
        "runtime_manifest_hash": RUNTIME_MANIFEST_HASH,
        "run_a_protection_hash": RUN_A_PROTECTION_HASH,
        "migration_manifest_hash": MIGRATION_MANIFEST_HASH,
        "sealed_input_set_sha256": target["sealed_input_set_sha256"],
        "published_snapshot_id": EXPECTED_SNAPSHOT_ID,
        "published_catalog_sha256": publication["published_catalog_sha256"],
        "catalog_hash": EXPECTED_CATALOG_HASH,
        "publication_record_sha256": publication["publication_record_sha256"],
        "publication_record_hash": EXPECTED_PUBLICATION_RECORD_HASH,
        "quality_report_sha256": publication["quality_report_sha256"],
        "quality_report_hash": EXPECTED_QUALITY_REPORT_HASH,
        "partition_count": EXPECTED_PARTITIONS,
        "group1_partition_count": EXPECTED_GROUP1_PARTITIONS,
        "fragment_count": EXPECTED_FRAGMENTS,
        "object_count": EXPECTED_OBJECTS,
        "seal_count": EXPECTED_SEALS,
        "allowed_commands": list(ALLOWED_COMMANDS),
        "generation_allowed": False,
        "release_allowed": False,
        "verification_allowed": False,
        "resume_allowed": False,
        "repacking_allowed": False,
        "adoption_allowed": False,
        "successor_creation_allowed": False,
        "input_mutation_allowed": False,
        "delete_allowed": False,
    }
    path = _amendment_path()
    _write_once(path, amendment)
    return {
        "status": amendment["status"],
        "target_run_id": TARGET_RUN_ID,
        "amendment_path": str(path),
        "amendment_sha256": sha256_file(path),
    }


def _execute_compare() -> dict[str, Any]:
    amendment = _validated_amendment()
    _validate_target_run()
    _validate_published_state()
    _validate_release_evidence()
    _require_no_comparison()
    orchestrator = CompareOnlyOrchestrator(ProductionRuntimeV2Backend())
    progress = PipelineProgressStore(_target_root())
    progress.update(
        name="RUN_A_RUN_B_COMPARE",
        status="RUNNING",
        done=0,
        total=EXPECTED_GROUP1_PARTITIONS,
        current_item="compare",
        message="CR-2026-019 exact comparison started",
    )
    try:
        result = orchestrator.compare(
            run_id=TARGET_RUN_ID,
            manifest_path=_runtime_manifest_path(),
            snapshot_id=_snapshot_id(),
            protection_path=_protection_path(),
            migration_path=_migration_path(),
        )
        _validate_comparison_result(result)
    except Exception as exc:
        progress.update(
            name="RUN_A_RUN_B_COMPARE",
            status="FAILED",
            done=0,
            total=EXPECTED_GROUP1_PARTITIONS,
            current_item="compare",
            message=f"CR-2026-019 compare failed: {type(exc).__name__}: {exc}",
            level="ERROR",
        )
        raise
    progress.update(
        name="RUN_A_RUN_B_COMPARE",
        status="PASS",
        done=EXPECTED_GROUP1_PARTITIONS,
        total=EXPECTED_GROUP1_PARTITIONS,
        current_item="compare",
        message="CR-2026-019 exact comparison completed: 61,776/61,776 matched",
    )
    return {
        **result.model_dump(mode="json"),
        "authority_sha256": sha256_file(_amendment_path()),
        "comparison_report_sha256": sha256_file(_comparison_path()),
        "compare_code_commit": amendment["compare_code_commit"],
    }


def _validated_amendment() -> dict[str, Any]:
    compare_commit, compare_tree = _assert_compare_code_authority(require_clean=True)
    target = _validate_target_run()
    publication = _validate_published_state()
    _validate_release_evidence()
    amendment = _read_object(_amendment_path())
    if (
        amendment.get("status") != "AUTHORIZED_COMPARE_ONLY"
        or amendment.get("change_request") != "CR-2026-019"
        or amendment.get("target_run_id") != TARGET_RUN_ID
        or amendment.get("compare_code_commit") != compare_commit
        or amendment.get("compare_code_tree_sha256") != compare_tree
        or amendment.get("checkpoint_sha256") != target["checkpoint_sha256"]
        or amendment.get("sealed_input_set_sha256") != EXPECTED_INPUT_SET_SHA256
        or amendment.get("published_catalog_sha256") != publication["published_catalog_sha256"]
        or amendment.get("publication_record_sha256") != publication["publication_record_sha256"]
        or amendment.get("quality_report_sha256") != publication["quality_report_sha256"]
        or amendment.get("allowed_commands") != list(ALLOWED_COMMANDS)
        or any(
            amendment.get(field) is not False
            for field in (
                "generation_allowed",
                "release_allowed",
                "verification_allowed",
                "resume_allowed",
                "repacking_allowed",
                "adoption_allowed",
                "successor_creation_allowed",
                "input_mutation_allowed",
                "delete_allowed",
            )
        )
    ):
        raise ValueError("compare-only Authority amendment changed")
    return amendment


def _assert_compare_code_authority(*, require_clean: bool) -> tuple[str, str]:
    if _git("branch", "--show-current") != COMPARE_BRANCH:
        raise ValueError(f"compare-only execution requires {COMPARE_BRANCH}")
    if require_clean and _git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("compare-only execution requires a clean worktree")
    changed = tuple(
        path
        for path in _git(
            "diff", "--name-only", RELEASE_COMMIT, "HEAD", "--", *_CODE_SURFACES
        ).splitlines()
        if path
    )
    if changed != (PRODUCTION_BACKEND_PATH,):
        raise ValueError(f"compare-only Runtime V2 code scope changed: {changed}")
    numstat = _git("diff", "--numstat", RELEASE_COMMIT, "HEAD", "--", PRODUCTION_BACKEND_PATH)
    if numstat != f"1\t1\t{PRODUCTION_BACKEND_PATH}":
        raise ValueError("compare-only production correction is not exactly one line")
    baseline = _git("show", f"{RELEASE_COMMIT}:{PRODUCTION_BACKEND_PATH}")
    current = (ROOT / PRODUCTION_BACKEND_PATH).read_text(encoding="utf-8")
    old = "v2_legacy_hash_algorithm=V2_RECEIPT_LEGACY_HASH_ALGORITHM"
    new = "v2_legacy_hash_algorithm=LEGACY_HASH_ALGORITHM"
    marker_filter = "receipt.legacy_hash_algorithm == V2_RECEIPT_LEGACY_HASH_ALGORITHM"
    if (
        old not in baseline
        or old in current
        or current.count(new) != 1
        or marker_filter not in current
    ):
        raise ValueError("compare-only algorithm-authority correction differs")
    return _git("rev-parse", "HEAD"), compute_v2_code_tree_sha256(ROOT)


def _validate_release_evidence() -> None:
    authority_path = _release_amendment_path()
    preflight_path = _release_preflight_path()
    if sha256_file(authority_path) != EXPECTED_RELEASE_AUTHORITY_SHA256:
        raise ValueError("CR-2026-018 release Authority changed")
    if sha256_file(preflight_path) != EXPECTED_RELEASE_PREFLIGHT_SHA256:
        raise ValueError("CR-2026-018 release preflight changed")
    authority = _read_object(authority_path)
    preflight = _read_object(preflight_path)
    if (
        authority.get("status") != "AUTHORIZED_RELEASE_ONLY"
        or authority.get("target_run_id") != TARGET_RUN_ID
        or authority.get("release_code_commit") != RELEASE_COMMIT
        or authority.get("sealed_input_set_sha256") != EXPECTED_INPUT_SET_SHA256
        or preflight.get("status") != "PASS"
        or preflight.get("checked_partition_count") != EXPECTED_PARTITIONS
        or preflight.get("physical_object_hash_verification") != "PASS"
    ):
        raise ValueError("CR-2026-018 release evidence changed")


def _validate_published_state() -> dict[str, str]:
    root = _target_root()
    record_path = root / "reports/v2-publication-record.json"
    quality_path = root / "reports/v2-quality-report.json"
    catalog_path = root / "published/snapshots" / EXPECTED_SNAPSHOT_ID / "catalog.json"
    hashes = {
        "publication_record_sha256": sha256_file(record_path),
        "quality_report_sha256": sha256_file(quality_path),
        "published_catalog_sha256": sha256_file(catalog_path),
    }
    if hashes != {
        "publication_record_sha256": EXPECTED_PUBLICATION_RECORD_SHA256,
        "quality_report_sha256": EXPECTED_QUALITY_REPORT_SHA256,
        "published_catalog_sha256": EXPECTED_PUBLISHED_CATALOG_SHA256,
    }:
        raise ValueError("published evidence bytes changed")
    record = _read_object(record_path)
    quality = _read_object(quality_path)
    if (
        record.get("publication_state") != "PUBLISHED_WITH_RESOURCE_ANOMALIES"
        or record.get("record_hash") != EXPECTED_PUBLICATION_RECORD_HASH
        or record.get("catalog_hash") != EXPECTED_CATALOG_HASH
        or record.get("quality_report_hash") != EXPECTED_QUALITY_REPORT_HASH
        or record.get("snapshot_id") != EXPECTED_SNAPSHOT_ID
        or quality.get("quality_status") != "PASS"
        or quality.get("catalog_hash") != EXPECTED_CATALOG_HASH
        or quality.get("report_hash") != EXPECTED_QUALITY_REPORT_HASH
        or quality.get("task_count") != len(EXPECTED_TASKS)
        or quality.get("partition_count") != EXPECTED_PARTITIONS
        or quality.get("fragment_count") != EXPECTED_FRAGMENTS
        or quality.get("object_count") != EXPECTED_OBJECTS
        or quality.get("seal_count") != EXPECTED_SEALS
        or quality.get("unknown_count") != 0
        or quality.get("error_count") != 0
        or quality.get("identity_conflict_count") != 0
    ):
        raise ValueError("published evidence semantics changed")
    return hashes


def _validate_comparison_result(result: RuntimeComparison) -> None:
    report = _read_object(_comparison_path())
    payload = report.get("report")
    if not isinstance(payload, dict):
        raise TypeError("comparison report payload is missing")
    if (
        result.matched_partition_count != EXPECTED_GROUP1_PARTITIONS
        or result.difference_count != 0
        or payload.get("status") != "PASS"
        or payload.get("matched_partition_count") != EXPECTED_GROUP1_PARTITIONS
        or payload.get("missing_in_v2") != []
        or payload.get("extra_in_v2") != []
        or payload.get("differences") != []
    ):
        raise ValueError("compare-only exact comparison differs")


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
        raise ValueError("target compare-only checkpoint changed")
    if _formal_files(root / "staging/group1/partials"):
        raise ValueError("target compare-only Run contains partial files")
    if len(_json_files_recursive(root / "staging/group1/packed-seals")) != EXPECTED_GROUP1_OBJECTS:
        raise ValueError("target Group-1 packed Seal coverage changed")
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
    return {**summary, "checkpoint_sha256": sha256_file(checkpoint_path)}


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


def _authority_root() -> Path:
    return _bounded_root(AUTHORITY_RUN_ID)


def _bounded_root(run_id: str) -> Path:
    root = (RUNS_ROOT / run_id).resolve()
    if not root.is_dir() or root.is_symlink() or not root.is_relative_to(RUNS_ROOT.resolve()):
        raise FileNotFoundError(root)
    return root


def _require_no_comparison() -> None:
    if _comparison_path().exists():
        raise FileExistsError("append-only exact comparison already exists")


def _amendment_path() -> Path:
    return _target_root() / "reports/compare-only-authority-cr-2026-019.json"


def _comparison_path() -> Path:
    return _target_root() / "reports/v2-run-a-comparison.json"


def _release_amendment_path() -> Path:
    return _target_root() / "reports/release-only-authority-cr-2026-018.json"


def _release_preflight_path() -> Path:
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
            raise FileExistsError(f"append-only CR-2026-019 evidence differs: {path}")
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
