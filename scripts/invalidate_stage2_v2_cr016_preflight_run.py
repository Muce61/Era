#!/usr/bin/env python3
"""Append-only disablement of the CR-2026-016 preflight-only Run B."""

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
PREFLIGHT_RUN_ID = "stage2-g1-v2-b-20260720T084846Z-3885667a"
EXPECTED_MANIFEST_COUNT = 3


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--preflight-run-id", choices=(PREFLIGHT_RUN_ID,), required=True)
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
    if args.replacement_run_id == args.preflight_run_id:
        raise ValueError("replacement Run B must use a new unique ID")

    run_root = _run_root(args.preflight_run_id)
    checkpoint_path = run_root / "checkpoint-v2.json"
    checkpoint = _read_json(checkpoint_path)
    if (
        checkpoint.get("run_id") != args.preflight_run_id
        or checkpoint.get("status") != "PREFLIGHT_PASSED"
        or checkpoint.get("phase") != "PREFLIGHT"
        or checkpoint.get("revision") != 0
        or checkpoint.get("completed_tasks") != []
        or checkpoint.get("active_task") is not None
        or checkpoint.get("failure") is not None
        or checkpoint.get("resource_pause") is not None
    ):
        raise ValueError("preflight-only Run B checkpoint changed")

    staging_files = _formal_files(run_root / "staging")
    published_files = _formal_files(run_root / "published")
    manifests = {
        path.relative_to(run_root).as_posix(): _sha256(path)
        for path in sorted((run_root / "manifests").glob("*.json"))
        if path.is_file() and not path.name.startswith("._")
    }
    if staging_files or published_files or len(manifests) != EXPECTED_MANIFEST_COUNT:
        raise ValueError("preflight-only Run B evidence matrix changed")

    payload: dict[str, Any] = {
        "schema_name": "stage2-v2-preflight-run-disablement",
        "disablement_version": "1.0",
        "status": "INVALIDATED_PRECHECK_ONLY",
        "prior_status": "PREFLIGHT_PASSED",
        "change_request": "CR-2026-016",
        "preflight_run_id": args.preflight_run_id,
        "checkpoint_sha256": _sha256(checkpoint_path),
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
    path = run_root / "reports" / "disablement-cr-2026-016.json"
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
