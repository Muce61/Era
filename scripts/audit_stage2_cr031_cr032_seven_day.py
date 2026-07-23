#!/usr/bin/env python3
"""Run or verify the isolated CR-2026-031/032 seven-day audit."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from era100x.research.stage_2.baselines.conditional.seven_day_audit import (
    run_seven_day_audit,
    verify_seven_day_audit,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "verify"))
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2020, 1, 1))
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.mode == "run":
        if args.output_root is None:
            raise SystemExit("run requires --output-root")
        result, report_path = run_seven_day_audit(
            output_root=args.output_root, start_date=args.start_date
        )
        output = {**result, "report_path": str(report_path)}
    else:
        if args.report is None:
            raise SystemExit("verify requires --report")
        output = verify_seven_day_audit(report_path=args.report)
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0 if output["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
