from __future__ import annotations

import json
from pathlib import Path

import pytest

from era100x.research.stage_2.baselines.conditional import successor_policy
from era100x.research.stage_2.baselines.conditional.successor_policy import (
    FAILED_CR028_SUCCESSOR_AUTHORITY_HASH,
    FAILED_CR028_SUCCESSOR_BINNING_SET_HASH,
    FAILED_CR028_SUCCESSOR_FAILURE_CODE,
    FAILED_CR028_SUCCESSOR_RUN_ID,
    FAILED_PREDECESSOR_AUTHORITY_HASH,
    FAILED_PREDECESSOR_BINNING_SET_HASH,
    FAILED_PREDECESSOR_FAILURE_CODE,
    FAILED_PREDECESSOR_RUN_ID,
    require_final_successor_creation_state,
    require_final_successor_resume_state,
)


@pytest.fixture(autouse=True)
def _isolate_legacy_successor_policy_logic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the frozen CR-030 policy separately from the current-state gate."""

    monkeypatch.setattr(successor_policy, "require_operation_allowed", lambda operation: None)


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


def _write_failed_cr028_successor(runs_root: Path) -> Path:
    run_root = runs_root / FAILED_CR028_SUCCESSOR_RUN_ID
    run_root.mkdir(parents=True)
    checkpoint = {
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
    }
    (run_root / "checkpoint.json").write_text(
        json.dumps(checkpoint, sort_keys=True), encoding="utf-8"
    )
    return run_root


def test_successor_policy_allows_only_one_final_creation_and_resume(tmp_path: Path) -> None:
    predecessor = _write_failed_predecessor(tmp_path)
    failed_successor = _write_failed_cr028_successor(tmp_path)
    assert predecessor != failed_successor
    assert require_final_successor_creation_state(tmp_path) == failed_successor

    successor = tmp_path / "stage2-s2t15-conditional-20260722T120000Z-aaaaaaaaaaaa"
    successor.mkdir()
    assert require_final_successor_resume_state(tmp_path, successor.name) == failed_successor

    extra = tmp_path / "stage2-s2t15-conditional-20260722T120001Z-bbbbbbbbbbbb"
    extra.mkdir()
    with pytest.raises(ValueError, match="chain count drift"):
        require_final_successor_resume_state(tmp_path, successor.name)


def test_successor_policy_rejects_nonterminal_or_published_predecessor(tmp_path: Path) -> None:
    predecessor = _write_failed_predecessor(tmp_path)
    _write_failed_cr028_successor(tmp_path)
    checkpoint_path = predecessor / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_bytes())
    checkpoint["resume_allowed"] = True
    checkpoint_path.write_text(json.dumps(checkpoint, sort_keys=True), encoding="utf-8")
    with pytest.raises(ValueError, match="checkpoint binding drift"):
        require_final_successor_creation_state(tmp_path)

    checkpoint["resume_allowed"] = False
    checkpoint_path.write_text(json.dumps(checkpoint, sort_keys=True), encoding="utf-8")
    (predecessor / "published").mkdir()
    with pytest.raises(ValueError, match="published output"):
        require_final_successor_creation_state(tmp_path)


def test_successor_policy_rejects_tampered_failed_cr028_successor(tmp_path: Path) -> None:
    _write_failed_predecessor(tmp_path)
    failed_successor = _write_failed_cr028_successor(tmp_path)
    checkpoint_path = failed_successor / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_bytes())
    checkpoint["completed_group_count"] = 455
    checkpoint_path.write_text(json.dumps(checkpoint, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="checkpoint binding drift"):
        require_final_successor_creation_state(tmp_path)
