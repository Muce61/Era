from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from era100x.research.stage_2.rerun.orchestrator import (
    APPROVAL_SCHEMA,
    GOVERNANCE_PATHS,
    RERUN_TASKS,
    approval_readiness,
    canonical_hash,
    create_approval_receipt,
    create_chain,
    governance_hashes,
    governance_projection,
    read_latest_chain_projection,
    resume_chain,
    run_chain,
    seal_handoff,
    validate_approval_receipt,
    validate_handoff,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _repo(tmp_path: Path, *, oq9: str = "OPEN") -> Path:
    root = tmp_path / "repo"
    for name, relative in GOVERNANCE_PATHS.items():
        content = name
        if name == "cr_2026_031":
            content = "status: APPROVED\nS2-T11-T15 SUCCESSOR AUTHORIZED\n"
        elif name == "cr_2026_032":
            content = "status: APPROVED DIRECTION\n"
        elif name == "adr_s2_010":
            content = "## Status\nAPPROVED\n## Context\n"
        elif name == "adr_s2_011":
            content = "## Status\nAPPROVED DIRECTION\n## Context\n"
        elif name == "open_questions":
            content = (
                f"| OQ-S2-009 | missingness | {oq9} | audit | gate | decision |\n"
                "| OQ-S2-010 | lifecycle | OPEN | future | gate | decision |\n"
            )
        _write(root / relative, content)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "governance",
        ],
        cwd=root,
        check=True,
    )
    return root


def _approval(root: Path, tmp_path: Path) -> Path:
    audit = {
        "schema_name": "stage2-s2t15-availability-audit-v1",
        "status": "PASS",
        "instruments": ["BTCUSDT", "ETHUSDT"],
    }
    audit["audit_hash"] = canonical_hash(audit)
    audit_path = tmp_path / "availability.json"
    _write(audit_path, json.dumps(audit))
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    approval: dict[str, Any] = {
        "schema_name": APPROVAL_SCHEMA,
        "status": "APPROVED",
        "tasks": list(RERUN_TASKS),
        "formal_successor_authorized": True,
        "skip_seven_day_audit": True,
        "lifecycle_implementation_authorized": False,
        "availability_audit_path": str(audit_path),
        "availability_audit_hash": audit["audit_hash"],
        "governance_hashes": governance_hashes(root),
        "code_commit": commit,
        "approved_by": "Muce",
    }
    approval["approval_hash"] = canonical_hash(approval)
    path = tmp_path / "approval.json"
    _write(path, json.dumps(approval))
    return path


