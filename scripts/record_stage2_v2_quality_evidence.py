"""Run and append-only record the approved Runtime V2 quality gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
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
from era100x.research.stage_2.runtime_v2.production_backend import (
    STAGE1_CATALOG_ROOT,
    STAGE1_CATALOG_SHA256S,
    STAGE1_PHYSICAL_MANIFEST_SHA256,
)
from era100x.research.stage_2.runtime_v2.transition import sha256_file

ROOT = Path(__file__).resolve().parents[1]
STAGE2_ROOT = Path("/Volumes/FuckingLife/era100x_stage2")
RUNS_ROOT = STAGE2_ROOT / "runs"
APPROVED_BRANCH = "stage/2-multi-event-runtime-v2"
STAGE1_BASELINE_COMMIT = "b7d4ff3d18dcfc515feb8892659cb0b186cd68f8"
RUN_A_ROOT = RUNS_ROOT / "stage2-g1-full-a-20260716T144233Z-366a541b7956"
RUN_A_LOGICAL_HASH = "8583f220dc880bf5b7e7ace1435ca2285e59b80dd48aa7d15bd2f8cacac60870"
RUN_A_PHYSICAL_HASH = "9fe33a4e7fde1ace3281a208c46f7474f66bc5c5a0e538871b273b2f20131578"
RUN_B_REQUIRED_FREE_BYTES = 1_345_364_951_040


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
        (sys.executable, "-m", "pytest", "tests/research/stage_2", "-q"),
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
    safety = _safety_checks()
    if safety["errors"]:
        raise RuntimeError(f"Runtime V2 safety checks failed: {safety['errors']}")
    payload = {
        "schema_name": "stage2-runtime-v2-quality-evidence-v1",
        "evidence_version": "1.0",
        "status": "PASS",
        "change_requests": [
            "CR-2026-007",
            "CR-2026-008",
            "CR-2026-009",
            "CR-2026-010",
            "CR-2026-011",
            "CR-2026-012",
            "CR-2026-013",
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
        "safety": safety,
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


def _safety_checks() -> dict[str, Any]:
    errors: list[str] = []
    if _git("rev-list", "-n", "1", "stage-1-v1.0-passed") != STAGE1_BASELINE_COMMIT:
        errors.append("Stage 1 tag changed")
    manifest = STAGE1_CATALOG_ROOT / "manifest.json"
    if sha256_file(manifest) != STAGE1_PHYSICAL_MANIFEST_SHA256:
        errors.append("Stage 1 physical Manifest hash changed")
    catalog_hashes = {
        instrument: sha256_file(STAGE1_CATALOG_ROOT / f"{instrument}.catalog.json")
        for instrument in ("BTCUSDT", "ETHUSDT")
    }
    if catalog_hashes != STAGE1_CATALOG_SHA256S:
        errors.append("Stage 1 Catalog hashes changed")
    run_a_catalog = _read_json(RUN_A_ROOT / "manifests" / "catalog.json")
    if (
        run_a_catalog.get("logical_hash") != RUN_A_LOGICAL_HASH
        or run_a_catalog.get("physical_hash") != RUN_A_PHYSICAL_HASH
    ):
        errors.append("Run A published hashes changed")
    errors.extend(_markdown_link_errors())
    errors.extend(_task_dag_errors())
    tracked = [ROOT / item for item in _git("ls-files").splitlines()]
    large = [
        str(path.relative_to(ROOT))
        for path in tracked
        if path.is_file() and path.stat().st_size > 10_000_000
    ]
    secret_patterns = (
        re.compile(rb"AKIA[0-9A-Z]{16}"),
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    )
    secret_hits: list[str] = []
    for path in tracked:
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        raw = path.read_bytes()
        if any(pattern.search(raw) for pattern in secret_patterns):
            secret_hits.append(str(path.relative_to(ROOT)))
    if secret_hits:
        errors.append(f"secret scan hits: {secret_hits}")
    runtime_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "src/era100x/research/stage_2/runtime_v2").glob("*.py"))
    )
    trading_tokens = ("create_order(", "futures_create_order", "EntryIntent(")
    trading_hits = [token for token in trading_tokens if token in runtime_source]
    if trading_hits:
        errors.append(f"forbidden trading capability hits: {trading_hits}")
    later_stage_tokens = ("MFE", "MAE", "TARGET_FIRST", "STOP_FIRST", "BOOTSTRAP", "PNL")
    later_stage_hits = [token for token in later_stage_tokens if token in runtime_source]
    if later_stage_hits:
        errors.append(f"forbidden later-stage output hits: {later_stage_hits}")
    free_bytes = shutil.disk_usage(STAGE2_ROOT).free
    anomalies: list[dict[str, object]] = []
    if large:
        anomalies.append({"type": "GIT_LARGE_FILE", "paths": large})
    if free_bytes < RUN_B_REQUIRED_FREE_BYTES:
        anomalies.append(
            {
                "type": "DISK_CAPACITY",
                "observed": free_bytes,
                "threshold": RUN_B_REQUIRED_FREE_BYTES,
            }
        )
    return {
        "errors": errors,
        "resource_anomalies": anomalies,
        "stage1_tag_commit": STAGE1_BASELINE_COMMIT,
        "stage1_physical_manifest_sha256": sha256_file(manifest),
        "stage1_catalog_sha256s": catalog_hashes,
        "run_a_logical_hash": run_a_catalog.get("logical_hash"),
        "run_a_physical_hash": run_a_catalog.get("physical_hash"),
        "markdown_links": "PASS" if not _markdown_link_errors() else "FAIL",
        "task_dag": "PASS" if not _task_dag_errors() else "FAIL",
        "large_file_scan": "PASS" if not large else "ANOMALY_RECORDED",
        "secret_scan": "PASS" if not secret_hits else "FAIL",
        "future_leakage_output_scan": "PASS" if not later_stage_hits else "FAIL",
        "trading_capability_scan": "PASS" if not trading_hits else "FAIL",
        "free_bytes": free_bytes,
        "required_free_bytes": RUN_B_REQUIRED_FREE_BYTES,
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _markdown_link_errors() -> list[str]:
    errors: list[str] = []
    pattern = re.compile(r"\[[^]]*]\(([^)]+)\)")
    for path in (ROOT / "docs").rglob("*.md"):
        for target in pattern.findall(path.read_text(encoding="utf-8")):
            target = target.strip("<>").split("#", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:", "/")):
                continue
            if not (path.parent / target).resolve().exists():
                errors.append(f"broken Markdown link: {path.relative_to(ROOT)} -> {target}")
    return errors


def _task_dag_errors() -> list[str]:
    task_files = list((ROOT / "docs/development/tasks").glob("stage_*/*.md"))
    task_ids: dict[str, Path] = {}
    errors: list[str] = []
    for path in task_files:
        match = re.search(r"^- task_id: (S\d+-T\d+)$", path.read_text(), re.MULTILINE)
        if match:
            task_id = match.group(1)
            if task_id in task_ids:
                errors.append(f"duplicate Task ID: {task_id}")
            task_ids[task_id] = path
    graph: dict[str, set[str]] = {task: set() for task in task_ids}
    for task, path in task_ids.items():
        dependency_line = next(
            (line for line in path.read_text().splitlines() if line.startswith("- dependencies:")),
            "",
        )
        for dependency in re.findall(r"S\d+-T\d+", dependency_line):
            if dependency not in task_ids:
                errors.append(f"dangling Task dependency: {task}->{dependency}")
            else:
                graph[task].add(dependency)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task: str) -> None:
        if task in visiting:
            errors.append(f"Task dependency cycle at {task}")
            return
        if task in visited:
            return
        visiting.add(task)
        for dependency in graph[task]:
            visit(dependency)
        visiting.remove(task)
        visited.add(task)

    for task in graph:
        visit(task)
    return errors


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
