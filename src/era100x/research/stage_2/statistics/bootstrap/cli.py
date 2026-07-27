"""Command line interface for S2P15-T18."""

from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .formatting import canonical_hash, read_json
from .governance import (
    audit_sources,
    load_policy,
    record_approval,
    validate_approval,
)
from .runner import format_smoke, resume_formal, run_formal, verify_run

DEFAULT_POLICY = Path("configs/governance/stage2_active_policy_v4.json")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="S2P15-T18 cluster bootstrap")
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    audit = subparsers.add_parser("audit")
    audit.add_argument("--full-hash-scan", action="store_true")
    subparsers.add_parser("format-smoke")
    approval = subparsers.add_parser("record-approval")
    approval.add_argument("--approved-by", required=True)
    approval.add_argument("--approval-source", required=True)
    approval.add_argument("--format-smoke-hash", required=True)
    approval.add_argument("--approved-at")
    run = subparsers.add_parser("run")
    run.add_argument("--approval", type=Path, required=True)
    resume = subparsers.add_parser("resume")
    resume.add_argument("--approval", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--run-root", type=Path, required=True)
    return parser


def _lock_is_held(path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return False


def _status(policy: Any, repository_root: Path) -> dict[str, Any]:
    sources = audit_sources(policy, repository_root=repository_root, full_hash_scan=False)
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository_root, text=True
    ).strip()
    smokes = []
    for path in (policy.operations_root / "format-smokes").glob("*.json"):
        if not path.is_file() or path.is_symlink() or path.name.startswith("._"):
            continue
        payload = read_json(path)
        claimed = payload.get("format_smoke_hash")
        if (
            isinstance(claimed, str)
            and claimed
            == canonical_hash(
                {key: value for key, value in payload.items() if key != "format_smoke_hash"}
            )
            and payload.get("status") == "PASS"
            and payload.get("code_commit") == commit
            and payload.get("policy_hash") == policy.policy_hash
            and payload.get("source_t16_verify_hash") == sources.t16.verify_hash
            and payload.get("source_t17_verify_hash") == sources.t17.verify_hash
        ):
            smokes.append(path)
    approvals = []
    for path in (policy.operations_root / "approvals").glob("approval-*.json"):
        if not path.is_file() or path.is_symlink() or path.name.startswith("._"):
            continue
        try:
            validate_approval(path, policy=policy, repository_root=repository_root)
        except (OSError, ValueError):
            continue
        approvals.append(path)
    authorities = tuple(
        path
        for path in (policy.evidence_root / "authorities").glob("authority-*.json")
        if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
    )
    runs = tuple(
        sorted(
            path
            for path in (policy.evidence_root / "runs").glob("stage2-s2p15-t18-*")
            if path.is_dir() and not path.is_symlink()
        )
    )
    active: dict[str, Any] = {}
    if runs and (runs[-1] / "checkpoint.json").is_file():
        active = read_json(runs[-1] / "checkpoint.json")
    if active:
        status = str(active.get("status", "IN_PROGRESS"))
        reason = (
            "FORMAL_TASK_VERIFIED_PASS"
            if status == "PASS"
            else str(active.get("phase", "IN_PROGRESS"))
        )
    elif authorities or runs:
        status, reason = "BLOCKED", "UNFINISHED_FORMAL_PREFIX"
    elif approvals:
        status, reason = "NOT_STARTED", "FORMAL_APPROVAL_PRESENT"
    elif smokes:
        status, reason = "BLOCKED", "COMMIT_BOUND_APPROVAL_REQUIRED"
    else:
        status, reason = "BLOCKED", "FORMAT_SMOKE_REQUIRED"
    return {
        "schema_name": "s2p15-t18-status",
        "schema_version": "1.0",
        "stage_plan_version": "1.5",
        "task_id": "S2P15-T18",
        "status": status,
        "reason_code": reason,
        "repo_root": str(repository_root.resolve()),
        "repo_commit": commit,
        "policy_hash": policy.policy_hash,
        "source_t16_verify_hash": sources.t16.verify_hash,
        "source_t17_verify_hash": sources.t17.verify_hash,
        "source_counts": sources.t17.counts,
        "format_smoke_count": len(smokes),
        "approval_count": len(approvals),
        "authority_count": len(authorities),
        "run_count": len(runs),
        "active_run": active,
        "run_lock_held": _lock_is_held(policy.operations_root / "run.lock"),
        "evidence_label": "H2 historical cluster-bootstrap evidence",
        "research_status": "STATISTICAL_EVIDENCE_ONLY_FINAL_GATE_PENDING",
        "stage3_locked": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    root = arguments.repository_root.resolve()
    policy_path = arguments.policy
    if not policy_path.is_absolute():
        policy_path = root / policy_path
    policy = load_policy(policy_path, repository_root=root)
    if arguments.command == "status":
        result = _status(policy, root)
    elif arguments.command == "audit":
        sources = audit_sources(
            policy, repository_root=root, full_hash_scan=arguments.full_hash_scan
        )
        result = {
            "status": "PASS",
            "source_t16_verify_hash": sources.t16.verify_hash,
            "source_t17_verify_hash": sources.t17.verify_hash,
            "source_counts": sources.t17.counts,
            "formal_objects_created": False,
        }
    elif arguments.command == "format-smoke":
        sources = audit_sources(policy, repository_root=root, full_hash_scan=False)
        result = format_smoke(policy=policy, sources=sources, repository_root=root)
    elif arguments.command == "record-approval":
        path = record_approval(
            policy=policy,
            repository_root=root,
            approved_by=arguments.approved_by,
            approval_source=arguments.approval_source,
            format_smoke_hash=arguments.format_smoke_hash,
            approved_at=arguments.approved_at,
        )
        result = {"status": "PASS", "approval_path": str(path)}
    elif arguments.command == "run":
        result = run_formal(
            policy=policy,
            approval_path=arguments.approval,
            repository_root=root,
        )
    elif arguments.command == "resume":
        result = resume_formal(
            policy=policy,
            approval_path=arguments.approval,
            repository_root=root,
        )
    elif arguments.command == "verify":
        result = verify_run(arguments.run_root)
    else:  # pragma: no cover
        raise AssertionError(arguments.command)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0
