from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).parents[2] / "scripts/run_stage2_first_passage.py"
SPEC = importlib.util.spec_from_file_location("run_stage2_first_passage", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_preflight_cli_reports_no_run_id(tmp_path: Path, monkeypatch, capsys) -> None:
    authority = {
        "authority_hash": "a" * 64,
        "expected_path_rows": 44,
        "expected_classification_count": 1320,
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
    assert result["expected_classification_count"] == 1320


def test_verify_cli_requires_explicit_run_id(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", [str(MODULE_PATH), "verify"])
    try:
        MODULE.main()
    except SystemExit as exc:
        assert str(exc) == "verify requires --run-id"
    else:
        raise AssertionError("verify unexpectedly accepted an implicit Run")
