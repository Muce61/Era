"""Frozen S2-T10 full candidate CLI: preflight, run, resume and verify only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from era100x.research.stage_2.pipelines.candidates.runner import CandidateRun, Instrument, Variant
from era100x.research.stage_2.pipelines.candidates.release import semantic_comparison
from era100x.research.stage_2.pipelines.candidates.release_recovery import ReleaseRecovery
from era100x.research.stage_2.pipelines.candidates.runner import STAGE2_ROOT, dates


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--run-id", required=True)
    preflight.add_argument("--manifest", type=Path, required=True)
    for name in ("run", "resume"):
        command = commands.add_parser(name)
        command.add_argument("--run-id", required=True)
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--instrument", choices=("BTCUSDT", "ETHUSDT"), required=True)
        command.add_argument("--variant", choices=("V1_PRICE", "V1_FLOW"), required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--compare-run-id")
    recovery = commands.add_parser("release-recovery")
    recovery.add_argument("--action", choices=("prepare", "run", "resume", "verify"), required=True)
    recovery.add_argument("--run-id", required=True)
    recovery.add_argument("--supplement", type=Path, required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "release-recovery":
        recovery = ReleaseRecovery(STAGE2_ROOT / "runs" / args.run_id, args.supplement)
        if args.action == "prepare":
            result = recovery.prepare()
        elif args.action == "verify":
            result = recovery.structural_verify()
        else:
            result = recovery.release(expected_partition_count=len(dates()))
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.command == "preflight":
        run = CandidateRun.preflight(args.run_id, args.manifest)
        print(run.run_id)
        return 0
    run = CandidateRun(args.run_id, args.manifest)
    if args.command in {"run", "resume"}:
        run.execute(
            cast(Instrument, args.instrument),
            cast(Variant, args.variant),
            resume=args.command == "resume",
        )
        return 0
    catalog = run.verify()
    result = {
        "logical_hash": catalog["logical_hash"],
        "physical_hash": catalog["physical_hash"],
        "entries": len(catalog["entries"]),
    }
    if args.compare_run_id:
        other = CandidateRun(args.compare_run_id, args.manifest).verify()
        comparison = semantic_comparison(catalog["release_analysis"], other["release_analysis"])
        result["comparison"] = comparison
        if comparison["status"] != "PASS":
            raise ValueError(f"deterministic full-run mismatch: {comparison['different_fields']}")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
