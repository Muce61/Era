#!/usr/bin/env python3
"""Append-only invalidation for the terminal CR-2026-013 predecessor Run B."""

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

RUNS_ROOT = Path("/Volumes/FuckingLife/era100x_stage2/runs")
FAILED_RUN_ID = "stage2-g1-v2-b-20260718T141137Z-f0c150bfa1c9"
EXPECTED_TASK = "FOUNDATION:BTCUSDT"
EXPECTED_MONTHLY = 316
EXPECTED_PACKED = 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--failed-run-id", choices=(FAILED_RUN_ID,), required=True)
    result.add_argument("--replacement-authority-run-id", required=True)
    result.add_argument("--replacement-run-id", required=True)
    result.add_argument("--code-commit", required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() != (
        args.code_commit
    ):
        raise ValueError("invalidation code commit differs from current HEAD")
    if not args.replacement_authority_run_id.startswith("stage2-g1-v2-authority-"):
        raise ValueError("invalid replacement Authority run_id")
    if not args.replacement_run_id.startswith("stage2-g1-v2-b-"):
        raise ValueError("invalid replacement Run B ID")
    if args.replacement_run_id == args.failed_run_id:
        raise ValueError("replacement Run B must use a new unique ID")

    failed_root = _failed_root(args.failed_run_id)
    checkpoint_path = failed_root / "checkpoint-v2.json"
    checkpoint = _read_json(checkpoint_path)
    failure_path = failed_root / str(checkpoint.get("failure", {}).get("report_relative_path"))
    failure = _read_json(failure_path)
    if (
        checkpoint.get("status") != "FAILED_UNPUBLISHED"
        or checkpoint.get("completed_tasks") != []
        or checkpoint.get("active_task") is not None
        or checkpoint.get("failure", {}).get("task_id") != EXPECTED_TASK
        or failure.get("publication_status") != "FAILED_UNPUBLISHED"
        or failure.get("task_id") != EXPECTED_TASK
        or failure.get("error_type") != "MemoryError"
    ):
        raise ValueError("failed Run B terminal evidence changed")

    monthly = _json_files(failed_root / "staging/foundation/checkpoints")
    packed = _json_files(failed_root / "staging/foundation/packed-checkpoints")
    objects = _formal_files(failed_root / "staging/foundation/monthly-catalog")
    seals = _json_files(failed_root / "staging/foundation/seals")
    published = _formal_files(failed_root / "published")
    if (
        len(monthly) != EXPECTED_MONTHLY
        or len(packed) != EXPECTED_PACKED
        or len(objects) != EXPECTED_MONTHLY
        or len(seals) != EXPECTED_MONTHLY
        or published
    ):
        raise ValueError("failed Run B retained-evidence matrix changed")

    manifests = {
        path.relative_to(failed_root).as_posix(): _sha256(path)
        for path in sorted((failed_root / "manifests").glob("*.json"))
        if path.is_file() and not path.name.startswith("._")
    }
    payload: dict[str, Any] = {
        "schema_name": "stage2-v2-failed-run-invalidation",
        "invalidation_version": "1.0",
        "status": "INVALIDATED",
        "prior_status": "FAILED_UNPUBLISHED",
        "change_request": "CR-2026-013",
        "failed_run_id": args.failed_run_id,
        "failed_task": EXPECTED_TASK,
        "failure_reason": checkpoint["failure"]["reason"],
        "checkpoint_sha256": _sha256(checkpoint_path),
        "failure_report_sha256": _sha256(failure_path),
        "manifest_physical_sha256s": manifests,
        "completed_tasks": 0,
        "monthly_checkpoint_count": len(monthly),
        "packed_checkpoint_count": len(packed),
        "monthly_object_count": len(objects),
        "seal_count": len(seals),
        "published_files": 0,
        "resume_allowed": False,
        "source_object_adoption_requires_manifest": True,
        "delete_allowed": False,
        "replacement_authority_run_id": args.replacement_authority_run_id,
        "replacement_run_id": args.replacement_run_id,
        "replacement_code_commit": args.code_commit,
    }
    path = failed_root / "reports" / "invalidation-cr-2026-013.json"
    _write_once(path, (canonical_json(payload) + "\n").encode())
    print(canonical_json({"path": str(path), "physical_sha256": _sha256(path)}))
    return 0


def _failed_root(run_id: str) -> Path:
    root = (RUNS_ROOT / run_id).resolve()
    if not root.is_dir() or root.is_symlink() or not root.is_relative_to(RUNS_ROOT.resolve()):
        raise FileNotFoundError(root)
    return root


def _json_files(root: Path) -> tuple[Path, ...]:
    if not root.exists():
        return ()
    return tuple(
        path
        for path in sorted(root.rglob("*.json"))
        if path.is_file() and not path.name.startswith("._")
    )


def _formal_files(root: Path) -> tuple[str, ...]:
    if not root.exists():
        return ()
    return tuple(
        path.relative_to(root).as_posix()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.name.startswith("._")
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
            raise FileExistsError(f"append-only invalidation differs: {path}")
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
