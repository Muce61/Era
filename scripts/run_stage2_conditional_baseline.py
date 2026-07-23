#!/usr/bin/env python3
"""S2-T15 v1.4 append-only conditional-baseline CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from era100x.foundation.governance import require_operation_allowed
from era100x.research.stage_2.baselines.conditional.full_run import (
    BIN_ROOT,
    RUNS_ROOT,
    T13_SNAPSHOT,
    T10_SNAPSHOT,
    T10_SNAPSHOT_ID,
    audit_upstream,
    current_code_commit,
    freeze_authority,
    preflight,
    repository_is_clean,
)
from era100x.research.stage_2.baselines.conditional.binning_run import (
    freeze_binning_snapshots,
)
from era100x.research.stage_2.baselines.conditional.receipt_supplement import (
    build_receipt_distribution_supplement,
)
from era100x.research.stage_2.baselines.conditional.context_receipt_supplement import (
    build_context_receipt_supplement,
)
from era100x.research.stage_2.baselines.conditional.execution_run import (
    run_full_execution,
    verify_published_run,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", choices=("audit", "freeze-authority", "freeze-bins", "preflight", "run", "verify")
    )
    parser.add_argument("--audit-report", type=Path)
    parser.add_argument("--authority", type=Path)
    parser.add_argument("--binning-set", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument(
        "--build-receiver-supplement",
        action="store_true",
        help="audit-only CR-2026-027 append-only supplement; never creates Authority or Run",
    )
    parser.add_argument(
        "--build-context-supplement",
        action="store_true",
        help="audit-only CR-2026-028 price-trigger supplement; never creates Authority or Run",
    )
    return parser


def _requested_operation(args: argparse.Namespace) -> str:
    if args.mode == "audit":
        if args.build_receiver_supplement or args.build_context_supplement:
            return "BUILD_AUDIT_SUPPLEMENT"
        return "READ_ONLY_AUDIT"
    if args.mode == "freeze-authority":
        return "FREEZE_AUTHORITY"
    if args.mode == "freeze-bins":
        return "FREEZE_BINS"
    if args.mode == "preflight":
        return "PREFLIGHT"
    if args.mode == "run":
        return "RESUME" if args.run_id is not None else "RUN"
    if args.mode == "verify":
        return "VERIFY_EXISTING_EVIDENCE"
    raise AssertionError("unreachable mode")


def main() -> int:
    args = _parser().parse_args()
    require_operation_allowed(_requested_operation(args))
    if args.mode == "audit":
        supplement_build = None
        if args.build_receiver_supplement:
            supplement, supplement_path = build_receipt_distribution_supplement()
            supplement_build = {
                "status": supplement["status"],
                "manifest_hash": supplement["manifest_hash"],
                "path": str(supplement_path),
                "authority_created": False,
                "run_id_created": False,
            }
        context_supplement_build = None
        if args.build_context_supplement:
            context_supplement, context_supplement_path = build_context_receipt_supplement()
            context_supplement_build = {
                "status": context_supplement["status"],
                "manifest_hash": context_supplement["manifest_hash"],
                "path": str(context_supplement_path),
                "authority_created": False,
                "run_id_created": False,
            }
        result = audit_upstream()
        if supplement_build is not None:
            result["receiver_supplement_build"] = supplement_build
        if context_supplement_build is not None:
            result["context_receiver_supplement_build"] = context_supplement_build
    elif args.mode == "freeze-authority":
        authority, path = freeze_authority(audit_path=args.audit_report)
        result = {
            "status": "PASS",
            "authority_hash": authority.authority_hash,
            "authority_path": str(path),
            "run_id_created": False,
        }
    elif args.mode == "preflight":
        if args.authority is None or args.binning_set is None:
            raise SystemExit("preflight requires --authority and --binning-set")
        result = preflight(
            authority_path=args.authority,
            binning_set_path=args.binning_set,
        )
    elif args.mode == "freeze-bins":
        if args.authority is None:
            raise SystemExit("freeze-bins requires --authority")
        bins, path = freeze_binning_snapshots(
            authority_path=args.authority,
            bin_root=BIN_ROOT,
            t10_snapshot=T10_SNAPSHOT,
            t10_snapshot_id=T10_SNAPSHOT_ID,
            current_commit=current_code_commit(),
            repository_clean=repository_is_clean(),
        )
        result = {
            "status": bins["status"],
            "binning_set_hash": bins["binning_set_hash"],
            "binning_set_path": str(path),
            "run_id_created": False,
        }
    elif args.mode == "run":
        if args.authority is None or args.binning_set is None:
            raise SystemExit("run requires --authority and --binning-set")
        if args.run_id is None:
            preflight(authority_path=args.authority, binning_set_path=args.binning_set)
        manifest, path = run_full_execution(
            authority_path=args.authority,
            binning_set_path=args.binning_set,
            runs_root=RUNS_ROOT,
            t10_snapshot=T10_SNAPSHOT,
            t10_snapshot_id=T10_SNAPSHOT_ID,
            t13_snapshot=T13_SNAPSHOT,
            current_commit=current_code_commit(),
            repository_clean=repository_is_clean(),
            resume_run_id=args.run_id,
        )
        result = {
            "status": "COMPLETE_PENDING_VERIFY",
            "run_id": manifest["run_id"],
            "snapshot_id": manifest["snapshot_id"],
            "published_path": str(path),
        }
    elif args.mode == "verify":
        if args.run_id is None:
            raise SystemExit("verify requires --run-id")
        verify, path = verify_published_run(run_root=RUNS_ROOT / args.run_id)
        result = {**verify, "verify_path": str(path)}
    else:
        raise AssertionError("unreachable mode")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
