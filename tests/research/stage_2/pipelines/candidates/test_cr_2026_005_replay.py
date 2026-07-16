from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parents[5] / "scripts" / "replay_stage2_cr_2026_005.py"
SPEC = importlib.util.spec_from_file_location("replay_stage2_cr_2026_005", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)


def _result(logical_hash: str = "a" * 64) -> dict[str, object]:
    return {
        "target_days": ["2020-04-27", "2020-04-28"],
        "daily": {},
        "counts": {"candidate_attempts": 2},
        "candidate_id_set_hash": "b" * 64,
        "candidate_payload_set_hash": "c" * 64,
        "candidate_attempt_count": 2,
        "candidate_id_count": 2,
        "identity_conflict_count": 0,
        "exact_duplicate_excluded_count": 0,
        "selected_original_conflicts": {},
        "replay_logical_hash": logical_hash,
    }


def test_diagnostic_evidence_is_append_only_and_never_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(replay, "_assert_frozen_inputs", lambda *_args: {"baseline": "valid"})
    monkeypatch.setattr(replay, "_replay", lambda *_args: _result())
    output = tmp_path / "diagnostic"

    result = replay.create_evidence(
        stage2_root=tmp_path / "stage2",
        output_root=output,
        code_commit="a" * 40,
    )

    assert result["status"] == "PASS"
    assert result["dual_replay_match"] is True
    assert not (output / "published" / "data").exists()
    assert len(list((output / "manifests").glob("*.json"))) == 1
    with pytest.raises(FileExistsError, match="append-only"):
        replay.create_evidence(
            stage2_root=tmp_path / "stage2",
            output_root=output,
            code_commit="a" * 40,
        )


def test_diagnostic_rejects_replay_mismatch_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(replay, "_assert_frozen_inputs", lambda *_args: {"baseline": "valid"})
    results = iter((_result(), _result("d" * 64)))
    monkeypatch.setattr(replay, "_replay", lambda *_args: next(results))
    output = tmp_path / "diagnostic"

    with pytest.raises(ValueError, match="not deterministic"):
        replay.create_evidence(
            stage2_root=tmp_path / "stage2",
            output_root=output,
            code_commit="a" * 40,
        )

    assert not output.exists()
