from __future__ import annotations

import json
from pathlib import Path

import pytest

from era100x.research.stage_2.baselines.conditional import execution_run
from era100x.research.stage_2.baselines.conditional.binning_run import (
    freeze_binning_snapshots,
)
from era100x.research.stage_2.baselines.conditional.execution_run import (
    run_full_execution,
)
from era100x.research.stage_2.baselines.conditional.v14_contracts import (
    S2P13T16ContractAuthority,
    validate_contract_authority_json,
)


def _authority() -> S2P13T16ContractAuthority:
    return S2P13T16ContractAuthority.seal(
        {
            "code_commit": "1" * 40,
            "chain_authority_hash": "2" * 64,
            "policy_hash": "3" * 64,
            "source_t10_binding_hash": "4" * 64,
            "source_s2p13_t11_binding_hash": "5" * 64,
            "source_s2p13_t13_binding_hash": "6" * 64,
            "source_s2p13_t15_binding_hash": "7" * 64,
            "context_binding_hash": "8" * 64,
            "label_contract_hash": "9" * 64,
            "preregistration_hash": "a" * 64,
        }
    )


def _write_authority(path: Path) -> S2P13T16ContractAuthority:
    authority = _authority()
    path.write_text(authority.model_dump_json(), encoding="utf-8")
    return authority


def test_plan_v13_authority_round_trips_from_real_json_arrays() -> None:
    authority = _authority()
    encoded = authority.model_dump_json()
    decoded = json.loads(encoded)

    assert isinstance(decoded["feature_formula_ids"], list)
    assert isinstance(decoded["registered_parameter_timing_pairs"], list)
    assert validate_contract_authority_json(encoded) == authority


def test_bin_freeze_reads_plan_v13_authority_before_preparation(tmp_path: Path) -> None:
    authority_path = tmp_path / "authority.json"
    authority = _write_authority(authority_path)

    with pytest.raises(ValueError, match="clean Authority commit"):
        freeze_binning_snapshots(
            authority_path=authority_path,
            bin_root=tmp_path / "bins",
            t10_snapshot=tmp_path / "t10",
            t10_snapshot_id="unused",
            current_commit=authority.code_commit,
            repository_clean=False,
            lightweight_policy_authorized=True,
        )


def test_new_run_reads_plan_v13_authority_before_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority_path = tmp_path / "authority.json"
    authority = _write_authority(authority_path)
    monkeypatch.setattr(
        execution_run,
        "read_binning_set",
        lambda *_args, **_kwargs: {
            "authority_hash": authority.authority_hash,
            "binning_set_hash": "b" * 64,
            "code_commit": authority.code_commit,
        },
    )

    with pytest.raises(ValueError, match="clean Authority commit"):
        run_full_execution(
            authority_path=authority_path,
            binning_set_path=tmp_path / "bins.json",
            runs_root=tmp_path / "runs",
            t10_snapshot=tmp_path / "t10",
            t10_snapshot_id="unused",
            t13_snapshot=tmp_path / "t13",
            current_commit=authority.code_commit,
            repository_clean=False,
            lightweight_policy_authorized=True,
        )
    assert not (tmp_path / "runs").exists()


def test_resume_reads_stored_plan_v13_authority_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority_path = tmp_path / "authority.json"
    authority = _write_authority(authority_path)
    bins = {
        "authority_hash": authority.authority_hash,
        "binning_set_hash": "b" * 64,
        "code_commit": authority.code_commit,
    }
    monkeypatch.setattr(execution_run, "read_binning_set", lambda *_args, **_kwargs: bins)
    monkeypatch.setattr(
        execution_run,
        "require_final_successor_resume_state",
        lambda *_args, **_kwargs: Path("accepted-predecessor"),
    )

    run_id = f"stage2-s2p13-t16-20260725T000000Z-{authority.authority_hash[:12]}"
    run_root = tmp_path / "runs" / run_id
    manifests = run_root / "manifests"
    manifests.mkdir(parents=True)
    (manifests / "authority.json").write_text(authority.model_dump_json(), encoding="utf-8")
    (manifests / "binning-set.json").write_text(
        json.dumps({**bins, "drift": True}), encoding="utf-8"
    )
    (run_root / "checkpoint.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "authority_hash": authority.authority_hash,
                "binning_set_hash": bins["binning_set_hash"],
                "status": "IN_PROGRESS",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="resume Authority or binning evidence drift"):
        run_full_execution(
            authority_path=authority_path,
            binning_set_path=tmp_path / "bins.json",
            runs_root=tmp_path / "runs",
            t10_snapshot=tmp_path / "t10",
            t10_snapshot_id="unused",
            t13_snapshot=tmp_path / "t13",
            current_commit=authority.code_commit,
            repository_clean=True,
            resume_run_id=run_id,
        )
