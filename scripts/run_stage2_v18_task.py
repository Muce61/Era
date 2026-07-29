#!/usr/bin/env python3
"""Authority-bound production entry point for one Plan v1.8 successor Task."""

from __future__ import annotations

import argparse
import os

from era100x.research.stage_2.lifecycle.formal_chain import TASK_ORDER
from era100x.research.stage_2.lifecycle.production import run_from_environment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id", choices=TASK_ORDER)
    args = parser.parse_args()
    if os.environ.get("ERA_S2P18_TASK_ID") != args.task_id:
        raise ValueError("adapter argv and Authority environment Task identities differ")
    print(run_from_environment())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
