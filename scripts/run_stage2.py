#!/usr/bin/env python3
"""Single lightweight entrypoint for Stage 2 status and approval evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from era100x.research.stage_2.rerun.lightweight_governance import (
    adopt_verified_prefix,
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
        "mode",
        choices=(
            "status",
            "rehearse",
            "record-approval",
            "adopt-verified-prefix",
            "run",
            "resume",
            "verify",
        ),
    )
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--rehearsal", type=Path)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--source-chain", type=Path)
    parser.add_argument("--approved-by", default="Muce")
    parser.add_argument("--approval-source")
    parser.add_argument("--waive-rehearsal-for-background-runtime", action="store_true")
    parser.add_argument("--waiver-reason")
    args = parser.parse_args()
    policy = load_policy(args.policy, repository_root=ROOT)
    os.environ["ERA_S2P13_TRADE_SUPPLEMENT_ACCEPTANCE_PATH"] = str(policy.trade_supplement_path)
    os.environ["ERA_S2P13_TRADE_SUPPLEMENT_ACCEPTANCE_HASH"] = policy.trade_supplement_file_hash
    if args.mode == "status":
        result = {
            "status": "PASS",
            "policy_hash": policy.policy_hash,
            "repository": repository_head(ROOT),
            "stage_plan_version": "1.3",
            "stage3_locked": True,
            "evidence_root": str(policy.evidence_root),
            "trade_supplement_acceptance_hash": policy.trade_supplement_acceptance_hash,
        }
    elif args.mode == "record-approval":
        if not args.approval_source:
            parser.error("record-approval requires --approval-source")
        if args.waive_rehearsal_for_background_runtime:
            if args.rehearsal is not None or not args.waiver_reason:
                parser.error("background waiver requires --waiver-reason and forbids --rehearsal")
        elif args.waiver_reason is not None:
            parser.error("waiver reason requires the explicit background waiver flag")
        path = record_approval(
            policy=policy,
            repository_root=ROOT,
            rehearsal_path=args.rehearsal,
            approved_by=args.approved_by,
            approval_source=args.approval_source,
            background_runtime_waiver=args.waive_rehearsal_for_background_runtime,
            waiver_reason=args.waiver_reason,
        )
        result = {"status": "APPROVED", "approval_path": str(path)}
    elif args.mode == "adopt-verified-prefix":
        if args.approval is None or args.source_chain is None:
            parser.error("adopt-verified-prefix requires --approval and --source-chain")
        result = adopt_verified_prefix(
            approval_path=args.approval,
            source_chain_root=args.source_chain,
            policy=policy,
            repository_root=ROOT,
        )
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
