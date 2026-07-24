#!/usr/bin/env python3
"""Build or verify one append-only Stage 2 Trade partition supplement."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from era100x.research.stage_2.rerun.trade_supplement import (
    build_trade_supplement,
    verify_trade_supplement,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    build = subcommands.add_parser("build")
    build.add_argument("--source-archive", required=True, type=Path)
    build.add_argument("--checksum", required=True, type=Path)
    build.add_argument("--original-partition-root", required=True, type=Path)
    build.add_argument("--output-root", required=True, type=Path)
    build.add_argument("--instrument", required=True, choices=("BTCUSDT", "ETHUSDT"))
    build.add_argument("--date", required=True, type=date.fromisoformat)
    verify = subcommands.add_parser("verify")
    verify.add_argument("--acceptance", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "build":
        acceptance = build_trade_supplement(
            source_archive=args.source_archive,
            checksum_path=args.checksum,
            original_partition_root=args.original_partition_root,
            output_root=args.output_root,
            instrument=args.instrument,
            owner_date=args.date,
        )
        result = verify_trade_supplement(acceptance)
        result["acceptance_path"] = str(acceptance)
    else:
        result = verify_trade_supplement(args.acceptance)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
