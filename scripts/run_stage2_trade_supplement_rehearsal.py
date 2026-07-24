#!/usr/bin/env python3
"""Run the seven-day successor chain across the accepted Trade supplement date."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

from era100x.research.stage_2.rerun.lightweight_governance import load_policy
from era100x.research.stage_2.rerun.seven_day_rehearsal import run_final_code_rehearsal

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "configs/governance/stage2_active_policy_v2.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    args = parser.parse_args()
    policy = load_policy(args.policy, repository_root=ROOT)
    os.environ["ERA_S2P13_TRADE_SUPPLEMENT_ACCEPTANCE_PATH"] = str(policy.trade_supplement_path)
    os.environ["ERA_S2P13_TRADE_SUPPLEMENT_ACCEPTANCE_HASH"] = policy.trade_supplement_file_hash
    report, report_path = run_final_code_rehearsal(
        output_root=args.output_root,
        start_date=date(2022, 2, 27),
        purpose="TRADE_SUPPLEMENT_COVERAGE",
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "report_path": str(report_path),
                "start_date": report["start_date"],
                "end_date_exclusive": report["end_date_exclusive"],
                "trade_supplement_acceptance_hash": (policy.trade_supplement_acceptance_hash),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
