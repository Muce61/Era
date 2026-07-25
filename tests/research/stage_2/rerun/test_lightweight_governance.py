from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from era100x.research.stage_2.rerun import lightweight_governance as subject
from era100x.research.stage_2.rerun.orchestrator import TASKS, TaskHandoff, canonical_hash


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
    supplement = tmp_path / "supplement-acceptance.json"
    supplement.write_text('{"fixture":true}\n', encoding="utf-8")
    monkeypatch.setattr(
        subject,
        "verify_trade_supplement",
        lambda _path: {"status": "PASS", "acceptance_hash": "d" * 64},
    )
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
        "trade_supplement_acceptance_path": str(supplement),
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
            "FINAL_CODE_7_DAY_REHEARSAL_DEFAULT_OR_EXPLICIT_BACKGROUND_WAIVER",
            "COMMIT_BOUND_HUMAN_APPROVAL",
            "CHAIN_AUTHORITY",
            "FULL_VERIFY",
        ],
        "rehearsal_gate_policy": {
            "default_required": True,
            "explicit_background_waiver_allowed": True,
            "waiver_scope": subject.BACKGROUND_WAIVER_SCOPE,
            "waiver_must_bind_current_commit": True,
        },
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


def test_rehearsal_is_default_but_explicit_background_waiver_is_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = _policy(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="requires rehearsal by default"):
        subject.record_approval(
            policy=policy,
            repository_root=policy.path.parent,
            rehearsal_path=None,
            approved_by="Muce",
            approval_source="generic approval",
        )

    approval_path = subject.record_approval(
        policy=policy,
        repository_root=policy.path.parent,
        rehearsal_path=None,
        approved_by="Muce",
        approval_source="explicit unattended background approval",
        approved_at="2026-07-25T00:00:00+00:00",
        background_runtime_waiver=True,
        waiver_reason="operator requested no rehearsal for this overnight runtime",
    )
    approval = subject.validate_approval(
        approval_path,
        policy=policy,
        repository_root=policy.path.parent,
    )
    assert approval["rehearsal_gate_mode"] == subject.BACKGROUND_WAIVER_MODE
    assert approval["rehearsal_receipt_path"] is None
    assert approval["background_runtime_waiver"]["scope"] == subject.BACKGROUND_WAIVER_SCOPE
    assert "FULL_VERIFY" in approval["background_runtime_waiver"]["does_not_waive"]

    chain_path = subject.freeze_chain_authority(
        approval_path=approval_path,
        policy=policy,
        repository_root=policy.path.parent,
    )
    chain = json.loads(chain_path.read_text())
    assert chain["rehearsal_gate_mode"] == subject.BACKGROUND_WAIVER_MODE
    assert chain["background_runtime_waiver"]["explicitly_approved"] is True


def test_background_waiver_rejects_receipt_or_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = _policy(tmp_path, monkeypatch)
    rehearsal = tmp_path / "rehearsal.json"
    _rehearsal(rehearsal)
    with pytest.raises(ValueError, match="mutually exclusive"):
        subject.record_approval(
            policy=policy,
            repository_root=policy.path.parent,
            rehearsal_path=rehearsal,
            approved_by="Muce",
            approval_source="explicit approval",
            background_runtime_waiver=True,
            waiver_reason="not allowed with receipt",
        )

    approval_path = subject.record_approval(
        policy=policy,
        repository_root=policy.path.parent,
        rehearsal_path=None,
        approved_by="Muce",
        approval_source="explicit approval",
        background_runtime_waiver=True,
        waiver_reason="overnight runtime",
    )
    payload = json.loads(approval_path.read_text())
    payload["background_runtime_waiver"]["reason"] = ""
    payload["approval_hash"] = canonical_hash(
        {key: value for key, value in payload.items() if key != "approval_hash"}
    )
    _write(approval_path, payload)
    with pytest.raises(ValueError, match="background waiver drift"):
        subject.validate_approval(
            approval_path,
            policy=policy,
            repository_root=policy.path.parent,
        )


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


def _formal_handoff(
    tmp_path: Path,
    task: str,
    *,
    preregistration_hash: str | None = None,
) -> TaskHandoff:
    scope = {
        "mode": "FULL_HISTORY",
        "start_date": "2020-01-01",
        "end_date_exclusive": "2026-07-04",
    }
    artifact_root = tmp_path / "source-chain" / "tasks" / task / "artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    manifest = artifact_root / "manifest.json"
    catalog = artifact_root / "catalog.json"
    manifest_payload = {
        "schema_name": "source-manifest",
        **(
            {"preregistration_hash": preregistration_hash}
            if preregistration_hash is not None
            else {}
        ),
    }
    manifest_payload["manifest_hash"] = canonical_hash(manifest_payload)
    catalog_payload = {"schema_name": "source-catalog"}
    catalog_payload["catalog_hash"] = canonical_hash(catalog_payload)
    _write(manifest, manifest_payload)
    _write(catalog, catalog_payload)
    return TaskHandoff(
        task_id=task,
        execution_mode="FORMAL",
        chain_id="source-chain",
        run_id=f"source-{task.lower()}",
        evidence_id=f"source-{task.lower()}",
        artifact_root=str(artifact_root),
        snapshot_id="snapshot",
        manifest_path=str(manifest),
        manifest_hash=manifest_payload["manifest_hash"],
        catalog_path=str(catalog),
        catalog_hash=catalog_payload["catalog_hash"],
        output_hash="3" * 64,
        row_count=12,
        execution_scope_hash=canonical_hash(scope),
        producer_receipt_hash="5" * 64,
        consumer_readback="PASS",
        reconciliation="PASS",
        verify_status="PASS",
    )


