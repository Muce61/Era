"""Command line surface for S2P14-T17."""

from __future__ import annotations

import argparse
import fcntl
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .governance import (
    audit_t16_source,
    load_policy,
    read_json,
    record_approval,
)
from .runner import resume_formal, run_formal, verify_run

DEFAULT_POLICY = Path("configs/governance/stage2_active_policy_v3.json")


def _run_lock_is_held(path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="S2P14-T17 historical placebo evidence")
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    audit = subparsers.add_parser("audit")
    audit.add_argument("--full-hash-scan", action="store_true")
    approval = subparsers.add_parser("record-approval")
    approval.add_argument("--approved-by", required=True)
    approval.add_argument("--approval-source", required=True)
    approval.add_argument("--approved-at")
    approval.add_argument("--supersedes-authority")
    approval.add_argument("--supersedes-run")
    approval.add_argument(
        "--superseded-run-state",
        choices=("EMPTY_RUN", "AUDIT_ONLY"),
    )
    run = subparsers.add_parser("run")
    run.add_argument("--approval", type=Path, required=True)
    resume = subparsers.add_parser("resume")
    resume.add_argument("--approval", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--run-root", type=Path, required=True)
    return parser


def _status(policy: Any, repository_root: Path) -> dict[str, Any]:
    binding = audit_t16_source(policy, full_hash_scan=False)
    approvals = tuple(
        path
        for path in (policy.operations_root / "approvals").glob("approval-*.json")
        if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
    )
    authorities = tuple(
        path
        for path in (policy.evidence_root / "authorities").glob("authority-*.json")
        if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
    )
    runs = tuple(
        path
        for path in (policy.evidence_root / "runs").glob("stage2-s2p14-t17-*")
        if path.is_dir() and not path.is_symlink()
    )
    active_run: dict[str, Any] = {}
    if runs:
        checkpoint = runs[-1] / "checkpoint.json"
        if checkpoint.is_file() and not checkpoint.is_symlink():
            active_run = read_json(checkpoint)
    status = "BLOCKED"
    reason = "FORMAL_APPROVAL_REQUIRED"
    if approvals:
        status, reason = "NOT_STARTED", "FORMAL_APPROVAL_PRESENT"
    if authorities:
        status, reason = (
            ("BLOCKED", "EMPTY_RUN_PREFIX_BLOCKED")
            if runs and not active_run
            else ("BLOCKED", "AUTHORITY_SEALED_WITHOUT_RUN")
        )
    if active_run:
        if _run_lock_is_held(policy.operations_root / "run.lock"):
            status = str(active_run.get("status", "IN_PROGRESS"))
            reason = str(active_run.get("phase", "RUN_IN_PROGRESS"))
        else:
            status, reason = "BLOCKED", "PRE_BLIND_PREFIX_FAILED"
    return {
        "schema_name": "s2p14-t17-status",
        "stage_plan_version": "1.4",
        "task_id": "S2P14-T17",
        "status": status,
        "reason_code": reason,
        "policy_hash": policy.policy_hash,
        "repo_root": str(repository_root.resolve()),
        "repo_commit": __import__("subprocess")
        .check_output(["git", "rev-parse", "HEAD"], cwd=repository_root, text=True)
        .strip(),
        "source_t16_verify_hash": binding.verify_hash,
        "source_counts": binding.counts,
        "approval_count": len(approvals),
        "authority_count": len(authorities),
        "run_count": len(runs),
        "active_run": active_run,
        "evidence_label": "H2 historical placebo evidence",
        "research_status": "DESCRIPTIVE_ONLY_CLUSTERING_BOOTSTRAP_PENDING",
        "stage3_locked": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    repository_root = arguments.repository_root.resolve()
    policy_path = arguments.policy
    if not policy_path.is_absolute():
        policy_path = repository_root / policy_path
    policy = load_policy(policy_path, repository_root=repository_root)
    if arguments.command == "status":
        result = _status(policy, repository_root)
    elif arguments.command == "audit":
        binding = audit_t16_source(policy, full_hash_scan=arguments.full_hash_scan)
        result = {
            "status": "PASS",
            "source_t16_verify_hash": binding.verify_hash,
            "source_t16_snapshot_id": binding.snapshot_id,
            "counts": binding.counts,
            "formal_objects_created": False,
        }
    elif arguments.command == "record-approval":
        path = record_approval(
            policy=policy,
            repository_root=repository_root,
            approved_by=arguments.approved_by,
            approval_source=arguments.approval_source,
            approved_at=arguments.approved_at,
            supersedes_authority_hash=arguments.supersedes_authority,
            supersedes_run_id=arguments.supersedes_run,
            superseded_run_state=arguments.superseded_run_state,
        )
        result = {"status": "PASS", "approval_path": str(path)}
    elif arguments.command == "run":
        result = run_formal(
            policy=policy,
            approval_path=arguments.approval,
            repository_root=repository_root,
        )
    elif arguments.command == "resume":
        result = resume_formal(
            policy=policy,
            approval_path=arguments.approval,
            repository_root=repository_root,
        )
    elif arguments.command == "verify":
        binding = audit_t16_source(policy, full_hash_scan=False)
        result = verify_run(arguments.run_root, binding=binding)
    else:  # pragma: no cover
        raise AssertionError(arguments.command)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0
