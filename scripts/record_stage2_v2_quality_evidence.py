"""Run and append-only record the approved Runtime V2 quality gate."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mypy.version
import polars
import pytest

from era100x.research.stage_2.manifests.models import canonical_json
from era100x.research.stage_2.runtime_v2.orchestrator import compute_v2_code_tree_sha256

ROOT = Path(__file__).resolve().parents[1]
STAGE2_ROOT = Path("/Volumes/FuckingLife/era100x_stage2")
RUNS_ROOT = STAGE2_ROOT / "runs"
APPROVED_BRANCH = "stage/2-multi-event-runtime-v2"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Record Runtime V2 quality evidence")
    result.add_argument("--transition-run-id", required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    transition_root = _bounded_run_root(args.transition_run_id)
    head = _git("rev-parse", "HEAD")
    if _git("branch", "--show-current") != APPROVED_BRANCH:
        raise ValueError(f"quality evidence requires {APPROVED_BRANCH}")
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("quality evidence requires a clean worktree")
    commands = (
        (sys.executable, "-m", "pytest", "tests/research/stage_2/runtime_v2", "-q"),
        (sys.executable, "scripts/run_quality_gate.py"),
        (sys.executable, "scripts/check_traceability.py", "--strict"),
        ("git", "diff", "--check"),
    )
    results = tuple(_run(command) for command in commands)
    failed = tuple(item for item in results if item["returncode"] != 0)
    if failed:
        raise RuntimeError(
            f"Runtime V2 quality commands failed: {[item['command'] for item in failed]}"
        )
    payload = {
        "schema_name": "stage2-runtime-v2-quality-evidence-v1",
        "evidence_version": "1.0",
        "status": "PASS",
        "change_requests": [
            "CR-2026-007",
            "CR-2026-008",
            "CR-2026-009",
            "CR-2026-010",
        ],
        "code_commit": head,
        "repository_tree_sha1": _git("rev-parse", "HEAD^{tree}"),
        "runtime_v2_code_tree_sha256": compute_v2_code_tree_sha256(ROOT),
        "created_at": datetime.now(UTC).isoformat(),
        "tool_versions": {
            "python": sys.version.split()[0],
            "polars": polars.__version__,
            "pytest": pytest.__version__,
            "ruff": subprocess.check_output(["ruff", "--version"], text=True).strip(),
            "mypy": mypy.version.__version__,
        },
        "commands": results,
    }
    encoded = (canonical_json(payload) + "\n").encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    path = transition_root / "reports" / f"runtime-v2-quality-{digest}.json"
    _write_once(path, encoded)
    print(canonical_json({"quality_evidence_hash": digest, "path": str(path)}))
    return 0


def _run(command: tuple[str, ...]) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    output = completed.stdout + completed.stderr
    return {
        "command": list(command),
        "returncode": completed.returncode,
        "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "output_tail": output[-4000:],
    }


def _bounded_run_root(run_id: str) -> Path:
    if not run_id.startswith("stage2-g1-v2-authority-") or "/" in run_id or ".." in run_id:
        raise ValueError("invalid V2 transition run_id")
    if not Path("/Volumes/FuckingLife").is_mount() or not RUNS_ROOT.is_dir():
        raise FileNotFoundError("approved Stage 2 volume is unavailable")
    root = RUNS_ROOT / run_id
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.resolve().is_relative_to(RUNS_ROOT.resolve()):
        raise ValueError("unsafe V2 transition root")
    return root


def _write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != payload:
            raise FileExistsError(f"append-only quality evidence differs: {path}")
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


def _git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


if __name__ == "__main__":
    raise SystemExit(main())
