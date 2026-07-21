from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[2] / "scripts/run_stage2_ambiguity_bounds.py"
SPEC = importlib.util.spec_from_file_location("run_stage2_ambiguity_bounds", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_preflight_cli_reports_no_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    authority = {
        "authority_hash": "a" * 64,
        "expected_classification_count": 1_320,
        "expected_distribution_count": 2_280,
    }
    authority_path = tmp_path / "authority.json"
    monkeypatch.setattr(MODULE, "current_code_commit", lambda: "abc123")
    monkeypatch.setattr(
        MODULE,
        "create_preflight_manifest",
        lambda **_kwargs: (authority, authority_path),
    )
    monkeypatch.setattr(sys, "argv", [str(MODULE_PATH), "preflight"])

    assert MODULE.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "PASS"
    assert result["run_id_created"] is False
    assert result["expected_classification_count"] == 1_320
    assert result["expected_distribution_count"] == 2_280


def test_run_and_resume_cli_forward_explicit_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    preflight = tmp_path / "authority.json"
    run_root = tmp_path / "runs" / "stage2-s2t14-ambiguity-bounds-test"
    monkeypatch.setattr(MODULE, "execute_run", lambda **kwargs: run_root)
    monkeypatch.setattr(
        sys,
        "argv",
        [str(MODULE_PATH), "run", "--preflight-manifest", str(preflight), "--run-id", "x"],
    )
    assert MODULE.main() == 0
    assert json.loads(capsys.readouterr().out)["run_root"] == str(run_root)

    monkeypatch.setattr(MODULE, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(MODULE, "resume_run", lambda selected: selected)
    monkeypatch.setattr(sys, "argv", [str(MODULE_PATH), "resume", "--run-id", run_root.name])
    assert MODULE.main() == 0
    assert json.loads(capsys.readouterr().out)["run_root"] == str(run_root)


def test_verify_cli_requires_explicit_run_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", [str(MODULE_PATH), "verify"])
    with pytest.raises(SystemExit, match="verify requires --run-id"):
        MODULE.main()


def test_verify_cli_fails_closed_on_invalid_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(MODULE, "RUNS_ROOT", tmp_path)
    monkeypatch.setattr(
        MODULE,
        "verify_run",
        lambda _path: {"status": "FAIL", "reason": "tampered output"},
    )
    monkeypatch.setattr(sys, "argv", [str(MODULE_PATH), "verify", "--run-id", "bad-run"])

    with pytest.raises(SystemExit, match="tampered output"):
        MODULE.main()
