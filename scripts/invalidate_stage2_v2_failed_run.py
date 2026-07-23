#!/usr/bin/env python3
"""Append-only invalidation for the terminal CR-2026-011 predecessor Run B."""

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

STAGE2_ROOT = Path("/Volumes/FuckingLife/era100x_stage2")
RUNS_ROOT = STAGE2_ROOT / "runs"
FAILED_RUN_ID = "stage2-g1-v2-b-20260718T092459Z-85a6a71ab953"
EXPECTED_FAILURE_TASK = "FOUNDATION:BTCUSDT"


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
        or checkpoint.get("failure", {}).get("task_id") != EXPECTED_FAILURE_TASK
        or failure.get("publication_status") != "FAILED_UNPUBLISHED"
        or failure.get("task_id") != EXPECTED_FAILURE_TASK
    ):
        raise ValueError("failed Run B terminal evidence changed")
    staging_files = _formal_files(failed_root / "staging")
    published_files = _formal_files(failed_root / "published")
    if staging_files or published_files:
        raise ValueError("failed Run B unexpectedly contains reusable or published output")
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
        "change_request": "CR-2026-011",
        "failed_run_id": args.failed_run_id,
        "failed_task": EXPECTED_FAILURE_TASK,
        "failure_reason": checkpoint["failure"]["reason"],
        "checkpoint_sha256": _sha256(checkpoint_path),
        "failure_report_sha256": _sha256(failure_path),
        "manifest_physical_sha256s": manifests,
        "completed_tasks": 0,
        "staging_files": 0,
        "published_files": 0,
        "resume_allowed": False,
        "reuse_allowed": False,
        "delete_allowed": False,
        "replacement_authority_run_id": args.replacement_authority_run_id,
        "replacement_run_id": args.replacement_run_id,
        "replacement_code_commit": args.code_commit,
    }
    encoded = (canonical_json(payload) + "\n").encode()
    path = failed_root / "reports" / "invalidation-cr-2026-011.json"
    _write_once(path, encoded)
    print(canonical_json({"path": str(path), "physical_sha256": _sha256(path)}))
    return 0


def _failed_root(run_id: str) -> Path:
    if not Path("/Volumes/FuckingLife").is_mount():
        raise FileNotFoundError("approved Stage 2 volume is unavailable")
    root = (RUNS_ROOT / run_id).resolve()
    if not root.is_dir() or root.is_symlink() or not root.is_relative_to(RUNS_ROOT.resolve()):
        raise FileNotFoundError(root)
    return root


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
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
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


if __name__ == "__main__":
    raise SystemExit(main())
