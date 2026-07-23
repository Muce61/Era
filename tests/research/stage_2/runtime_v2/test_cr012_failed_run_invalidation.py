from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import invalidate_stage2_v2_cr012_failed_run as module


def _fixture(tmp_path: Path) -> tuple[Path, bytes]:
    failed = tmp_path / "runs" / module.FAILED_RUN_ID
    report = failed / "reports/failure.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        json.dumps({"publication_status": "FAILED_UNPUBLISHED", "task_id": module.EXPECTED_TASK})
    )
    checkpoint = failed / "checkpoint-v2.json"
    checkpoint.write_text(
        json.dumps(
            {
                "status": "FAILED_UNPUBLISHED",
                "completed_tasks": [],
                "active_task": None,
                "failure": {
                    "task_id": module.EXPECTED_TASK,
                    "reason": "lifetime peak fixture",
                    "report_relative_path": "reports/failure.json",
                },
            }
        )
    )
    for ordinal in range(module.EXPECTED_MONTHLY):
        path = failed / "staging/foundation/checkpoints" / f"{ordinal}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
    for ordinal in range(module.EXPECTED_PACKED):
        path = failed / "staging/foundation/packed-checkpoints" / f"{ordinal}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
    (failed / "manifests").mkdir()
    (failed / "manifests/runtime.json").write_text("{}")
    return failed, checkpoint.read_bytes()


def test_cr012_invalidation_preserves_staging_and_is_write_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failed, checkpoint_bytes = _fixture(tmp_path)
    commit = "a" * 40
    monkeypatch.setattr(module, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(Path, "is_mount", lambda _path: True)
    monkeypatch.setattr(module.subprocess, "check_output", lambda *_a, **_k: f"{commit}\n")
    argv = [
        "--failed-run-id",
        module.FAILED_RUN_ID,
        "--replacement-authority-run-id",
        "stage2-g1-v2-authority-new",
        "--replacement-run-id",
        "stage2-g1-v2-b-new",
        "--code-commit",
        commit,
    ]

    assert module.main(argv) == 0
    receipt = failed / "reports/invalidation-cr-2026-012.json"
    first = receipt.read_bytes()
    assert module.main(argv) == 0
    payload = json.loads(first)

    assert receipt.read_bytes() == first
    assert (failed / "checkpoint-v2.json").read_bytes() == checkpoint_bytes
    assert payload["monthly_checkpoint_count"] == module.EXPECTED_MONTHLY
    assert payload["packed_checkpoint_count"] == module.EXPECTED_PACKED
    assert payload["retained_staging_file_count"] > 0
    assert payload["reuse_allowed"] is False


def test_cr012_invalidation_rejects_missing_packed_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failed, _checkpoint = _fixture(tmp_path)
    next((failed / "staging/foundation/packed-checkpoints").glob("*.json")).unlink()
    commit = "a" * 40
    monkeypatch.setattr(module, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(Path, "is_mount", lambda _path: True)
    monkeypatch.setattr(module.subprocess, "check_output", lambda *_a, **_k: f"{commit}\n")

    with pytest.raises(ValueError, match="retained-evidence matrix"):
        module.main(
            [
                "--failed-run-id",
                module.FAILED_RUN_ID,
                "--replacement-authority-run-id",
                "stage2-g1-v2-authority-new",
                "--replacement-run-id",
                "stage2-g1-v2-b-new",
                "--code-commit",
                commit,
            ]
        )
