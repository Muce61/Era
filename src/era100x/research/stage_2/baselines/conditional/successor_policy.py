"""CR-2026-030 fail-closed policy for the final S2-T15 replacement chain."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

RERUN_SUCCESSOR_APPROVAL: Path | None = None

FAILED_PREDECESSOR_RUN_ID = "stage2-s2t15-conditional-20260722T071250Z-871c404c5f43"
FAILED_PREDECESSOR_AUTHORITY_HASH = (
    "871c404c5f43c5c07539d7a373801756c150ad5f3e6724eee0b016699a5cfbd1"
)
FAILED_PREDECESSOR_BINNING_SET_HASH = (
    "0b604d6c7ea8fabcca2870ddaf7b25bc38b8e695213b75e21b697e7e6f0ee4d0"
)
FAILED_PREDECESSOR_FAILURE_CODE = "S2_T15_EPISODE_CONTEXT_ANCHOR_MISMATCH"
FAILED_CR028_SUCCESSOR_RUN_ID = "stage2-s2t15-conditional-20260722T120658Z-023f47cffef2"
FAILED_CR028_SUCCESSOR_AUTHORITY_HASH = (
    "023f47cffef210deac9d63c5adf99b381d7942b9db2a6e082a0c97760de76a58"
)
FAILED_CR028_SUCCESSOR_BINNING_SET_HASH = (
    "4904212e77e8f78e38183411278c99238636519af6261338b297e45afebc097e"
)
FAILED_CR028_SUCCESSOR_FAILURE_CODE = "S2_T15_CONTROL_ENTRY_PRICE_STRICT_JSON_DECIMAL"


def _t15_runs(runs_root: Path) -> tuple[Path, ...]:
    candidates = tuple(sorted(runs_root.glob("stage2-s2t15-conditional-*")))
    if any(path.is_symlink() or not path.is_dir() for path in candidates):
        raise ValueError("unsafe T15 Run entry blocks final successor recovery")
    return candidates


def configure_rerun_successor_approval(path: Path | None) -> None:
    """Select the separately approved rerun receipt; ``None`` preserves CR-2026-030."""

    global RERUN_SUCCESSOR_APPROVAL
    RERUN_SUCCESSOR_APPROVAL = path


def rerun_successor_approval_hash() -> str | None:
    if RERUN_SUCCESSOR_APPROVAL is None:
        return None
    from era100x.research.stage_2.rerun.orchestrator import validate_approval_receipt

    return str(validate_approval_receipt(RERUN_SUCCESSOR_APPROVAL)["approval_hash"])


def _checkpoint(run_root: Path) -> dict[str, Any]:
    path = run_root / "checkpoint.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"T15 Run checkpoint is missing or unsafe: {run_root.name}")
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, dict) or payload.get("run_id") != run_root.name:
        raise ValueError(f"T15 Run checkpoint binding drift: {run_root.name}")
    return cast(dict[str, Any], payload)


def _require_approved_rerun_creation_state(runs_root: Path, approval_hash: str) -> Path:
    runs = _t15_runs(runs_root)
    if not runs:
        raise ValueError("approved T15 rerun requires preserved predecessor evidence")
    bound = []
    for run_root in runs:
        checkpoint = _checkpoint(run_root)
        if checkpoint.get("rerun_approval_hash") == approval_hash:
            bound.append(run_root)
        if checkpoint.get("status") in {"IN_PROGRESS", "COMPLETE_PENDING_VERIFY"}:
            raise ValueError(f"another active T15 Run blocks rerun creation: {run_root.name}")
    if bound:
        raise ValueError("the approved T15 rerun successor has already been created")
    return max(runs, key=lambda path: (path.stat().st_mtime_ns, path.name))


def _require_approved_rerun_resume_state(
    runs_root: Path, successor_run_id: str, approval_hash: str
) -> Path:
    successor = runs_root / successor_run_id
    if successor.is_symlink() or not successor.is_dir():
        raise ValueError("approved T15 rerun resume target is missing or unsafe")
    checkpoint = _checkpoint(successor)
    if checkpoint.get("rerun_approval_hash") != approval_hash:
        raise ValueError("T15 rerun resume approval binding drift")
    predecessors = [path for path in _t15_runs(runs_root) if path != successor]
    if not predecessors:
        raise ValueError("T15 rerun predecessor evidence is missing")
    return max(predecessors, key=lambda path: (path.stat().st_mtime_ns, path.name))


def _validate_failed_run(
    runs_root: Path,
    *,
    run_id: str,
    expected: dict[str, object],
    change_request: str,
) -> Path:
    run_root = runs_root / run_id
    if run_root.is_symlink() or not run_root.is_dir():
        raise ValueError(f"{change_request} failed Run is missing or unsafe")
    checkpoint_path = run_root / "checkpoint.json"
    if checkpoint_path.is_symlink() or not checkpoint_path.is_file():
        raise ValueError(f"{change_request} failed Run checkpoint is missing or unsafe")
    checkpoint = cast(dict[str, Any], json.loads(checkpoint_path.read_bytes()))
    if any(checkpoint.get(key) != value for key, value in expected.items()):
        raise ValueError(f"{change_request} failed Run checkpoint binding drift")
    published = run_root / "published"
    if published.exists() or published.is_symlink():
        raise ValueError(f"{change_request} failed Run unexpectedly contains published output")
    return run_root


def validate_failed_predecessor(runs_root: Path) -> Path:
    """Prove the exact unpublished predecessor is immutable and terminal."""

    return _validate_failed_run(
        runs_root,
        run_id=FAILED_PREDECESSOR_RUN_ID,
        change_request="CR-2026-028",
        expected={
            "run_id": FAILED_PREDECESSOR_RUN_ID,
            "authority_hash": FAILED_PREDECESSOR_AUTHORITY_HASH,
            "binning_set_hash": FAILED_PREDECESSOR_BINNING_SET_HASH,
            "status": "FAILED_UNPUBLISHED",
            "phase": "FAILED",
            "failure_code": FAILED_PREDECESSOR_FAILURE_CODE,
            "published": False,
            "resume_allowed": False,
        },
    )


def validate_failed_cr028_successor(runs_root: Path) -> Path:
    """Prove the consumed CR-2026-028 successor is terminal and unpublished."""

    return _validate_failed_run(
        runs_root,
        run_id=FAILED_CR028_SUCCESSOR_RUN_ID,
        change_request="CR-2026-029",
        expected={
            "run_id": FAILED_CR028_SUCCESSOR_RUN_ID,
            "authority_hash": FAILED_CR028_SUCCESSOR_AUTHORITY_HASH,
            "binning_set_hash": FAILED_CR028_SUCCESSOR_BINNING_SET_HASH,
            "status": "FAILED_UNPUBLISHED",
            "phase": "FAILED",
            "completed_group_count": 456,
            "expected_group_count": 456,
            "failure_code": FAILED_CR028_SUCCESSOR_FAILURE_CODE,
            "published": False,
            "resume_allowed": False,
            "supersedes_failed_run_id": FAILED_PREDECESSOR_RUN_ID,
        },
    )


def require_final_successor_creation_state(runs_root: Path) -> Path:
    """Allow one final Run only when both exact failed Runs are the complete universe."""

    approval_hash = rerun_successor_approval_hash()
    if approval_hash is not None:
        return _require_approved_rerun_creation_state(runs_root, approval_hash)

    predecessor = validate_failed_predecessor(runs_root)
    failed_successor = validate_failed_cr028_successor(runs_root)
    if _t15_runs(runs_root) != tuple(sorted((predecessor, failed_successor))):
        raise ValueError("CR-2026-030 allows exactly one final successor and no other T15 Run")
    return failed_successor


def require_final_successor_resume_state(runs_root: Path, successor_run_id: str) -> Path:
    """Allow resume only for the final Run created after both failed Runs."""

    approval_hash = rerun_successor_approval_hash()
    if approval_hash is not None:
        return _require_approved_rerun_resume_state(runs_root, successor_run_id, approval_hash)

    predecessor = validate_failed_predecessor(runs_root)
    failed_successor = validate_failed_cr028_successor(runs_root)
    successor = runs_root / successor_run_id
    if (
        successor in {predecessor, failed_successor}
        or successor.is_symlink()
        or not successor.is_dir()
    ):
        raise ValueError("CR-2026-030 final successor resume target is missing or unsafe")
    if set(_t15_runs(runs_root)) != {predecessor, failed_successor, successor}:
        raise ValueError("CR-2026-030 final successor chain count drift")
    return failed_successor
