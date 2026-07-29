from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from era100x.research.stage_2.acceptance.canonical_json import (
    canonical_content_hash,
    read_canonical_json,
    sha256_file,
)
from era100x.research.stage_2.lifecycle import formal_chain
from era100x.research.stage_2.lifecycle.formal_chain import (
    TASK_ORDER,
    freeze_authority,
    load_adapter_plan,
    record_approval,
    run_formal_chain,
)
from era100x.research.stage_2.lifecycle.governance import LifecycleRepairPolicy
from era100x.research.stage_2.lifecycle.input_catalog import (
    load_input_catalog,
    write_input_catalog,
)

COMMIT = "a" * 40


def _policy(tmp_path: Path) -> LifecycleRepairPolicy:
    payload = {
        "task_dag": {
            "S2P18-T11": [],
            "S2P18-T12": ["S2P18-T11"],
            "S2P18-T13": ["S2P18-T12"],
            "S2P18-T14": ["S2P18-T12"],
            "S2P18-T15": ["S2P18-T14"],
            "S2P18-T16": ["S2P18-T11", "S2P18-T13", "S2P18-T15"],
            "S2P18-T17": ["S2P18-T16"],
            "S2P18-T18": ["S2P18-T16", "S2P18-T17"],
            "S2P18-T19": ["S2P18-T11", "S2P18-T16", "S2P18-T17", "S2P18-T18"],
            "S2P18-T20": ["S2P18-T19"],
        }
    }
    return LifecycleRepairPolicy(
        path=tmp_path / "policy.json",
        payload=payload,
        policy_hash="b" * 64,
        preregistration_hash="c" * 64,
        source_audit_hash="d" * 64,
        contract_hashes={},
    )


