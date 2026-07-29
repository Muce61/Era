#!/usr/bin/env python3
"""Plan v1.8 formal approval, Authority, Run, reconciliation and Verify CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from era100x.research.stage_2.lifecycle.formal_chain import (
    build_catalog_and_manifest,
    freeze_authority,
    load_adapter_plan,
    publish_candidate_chain,
    record_approval,
    run_formal_chain,
    seal_publication,
    validate_approval,
    validate_authority,
    verify_formal_chain,
)
from era100x.research.stage_2.lifecycle.governance import load_policy

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "configs/governance/stage2_active_policy_v7.json"
DEFAULT_EVIDENCE_ROOT = Path(
    "/Volumes/FuckingLife/era100x_stage2/formal/stage2-plan-v1.8"
)


def _inputs(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError("input bindings must be a JSON object")
    return {str(key): str(value) for key, value in payload.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "status",
            "record-approval",
            "freeze-authority",
            "run",
            "resume",
            "reconcile",
            "publish-candidate",
            "verify",
            "seal-publication",
        ),
    )
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--adapter-plan", type=Path)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--authority", type=Path)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--verify-path", type=Path)
    parser.add_argument("--input-bindings", type=Path)
    parser.add_argument("--approved-by")
    parser.add_argument("--approval-source")
    parser.add_argument("--approved-commit")
    args = parser.parse_args()

    policy = load_policy(args.policy, repository_root=ROOT)
    if args.command == "status":
        adapters = (
            load_adapter_plan(args.adapter_plan, repository_root=ROOT)
            if args.adapter_plan is not None
            else None
        )
        print(
            json.dumps(
                {
                    "stage_plan_version": "1.8",
                    "policy_hash": policy.policy_hash,
                    "adapter_plan_hash": adapters.plan_hash if adapters else None,
                    "adapter_plan_status": "PASS" if adapters else "NOT_FROZEN",
                    "approval_count": len(
                        tuple((args.evidence_root / "operations/approvals").glob("*.json"))
                    ),
                    "authority_count": len(
                        tuple((args.evidence_root / "authorities").glob("authority-*.json"))
                    ),
                    "run_count": len(
                        tuple((args.evidence_root / "runs").glob("stage2-s2p18-*"))
                    ),
                    "stage3_locked": True,
                },
                sort_keys=True,
            )
        )
        return 0
    if args.adapter_plan is None:
        raise ValueError(f"{args.command} requires --adapter-plan")
    adapters = load_adapter_plan(args.adapter_plan, repository_root=ROOT)
    if args.command == "record-approval":
        if not all((args.approved_by, args.approval_source, args.approved_commit)):
            raise ValueError("record-approval requires approver, source and exact commit")
        path = record_approval(
            policy=policy,
            adapter_plan=adapters,
            repository_root=ROOT,
            operations_root=args.evidence_root / "operations",
            approved_by=args.approved_by,
            approval_source=args.approval_source,
            approved_commit=args.approved_commit,
        )
        print(path)
        return 0
    if args.approval is None:
        raise ValueError(f"{args.command} requires --approval")
    validate_approval(
        args.approval,
        policy=policy,
        adapter_plan=adapters,
        repository_root=ROOT,
    )
    if args.command == "freeze-authority":
        if args.input_bindings is None:
            raise ValueError("freeze-authority requires --input-bindings")
        path = freeze_authority(
            policy=policy,
            adapter_plan=adapters,
            approval_path=args.approval,
            repository_root=ROOT,
            evidence_root=args.evidence_root,
            input_bindings=_inputs(args.input_bindings),
        )
        print(path)
        return 0
    if args.authority is None:
        raise ValueError(f"{args.command} requires --authority")
    validate_authority(
        args.authority,
        policy=policy,
        adapter_plan=adapters,
        approval_path=args.approval,
        repository_root=ROOT,
    )
    if args.command in {"run", "resume"}:
        if args.command == "resume" and args.run_root is None:
            raise ValueError("resume requires --run-root")
        path = run_formal_chain(
            policy=policy,
            adapter_plan=adapters,
            approval_path=args.approval,
            authority_path=args.authority,
            repository_root=ROOT,
            evidence_root=args.evidence_root,
            resume_run_root=args.run_root if args.command == "resume" else None,
        )
        print(path)
        return 0
    if args.run_root is None:
        raise ValueError(f"{args.command} requires --run-root")
    if args.command == "reconcile":
        catalog, manifest = build_catalog_and_manifest(
            run_root=args.run_root,
            authority_path=args.authority,
        )
        print(json.dumps({"catalog": str(catalog), "manifest": str(manifest)}))
        return 0
    if args.command == "publish-candidate":
        catalog = args.run_root / "reconcile/catalog.json"
        manifest = args.run_root / "reconcile/manifest.json"
        print(
            publish_candidate_chain(
                run_root=args.run_root,
                catalog_path=catalog,
                manifest_path=manifest,
            )
        )
        return 0
    if args.command == "verify":
        print(
            verify_formal_chain(
                run_root=args.run_root,
                authority_path=args.authority,
                full_hash_scan=True,
            )
        )
        return 0
    if args.verify_path is None:
        raise ValueError("seal-publication requires --verify-path")
    print(seal_publication(run_root=args.run_root, verify_path=args.verify_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
