#!/usr/bin/env python3
"""Build or verify CR-2026-038 historical funding evidence."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from era100x.research.stage_2.funding import (
    accept_local_history,
    build_funding_evidence,
    verify_funding_acceptance,
    verify_funding_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--output-root", type=Path, required=True)
    run.add_argument("--evidence-id", required=True)
    run.add_argument("--local-root", type=Path, required=True)
    run.add_argument("--start-date", type=date.fromisoformat, required=True)
    run.add_argument("--end-date-exclusive", type=date.fromisoformat, required=True)
    run.add_argument("--scope", choices=("SEVEN_DAY_REHEARSAL", "FULL_HISTORY"), required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--evidence-root", type=Path, required=True)
    accept = subparsers.add_parser("accept")
    accept.add_argument("--evidence-root", type=Path, required=True)
    accept.add_argument("--accepted-by", required=True)
    verify_acceptance = subparsers.add_parser("verify-acceptance")
    verify_acceptance.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        result = build_funding_evidence(
            output_root=args.output_root,
            evidence_id=args.evidence_id,
            local_root=args.local_root,
            start_date=args.start_date,
            end_date_exclusive=args.end_date_exclusive,
            scope=args.scope,
        )
    elif args.command == "verify":
        result = verify_funding_evidence(args.evidence_root)
    elif args.command == "accept":
        result = accept_local_history(args.evidence_root, accepted_by=args.accepted_by)
    else:
        result = verify_funding_acceptance(args.evidence_root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
