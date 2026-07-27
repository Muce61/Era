from __future__ import annotations

import json
import shutil
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from era100x.research.stage_2.baselines.placebo.contracts import (
    RELAXATION_LEVELS,
    S2P14T17Authority,
    canonical_hash,
)
from era100x.research.stage_2.baselines.placebo.governance import T16Binding
from era100x.research.stage_2.baselines.placebo.runner import (
    MATCH_SCHEMA,
    SUMMARY_SCHEMA,
    _catalog,
    _validate_formal_prefix,
    produce_blind_selections,
    verify_run,
)


def _write(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    )
    return path


def _binding(tmp_path: Path) -> T16Binding:
    return T16Binding(
        receipt_path=tmp_path / "receipt.json",
        receipt_hash="1" * 64,
        artifact_manifest_hash="2" * 64,
        artifact_catalog_hash="3" * 64,
        authority_hash="4" * 64,
        binning_hash="5" * 64,
        snapshot_id="6" * 64,
        verify_hash="7" * 64,
        snapshot_root=tmp_path / "snapshot",
        binning_root=tmp_path / "bins",
        prepared_episodes_path=tmp_path / "episodes.parquet",
        selections_root=tmp_path / "selections",
        outcome_path=tmp_path / "outcomes.parquet",
        match_path=tmp_path / "matches.parquet",
        summary_path=tmp_path / "summary.parquet",
        counts={
            "eligible": 11,
            "matched": 10,
            "unmatched": 1,
            "controls": 30,
            "summaries": 30,
            "groups": 1,
        },
    )


def test_resume_accepts_only_a_hash_valid_outcome_blind_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "blind"
    seal = {
        "schema_name": "s2p14-t17-blind-selection-seal",
        "schema_version": "1.0",
        "source_t16_verify_hash": "7" * 64,
        "group_count": 456,
        "placebo_slot_count": 413827,
        "source_unmatched_not_sampled": 10,
        "selection_set_hash": "8" * 64,
        "outcome_fields_read": [],
        "status": "SEALED",
    }
    seal["seal_hash"] = canonical_hash(seal)
    _write(root / "selection-seal.json", seal)
    monkeypatch.setattr(
        "era100x.research.stage_2.baselines.placebo.runner._selection_files",
        lambda _root: (_ for _ in ()).throw(AssertionError("must not recompute sealed prefix")),
    )
    assert (
        produce_blind_selections(binding=_binding(tmp_path), output_root=root)["seal_hash"]
        == seal["seal_hash"]
    )
    seal["outcome_fields_read"] = ["outcomes_json"]
    _write(root / "selection-seal.json", seal)
    with pytest.raises(ValueError, match="seal is invalid"):
        produce_blind_selections(binding=_binding(tmp_path), output_root=root)


def test_verify_recomputes_catalog_and_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("era100x.research.stage_2.baselines.placebo.runner.EXPECTED_GROUPS", 1)
    monkeypatch.setattr("era100x.research.stage_2.baselines.placebo.runner.EXPECTED_SUMMARIES", 1)
    run_root = tmp_path / "stage2-s2p14-t17-fixture"
    work = tmp_path / "work"
    match_path = work / "results/matches/BTCUSDT/P1/F0/G1-PRIMARY-V1__T2.parquet"
    match_path.parent.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_episode_id": "1" * 64,
                    "status": "MATCHED",
                    "placebo_event_candidate_id": "2" * 64,
                    "placebo_control_candidate_ids": ["3" * 64] * 5,
                    "output_hash": "4" * 64,
                    "matrix_json": "{}",
                }
            ],
            schema=MATCH_SCHEMA,
        ),
        match_path,
    )
    summary_path = work / "results/descriptive_summaries.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "instrument": "BTCUSDT",
                    "pre_registered_period": "P1",
                    "evaluation_fold": "F0",
                    "parameter_set_id": "G1-PRIMARY-V1",
                    "time_combination_id": "T2",
                    "combination_id": "target=20|stop=15",
                    "slot_count": 1,
                    "matched_count": 1,
                    "unmatched_count": 0,
                    "placebo_event_rate": "0",
                    "placebo_baseline_rate": "0",
                    "placebo_delta": "0",
                    "real_event_delta": "0",
                    "placebo_minus_real_delta": "0",
                    "research_status": "DESCRIPTIVE_ONLY_CLUSTERING_BOOTSTRAP_PENDING",
                }
            ],
            schema=SUMMARY_SCHEMA,
        ),
        summary_path,
    )
    reconciliation = {
        "schema_name": "s2p14-t17-reconciliation",
        "source_matched_slots": 1,
        "placebo_matched": 1,
        "placebo_unmatched": 0,
        "group_count": 1,
        "summary_row_count": 1,
        "status": "PASS",
    }
    reconciliation["reconciliation_hash"] = canonical_hash(reconciliation)
    _write(work / "results/reconciliation.json", reconciliation)
    catalog = _catalog(work)
    snapshot = run_root / "published/snapshots" / str(catalog["catalog_hash"])
    shutil.copytree(work, snapshot)
    _write(snapshot / "catalog.json", catalog)
    manifest = {
        "schema_name": "s2p14-t17-manifest",
        "run_id": run_root.name,
        "snapshot_id": snapshot.name,
        "catalog_hash": catalog["catalog_hash"],
        "source_t16_verify_hash": "7" * 64,
        "stage3_locked": True,
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    _write(snapshot / "manifest.json", manifest)

    result = verify_run(run_root, binding=_binding(tmp_path))
    assert result["status"] == "PASS"
    assert result["placebo_slot_count"] == 1

    match_path = snapshot / match_path.relative_to(work)
    match_path.write_bytes(match_path.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="Hash drift"):
        verify_run(run_root, binding=_binding(tmp_path))


def test_successor_requires_exactly_one_approved_authority_only_prefix(tmp_path: Path) -> None:
    authority = S2P14T17Authority.seal(
        {
            "code_commit": "1" * 40,
            "policy_hash": "2" * 64,
            "approval_hash": "3" * 64,
            "preregistration_hash": "4" * 64,
            "source_t16_receipt_hash": "5" * 64,
            "source_t16_authority_hash": "6" * 64,
            "source_t16_binning_hash": "7" * 64,
            "source_t16_manifest_hash": "8" * 64,
            "source_t16_catalog_hash": "9" * 64,
            "source_t16_snapshot_id": "a" * 64,
            "source_t16_verify_hash": "b" * 64,
            "source_counts_hash": "c" * 64,
            "exact_fields": ("instrument", "evaluation_fold"),
            "relaxation_order": RELAXATION_LEVELS,
        }
    )
    authority_path = tmp_path / f"authority-{authority.authority_hash}.json"
    authority_path.write_text(authority.model_dump_json())
    approval = {"supersedes_authority_hash": authority.authority_hash}

    _validate_formal_prefix(
        existing_authorities=(authority_path,),
        existing_runs=(),
        approval=approval,
    )

    with pytest.raises(ValueError, match="Hash does not match"):
        _validate_formal_prefix(
            existing_authorities=(authority_path,),
            existing_runs=(),
            approval={"supersedes_authority_hash": "d" * 64},
        )
    with pytest.raises(ValueError, match="Run already exists"):
        _validate_formal_prefix(
            existing_authorities=(authority_path,),
            existing_runs=(tmp_path / "stage2-s2p14-t17-existing",),
            approval=approval,
        )
