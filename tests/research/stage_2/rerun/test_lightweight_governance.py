from __future__ import annotations

import json
from pathlib import Path

import pytest

from era100x.research.stage_2.rerun import lightweight_governance as subject
from era100x.research.stage_2.rerun.orchestrator import TASKS, canonical_hash


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> subject.Stage2ActivePolicy:
    repository = tmp_path / "repo"
    repository.mkdir()
    contracts = []
    for name in ("manual.md", "plan.md", "t20.md"):
        target = repository / name
        target.write_text(name, encoding="utf-8")
        contracts.append(name)
    evidence = tmp_path / "evidence"
    payload = {
        "schema_name": subject.POLICY_SCHEMA,
        "schema_version": "2.0",
        "stage": "S2",
        "stage_plan_version": "1.3",
        "execution_limit": "S2P13-T16",
        "stage3_locked": True,
        "code_commit_mode": "CURRENT_CLEAN_HEAD",
        "contract_paths": contracts[:2],
        "preregistration_path": "t20.md",
        "evidence_root": str(evidence),
        "task_dag": {
            "S2P13-T11": [],
            "S2P13-T12": ["S2P13-T11"],
            "S2P13-T13": ["S2P13-T12"],
            "S2P13-T14": ["S2P13-T12"],
            "S2P13-T15": ["S2P13-T14"],
            "S2P13-T16": ["S2P13-T11", "S2P13-T13", "S2P13-T15"],
        },
        "full_history_scope": {
            "start_date": "2020-01-01",
            "end_date_exclusive": "2026-07-04",
        },
        "required_gates": [
            "FINAL_CODE_7_DAY_REHEARSAL",
            "COMMIT_BOUND_HUMAN_APPROVAL",
            "CHAIN_AUTHORITY",
            "FULL_VERIFY",
        ],
    }
    path = repository / "policy.json"
    _write(path, payload)
    monkeypatch.setattr(subject, "current_commit", lambda _root: "a" * 40)
    monkeypatch.setattr(subject, "repository_clean", lambda _root: True)
    return subject.load_policy(path, repository_root=repository)


def _rehearsal(path: Path) -> None:
    value = {
        "schema_name": subject.REHEARSAL_SCHEMA,
        "status": "PASS",
        "tasks": list(TASKS),
        "code_commit": "a" * 40,
        "day_count": 7,
        "producer_serialization": "PASS",
        "strict_consumer_readback": "PASS",
        "reconciliation": "PASS",
        "verify": "PASS",
        "ui_projection": "PASS",
        "authority_created": False,
        "formal_binning_snapshot_created": False,
        "formal_run_id_created": False,
    }
    value["receipt_hash"] = canonical_hash(value)
    _write(path, value)


def test_external_approval_does_not_touch_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = _policy(tmp_path, monkeypatch)
    rehearsal = tmp_path / "rehearsal.json"
    _rehearsal(rehearsal)
    before = {path: path.read_bytes() for path in policy.path.parent.iterdir() if path.is_file()}
    approval = subject.record_approval(
        policy=policy,
        repository_root=policy.path.parent,
        rehearsal_path=rehearsal,
        approved_by="Muce",
        approval_source="chat approval",
        approved_at="2026-07-24T00:00:00+00:00",
    )
    assert approval.is_relative_to(policy.evidence_root)
    assert before == {
        path: path.read_bytes() for path in policy.path.parent.iterdir() if path.is_file()
    }
    assert (
        subject.validate_approval(approval, policy=policy, repository_root=policy.path.parent)[
            "status"
        ]
        == "APPROVED"
    )


def test_approval_rejects_commit_or_policy_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = _policy(tmp_path, monkeypatch)
    rehearsal = tmp_path / "rehearsal.json"
    _rehearsal(rehearsal)
    approval = subject.record_approval(
        policy=policy,
        repository_root=policy.path.parent,
        rehearsal_path=rehearsal,
        approved_by="Muce",
        approval_source="chat approval",
    )
    monkeypatch.setattr(subject, "current_commit", lambda _root: "b" * 40)
    with pytest.raises(ValueError, match="binding drift"):
        subject.validate_approval(approval, policy=policy, repository_root=policy.path.parent)


def test_two_layer_authority_requires_formal_dynamic_handoffs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = _policy(tmp_path, monkeypatch)
    rehearsal = tmp_path / "rehearsal.json"
    _rehearsal(rehearsal)
    approval = subject.record_approval(
        policy=policy,
        repository_root=policy.path.parent,
        rehearsal_path=rehearsal,
        approved_by="Muce",
        approval_source="chat approval",
    )
    chain = subject.freeze_chain_authority(
        approval_path=approval,
        policy=policy,
        repository_root=policy.path.parent,
    )
    handoffs = {
        task: {
            "task_id": task,
            "execution_mode": "FORMAL",
            "run_id": f"run-{task}",
            "verify_status": "PASS",
        }
        for task in ("S2P13-T11", "S2P13-T13", "S2P13-T15")
    }
    authority = subject.freeze_t16_authority(
        chain_authority_path=chain,
        handoffs=handoffs,
        policy=policy,
    )
    assert json.loads(authority.read_text())["bin_source_roles"] == ["TRAIN"]
    handoffs["S2P13-T15"]["execution_mode"] = "REHEARSAL"
    with pytest.raises(ValueError, match="formal PASS"):
        subject.freeze_t16_authority(
            chain_authority_path=chain,
            handoffs=handoffs,
            policy=policy,
        )


def test_legacy_v1_approval_cannot_authorize_policy_v2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = _policy(tmp_path, monkeypatch)
    legacy = {
        "schema_name": "stage2-plan-v13-formal-run-approval-v1",
        "status": "APPROVED",
        "code_commit": "a" * 40,
        "policy_hash": policy.policy_hash,
    }
    legacy["approval_hash"] = canonical_hash(legacy)
    path = tmp_path / "legacy.json"
    _write(path, legacy)
    with pytest.raises(ValueError, match="binding drift"):
        subject.validate_approval(path, policy=policy, repository_root=policy.path.parent)


def test_adapter_plan_cannot_exist_before_chain_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = _policy(tmp_path, monkeypatch)
    rehearsal = tmp_path / "rehearsal.json"
    _rehearsal(rehearsal)
    approval = subject.record_approval(
        policy=policy,
        repository_root=policy.path.parent,
        rehearsal_path=rehearsal,
        approved_by="Muce",
        approval_source="chat approval",
    )
    with pytest.raises(ValueError, match="missing Stage 2 evidence"):
        subject.prepare_adapter_plan(
            approval_path=approval,
            chain_authority_path=policy.evidence_root / "missing-authority.json",
            policy=policy,
            repository_root=policy.path.parent,
        )
