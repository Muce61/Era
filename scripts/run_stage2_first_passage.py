#!/usr/bin/env python3
"""Approved S2-T13 v1.3 historical first-passage full-output CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from era100x.research.stage_2.labels.first_passage.full_run import (
    RUNS_ROOT,
    create_preflight_manifest,
    current_code_commit,
    execute_run,
    find_resumable_run,
    latest_preflight_manifest,
    resume_run,
    verify_run,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "run", "resume", "verify"))
    parser.add_argument("--preflight-manifest", type=Path)
    parser.add_argument("--run-id")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.mode == "preflight":
        authority, path = create_preflight_manifest(code_commit=current_code_commit())
        result = {
            "status": "PASS",
            "mode": "preflight",
            "authority_hash": authority["authority_hash"],
            "authority_path": str(path),
            "expected_path_rows": authority["expected_path_rows"],
            "expected_classification_count": authority["expected_classification_count"],
            "run_id_created": False,
        }
    elif args.mode == "run":
        preflight = args.preflight_manifest or latest_preflight_manifest()
        run_root = execute_run(preflight_path=preflight, run_id=args.run_id)
        result = {"status": "PASS", "mode": "run", "run_root": str(run_root)}
    elif args.mode == "resume":
        run_root = RUNS_ROOT / args.run_id if args.run_id else find_resumable_run()
        result = {"status": "PASS", "mode": "resume", "run_root": str(resume_run(run_root))}
    else:
        if not args.run_id:
            raise SystemExit("verify requires --run-id")
        result = {"mode": "verify", **verify_run(RUNS_ROOT / args.run_id)}
        if result["status"] != "PASS":
            raise SystemExit(json.dumps(result, sort_keys=True))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
