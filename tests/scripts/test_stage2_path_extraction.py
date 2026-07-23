from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from era100x.research.stage_2.paths.extraction.full_run import (
    EPISODE_SCHEMA,
    H1_SLICE_SCHEMA,
    H2_SLICE_SCHEMA,
    QUALITY_SCHEMA,
    H2RowGroup,
    _json_hash,
    read_preflight_manifest,
    resume_run,
    select_h2_row_groups,
)


def group(ordinal: int, start: int, end: int) -> H2RowGroup:
    return H2RowGroup(
        owner_date=date(2026, 7, 1),
        source_relative_path="BTCUSDT/date=2026-07-01/part-000.parquet",
        source_byte_sha256="1" * 64,
        source_logical_sha256="2" * 64,
        ordinal=ordinal,
        row_count=10,
        start_ns=start,
        end_ns=end,
    )


def test_h2_row_group_selection_is_left_closed_right_open() -> None:
    groups = (group(0, 0, 10), group(1, 10, 20), group(2, 20, 30))

    assert [item.ordinal for item in select_h2_row_groups(groups, 10, 20)] == [1]
    assert [item.ordinal for item in select_h2_row_groups(groups, 9, 21)] == [0, 1, 2]
    assert select_h2_row_groups(groups, 30, 40) == ()


def test_formal_schemas_are_path_only_and_preserve_h2_identity_order() -> None:
    all_fields = {
        *EPISODE_SCHEMA.names,
        *H1_SLICE_SCHEMA.names,
        *H2_SLICE_SCHEMA.names,
        *QUALITY_SCHEMA.names,
    }
    assert not {"mfe", "mae", "first_passage", "return", "pnl"}.intersection(all_fields)
    assert {"fact_identity", "stable_order", "source_byte_sha256"}.issubset(H2_SLICE_SCHEMA.names)
    assert "source_semantic_sha256" in H1_SLICE_SCHEMA.names


def test_preflight_authority_is_hash_bound_and_symlinks_fail_closed(tmp_path: Path) -> None:
    payload = {
        "schema_name": "stage2-s2t11-preflight-authority",
        "task_version": "1.3",
        "source": {"snapshot_id": "fixed"},
    }
    payload["authority_hash"] = _json_hash(payload)
    path = tmp_path / "authority.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert read_preflight_manifest(path) == payload

    tampered = {**payload, "source": {"snapshot_id": "changed"}}
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="authority hash"):
        read_preflight_manifest(path)

    target = tmp_path / "target.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="unsafe"):
        read_preflight_manifest(link)


def test_resume_never_reopens_a_completed_run(tmp_path: Path) -> None:
    run_root = tmp_path / "stage2-s2t11-paths-complete"
    (run_root / "reports").mkdir(parents=True)
    (run_root / "reports/completion.json").write_text("{}", encoding="utf-8")

    with pytest.raises((FileNotFoundError, ValueError)):
        resume_run(run_root)


def test_cli_freezes_exact_four_modes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/run_stage2_path_extraction.py", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "{preflight,run,resume,verify}" in result.stdout