def test_readiness_blocks_while_missingness_question_is_open(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    projection = governance_projection(root)
    readiness = approval_readiness(repository_root=root)
    assert projection["cr_2026_031"] is True
    assert projection["cr_2026_032_direction"] is True
    assert projection["oq_s2_009_status"] == "OPEN"
    assert readiness["status"] == "BLOCKED"
    assert readiness["reason_code"] == "S2_RERUN_OQ_S2_009_OPEN"


def test_approval_binds_governance_availability_and_clean_commit(tmp_path: Path) -> None:
    root = _repo(tmp_path, oq9="RESOLVED")
    path = _approval(root, tmp_path)
    payload = validate_approval_receipt(path, repository_root=root)
    assert payload["formal_successor_authorized"] is True
    _write(root / GOVERNANCE_PATHS["current_stage"], "drift")
    with pytest.raises(ValueError, match="governance Hashes drifted"):
        validate_approval_receipt(path, repository_root=root, require_clean=False)


def test_handoff_is_self_hashed_and_historical_only(tmp_path: Path) -> None:
    chain_root = tmp_path / "s2-t11-t15-rerun-20260723T010203Z-abcdef123456"
    payload, path = seal_handoff(
        chain_root,
        task_id="S2-T11",
        evidence={
            "run_id": "stage2-s2t11-paths-20260723T010203Z-abcdef123456",
            "snapshot_id": "1" * 64,
            "manifest_hash": "2" * 64,
            "catalog_hash": "3" * 64,
            "authority_hash": "4" * 64,
        },
    )
    assert validate_handoff(path, expected_task="S2-T11") == payload
    stored = json.loads(path.read_text())
    stored["status"] = "PASS"
    path.write_text(json.dumps(stored))
    with pytest.raises(ValueError, match="self-hash mismatch"):
        validate_handoff(path)


class _FakeDriver:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute_task(
        self,
        task_id: str,
        *,
        handoffs: dict[str, dict[str, Any]],
        chain_root: Path,
        approval_path: Path,
        task_state: dict[str, Any],
        progress: Any,
    ) -> dict[str, Any]:
        del handoffs, approval_path, task_state
        self.calls.append(task_id)
        progress("preflight", "PASS", {"authority_hash": "4" * 64})
        progress("run", "IN_PROGRESS", {"run_id": f"run-{task_id.lower()}"})
        evidence = {
            "run_id": f"run-{task_id.lower()}",
            "snapshot_id": "1" * 64,
            "manifest_hash": "2" * 64,
            "catalog_hash": "3" * 64,
            "authority_hash": "4" * 64,
            "code_commit": "5" * 40,
            "run_root": str(chain_root / task_id),
            "snapshot_root": str(chain_root / task_id / "snapshot"),
        }
        handoff, path = seal_handoff(chain_root, task_id=task_id, evidence=evidence)
        progress("verify", "PASS", {"verify_status": "PASS"})
        return {**evidence, "handoff_hash": handoff["handoff_hash"], "handoff_path": str(path)}


def test_single_resume_command_runs_all_tasks_and_projects_progress(tmp_path: Path) -> None:
    root = _repo(tmp_path, oq9="RESOLVED")
    approval = _approval(root, tmp_path)
    operations = tmp_path / "stage2/operations/s2-t11-t15-rerun"
    create_chain(approval, operations_root=operations, repository_root=root)
    driver = _FakeDriver()
    result = resume_chain(
        approval_path=approval,
        operations_root=operations,
        repository_root=root,
        driver=driver,  # type: ignore[arg-type]
    )
    assert result["status"] == "PASS"
    assert driver.calls == list(RERUN_TASKS)
    assert all(item["status"] == "PASS" for item in result["tasks"].values())
    projection = read_latest_chain_projection(tmp_path / "stage2", repository_root=root)
    assert projection["status"] == "PASS"
    assert projection["seven_day_audit"] == "SKIPPED_BY_USER_FOR_THIS_RERUN"
    assert projection["lifecycle_implementation_executed"] is False


def test_approval_receipt_is_generated_only_after_governance_and_audit_pass(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path, oq9="RESOLVED")
    audit: dict[str, Any] = {
        "schema_name": "stage2-s2t15-availability-audit-v1",
        "status": "PASS",
    }
    audit["audit_hash"] = canonical_hash(audit)
    audit_path = tmp_path / "availability-pass.json"
    _write(audit_path, json.dumps(audit))
    payload, path = create_approval_receipt(
        availability_audit_path=audit_path,
        approved_by="Muce",
        output_root=tmp_path / "operations",
        repository_root=root,
    )
    assert payload["skip_seven_day_audit"] is True
    assert payload["lifecycle_implementation_authorized"] is False
    assert validate_approval_receipt(path, repository_root=root) == payload


def test_one_run_command_creates_resumes_and_does_not_duplicate_chain(tmp_path: Path) -> None:
    root = _repo(tmp_path, oq9="RESOLVED")
    approval = _approval(root, tmp_path)
    operations = tmp_path / "stage2/operations/s2-t11-t15-rerun"
    driver = _FakeDriver()
    result = run_chain(
        approval_path=approval,
        operations_root=operations,
        repository_root=root,
        driver=driver,  # type: ignore[arg-type]
    )
    assert result["status"] == "PASS"
    assert driver.calls == list(RERUN_TASKS)
    chain_count = len(tuple(path for path in operations.iterdir() if path.is_dir()))
    replay = run_chain(
        approval_path=approval,
        operations_root=operations,
        repository_root=root,
        driver=driver,  # type: ignore[arg-type]
    )
    assert replay["status"] == "PASS"
    assert len(tuple(path for path in operations.iterdir() if path.is_dir())) == chain_count
    assert driver.calls == list(RERUN_TASKS)
