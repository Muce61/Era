from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from era100x.research.stage_2.rerun.orchestrator import TASKS, RetryableInterruption
from era100x.research.stage_2.rerun.production_adapters import (
    PLAN_SCHEMA,
    UPSTREAM_TASKS,
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
    tasks: dict[str, object] = {}
    for task_id in TASKS:
        task_root = evidence_root / task_id
        tasks[task_id] = {
            "required_upstream_tasks": list(UPSTREAM_TASKS[task_id]),
            "preflight_command": [sys.executable, "-c", "raise SystemExit(0)"],
            "run_command": [sys.executable, "-c", "raise SystemExit(0)"],
            "resume_command": [sys.executable, "-c", "raise SystemExit(0)"],
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
if mode == "preflight":
    raise SystemExit(0)
if mode == "retry":
    raise SystemExit(75)
upstream = json.loads(os.environ["ERA_S2P13_EXPECTED_UPSTREAM_HASHES"])
payload = {
    "schema_name": RECEIPT_SCHEMA,
    "status": "PASS",
    "task_id": os.environ["ERA_S2P13_TASK_ID"],
    "code_commit": os.environ["ERA_S2P13_CODE_COMMIT"],
    "adapter_plan_hash": os.environ["ERA_S2P13_ADAPTER_PLAN_HASH"],
    "upstream_output_hashes": upstream,
    "run_id": "formal-test-run",
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


def test_adapter_runs_real_argv_and_accepts_only_bound_receipt(tmp_path: Path) -> None:
    producer = tmp_path / "producer.py"
    _producer_script(producer)
    task_root = tmp_path / "evidence/S2P13-T12"
    checkpoint = tmp_path / "supervisor/checkpoint.json"
    _write_json(
        checkpoint,
        {
            "tasks": {
                "S2P13-T11": {
                    "status": "PASS",
                    "handoff": {"output_hash": "1" * 64},
                }
            }
        },
    )
    spec = ProductionTaskSpec(
        task_id="S2P13-T12",
        required_upstream_tasks=("S2P13-T11",),
        preflight_command=(sys.executable, str(producer), "preflight"),
        run_command=(sys.executable, str(producer), "run"),
        resume_command=(sys.executable, str(producer), "resume"),
        checkpoint_path=task_root / "checkpoint.json",
        receipt_path=task_root / "receipt.json",
    )
    adapter = CommandTaskAdapter(
        spec=spec,
        code_commit="a" * 40,
        adapter_plan_hash="2" * 64,
        supervisor_checkpoint_path=checkpoint,
        repository_root=Path.cwd(),
    )
    adapter.preflight()
    handoff = adapter.run_or_resume()
    assert handoff.task_id == "S2P13-T12"
    assert handoff.output_hash == "b" * 64
    assert handoff.row_count == 12
    assert adapter.run_or_resume() == handoff

    receipt = json.loads(spec.receipt_path.read_text())
    receipt["upstream_output_hashes"] = {"S2P13-T11": "wrong"}
    receipt["receipt_hash"] = receipt_hash(
        {key: value for key, value in receipt.items() if key != "receipt_hash"}
    )
    _write_json(spec.receipt_path, receipt)
    with pytest.raises(ValueError, match="receipt contract mismatch"):
        adapter.run_or_resume()


def test_retryable_exit_does_not_become_terminal_handoff(tmp_path: Path) -> None:
    producer = tmp_path / "producer.py"
    _producer_script(producer)
    task_root = tmp_path / "evidence/S2P13-T11"
    spec = ProductionTaskSpec(
        task_id="S2P13-T11",
        required_upstream_tasks=(),
        preflight_command=(sys.executable, str(producer), "preflight"),
        run_command=(sys.executable, str(producer), "retry"),
        resume_command=(sys.executable, str(producer), "resume"),
        checkpoint_path=task_root / "checkpoint.json",
        receipt_path=task_root / "receipt.json",
    )
    adapter = CommandTaskAdapter(
        spec=spec,
        code_commit="a" * 40,
        adapter_plan_hash="2" * 64,
        supervisor_checkpoint_path=tmp_path / "supervisor/checkpoint.json",
        repository_root=Path.cwd(),
    )
    with pytest.raises(RetryableInterruption, match="interrupted"):
        adapter.run_or_resume()
