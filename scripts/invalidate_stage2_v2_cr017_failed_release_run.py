#!/usr/bin/env python3
"""Append-only disablement of the CR-2026-017 failed-release Run B."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from era100x.research.stage_2.manifests.models import canonical_json
from era100x.research.stage_2.runtime_v2.group1_packing_recovery import (
    Group1MonthlyAdoptionManifestV1,
)
from era100x.research.stage_2.runtime_v2.progress import PipelineProgressV1

RUNS_ROOT = Path("/Volumes/FuckingLife/era100x_stage2/runs")
FAILED_RELEASE_RUN_ID = "stage2-g1-v2-b-20260720T111704Z-9c4b7c423a04"
EXPECTED_REVISION = 12
EXPECTED_TASKS = (
    "FOUNDATION:BTCUSDT",
    "FOUNDATION:ETHUSDT",
    "GROUP1:BTCUSDT:V1_PRICE",
    "GROUP1:BTCUSDT:V1_FLOW",
    "GROUP1:ETHUSDT:V1_PRICE",
    "GROUP1:ETHUSDT:V1_FLOW",
)
EXPECTED_ADOPTED_FILES = 8_708
EXPECTED_ADOPTED_BYTES = 57_388_412_230
EXPECTED_PACKED_SEALS = 44
EXPECTED_COMPONENTS = 4


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--failed-run-id", choices=(FAILED_RELEASE_RUN_ID,), required=True)
    result.add_argument("--replacement-authority-run-id", required=True)
    result.add_argument("--replacement-run-id", required=True)
    result.add_argument("--code-commit", required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if _git_head() != args.code_commit:
        raise ValueError("disablement code commit differs from current HEAD")
    if not args.replacement_authority_run_id.startswith("stage2-g1-v2-authority-"):
        raise ValueError("invalid replacement Authority run_id")
    if not args.replacement_run_id.startswith("stage2-g1-v2-b-"):
        raise ValueError("invalid replacement Run B ID")
    if args.replacement_run_id == args.failed_run_id:
        raise ValueError("replacement Run B must use a new unique ID")

    run_root = _run_root(args.failed_run_id)
    checkpoint_path = run_root / "checkpoint-v2.json"
    checkpoint = _read_json(checkpoint_path)
    completed_tasks = tuple(
        item.get("task_id")
        for item in checkpoint.get("completed_tasks", [])
        if isinstance(item, dict)
    )
    if (
        checkpoint.get("run_id") != args.failed_run_id
        or checkpoint.get("status") != "GROUP1_COMPLETE"
        or checkpoint.get("phase") != "GROUP1"
        or checkpoint.get("revision") != EXPECTED_REVISION
        or completed_tasks != EXPECTED_TASKS
        or checkpoint.get("active_task") is not None
        or checkpoint.get("failure") is not None
        or checkpoint.get("resource_pause") is not None
    ):
        raise ValueError("failed-release Run B checkpoint changed")

    progress_path = run_root / "logs/pipeline-progress-v1.json"
    progress = PipelineProgressV1.model_validate_json(progress_path.read_bytes())
    release = next((item for item in progress.subflows if item.name == "RELEASE"), None)
    if (
        progress.run_id != args.failed_run_id
        or release is None
        or release.status != "FAILED"
        or release.message is None
        or "catalog object/seal summaries" not in release.message
    ):
        raise ValueError("failed-release progress evidence changed")

    adoption_paths = _json_files(run_root / "manifests", "group1-monthly-adoption-*.json")
    if len(adoption_paths) != 1:
        raise ValueError("failed-release adoption evidence changed")
    adoption = Group1MonthlyAdoptionManifestV1.model_validate_json(adoption_paths[0].read_bytes())
    if (
        adoption.destination_run_id != args.failed_run_id
        or adoption.adopted_file_count != EXPECTED_ADOPTED_FILES
        or adoption.adopted_byte_count != EXPECTED_ADOPTED_BYTES
        or adoption.foundation_checkpoint_count != 796
        or adoption.group1_month_count != 158
        or adoption.group1_dataset_count != 2_054
    ):
        raise ValueError("failed-release adoption coverage changed")

    backend_evidence = _json_files(run_root / "staging/backend-evidence")
    task_receipts = _json_files(run_root / "staging/receipts")
    components = _json_files(run_root / "staging/evidence/group1-components")
    packed_seals = _json_files(run_root / "staging/group1/packed-seals")
    partials = _formal_files(run_root / "staging/group1/partials")
    published = _formal_files(run_root / "published")
    if (
        len(backend_evidence) != len(EXPECTED_TASKS)
        or len(task_receipts) != len(EXPECTED_TASKS)
        or len(components) != EXPECTED_COMPONENTS
        or len(packed_seals) != EXPECTED_PACKED_SEALS
        or partials
        or published
        or (run_root / "reports/v2-publication-record.json").exists()
        or (run_root / "reports/v2-run-a-comparison.json").exists()
    ):
        raise ValueError("failed-release evidence matrix changed")

    payload: dict[str, Any] = {
        "schema_name": "stage2-v2-failed-release-run-disablement",
        "disablement_version": "1.0",
        "status": "INVALIDATED_RELEASE_FAILED_UNPUBLISHED",
        "prior_checkpoint_status": "GROUP1_COMPLETE",
        "change_request": "CR-2026-017",
        "failed_run_id": args.failed_run_id,
        "checkpoint_sha256": _sha256(checkpoint_path),
        "pipeline_progress_sha256": _sha256(progress_path),
        "adoption_manifest_hash": adoption.manifest_hash,
        "adoption_manifest_physical_sha256": _sha256(adoption_paths[0]),
        "completed_tasks": len(completed_tasks),
        "logical_partitions": 80_784,
        "packed_seals": len(packed_seals),
        "published_files": 0,
        "resume_allowed": False,
        "reuse_allowed": False,
        "delete_allowed": False,
        "replacement_authority_run_id": args.replacement_authority_run_id,
        "replacement_run_id": args.replacement_run_id,
        "replacement_code_commit": args.code_commit,
    }
    path = run_root / "reports/disablement-cr-2026-017.json"
    _write_once(path, (canonical_json(payload) + "\n").encode())
    print(canonical_json({"path": str(path), "physical_sha256": _sha256(path)}))
    return 0


def _git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def _run_root(run_id: str) -> Path:
    root = (RUNS_ROOT / run_id).resolve()
    if not root.is_dir() or root.is_symlink() or not root.is_relative_to(RUNS_ROOT.resolve()):
        raise FileNotFoundError(root)
    return root


def _json_files(root: Path, pattern: str = "*.json") -> tuple[Path, ...]:
    if not root.exists():
        return ()
    return tuple(
        path
        for path in sorted(root.rglob(pattern))
        if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
    )


def _formal_files(root: Path) -> tuple[str, ...]:
    if not root.exists():
        return ()
    return tuple(
        path.relative_to(root).as_posix()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _write_once(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.is_symlink() or path.read_bytes() != payload:
            raise FileExistsError(f"append-only disablement differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
