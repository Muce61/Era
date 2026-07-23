from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import invalidate_stage2_v2_cr016_preflight_run as cli

H = "a" * 64
AUTHORITY_ID = "stage2-g1-v2-authority-20260720T170000Z-final"
REPLACEMENT_ID = "stage2-g1-v2-b-20260720T170000Z-final"
COMMIT = "b" * 40


def _run(tmp_path: Path) -> Path:
    root = tmp_path / "runs" / cli.PREFLIGHT_RUN_ID
    for name in ("manifests", "reports", "staging", "published"):
        (root / name).mkdir(parents=True, exist_ok=True)
    checkpoint = {
        "run_id": cli.PREFLIGHT_RUN_ID,
        "status": "PREFLIGHT_PASSED",
        "phase": "PREFLIGHT",
        "revision": 0,
        "completed_tasks": [],
        "active_task": None,
        "failure": None,
        "resource_pause": None,
    }
    (root / "checkpoint-v2.json").write_text(json.dumps(checkpoint), encoding="utf-8")
    for index in range(3):
        (root / "manifests" / f"{index}.json").write_text(
            json.dumps({"sha256": H, "index": index}), encoding="utf-8"
        )
    return root


def _args() -> list[str]:
    return [
        "--preflight-run-id",
        cli.PREFLIGHT_RUN_ID,
        "--replacement-authority-run-id",
        AUTHORITY_ID,
        "--replacement-run-id",
        REPLACEMENT_ID,
        "--code-commit",
        COMMIT,
    ]


def test_preflight_run_is_disabled_append_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _run(tmp_path)
    monkeypatch.setattr(cli, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(cli, "_git_head", lambda: COMMIT)

    assert cli.main(_args()) == 0
    report_path = root / "reports" / "disablement-cr-2026-016.json"
    first = report_path.read_bytes()
    report = json.loads(first)
    assert report["status"] == "INVALIDATED_PRECHECK_ONLY"
    assert report["resume_allowed"] is False
    assert report["reuse_allowed"] is False
    assert report["staging_files"] == 0
    assert report["published_files"] == 0
    assert cli.main(_args()) == 0
    assert report_path.read_bytes() == first


def test_disablement_fails_if_staging_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _run(tmp_path)
    (root / "staging" / "unexpected.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(cli, "_git_head", lambda: COMMIT)

    with pytest.raises(ValueError, match="evidence matrix changed"):
        cli.main(_args())
