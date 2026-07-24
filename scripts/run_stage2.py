#!/usr/bin/env python3
"""Single lightweight entrypoint for Stage 2 status and approval evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from era100x.research.stage_2.rerun.lightweight_governance import (
    load_policy,
    record_approval,
    repository_head,
    run_formal_chain,
    verify_formal_chain,
)
from era100x.research.stage_2.rerun.seven_day_rehearsal import run_final_code_rehearsal

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "configs/governance/stage2_active_policy_v2.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", choices=("status", "rehearse", "record-approval", "run", "resume", "verify")
    )
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--rehearsal", type=Path)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--approved-by", default="Muce")
    parser.add_argument("--approval-source")
    args = parser.parse_args()
    policy = load_policy(args.policy, repository_root=ROOT)
    if args.mode == "status":
        result = {
            "status": "PASS",
            "policy_hash": policy.policy_hash,
            "repository": repository_head(ROOT),
            "stage_plan_version": "1.3",
            "stage3_locked": True,
            "evidence_root": str(policy.evidence_root),
        }
    elif args.mode == "record-approval":
        if args.rehearsal is None or not args.approval_source:
            parser.error("record-approval requires --rehearsal and --approval-source")
        path = record_approval(
            policy=policy,
            repository_root=ROOT,
            rehearsal_path=args.rehearsal,
            approved_by=args.approved_by,
            approval_source=args.approval_source,
        )
        result = {"status": "APPROVED", "approval_path": str(path)}
    elif args.mode in {"run", "resume"}:
        if args.approval is None:
            parser.error(f"{args.mode} requires --approval")
        result = run_formal_chain(
            approval_path=args.approval,
            policy=policy,
            repository_root=ROOT,
        )
    elif args.mode == "verify":
        if args.approval is None:
            parser.error("verify requires --approval")
        result = verify_formal_chain(
            approval_path=args.approval,
            policy=policy,
            repository_root=ROOT,
        )
    else:
        if args.rehearsal is None:
            parser.error("rehearse requires --rehearsal output root")
        report, report_path = run_final_code_rehearsal(output_root=args.rehearsal)
        result = {
            "status": report["status"],
            "report_path": str(report_path),
            "stage3_locked": True,
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
