from __future__ import annotations

import json
from pathlib import Path

import pytest

from era100x.research.stage_2.runtime_v2.orchestrator import RuntimeComparison
from scripts import run_stage2_compare_only_cr019 as cli


def test_parser_exposes_only_authorize_and_compare() -> None:
    for action in ("authorize", "compare"):
        assert cli.parser().parse_args([action]).action == action

    for forbidden in ("release", "verify", "resume", "repack"):
        with pytest.raises(SystemExit):
            cli.parser().parse_args([forbidden])


def test_authorize_is_append_only_and_disables_every_non_compare_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / cli.TARGET_RUN_ID
    target.mkdir()
    compare_commit = "1" * 40
    compare_tree = "2" * 64
    publication = {
        "published_catalog_sha256": cli.EXPECTED_PUBLISHED_CATALOG_SHA256,
        "publication_record_sha256": cli.EXPECTED_PUBLICATION_RECORD_SHA256,
        "quality_report_sha256": cli.EXPECTED_QUALITY_REPORT_SHA256,
    }
    monkeypatch.setattr(cli, "RUNS_ROOT", tmp_path)
    monkeypatch.setattr(
        cli,
        "_assert_compare_code_authority",
        lambda *, require_clean: (compare_commit, compare_tree),
    )
    monkeypatch.setattr(
        cli,
        "_validate_target_run",
        lambda: {
            "checkpoint_sha256": "3" * 64,
            "sealed_input_set_sha256": cli.EXPECTED_INPUT_SET_SHA256,
        },
    )
    monkeypatch.setattr(cli, "_validate_published_state", lambda: publication)
    monkeypatch.setattr(cli, "_validate_release_evidence", lambda: None)
    monkeypatch.setattr(cli, "_require_no_comparison", lambda: None)

    first = cli._authorize()
    path = Path(first["amendment_path"])
    first_bytes = path.read_bytes()
    second = cli._authorize()

    assert first == second
    assert path.read_bytes() == first_bytes
    amendment = json.loads(first_bytes)
    assert amendment["allowed_commands"] == ["compare"]
    for field in (
        "generation_allowed",
        "release_allowed",
        "verification_allowed",
        "resume_allowed",
        "repacking_allowed",
        "adoption_allowed",
        "successor_creation_allowed",
        "input_mutation_allowed",
        "delete_allowed",
    ):
        assert amendment[field] is False


def test_validate_comparison_requires_exact_full_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / cli.TARGET_RUN_ID
    report_path = target / "reports/v2-run-a-comparison.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "report": {
                    "status": "PASS",
                    "matched_partition_count": cli.EXPECTED_GROUP1_PARTITIONS,
                    "missing_in_v2": [],
                    "extra_in_v2": [],
                    "differences": [],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "RUNS_ROOT", tmp_path)
    result = RuntimeComparison(
        snapshot_id="4" * 64,
        manifest_hash="5" * 64,
        matched_partition_count=cli.EXPECTED_GROUP1_PARTITIONS,
        difference_count=0,
        comparison_sha256="6" * 64,
    )

    cli._validate_comparison_result(result)


def test_write_once_rejects_changed_authority(tmp_path: Path) -> None:
    path = tmp_path / "authority.json"
    cli._write_once(path, {"status": "AUTHORIZED_COMPARE_ONLY"})

    with pytest.raises(FileExistsError, match="append-only"):
        cli._write_once(path, {"status": "FAILED"})
