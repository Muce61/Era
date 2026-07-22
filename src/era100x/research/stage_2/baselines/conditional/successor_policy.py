"""CR-2026-028 fail-closed policy for the single S2-T15 successor chain."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

FAILED_PREDECESSOR_RUN_ID = "stage2-s2t15-conditional-20260722T071250Z-871c404c5f43"
FAILED_PREDECESSOR_AUTHORITY_HASH = (
    "871c404c5f43c5c07539d7a373801756c150ad5f3e6724eee0b016699a5cfbd1"
)
FAILED_PREDECESSOR_BINNING_SET_HASH = (
    "0b604d6c7ea8fabcca2870ddaf7b25bc38b8e695213b75e21b697e7e6f0ee4d0"
)
FAILED_PREDECESSOR_FAILURE_CODE = "S2_T15_EPISODE_CONTEXT_ANCHOR_MISMATCH"


def _t15_runs(runs_root: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in runs_root.glob("stage2-s2t15-conditional-*")
            if path.is_dir() and not path.is_symlink()
        )
    )


def validate_failed_predecessor(runs_root: Path) -> Path:
    """Prove the exact unpublished predecessor is immutable and terminal."""

    run_root = runs_root / FAILED_PREDECESSOR_RUN_ID
    if run_root.is_symlink() or not run_root.is_dir():
        raise ValueError("CR-2026-028 failed predecessor is missing or unsafe")
    checkpoint_path = run_root / "checkpoint.json"
    if checkpoint_path.is_symlink() or not checkpoint_path.is_file():
        raise ValueError("CR-2026-028 failed predecessor checkpoint is missing or unsafe")
    checkpoint = cast(dict[str, Any], json.loads(checkpoint_path.read_bytes()))
    expected = {
        "run_id": FAILED_PREDECESSOR_RUN_ID,
        "authority_hash": FAILED_PREDECESSOR_AUTHORITY_HASH,
        "binning_set_hash": FAILED_PREDECESSOR_BINNING_SET_HASH,
        "status": "FAILED_UNPUBLISHED",
        "phase": "FAILED",
        "failure_code": FAILED_PREDECESSOR_FAILURE_CODE,
        "published": False,
        "resume_allowed": False,
    }
    if any(checkpoint.get(key) != value for key, value in expected.items()):
        raise ValueError("CR-2026-028 failed predecessor checkpoint binding drift")
    published = run_root / "published"
    if published.exists() or published.is_symlink():
        raise ValueError("CR-2026-028 predecessor unexpectedly contains published output")
    return run_root


def require_single_successor_creation_state(runs_root: Path) -> Path:
    """Allow creation only when the exact failed predecessor is the sole T15 Run."""

    predecessor = validate_failed_predecessor(runs_root)
    if _t15_runs(runs_root) != (predecessor,):
        raise ValueError("CR-2026-028 allows exactly one successor and no other T15 Run")
    return predecessor


def require_single_successor_resume_state(runs_root: Path, successor_run_id: str) -> Path:
    """Allow resume only for the one Run created after the failed predecessor."""

    predecessor = validate_failed_predecessor(runs_root)
    successor = runs_root / successor_run_id
    if successor == predecessor or successor.is_symlink() or not successor.is_dir():
        raise ValueError("CR-2026-028 successor resume target is missing or unsafe")
    if set(_t15_runs(runs_root)) != {predecessor, successor}:
        raise ValueError("CR-2026-028 successor chain count drift")
    return predecessor
