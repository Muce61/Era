from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import invalidate_stage2_v2_failed_run as module


def test_failed_run_invalidation_is_write_once_and_does_not_mutate_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "runs"
    failed = runs / module.FAILED_RUN_ID
    report = failed / "reports" / "failure-foundation-btcusdt-r2.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        json.dumps(
            {
                "publication_status": "FAILED_UNPUBLISHED",
                "task_id": module.EXPECTED_FAILURE_TASK,
            }
        ),
        encoding="utf-8",
    )
    checkpoint = failed / "checkpoint-v2.json"
    checkpoint.write_text(
        json.dumps(
            {
                "status": "FAILED_UNPUBLISHED",
                "completed_tasks": [],
                "active_task": None,
                "failure": {
                    "task_id": module.EXPECTED_FAILURE_TASK,
                    "reason": "fixture memory gate",
                    "report_relative_path": "reports/failure-foundation-btcusdt-r2.json",
                },
            }
        ),
        encoding="utf-8",
    )
    (failed / "manifests").mkdir()
    (failed / "manifests" / "runtime.json").write_text("{}\n", encoding="utf-8")
    original_checkpoint = checkpoint.read_bytes()
    commit = "a" * 40
    monkeypatch.setattr(module, "RUNS_ROOT", runs)
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
    receipt_path = failed / "reports" / "invalidation-cr-2026-011.json"
    receipt_bytes = receipt_path.read_bytes()
    assert module.main(argv) == 0
    receipt = json.loads(receipt_bytes)

    assert receipt_path.read_bytes() == receipt_bytes
    assert checkpoint.read_bytes() == original_checkpoint
    assert receipt["status"] == "INVALIDATED"
    assert receipt["prior_status"] == "FAILED_UNPUBLISHED"
    assert receipt["resume_allowed"] is False
    assert receipt["reuse_allowed"] is False
    assert receipt["staging_files"] == receipt["published_files"] == 0


def test_failed_run_with_formal_staging_cannot_be_invalidated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "runs"
    failed = runs / module.FAILED_RUN_ID
    report = failed / "reports" / "failure.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        json.dumps(
            {
                "publication_status": "FAILED_UNPUBLISHED",
                "task_id": module.EXPECTED_FAILURE_TASK,
            }
        ),
        encoding="utf-8",
    )
    (failed / "checkpoint-v2.json").write_text(
        json.dumps(
            {
                "status": "FAILED_UNPUBLISHED",
                "completed_tasks": [],
                "active_task": None,
                "failure": {
                    "task_id": module.EXPECTED_FAILURE_TASK,
                    "reason": "fixture",
                    "report_relative_path": "reports/failure.json",
                },
            }
        ),
        encoding="utf-8",
    )
    staging = failed / "staging" / "object.parquet"
    staging.parent.mkdir()
    staging.write_bytes(b"not reusable")
    commit = "a" * 40
    monkeypatch.setattr(module, "RUNS_ROOT", runs)
    monkeypatch.setattr(Path, "is_mount", lambda _path: True)
    monkeypatch.setattr(module.subprocess, "check_output", lambda *_a, **_k: f"{commit}\n")

    with pytest.raises(ValueError, match="reusable or published"):
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
