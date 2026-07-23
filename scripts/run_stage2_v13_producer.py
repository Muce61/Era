#!/usr/bin/env python3
"""Unified fail-closed CLI for one Plan v1.3 successor producer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from era100x.research.stage_2.rerun.orchestrator import TASKS
from era100x.research.stage_2.rerun.producer_contracts import ExecutionScope, ProducerContext
from era100x.research.stage_2.rerun.producer_execution import (
    execute_producer,
    verify_producer,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id", choices=TASKS)
    parser.add_argument(
        "mode",
        choices=("static-preflight", "input-preflight", "rehearsal", "run", "resume", "verify"),
    )
    parser.add_argument("--execution-mode", choices=("REHEARSAL", "FORMAL"), required=True)
    parser.add_argument("--scope-mode", choices=("SEVEN_DAY", "FULL_HISTORY"), required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date-exclusive", required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    return parser


def main() -> int:
    args = _parser().parse_args()
    scope = ExecutionScope.seal(
        mode=args.scope_mode,
        start_date=args.start_date,
        end_date_exclusive=args.end_date_exclusive,
    )
    context = ProducerContext.from_environment(
        task_id=args.task_id,
        execution_mode=args.execution_mode,
        scope=scope,
        repository_root=args.repository_root,
        require_upstream=args.mode != "static-preflight",
    )
    if args.mode == "static-preflight":
        result = context.static_preflight()
    elif args.mode == "input-preflight":
        result = context.input_preflight()
    elif args.mode in {"rehearsal", "run", "resume"}:
        expected_mode = "REHEARSAL" if args.mode == "rehearsal" else "FORMAL"
        if args.execution_mode != expected_mode:
            raise SystemExit(f"{args.mode} requires execution mode {expected_mode}")
        result = execute_producer(context, resume=args.mode == "resume")
    else:
        result = verify_producer(context)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
