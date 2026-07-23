#!/usr/bin/env python3
"""Run or verify the Plan v1.3 read-only availability audit."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from era100x.foundation.governance import require_operation_allowed
from era100x.research.stage_2.rerun.availability import (
    run_availability_audit,
    verify_availability_audit,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "verify"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2020, 1, 1))
    parser.add_argument("--end-date-exclusive", type=date.fromisoformat, default=date(2020, 1, 8))
    args = parser.parse_args()
    require_operation_allowed("READ_ONLY_AUDIT")
    if args.mode == "run":
        if args.root is None:
            raise SystemExit("run requires --root")
        result, report = run_availability_audit(
            root=args.root,
            start_date=args.start_date,
            end_date_exclusive=args.end_date_exclusive,
        )
        output = {**result, "report_path": str(report)}
    else:
        if args.report is None:
            raise SystemExit("verify requires --report")
        output = verify_availability_audit(args.report)
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0 if output["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