def _source_receipt(path: Path, handoff: TaskHandoff) -> None:
    scope = {
        "mode": "FULL_HISTORY",
        "start_date": "2020-01-01",
        "end_date_exclusive": "2026-07-04",
        "execution_scope_hash": handoff.execution_scope_hash,
    }
    payload = {
        "schema_name": "stage2-plan-v13-production-task-receipt-v2",
        "status": "PASS",
        "stage_plan_version": "1.3",
        "execution_mode": "FORMAL",
        "task_id": handoff.task_id,
        "code_commit": "0" * 40,
        "chain_id": handoff.chain_id,
        "run_id": handoff.run_id,
        "evidence_id": handoff.evidence_id,
        "artifact_root": handoff.artifact_root,
        "snapshot_id": handoff.snapshot_id,
        "manifest_path": handoff.manifest_path,
        "manifest_hash": handoff.manifest_hash,
        "catalog_path": handoff.catalog_path,
        "catalog_hash": handoff.catalog_hash,
        "adapter_plan_hash": "6" * 64,
        "upstream_handoffs": {},
        "execution_scope": scope,
        "output_hash": handoff.output_hash,
        "row_count": handoff.row_count,
        "consumer_readback": "PASS",
        "reconciliation": "PASS",
        "verify_status": "PASS",
    }
    payload["receipt_hash"] = canonical_hash(payload)
    _write(path, payload)


def test_adapter_plan_can_bind_exact_verified_t11_t12_prefix(
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
    source_chain = tmp_path / "source-chain"
    adopted = {task: _formal_handoff(tmp_path, task) for task in subject.VERIFIED_PREFIX_TASKS}

    plan_path, _ = subject.prepare_adapter_plan(
        approval_path=approval,
        chain_authority_path=chain,
        policy=policy,
        repository_root=policy.path.parent,
        adopted_prefix=adopted,
        adopted_source_chain_root=source_chain,
    )

    plan = json.loads(plan_path.read_text())
    assert plan["verified_prefix_source"]["source_chain_root"] == str(source_chain)
    for task in subject.VERIFIED_PREFIX_TASKS:
        assert plan["tasks"][task]["allowed_artifact_root"] == adopted[task].artifact_root
    assert plan["tasks"]["S2P13-T13"]["allowed_artifact_root"] != adopted["S2P13-T12"].artifact_root


def test_adopt_verified_prefix_seeds_t13_without_recomputing_t11_t12(
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
    source_chain = tmp_path / "source-chain"
    source_chain.mkdir(exist_ok=True)
    handoffs = {
        task: _formal_handoff(
            tmp_path,
            task,
            preregistration_hash=policy.preregistration_hash,
        )
        for task in subject.VERIFIED_PREFIX_TASKS
    }
    handoffs["S2P13-T12"] = replace(handoffs["S2P13-T12"], row_count=532_708)
    receipt_paths = {}
    for task, handoff in handoffs.items():
        receipt_path = source_chain / "tasks" / task / "receipt.json"
        _source_receipt(receipt_path, handoff)
        receipt_payload = json.loads(receipt_path.read_text())
        handoffs[task] = replace(
            handoff,
            producer_receipt_hash=receipt_payload["receipt_hash"],
        )
        receipt_paths[task] = receipt_path
    monkeypatch.setattr(
        subject,
        "_load_verified_prefix",
        lambda **_kwargs: (handoffs, receipt_paths),
    )

    result = subject.adopt_verified_prefix(
        approval_path=approval,
        source_chain_root=source_chain,
        policy=policy,
        repository_root=policy.path.parent,
    )

    checkpoint = json.loads((Path(result["operations_root"]) / "checkpoint.json").read_text())
    assert checkpoint["current_task"] == "S2P13-T13"
    assert checkpoint["tasks"]["S2P13-T11"]["status"] == "PASS"
    assert checkpoint["tasks"]["S2P13-T12"]["status"] == "PASS"
    assert checkpoint["tasks"]["S2P13-T13"]["status"] == "NOT_STARTED"
    assert Path(result["verified_prefix_adoption_path"]).is_file()


class _FailingAdapter:
    def static_preflight(self) -> None:
        return None

    def input_preflight(self) -> None:
        return None

    def run_or_resume(self) -> object:
        raise ValueError("partition drift")


def test_terminal_failure_updates_current_task_state(tmp_path: Path) -> None:
    chain = {
        "schema_name": subject.CHAIN_AUTHORITY_SCHEMA,
        "authority_hash": "a" * 64,
    }
    chain_path = tmp_path / "chain.json"
    _write(chain_path, chain)
    adapters = {task: _FailingAdapter() for task in TASKS}
    supervisor = subject.LightweightSupervisor(
        root=tmp_path / "operations",
        approval={"code_commit": "b" * 40, "approval_hash": "c" * 64},
        chain_authority_path=chain_path,
        adapters=adapters,  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="partition drift"):
        supervisor.run_or_resume()
    checkpoint = json.loads((tmp_path / "operations/checkpoint.json").read_text())
    assert checkpoint["status"] == "TERMINAL_FAILED"
    assert checkpoint["tasks"]["S2P13-T11"]["status"] == "TERMINAL_FAILED"
    assert checkpoint["tasks"]["S2P13-T12"]["status"] == "NOT_STARTED"
