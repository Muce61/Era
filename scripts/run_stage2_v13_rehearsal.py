#!/usr/bin/env python3
"""Run, verify or finalize the Plan v1.3 real-input seven-day rehearsal."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from era100x.research.stage_2.rerun.seven_day_rehearsal import (
    finalize_ui_projection,
    run_final_code_rehearsal,
    verify_final_code_rehearsal,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    subcommands = value.add_subparsers(dest="command", required=True)
    run = subcommands.add_parser("run")
    run.add_argument("--output-root", required=True, type=Path)
    verify = subcommands.add_parser("verify")
    verify.add_argument("--report", required=True, type=Path)
    finalize = subcommands.add_parser("finalize-ui")
    finalize.add_argument("--report", required=True, type=Path)
    finalize.add_argument("--observed-repo-commit", required=True)
    finalize.add_argument("--observed-gate", required=True, choices=("PENDING",))
    return value


def main() -> int:
    args = parser().parse_args()
    if args.command == "run":
        report, path = run_final_code_rehearsal(output_root=args.output_root)
        result = {"status": report["status"], "report_path": str(path)}
    elif args.command == "verify":
        result = verify_final_code_rehearsal(args.report)
    else:
        path = finalize_ui_projection(
            report_path=args.report,
            observed_repo_commit=args.observed_repo_commit,
            observed_gate=args.observed_gate,
        )
        result = {"status": "PASS", "receipt_path": str(path)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
