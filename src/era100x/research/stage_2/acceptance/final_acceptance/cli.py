"""Command line interface for S2P17-T20 final acceptance."""

from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from era100x.research.stage_2.acceptance.canonical_json import (
    canonical_content_hash,
    read_canonical_json,
)

from .governance import (
    audit_sources,
    load_policy,
    record_approval,
    repository_clean,
    validate_approval,
)
from .runner import format_smoke, resume_formal, run_formal, verify_run

DEFAULT_POLICY = Path("configs/governance/stage2_active_policy_v6.json")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="S2P17-T20 final evidence acceptance")
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    audit = commands.add_parser("audit")
    audit.add_argument("--full-hash-scan", action="store_true")
    commands.add_parser("format-smoke")
    approval = commands.add_parser("record-approval")
    approval.add_argument("--approved-by", required=True)
    approval.add_argument("--approval-source", required=True)
    approval.add_argument("--format-smoke-hash", required=True)
    approval.add_argument("--approved-at")
    run = commands.add_parser("run")
    run.add_argument("--approval", type=Path, required=True)
    resume = commands.add_parser("resume")
    resume.add_argument("--approval", type=Path, required=True)
    verify = commands.add_parser("verify")
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


def status_payload(policy: Any, repository_root: Path) -> dict[str, Any]:
    sources = audit_sources(policy, repository_root=repository_root, full_hash_scan=False)
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository_root, text=True
    ).strip()
    clean = repository_clean(repository_root)
    smokes: list[Path] = []
    for path in (policy.operations_root / "format-smokes").glob("*.json"):
        if not path.is_file() or path.is_symlink() or path.name.startswith("._"):
            continue
        try:
            payload = read_canonical_json(path)
        except ValueError:
            continue
        if (
            payload.get("format_smoke_hash")
            == canonical_content_hash(
                {key: value for key, value in payload.items() if key != "format_smoke_hash"}
            )
            and payload.get("status") == "PASS"
            and payload.get("code_commit") == commit
            and payload.get("policy_hash") == policy.policy_hash
            and clean
        ):
            smokes.append(path)
    approvals: list[Path] = []
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
            for path in (policy.evidence_root / "runs").glob("stage2-s2p17-t20-*")
            if path.is_dir() and not path.is_symlink()
        )
    )
    checkpoint: dict[str, Any] = {}
    contract: dict[str, Any] = {}
    verify: dict[str, Any] = {}
    decision: dict[str, Any] = {}
    if runs:
        if (runs[-1] / "checkpoint.json").is_file():
            checkpoint = read_canonical_json(runs[-1] / "checkpoint.json")
        if (runs[-1] / "run-contract.json").is_file():
            contract = read_canonical_json(runs[-1] / "run-contract.json")
        verify_files = tuple(
            path
            for path in (runs[-1] / "verify").glob("*.json")
            if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
        )
        if len(verify_files) == 1:
            verify = read_canonical_json(verify_files[0])
        decision_path = runs[-1] / "published/stage2-final-decision.json"
        if decision_path.is_file():
            decision = read_canonical_json(decision_path)
    if checkpoint:
        status = str(checkpoint.get("status", "IN_PROGRESS"))
        reason = (
            "FORMAL_TASK_VERIFIED_PASS"
            if status == "PASS"
            else str(checkpoint.get("phase", "IN_PROGRESS"))
        )
    elif authorities or runs:
        status, reason = "BLOCKED", "UNFINISHED_FORMAL_PREFIX"
    elif approvals:
        status, reason = "NOT_STARTED", "FORMAL_APPROVAL_PRESENT"
    elif smokes:
        status, reason = "BLOCKED", "COMMIT_BOUND_APPROVAL_REQUIRED"
    else:
        status, reason = (
            ("BLOCKED", "FORMAT_SMOKE_REQUIRED")
            if clean
            else ("BLOCKED", "CLEAN_COMMIT_FORMAT_SMOKE_REQUIRED")
        )
    source_cards = read_canonical_json(sources.t19.cards_path)
    source_lifecycle = source_cards.get("lifecycle")
    lifecycle = source_lifecycle if isinstance(source_lifecycle, dict) else {}
    source_recommendation = str(source_cards.get("overall_recommendation", "UNAVAILABLE"))
    return {
        "schema_name": "s2p17-t20-status",
        "schema_version": "1.0",
        "stage_plan_version": "1.7",
        "task_id": "S2P17-T20",
        "status": status,
        "reason_code": reason,
        "repo_root": str(repository_root.resolve()),
        "repo_commit": commit,
        "repository_clean": clean,
        "policy_hash": policy.policy_hash,
        "source_t11_receipt_hash": sources.upstreams.t11.receipt_hash,
        "source_t16_verify_hash": sources.upstreams.upstreams.t16.verify_hash,
        "source_t17_verify_hash": sources.upstreams.upstreams.t17.verify_hash,
        "source_t18_verify_hash": sources.upstreams.t18.verify_hash,
        "source_t19_verify_hash": sources.t19.verify_hash,
        "format_smoke_count": len(smokes),
        "latest_format_smoke_hash": smokes[-1].stem if smokes else None,
        "approval_count": len(approvals),
        "authority_count": len(authorities),
        "run_count": len(runs),
        "run_id": contract.get("run_id"),
        "run_code_commit": contract.get("code_commit"),
        "verify_hash": verify.get("verify_hash"),
        "active_run": checkpoint,
        "decision": decision,
        "source_decision": {
            "engineering_status": source_cards.get("engineering_status"),
            "h2_primary": source_cards.get("btc_primary"),
            "eth_classification": source_cards.get("eth_classification"),
            "h3_lifecycle": {
                instrument: (
                    lifecycle.get(instrument, {}).get("decision")
                    if isinstance(lifecycle.get(instrument), dict)
                    else None
                )
                for instrument in ("BTCUSDT", "ETHUSDT")
            },
            "source_recommendation": source_recommendation,
        },
        "run_lock_held": _lock_is_held(policy.operations_root / "run.lock"),
        "evidence_label": "H2/H3 historical final acceptance evidence",
        "research_status": decision.get("research_decision"),
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
        result = status_payload(policy, root)
    elif arguments.command == "audit":
        sources = audit_sources(
            policy, repository_root=root, full_hash_scan=arguments.full_hash_scan
        )
        result = {
            "status": "PASS",
            "source_t11_receipt_hash": sources.upstreams.t11.receipt_hash,
            "source_t16_verify_hash": sources.upstreams.upstreams.t16.verify_hash,
            "source_t17_verify_hash": sources.upstreams.upstreams.t17.verify_hash,
            "source_t18_verify_hash": sources.upstreams.t18.verify_hash,
            "source_t19_verify_hash": sources.t19.verify_hash,
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
