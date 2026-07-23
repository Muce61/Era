from __future__ import annotations

import json
from pathlib import Path

import pytest

from era100x.research.stage_2.runtime_v2.group1_packing_recovery import (
    Group1MonthlyAdoptionManifestV1,
)
from era100x.research.stage_2.runtime_v2.progress import PipelineProgressV1
from scripts import invalidate_stage2_v2_cr017_failed_release_run as cli

H = "a" * 64
COMMIT = "b" * 40
AUTHORITY_ID = "stage2-g1-v2-authority-20260720T220000Z-final"
REPLACEMENT_ID = "stage2-g1-v2-b-20260720T220000Z-final"


def _write(path: Path, content: str = "{}") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run(tmp_path: Path) -> Path:
    root = tmp_path / "runs" / cli.FAILED_RELEASE_RUN_ID
    checkpoint = {
        "run_id": cli.FAILED_RELEASE_RUN_ID,
        "status": "GROUP1_COMPLETE",
        "phase": "GROUP1",
        "revision": cli.EXPECTED_REVISION,
        "completed_tasks": [{"task_id": item} for item in cli.EXPECTED_TASKS],
        "active_task": None,
        "failure": None,
        "resource_pause": None,
    }
    _write(root / "checkpoint-v2.json", json.dumps(checkpoint))
    progress = PipelineProgressV1.seal(
        {
            "run_id": cli.FAILED_RELEASE_RUN_ID,
            "subflows": (
                {
                    "name": "RELEASE",
                    "status": "FAILED",
                    "message": "catalog object/seal summaries crossed the obsolete limit",
                },
            ),
            "updated_at": "2026-07-20T22:00:00Z",
        }
    )
    _write(root / "logs/pipeline-progress-v1.json", progress.model_dump_json())
    adoption = Group1MonthlyAdoptionManifestV1.seal(
        {
            "source_run_id": "stage2-g1-v2-b-source",
            "destination_run_id": cli.FAILED_RELEASE_RUN_ID,
            "source_snapshot_id": H,
            "destination_snapshot_id": H,
            "source_manifest_hash": H,
            "destination_manifest_hash": H,
            "stage1_data_run_id": "stage1-fixture",
            "config_sha256": H,
            "source_checkpoint_sha256": H,
            "source_failure_sha256": H,
            "adopted_files": (),
            "excluded_prefixes": (),
            "adopted_file_count": 0,
            "adopted_byte_count": 0,
        }
    )
    _write(
        root / "manifests" / f"group1-monthly-adoption-{adoption.manifest_hash}.json",
        adoption.model_dump_json(),
    )
    for index in range(len(cli.EXPECTED_TASKS)):
        _write(root / "staging/backend-evidence" / f"{index}.json")
        _write(root / "staging/receipts" / f"{index}.json")
    for index in range(cli.EXPECTED_COMPONENTS):
        _write(root / "staging/evidence/group1-components" / f"{index}.json")
    for index in range(cli.EXPECTED_PACKED_SEALS):
        _write(root / "staging/group1/packed-seals" / f"{index}.json")
    (root / "staging/group1/partials").mkdir(parents=True, exist_ok=True)
    (root / "published").mkdir(parents=True, exist_ok=True)
    return root


def _args() -> list[str]:
    return [
        "--failed-run-id",
        cli.FAILED_RELEASE_RUN_ID,
        "--replacement-authority-run-id",
        AUTHORITY_ID,
        "--replacement-run-id",
        REPLACEMENT_ID,
        "--code-commit",
        COMMIT,
    ]


def _fixture_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "EXPECTED_ADOPTED_FILES", 0)
    monkeypatch.setattr(cli, "EXPECTED_ADOPTED_BYTES", 0)


def test_failed_release_run_is_disabled_append_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _run(tmp_path)
    monkeypatch.setattr(cli, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(cli, "_git_head", lambda: COMMIT)
    _fixture_counts(monkeypatch)

    assert cli.main(_args()) == 0
    report_path = root / "reports/disablement-cr-2026-017.json"
    first = report_path.read_bytes()
    report = json.loads(first)
    assert report["status"] == "INVALIDATED_RELEASE_FAILED_UNPUBLISHED"
    assert report["resume_allowed"] is False
    assert report["reuse_allowed"] is False
    assert report["delete_allowed"] is False
    assert cli.main(_args()) == 0
    assert report_path.read_bytes() == first


def test_disablement_fails_if_publication_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _run(tmp_path)
    _write(root / "published/unexpected.json")
    monkeypatch.setattr(cli, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(cli, "_git_head", lambda: COMMIT)
    _fixture_counts(monkeypatch)

    with pytest.raises(ValueError, match="evidence matrix changed"):
        cli.main(_args())
