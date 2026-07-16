"""Frozen S2-T10 full candidate CLI: preflight, run, resume and verify only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from era100x.research.stage_2.pipelines.candidates.runner import CandidateRun, Instrument, Variant


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
    return root


def main() -> int:
    args = parser().parse_args()
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
    if args.compare_run_id:
        other = CandidateRun(args.compare_run_id, args.manifest).verify()
        if catalog["logical_hash"] != other["logical_hash"]:
            raise ValueError("deterministic full-run logical hash mismatch")
    print(json.dumps({"logical_hash": catalog["logical_hash"], "entries": len(catalog["entries"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
