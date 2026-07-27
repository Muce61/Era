from __future__ import annotations

import json
from pathlib import Path

import pytest

from era100x.research.stage_2.baselines.placebo.contracts import canonical_hash
from era100x.research.stage_2.baselines.placebo.governance import (
    EXPECTED_CHAIN,
    PlaceboPolicy,
    T16Binding,
    load_policy,
    validate_approval,
)


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    )
    return path


def _policy_file(tmp_path: Path) -> tuple[Path, Path]:
    repository = tmp_path / "repo"
    contracts = [
        "docs/spec/system_manual_v1.3.5_final.md",
        "docs/development/plans/stage_2_plan_v1.4.md",
        "docs/development/changes/CR-2026-046.md",
        "docs/development/decisions/ADR-S2-022-placebo-signal.md",
        "docs/development/tasks/stage_2/S2P14-T17-placebo.md",
        "configs/research/stage_2/s2p14_t17_placebo_v1.json",
    ]
    for relative in contracts:
        _write(repository / relative, {"contract": relative})
    source = tmp_path / EXPECTED_CHAIN
    source.mkdir()
    policy = {
        "schema_name": "stage2-active-policy-v3",
        "schema_version": "3.0",
        "stage": "S2",
        "stage_plan_version": "1.4",
        "execution_limit": "S2P14-T17",
        "stage3_locked": True,
        "code_commit_mode": "CURRENT_CLEAN_HEAD",
        "contract_paths": contracts,
        "preregistration_path": contracts[-1],
        "evidence_root": str(tmp_path / "evidence"),
        "task_dag": {"S2P14-T17": ["S2P13-T16"]},
        "source_t16_chain_root": str(source),
        "required_gates": [
            "COMMIT_BOUND_HUMAN_APPROVAL",
            "AUTHORITY_BEFORE_RUN",
            "UNIQUE_RUN_LOCK",
            "FULL_RECONCILIATION",
            "FULL_VERIFY",
        ],
    }
    return repository, _write(repository / "policy.json", policy)


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
            "eligible": 413837,
            "matched": 413827,
            "unmatched": 10,
            "controls": 1278527,
            "summaries": 13680,
            "groups": 456,
        },
    )


def test_policy_v3_is_single_authority_and_rejects_old_plan(tmp_path: Path) -> None:
    repository, policy_path = _policy_file(tmp_path)
    policy = load_policy(policy_path, repository_root=repository)
    assert policy.payload["task_dag"] == {"S2P14-T17": ["S2P13-T16"]}
    payload = json.loads(policy_path.read_text())
    payload["stage_plan_version"] = "1.3"
    _write(policy_path, payload)
    with pytest.raises(ValueError, match="contract drift"):
        load_policy(policy_path, repository_root=repository)


def test_approval_is_bound_to_commit_policy_and_t16_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, policy_path = _policy_file(tmp_path)
    policy = load_policy(policy_path, repository_root=repository)
    binding = _binding(tmp_path)
    monkeypatch.setattr(
        "era100x.research.stage_2.baselines.placebo.governance.repository_commit",
        lambda _root: "a" * 40,
    )
    payload = {
        "schema_name": "s2p14-t17-formal-approval-v1",
        "schema_version": "1.0",
        "code_commit": "a" * 40,
        "policy_hash": policy.policy_hash,
        "preregistration_hash": policy.preregistration_hash,
        "source_t16_verify_hash": binding.verify_hash,
        "source_t16_receipt_hash": binding.receipt_hash,
        "authority_count": 1,
        "run_count": 1,
        "stage3_locked": True,
    }
    payload["approval_hash"] = canonical_hash(payload)
    path = _write(tmp_path / "approval.json", payload)
    assert (
        validate_approval(
            path,
            policy=policy,
            repository_root=repository,
            binding=binding,
        )["approval_hash"]
        == payload["approval_hash"]
    )
    payload["source_t16_verify_hash"] = "8" * 64
    payload["approval_hash"] = canonical_hash(
        {key: value for key, value in payload.items() if key != "approval_hash"}
    )
    _write(path, payload)
    with pytest.raises(ValueError, match="invalid or stale"):
        validate_approval(
            path,
            policy=policy,
            repository_root=repository,
            binding=binding,
        )


def test_policy_type_cannot_authorize_plan_v13_evidence(tmp_path: Path) -> None:
    repository, policy_path = _policy_file(tmp_path)
    policy = load_policy(policy_path, repository_root=repository)
    assert isinstance(policy, PlaceboPolicy)
    assert policy.payload["execution_limit"] == "S2P14-T17"