def _producer(
    path: Path,
    *,
    fail_task: str | None = None,
    retry_task: str | None = None,
) -> None:
    path.write_text(
        f"""
import hashlib, json, os
from pathlib import Path

def seal(payload, field):
    body = {{key: value for key, value in payload.items() if key != field}}
    payload[field] = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return payload

task = os.environ["ERA_S2P18_TASK_ID"]
run_root = Path(os.environ["ERA_S2P18_RUN_ROOT"])
task_root = Path(os.environ["ERA_S2P18_TASK_ROOT"])
if task == {fail_task!r}:
    raise SystemExit(17)
retry_marker = task_root / "retry-marker"
if task == {retry_task!r} and not retry_marker.exists():
    retry_marker.write_text("resume\\n")
    raise SystemExit(75)
output = task_root / "output.json"
content = {{"task_id": task, "status": "PASS"}}
output.write_text(json.dumps(content, sort_keys=True) + "\\n")
entry = {{
    "relative_path": "output.json",
    "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    "size_bytes": output.stat().st_size,
}}
receipt = seal({{
    "schema_name": "s2p18-task-receipt-v1",
    "schema_version": "1.0",
    "task_id": task,
    "run_id": run_root.name,
    "authority_hash": os.environ["ERA_S2P18_AUTHORITY_HASH"],
    "adapter_plan_hash": os.environ["ERA_S2P18_ADAPTER_PLAN_HASH"],
    "code_commit": os.environ["ERA_S2P18_CODE_COMMIT"],
    "upstream_receipt_hashes": json.loads(
        os.environ["ERA_S2P18_UPSTREAM_RECEIPT_HASHES"]
    ),
    "status": "PASS",
    "row_count": 1,
    "output_files": [entry],
    "completed_at": "2026-07-29T00:00:00+00:00",
    "historical_execution_claim": False,
}}, "task_receipt_hash")
receipt_path = run_root / "receipts" / f"{{task}}.json"
receipt_path.parent.mkdir(parents=True, exist_ok=True)
with receipt_path.open("x") as handle:
    json.dump(receipt, handle, sort_keys=True, separators=(",", ":"))
    handle.write("\\n")
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _adapter_plan(root: Path, producer: Path) -> Path:
    executable_hash = sha256_file(producer)
    payload: dict[str, object] = {
        "schema_name": "s2p18-task-adapter-plan-v1",
        "schema_version": "1.0",
        "stage_plan_version": "1.8",
        "task_order": list(TASK_ORDER),
        "adapters": [
            {
                "task_id": task_id,
                "argv": [sys.executable, str(producer)],
                "executable_paths": [producer.name],
                "executable_hashes": [executable_hash],
                "timeout_seconds": 30,
            }
            for task_id in TASK_ORDER
        ],
    }
    payload["adapter_plan_hash"] = canonical_content_hash(payload)
    path = root / "adapters.json"
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return path


def _authorized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_task: str | None = None,
    retry_task: str | None = None,
) -> tuple[LifecycleRepairPolicy, formal_chain.AdapterPlan, Path, Path, Path]:
    producer = tmp_path / "producer.py"
    _producer(producer, fail_task=fail_task, retry_task=retry_task)
    adapters = load_adapter_plan(_adapter_plan(tmp_path, producer), repository_root=tmp_path)
    policy = _policy(tmp_path)
    monkeypatch.setattr(formal_chain, "repository_clean", lambda _root: True)
    monkeypatch.setattr(formal_chain, "repository_commit", lambda _root: COMMIT)
    evidence_root = tmp_path / "evidence"
    approval = record_approval(
        policy=policy,
        adapter_plan=adapters,
        repository_root=tmp_path,
        operations_root=evidence_root / "operations",
        approved_by="Muce",
        approval_source="test approval",
        approved_commit=COMMIT,
    )
    inputs_root = tmp_path / "inputs"
    inputs_root.mkdir()
    input_entries: dict[str, tuple[Path, str]] = {}
    for key in formal_chain.REQUIRED_INPUT_BINDINGS:
        evidence = inputs_root / f"{key}.json"
        evidence.write_text(json.dumps({"role": key}) + "\n", encoding="utf-8")
        input_entries[key] = (
            evidence.resolve(),
            hashlib.sha256(key.encode()).hexdigest(),
        )
    input_catalog_path = write_input_catalog(
        path=evidence_root / "operations/input-catalog.json",
        entries=input_entries,
    )
    authority = freeze_authority(
        policy=policy,
        adapter_plan=adapters,
        approval_path=approval,
        repository_root=tmp_path,
        evidence_root=evidence_root,
        input_catalog=load_input_catalog(input_catalog_path),
    )
    return policy, adapters, approval, authority, evidence_root


def test_formal_chain_orders_all_tasks_and_seals_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy, adapters, approval, authority, evidence_root = _authorized(
        tmp_path, monkeypatch
    )
    run_root = run_formal_chain(
        policy=policy,
        adapter_plan=adapters,
        approval_path=approval,
        authority_path=authority,
        repository_root=tmp_path,
        evidence_root=evidence_root,
    )

    assert [path.stem for path in sorted((run_root / "receipts").glob("*.json"))] == list(
        TASK_ORDER
    )
    assert read_canonical_json(run_root / "published/publication.json")["stage3_locked"]
    verify_files = tuple((run_root / "verify").glob("*.json"))
    assert len(verify_files) == 1
    assert read_canonical_json(verify_files[0])["status"] == "PASS"
    checkpoints = tuple(sorted((run_root / "checkpoints").glob("*.json")))
    assert len(checkpoints) == 21
    assert read_canonical_json(checkpoints[-1])["status"] == "COMPLETE"


def test_failed_task_is_terminal_unpublished_and_preserves_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy, adapters, approval, authority, evidence_root = _authorized(
        tmp_path, monkeypatch, fail_task="S2P18-T14"
    )
    with pytest.raises(ValueError, match="Task producer failed"):
        run_formal_chain(
            policy=policy,
            adapter_plan=adapters,
            approval_path=approval,
            authority_path=authority,
            repository_root=tmp_path,
            evidence_root=evidence_root,
        )

    run_root = next((evidence_root / "runs").iterdir())
    last = read_canonical_json(sorted((run_root / "checkpoints").glob("*.json"))[-1])
    assert last["status"] == "FAILED"
    assert not (run_root / "published/publication.json").exists()
    assert (run_root / "logs/S2P18-T14/attempt-0001.json").is_file()


def test_adapter_hash_drift_fails_before_approval(
    tmp_path: Path,
) -> None:
    producer = tmp_path / "producer.py"
    _producer(producer)
    plan_path = _adapter_plan(tmp_path, producer)
    producer.write_text("# drift\n", encoding="utf-8")

    with pytest.raises(ValueError, match="executable Hash drift"):
        load_adapter_plan(plan_path, repository_root=tmp_path)


def test_authority_requires_every_frozen_input_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    producer = tmp_path / "producer.py"
    _producer(producer)
    adapters = load_adapter_plan(
        _adapter_plan(tmp_path, producer), repository_root=tmp_path
    )
    policy = _policy(tmp_path)
    monkeypatch.setattr(formal_chain, "repository_clean", lambda _root: True)
    monkeypatch.setattr(formal_chain, "repository_commit", lambda _root: COMMIT)
    evidence_root = tmp_path / "evidence"
    record_approval(
        policy=policy,
        adapter_plan=adapters,
        repository_root=tmp_path,
        operations_root=evidence_root / "operations",
        approved_by="Muce",
        approval_source="test approval",
        approved_commit=COMMIT,
    )
    source = tmp_path / "only-one.json"
    source.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="requires twelve exact roles"):
        write_input_catalog(
            path=evidence_root / "operations/input-catalog.json",
            entries={
                "btc_stage1_logical_hash": (
                    source.resolve(),
                    hashlib.sha256(b"btc").hexdigest(),
                )
            },
        )
    assert not (evidence_root / "authorities").exists()
    assert not (evidence_root / "runs").exists()


def test_one_approval_freezes_only_one_authority_and_one_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy, adapters, approval, authority, evidence_root = _authorized(
        tmp_path, monkeypatch
    )
    input_catalog = load_input_catalog(
        evidence_root / "operations/input-catalog.json"
    )
    with pytest.raises(ValueError, match="one approval"):
        freeze_authority(
            policy=policy,
            adapter_plan=adapters,
            approval_path=approval,
            repository_root=tmp_path,
            evidence_root=evidence_root,
            input_catalog=input_catalog,
        )

    run_formal_chain(
        policy=policy,
        adapter_plan=adapters,
        approval_path=approval,
        authority_path=authority,
        repository_root=tmp_path,
        evidence_root=evidence_root,
    )
    with pytest.raises(ValueError, match="one Authority"):
        run_formal_chain(
            policy=policy,
            adapter_plan=adapters,
            approval_path=approval,
            authority_path=authority,
            repository_root=tmp_path,
            evidence_root=evidence_root,
        )
    assert len(tuple((evidence_root / "runs").iterdir())) == 1


def test_retryable_task_interruption_resumes_same_run_and_new_log_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy, adapters, approval, authority, evidence_root = _authorized(
        tmp_path,
        monkeypatch,
        retry_task="S2P18-T14",
    )
    with pytest.raises(
        formal_chain.RetryableTaskInterruption,
        match="resumable checkpoint",
    ):
        run_formal_chain(
            policy=policy,
            adapter_plan=adapters,
            approval_path=approval,
            authority_path=authority,
            repository_root=tmp_path,
            evidence_root=evidence_root,
        )
    run_root = next((evidence_root / "runs").iterdir())
    interrupted = read_canonical_json(
        sorted((run_root / "checkpoints").glob("*.json"))[-1]
    )
    assert interrupted["status"] == "INTERRUPTED"

    resumed = run_formal_chain(
        policy=policy,
        adapter_plan=adapters,
        approval_path=approval,
        authority_path=authority,
        repository_root=tmp_path,
        evidence_root=evidence_root,
        resume_run_root=run_root,
    )
    assert resumed == run_root
    assert read_canonical_json(run_root / "published/publication.json")[
        "stage3_locked"
    ]
    assert len(tuple((run_root / "logs/S2P18-T14").glob("attempt-*.json"))) == 2
