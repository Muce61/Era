from __future__ import annotations

import hashlib
import fcntl
import json
import os
from pathlib import Path

import pytest

from scripts import run_stage2_release_only_cr018 as cli


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def test_parser_exposes_only_release_only_commands() -> None:
    for action in ("authorize", "preflight", "release", "verify", "compare"):
        assert cli.parser().parse_args([action]).action == action

    with pytest.raises(SystemExit):
        cli.parser().parse_args(["resume"])
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["release", "--run-id", "another-run"])


def test_execute_rejects_generation_command_before_reading_external_state() -> None:
    with pytest.raises(ValueError, match="not allowed"):
        cli._execute("resume")


def test_authorize_is_append_only_and_disables_resume_repack_and_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / cli.TARGET_RUN_ID
    superseded = tmp_path / cli.SUPERSEDED_RUN_ID
    authority = tmp_path / cli.AUTHORITY_RUN_ID
    for root in (target, superseded, authority):
        root.mkdir()
    disablement = target / "reports/disablement-cr-2026-017.json"
    _write_json(
        disablement,
        {"resume_allowed": False, "reuse_allowed": False, "delete_allowed": False},
    )
    disablement_hash = hashlib.sha256(disablement.read_bytes()).hexdigest()
    target_checkpoint = "1" * 64
    superseded_checkpoint = "2" * 64
    release_commit = "3" * 40
    release_tree = "4" * 64
    monkeypatch.setattr(cli, "RUNS_ROOT", tmp_path)
    monkeypatch.setattr(cli, "EXPECTED_DISABLEMENT_SHA256", disablement_hash)
    monkeypatch.setattr(
        cli,
        "_assert_release_code_authority",
        lambda *, require_clean: (release_commit, release_tree),
    )
    monkeypatch.setattr(
        cli,
        "_validate_target_run",
        lambda: {
            "checkpoint_sha256": target_checkpoint,
            "sealed_input_set_sha256": cli.EXPECTED_INPUT_SET_SHA256,
        },
    )
    monkeypatch.setattr(
        cli,
        "_validate_superseded_run",
        lambda: {"checkpoint_sha256": superseded_checkpoint},
    )

    first = cli._authorize()
    amendment_path = Path(first["amendment_path"])
    supersession_path = Path(first["supersession_path"])
    amendment_bytes = amendment_path.read_bytes()
    supersession_bytes = supersession_path.read_bytes()
    second = cli._authorize()

    assert first == second
    assert amendment_path.read_bytes() == amendment_bytes
    assert supersession_path.read_bytes() == supersession_bytes
    amendment = json.loads(amendment_bytes)
    supersession = json.loads(supersession_bytes)
    assert amendment["allowed_commands"] == ["release", "verify", "compare"]
    assert amendment["generation_allowed"] is False
    assert amendment["resume_allowed"] is False
    assert amendment["repacking_allowed"] is False
    assert amendment["input_mutation_allowed"] is False
    assert supersession["status"] == "SUPERSEDED_INCOMPLETE_NO_REUSE"
    assert supersession["resume_allowed"] is False
    assert supersession["reuse_allowed"] is False
    assert supersession["replacement_run_allowed"] is False


def test_write_once_rejects_changed_evidence(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    cli._write_once(path, {"status": "PASS"})

    with pytest.raises(FileExistsError, match="append-only"):
        cli._write_once(path, {"status": "FAILED"})


def test_run_idle_uses_runtime_v2_command_lock(tmp_path: Path) -> None:
    lock = tmp_path / "orchestration-v2.lock"
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="command is active"):
            cli._assert_run_idle(tmp_path)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
