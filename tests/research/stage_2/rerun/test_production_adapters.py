from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path

import pytest

from era100x.research.stage_2.rerun.orchestrator import TASKS, RetryableInterruption
from era100x.research.stage_2.rerun.production_adapters import (
    PLAN_SCHEMA,
    UPSTREAM_TASKS,
    VERIFIED_PREFIX_ADOPTION_SCHEMA,
    CommandTaskAdapter,
    ProductionTaskSpec,
    load_adapter_plan,
)
from era100x.research.stage_2.rerun.production_adapters import (
    canonical_hash as receipt_hash,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _seal(payload: dict[str, object], field: str) -> dict[str, object]:
    result = dict(payload)
    result[field] = receipt_hash(payload)
    return result


def _approved_plan(tmp_path: Path, *, commit: str = "a" * 40) -> Path:
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    preregistration = tmp_path / "S2P13-T20-preregistration.md"
    preregistration.write_text("frozen preregistration", encoding="utf-8")
    tasks: dict[str, object] = {}
    for task_id in TASKS:
        task_root = evidence_root / task_id
        artifact_root = task_root / "artifacts"
        artifact_root.mkdir(parents=True)
        tasks[task_id] = {
            "required_upstream_tasks": list(UPSTREAM_TASKS[task_id]),
            "static_preflight_command": [sys.executable, "-c", "raise SystemExit(0)"],
            "input_preflight_command": [sys.executable, "-c", "raise SystemExit(0)"],
            "run_command": [sys.executable, "-c", "raise SystemExit(0)"],
            "resume_command": [sys.executable, "-c", "raise SystemExit(0)"],
            "allowed_artifact_root": str(artifact_root),
            "checkpoint_path": str(task_root / "checkpoint.json"),
            "receipt_path": str(task_root / "receipt.json"),
        }
    payload = _seal(
        {
            "schema_name": PLAN_SCHEMA,
            "status": "APPROVED",
            "stage_plan_version": "1.3",
            "code_commit": commit,
            "evidence_root": str(evidence_root),
            "preregistration_path": str(preregistration),
            "preregistration_hash": hashlib.sha256(preregistration.read_bytes()).hexdigest(),
            "tasks": tasks,
            "formal_run_created": False,
        },
        "adapter_plan_hash",
    )
    path = tmp_path / "adapter-plan.json"
    _write_json(path, payload)
    return path


def test_load_adapter_plan_requires_exact_dag_and_no_shell(tmp_path: Path) -> None:
    path = _approved_plan(tmp_path)
    plan = load_adapter_plan(path, code_commit="a" * 40)
    assert tuple(plan.tasks) == TASKS
    assert plan.tasks["S2P13-T16"].required_upstream_tasks == (
        "S2P13-T11",
        "S2P13-T13",
        "S2P13-T15",
    )
    assert plan.tasks["S2P13-T14"].required_upstream_tasks == ("S2P13-T12",)

    payload = json.loads(path.read_text())
    payload["tasks"]["S2P13-T11"]["run_command"] = ["sh", "-c", "true"]
    payload["adapter_plan_hash"] = receipt_hash(
        {key: value for key, value in payload.items() if key != "adapter_plan_hash"}
    )
    _write_json(path, payload)
    with pytest.raises(ValueError, match="cannot invoke a shell"):
        load_adapter_plan(path, code_commit="a" * 40)


def _producer_script(path: Path) -> None:
    path.write_text(
        """
import json
import os
import sys
from pathlib import Path
from era100x.research.stage_2.rerun.orchestrator import canonical_hash
from era100x.research.stage_2.rerun.production_adapters import RECEIPT_SCHEMA

mode = sys.argv[1]
if mode in {"static-preflight", "input-preflight"}:
    raise SystemExit(0)
if mode == "retry":
    raise SystemExit(75)
upstream = json.loads(os.environ["ERA_S2P13_EXPECTED_UPSTREAM_HANDOFFS"])
root = Path(os.environ["ERA_S2P13_TASK_RECEIPT_PATH"]).parent / "artifacts"
root.mkdir(parents=True, exist_ok=True)
manifest = {"schema_name": "test-manifest"}
manifest["manifest_hash"] = canonical_hash(manifest)
catalog = {"schema_name": "test-catalog"}
catalog["catalog_hash"] = canonical_hash(catalog)
(root / "manifest.json").write_text(json.dumps(manifest))
(root / "catalog.json").write_text(json.dumps(catalog))
scope = {
    "mode": "FULL_HISTORY",
    "start_date": "2020-01-01",
    "end_date_exclusive": "2026-07-04",
}
scope["execution_scope_hash"] = canonical_hash(scope)
payload = {
    "schema_name": RECEIPT_SCHEMA,
    "status": "PASS",
    "stage_plan_version": "1.3",
    "execution_mode": "FORMAL",
    "task_id": os.environ["ERA_S2P13_TASK_ID"],
    "code_commit": os.environ["ERA_S2P13_CODE_COMMIT"],
    "adapter_plan_hash": os.environ["ERA_S2P13_ADAPTER_PLAN_HASH"],
    "upstream_handoffs": upstream,
    "chain_id": "formal-test-chain",
    "run_id": "formal-test-run",
    "evidence_id": "formal-test-run",
    "artifact_root": str(root),
    "snapshot_id": "snapshot-test",
    "manifest_path": str(root / "manifest.json"),
    "manifest_hash": manifest["manifest_hash"],
    "catalog_path": str(root / "catalog.json"),
    "catalog_hash": catalog["catalog_hash"],
    "execution_scope": scope,
    "output_hash": "b" * 64,
    "row_count": 12,
    "consumer_readback": "PASS",
    "reconciliation": "PASS",
    "verify_status": "PASS",
}
payload["receipt_hash"] = canonical_hash(payload)
receipt = Path(os.environ["ERA_S2P13_TASK_RECEIPT_PATH"])
receipt.parent.mkdir(parents=True, exist_ok=True)
receipt.write_text(json.dumps(payload, sort_keys=True))
""".strip(),
        encoding="utf-8",
    )


def _upstream_handoff(tmp_path: Path, task_id: str) -> dict[str, object]:
    root = tmp_path / "upstream" / task_id
    root.mkdir(parents=True, exist_ok=True)
    manifest = _seal({"schema_name": "test-upstream-manifest"}, "manifest_hash")
    catalog = _seal({"schema_name": "test-upstream-catalog"}, "catalog_hash")
    manifest_path = root / "manifest.json"
    catalog_path = root / "catalog.json"
    _write_json(manifest_path, manifest)
    _write_json(catalog_path, catalog)
    return {
        "task_id": task_id,
        "execution_mode": "FORMAL",
        "chain_id": "formal-test-chain",
        "run_id": f"formal-{task_id.lower()}",
        "evidence_id": f"formal-{task_id.lower()}",
        "artifact_root": str(root),
        "snapshot_id": str(manifest["manifest_hash"]),
        "manifest_path": str(manifest_path),
        "manifest_hash": str(manifest["manifest_hash"]),
        "catalog_path": str(catalog_path),
        "catalog_hash": str(catalog["catalog_hash"]),
        "output_hash": "1" * 64,
        "row_count": 12,
        "execution_scope_hash": "4" * 64,
        "producer_receipt_hash": "5" * 64,
        "consumer_readback": "PASS",
        "reconciliation": "PASS",
        "verify_status": "PASS",
    }


def test_adapter_runs_real_argv_and_accepts_only_bound_receipt(tmp_path: Path) -> None:
    producer = tmp_path / "producer.py"
    _producer_script(producer)
    task_root = tmp_path / "evidence/S2P13-T12"
    (task_root / "artifacts").mkdir(parents=True)
    checkpoint = tmp_path / "supervisor/checkpoint.json"
    _write_json(
        checkpoint,
        {
            "tasks": {
                "S2P13-T11": {
                    "status": "PASS",
                    "handoff": _upstream_handoff(tmp_path, "S2P13-T11"),
                }
            }
        },
    )
    spec = ProductionTaskSpec(
        task_id="S2P13-T12",
        required_upstream_tasks=("S2P13-T11",),
        static_preflight_command=(sys.executable, str(producer), "static-preflight"),
        input_preflight_command=(sys.executable, str(producer), "input-preflight"),
        run_command=(sys.executable, str(producer), "run"),
        resume_command=(sys.executable, str(producer), "resume"),
        allowed_artifact_root=task_root / "artifacts",
        checkpoint_path=task_root / "checkpoint.json",
        receipt_path=task_root / "receipt.json",
    )
    adapter = CommandTaskAdapter(
        spec=spec,
        code_commit="a" * 40,
        adapter_plan_hash="2" * 64,
        supervisor_checkpoint_path=checkpoint,
        repository_root=Path.cwd(),
        preregistration_path=producer,
        preregistration_hash=hashlib.sha256(producer.read_bytes()).hexdigest(),
    )
    adapter.static_preflight()
    adapter.input_preflight()
    handoff = adapter.run_or_resume()
    assert handoff.task_id == "S2P13-T12"
    assert handoff.output_hash == "b" * 64
    assert handoff.row_count == 12
    assert adapter.run_or_resume() == handoff

    receipt = json.loads(spec.receipt_path.read_text())
    assert set(receipt["upstream_handoffs"]["S2P13-T11"]).isdisjoint(
        {"consumer_readback", "reconciliation", "verify_status"}
    )
    source_chain = tmp_path / "source-chain"
    source_receipt = source_chain / "tasks/S2P13-T12/receipt.json"
    _write_json(source_receipt, receipt)
    receipt["verified_prefix_adoption"] = {
        "schema_name": VERIFIED_PREFIX_ADOPTION_SCHEMA,
        "mode": "READ_ONLY",
        "source_chain_root": str(source_chain),
        "source_code_commit": receipt["code_commit"],
        "source_receipt_path": str(source_receipt),
        "source_receipt_hash": receipt["receipt_hash"],
        "source_run_id": receipt["run_id"],
        "source_task_id": "S2P13-T12",
    }
    receipt["receipt_hash"] = receipt_hash(
        {key: value for key, value in receipt.items() if key != "receipt_hash"}
    )
    _write_json(spec.receipt_path, receipt)
    assert adapter.run_or_resume().row_count == 12

    receipt["upstream_handoffs"] = {"S2P13-T11": {"output_hash": "wrong"}}
    receipt["receipt_hash"] = receipt_hash(
        {key: value for key, value in receipt.items() if key != "receipt_hash"}
    )
    _write_json(spec.receipt_path, receipt)
    with pytest.raises(ValueError, match="receipt contract mismatch"):
        adapter.run_or_resume()


@pytest.mark.parametrize("task_id", tuple(task for task in TASKS if UPSTREAM_TASKS[task]))
def test_all_downstream_adapters_normalize_verified_supervisor_handoffs(
    tmp_path: Path, task_id: str
) -> None:
    task_root = tmp_path / "evidence" / task_id
    (task_root / "artifacts").mkdir(parents=True)
    checkpoint = tmp_path / "supervisor" / "checkpoint.json"
    upstream = {
        upstream_task: {
            "status": "PASS",
            "handoff": _upstream_handoff(tmp_path, upstream_task),
        }
        for upstream_task in UPSTREAM_TASKS[task_id]
    }
    _write_json(checkpoint, {"tasks": upstream})
    spec = ProductionTaskSpec(
        task_id=task_id,
        required_upstream_tasks=UPSTREAM_TASKS[task_id],
        static_preflight_command=(sys.executable, "-c", "raise SystemExit(0)"),
        input_preflight_command=(sys.executable, "-c", "raise SystemExit(0)"),
        run_command=(sys.executable, "-c", "raise SystemExit(0)"),
        resume_command=(sys.executable, "-c", "raise SystemExit(0)"),
        allowed_artifact_root=task_root / "artifacts",
        checkpoint_path=task_root / "checkpoint.json",
        receipt_path=task_root / "receipt.json",
    )
    adapter = CommandTaskAdapter(
        spec=spec,
        code_commit="a" * 40,
        adapter_plan_hash="2" * 64,
        supervisor_checkpoint_path=checkpoint,
        repository_root=Path.cwd(),
        preregistration_path=Path(__file__),
        preregistration_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    )

    normalized = adapter._upstream_handoffs()

    assert tuple(normalized) == UPSTREAM_TASKS[task_id]
    for payload in normalized.values():
        assert set(payload).isdisjoint({"consumer_readback", "reconciliation", "verify_status"})


def test_adapter_rejects_upstream_without_all_three_pass_states(tmp_path: Path) -> None:
    handoff = _upstream_handoff(tmp_path, "S2P13-T11")
    handoff["verify_status"] = "FAIL"
    checkpoint = tmp_path / "supervisor" / "checkpoint.json"
    _write_json(
        checkpoint,
        {"tasks": {"S2P13-T11": {"status": "PASS", "handoff": handoff}}},
    )
    task_root = tmp_path / "evidence" / "S2P13-T12"
    (task_root / "artifacts").mkdir(parents=True)
    spec = ProductionTaskSpec(
        task_id="S2P13-T12",
        required_upstream_tasks=("S2P13-T11",),
        static_preflight_command=(sys.executable, "-c", "raise SystemExit(0)"),
        input_preflight_command=(sys.executable, "-c", "raise SystemExit(0)"),
        run_command=(sys.executable, "-c", "raise SystemExit(0)"),
        resume_command=(sys.executable, "-c", "raise SystemExit(0)"),
        allowed_artifact_root=task_root / "artifacts",
        checkpoint_path=task_root / "checkpoint.json",
        receipt_path=task_root / "receipt.json",
    )
    adapter = CommandTaskAdapter(
        spec=spec,
        code_commit="a" * 40,
        adapter_plan_hash="2" * 64,
        supervisor_checkpoint_path=checkpoint,
        repository_root=Path.cwd(),
        preregistration_path=Path(__file__),
        preregistration_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    )

    with pytest.raises(ValueError, match="required upstream handoff is not PASS"):
        adapter._upstream_handoffs()


def test_retryable_exit_does_not_become_terminal_handoff(tmp_path: Path) -> None:
    producer = tmp_path / "producer.py"
    _producer_script(producer)
    task_root = tmp_path / "evidence/S2P13-T11"
    (task_root / "artifacts").mkdir(parents=True)
    spec = ProductionTaskSpec(
        task_id="S2P13-T11",
        required_upstream_tasks=(),
        static_preflight_command=(sys.executable, str(producer), "static-preflight"),
        input_preflight_command=(sys.executable, str(producer), "input-preflight"),
        run_command=(sys.executable, str(producer), "retry"),
        resume_command=(sys.executable, str(producer), "resume"),
        allowed_artifact_root=task_root / "artifacts",
        checkpoint_path=task_root / "checkpoint.json",
        receipt_path=task_root / "receipt.json",
    )
    adapter = CommandTaskAdapter(
        spec=spec,
        code_commit="a" * 40,
        adapter_plan_hash="2" * 64,
        supervisor_checkpoint_path=tmp_path / "supervisor/checkpoint.json",
        repository_root=Path.cwd(),
        preregistration_path=producer,
        preregistration_hash=hashlib.sha256(producer.read_bytes()).hexdigest(),
    )
    with pytest.raises(RetryableInterruption, match="interrupted"):
        adapter.run_or_resume()
