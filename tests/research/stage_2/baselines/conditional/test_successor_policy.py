from __future__ import annotations

import json
from pathlib import Path

import pytest

from era100x.research.stage_2.baselines.conditional.successor_policy import (
    FAILED_PREDECESSOR_AUTHORITY_HASH,
    FAILED_PREDECESSOR_BINNING_SET_HASH,
    FAILED_PREDECESSOR_FAILURE_CODE,
    FAILED_PREDECESSOR_RUN_ID,
    require_single_successor_creation_state,
    require_single_successor_resume_state,
)


def _write_failed_predecessor(runs_root: Path) -> Path:
    run_root = runs_root / FAILED_PREDECESSOR_RUN_ID
    run_root.mkdir(parents=True)
    checkpoint = {
        "run_id": FAILED_PREDECESSOR_RUN_ID,
        "authority_hash": FAILED_PREDECESSOR_AUTHORITY_HASH,
        "binning_set_hash": FAILED_PREDECESSOR_BINNING_SET_HASH,
        "status": "FAILED_UNPUBLISHED",
        "phase": "FAILED",
        "failure_code": FAILED_PREDECESSOR_FAILURE_CODE,
        "published": False,
        "resume_allowed": False,
    }
    (run_root / "checkpoint.json").write_text(
        json.dumps(checkpoint, sort_keys=True), encoding="utf-8"
    )
    return run_root


def test_successor_policy_allows_only_one_creation_and_one_resume(tmp_path: Path) -> None:
    predecessor = _write_failed_predecessor(tmp_path)
    assert require_single_successor_creation_state(tmp_path) == predecessor

    successor = tmp_path / "stage2-s2t15-conditional-20260722T120000Z-aaaaaaaaaaaa"
    successor.mkdir()
    assert require_single_successor_resume_state(tmp_path, successor.name) == predecessor

    extra = tmp_path / "stage2-s2t15-conditional-20260722T120001Z-bbbbbbbbbbbb"
    extra.mkdir()
    with pytest.raises(ValueError, match="chain count drift"):
        require_single_successor_resume_state(tmp_path, successor.name)


def test_successor_policy_rejects_nonterminal_or_published_predecessor(tmp_path: Path) -> None:
    predecessor = _write_failed_predecessor(tmp_path)
    checkpoint_path = predecessor / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_bytes())
    checkpoint["resume_allowed"] = True
    checkpoint_path.write_text(json.dumps(checkpoint, sort_keys=True), encoding="utf-8")
    with pytest.raises(ValueError, match="checkpoint binding drift"):
        require_single_successor_creation_state(tmp_path)

    checkpoint["resume_allowed"] = False
    checkpoint_path.write_text(json.dumps(checkpoint, sort_keys=True), encoding="utf-8")
    (predecessor / "published").mkdir()
    with pytest.raises(ValueError, match="published output"):
        require_single_successor_creation_state(tmp_path)
