"""Run and immutably record the complete S2-T10 pre-run quality gate."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mypy.version
import polars
import pytest

from era100x.research.stage_2.manifests.models import Stage2PreregistrationManifest
from era100x.research.stage_2.pipelines.candidates.stage1_catalog import (
    Stage1CatalogAuthority,
    Stage1TradesCatalogIndex,
)

ROOT = Path(__file__).resolve().parents[1]
STAGE2_ROOT = Path("/Volumes/FuckingLife/era100x_stage2")
STAGE1_RUN_ID = "stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682"
PREREGISTRATION_PATH = (
    STAGE2_ROOT / "runs/stage2-g1-preregistration-v1.0/manifests/"
    "6b0f66e4007b86e08b58a9b366170eeee952199baa203d7f174b2ca69478c1f9.json"
)
STAGE1_CATALOG_ROOT = Path("/Volumes/FuckingLife/era100x_stage1/catalog/runs") / STAGE1_RUN_ID
STAGE1_PUBLISHED_ROOT = (
    Path("/Volumes/FuckingLife/era100x_stage1/published/stage1-trades-v2") / STAGE1_RUN_ID
)
REPORT_ROOT = STAGE2_ROOT / "runs/stage2-g1-preregistration-v1.0/reports"


def main() -> int:
    head = _git("rev-parse", "HEAD")
    if _git("branch", "--show-current") != "stage/2-event-construction":
        raise ValueError("quality gate requires stage/2-event-construction")
    if _git("status", "--porcelain"):
        raise ValueError("quality evidence requires a clean worktree")
    tool_versions = _tool_versions()
    commands = (
        (sys.executable, "-m", "pytest", "tests/research/stage_2/pipelines/candidates", "-q"),
        (sys.executable, "-m", "pytest", "tests/research/stage_2", "-q"),
        (sys.executable, "scripts/run_quality_gate.py"),
        ("git", "diff", "--check"),
    )
    results = [_run(command) for command in commands]
    failed = [item for item in results if item["returncode"] != 0]
    if failed:
        raise RuntimeError(f"quality commands failed: {[item['command'] for item in failed]}")
    safety = _safety_checks()
    if safety["errors"]:
        raise RuntimeError(f"release safety checks failed: {safety['errors']}")
    payload = {
        "schema_name": "stage2-group1-pre-run-quality-evidence-v1",
        "status": "PASS",
        "created_at": datetime.now(UTC).isoformat(),
        "code_commit": head,
        "tool_versions": tool_versions,
        "commands": results,
        "safety": safety,
    }
    raw = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode()
    digest = hashlib.sha256(raw).hexdigest()
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    path = REPORT_ROOT / f"quality-gate-{digest}.json"
    with path.open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"quality_gate_evidence_hash": digest, "path": str(path)}))
    return 0


def _run(command: tuple[str, ...]) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    output = completed.stdout + completed.stderr
    return {
        "command": list(command),
        "returncode": completed.returncode,
        "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
        "output_tail": output[-4000:],
    }


def _tool_versions() -> dict[str, str]:
    ruff_version = subprocess.check_output(["ruff", "--version"], text=True).strip().split()[-1]
    return {
        "python": sys.version.split()[0],
        "polars": polars.__version__,
        "pytest": pytest.__version__,
        "ruff": ruff_version,
        "mypy": mypy.version.__version__,
    }


def _safety_checks() -> dict[str, Any]:
    errors: list[str] = []
    preregistration = Stage2PreregistrationManifest.model_validate_json(
        PREREGISTRATION_PATH.read_bytes()
    )
    baseline = preregistration.stage1
    authority = Stage1CatalogAuthority(
        data_run_id=baseline.data_run_id,
        dataset_version="stage1-trades-v2",
        canonical_manifest_sha256=baseline.canonical_manifest_sha256,
        physical_manifest_sha256=baseline.physical_manifest_sha256,
        catalog_sha256s={
            "BTCUSDT": baseline.btc_catalog_sha256,
            "ETHUSDT": baseline.eth_catalog_sha256,
        },
        logical_hashes={
            "BTCUSDT": baseline.btc_trades_logical_hash,
            "ETHUSDT": baseline.eth_trades_logical_hash,
        },
    )
    index = Stage1TradesCatalogIndex.load(
        catalog_run_root=STAGE1_CATALOG_ROOT,
        published_root=STAGE1_PUBLISHED_ROOT,
        authority=authority,
    )
    from datetime import date

    index.assert_coverage(date(2020, 1, 1), date(2026, 7, 4))
    if _git("rev-list", "-n", "1", "stage-1-v1.0-passed") != baseline.commit:
        errors.append("Stage 1 tag changed")
    errors.extend(_markdown_link_errors())
    errors.extend(_task_dag_errors())
    tracked = [ROOT / item for item in _git("ls-files").splitlines()]
    large = [
        str(path.relative_to(ROOT))
        for path in tracked
        if path.exists() and path.stat().st_size > 10_000_000
    ]
    if large:
        errors.append(f"tracked files over 10MB: {large}")
    secret_patterns = (
        re.compile(rb"AKIA[0-9A-Z]{16}"),
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    )
    secret_hits = []
    for path in tracked:
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        raw = path.read_bytes()
        if any(pattern.search(raw) for pattern in secret_patterns):
            secret_hits.append(str(path.relative_to(ROOT)))
    if secret_hits:
        errors.append(f"secret scan hits: {secret_hits}")
    candidate_source = "\n".join(
        path.read_text()
        for path in sorted(
            (ROOT / "src/era100x/research/stage_2/pipelines/candidates").glob("*.py")
        )
    )
    forbidden_calls = ("create_order(", "futures_create_order", "requests.post(", "EntryIntent(")
    hits = [token for token in forbidden_calls if token in candidate_source]
    if hits:
        errors.append(f"forbidden trading capability hits: {hits}")
    forbidden_outputs = ("MFE", "MAE", "TARGET_FIRST", "STOP_FIRST", "BOOTSTRAP", "PNL")
    output_hits = [token for token in forbidden_outputs if token in candidate_source]
    if output_hits:
        errors.append(f"forbidden later-stage output hits: {output_hits}")
    failed_root = STAGE2_ROOT / "runs/stage2-g1-full-a-20260716-4c15e46"
    failed = json.loads((failed_root / "checkpoint.json").read_text())
    if failed.get("status") != "FAILED" or (failed_root / "published/data").exists():
        errors.append("failed predecessor protection changed")
    invalidated = json.loads(
        (
            STAGE2_ROOT / "runs/stage2-g1-full-a-20260716-93a6016/reports/invalidation.json"
        ).read_text()
    )
    if invalidated.get("status") != "INVALIDATED":
        errors.append("invalidated predecessor protection changed")
    free = shutil.disk_usage(STAGE2_ROOT).free
    if free < 2_018_047_426_560:
        errors.append(f"Run A space gate failed: {free}")
    return {
        "errors": errors,
        "stage1_index_hash": index.logical_hash,
        "stage1_logical_hashes": authority.logical_hashes,
        "preregistration_hash": preregistration.manifest_hash,
        "config_hash": preregistration.config_hash,
        "free_bytes": free,
        "required_free_bytes": 2_018_047_426_560,
        "large_file_scan": "PASS" if not large else "FAIL",
        "secret_scan": "PASS" if not secret_hits else "FAIL",
        "future_leakage_output_scan": "PASS" if not output_hits else "FAIL",
        "trading_capability_scan": "PASS" if not hits else "FAIL",
        "markdown_links": "PASS" if not _markdown_link_errors() else "FAIL",
        "task_dag": "PASS" if not _task_dag_errors() else "FAIL",
    }


def _markdown_link_errors() -> list[str]:
    errors = []
    pattern = re.compile(r"\[[^]]*]\(([^)]+)\)")
    for path in (ROOT / "docs").rglob("*.md"):
        for target in pattern.findall(path.read_text()):
            target = target.strip("<>").split("#", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:", "/")):
                continue
            if not (path.parent / target).resolve().exists():
                errors.append(f"broken Markdown link: {path.relative_to(ROOT)} -> {target}")
    return errors


def _task_dag_errors() -> list[str]:
    task_files = list((ROOT / "docs/development/tasks").glob("stage_*/*.md"))
    task_ids = {}
    for path in task_files:
        match = re.search(r"^- task_id: (S\d+-T\d+)$", path.read_text(), re.MULTILINE)
        if match:
            task_ids[match.group(1)] = path
    graph: dict[str, set[str]] = {task: set() for task in task_ids}
    errors = []
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


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


if __name__ == "__main__":
    raise SystemExit(main())
