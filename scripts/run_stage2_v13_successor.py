#!/usr/bin/env python3
"""Inspect the Plan v1.3 successor chain without bypassing formal run gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from era100x.foundation.governance import load_current_development_state
from era100x.research.stage_2.rerun.orchestrator import approval_readiness


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inspect",))
    parser.add_argument("--rehearsal", type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    result = approval_readiness(
        state=load_current_development_state(),
        rehearsal_path=args.rehearsal,
        repository_root=args.repository_root,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
