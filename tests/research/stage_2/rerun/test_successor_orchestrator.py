from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from era100x.foundation.governance.current_state import canonical_state_hash
from era100x.research.stage_2.rerun.orchestrator import (
    APPROVAL_SCHEMA,
    REHEARSAL_SCHEMA,
    TASKS,
    RetryableInterruption,
    SuccessorSupervisor,
    TaskHandoff,
    approval_readiness,
    canonical_hash,
)


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _state(tmp_path: Path, *, blocked: bool) -> Path:
    operations = [
        "READ_ONLY_AUDIT",
        "VERIFY_EXISTING_EVIDENCE",
        "READ_ONLY_UI",
        "BUILD_AUDIT_SUPPLEMENT",
        "FREEZE_AUTHORITY",
        "FREEZE_BINS",
        "PREFLIGHT",
        "RUN",
        "RESUME",
        "PUBLISH",
    ]
    payload: dict[str, object] = {
        "schema_name": "era-current-development-state",
        "schema_version": "1.2",
        "current_stage": "S2",
        "current_plan": "stage_2_plan_v1.3",
        "current_task": "S2P13-T11",
        "current_task_version": "1.0",
        "task_status": "READY_FOR_FORMAL_RUN",
        "stage_status": "IN_PROGRESS",
        "research_decision": "PENDING",
        "current_policy_path": "configs/governance/stage2_active_policy_v2.json",
        "formal_successor_result_exists": False,
        "stage3_locked": True,
        "srp_execution_status": "FORMAL_TASK_ACTIVE",
        "approved_execution_limit": "S2P13-T16",
        "formal_run_receipt_required": True,
        "allowed_operations": operations[:3] if blocked else operations,
        "blocked_operations": operations[3:] if blocked else [],
        "blocking_questions": ["OQ-S2-009"] if blocked else [],
        "sealed_tasks": ["S2-T10", "S2-T11", "S2-T12", "S2-T13", "S2-T14"],
        "source_records": ["docs/development/CURRENT_STAGE.md"],
        "state_hash": "",
    }
    payload["state_hash"] = canonical_state_hash(payload)
    path = tmp_path / "state.json"
    _write_json(path, payload)
    return path


def _receipts(tmp_path: Path, repository_root: Path, state_path: Path) -> Path:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository_root, text=True
    ).strip()
    rehearsal: dict[str, object] = {
        "schema_name": REHEARSAL_SCHEMA,
        "status": "PASS",
        "tasks": list(TASKS),
        "code_commit": commit,
        "day_count": 7,
        "producer_serialization": "PASS",
        "strict_consumer_readback": "PASS",
        "reconciliation": "PASS",
        "verify": "PASS",
        "ui_projection": "PASS",
    }
    rehearsal["receipt_hash"] = canonical_hash(rehearsal)
    rehearsal_path = tmp_path / "rehearsal.json"
    _write_json(rehearsal_path, rehearsal)
    state = json.loads(state_path.read_text())
    approval: dict[str, object] = {
        "schema_name": APPROVAL_SCHEMA,
        "status": "APPROVED",
        "tasks": list(TASKS),
        "code_commit": commit,
        "governance_state_hash": state["state_hash"],
        "rehearsal_receipt_path": str(rehearsal_path),
        "rehearsal_receipt_hash": rehearsal["receipt_hash"],
    }
    approval["approval_hash"] = canonical_hash(approval)
    approval_path = tmp_path / "approval.json"
    _write_json(approval_path, approval)
    return approval_path


@dataclass
class Adapter:
    task: str
    interruption: bool = False
    failure: bool = False
    calls: int = 0

    def static_preflight(self) -> None:
        if self.failure:
            raise ValueError("contract drift")

    def input_preflight(self) -> None:
        return None

    def run_or_resume(self) -> TaskHandoff:
        self.calls += 1
        if self.interruption and self.calls == 1:
            raise RetryableInterruption("process killed")
        return TaskHandoff(
            task_id=self.task,
            execution_mode="FORMAL",
            chain_id="formal-chain",
            run_id=f"run-{self.task.lower()}",
            evidence_id=f"run-{self.task.lower()}",
            artifact_root="/tmp/formal-chain",
            snapshot_id="snapshot",
            manifest_path="/tmp/formal-chain/manifest.json",
            manifest_hash="a" * 64,
            catalog_path="/tmp/formal-chain/catalog.json",
            catalog_hash="a" * 64,
            output_hash="a" * 64,
            row_count=1,
            execution_scope_hash="a" * 64,
            producer_receipt_hash="a" * 64,
            consumer_readback="PASS",
            reconciliation="PASS",
            verify_status="PASS",
        )


def test_current_repository_state_blocks_formal_approval(tmp_path: Path) -> None:
    from era100x.foundation.governance import load_current_development_state

    state = load_current_development_state()
    result = approval_readiness(state=state, rehearsal_path=None, repository_root=Path.cwd())
    assert result["status"] == "BLOCKED"
    assert result["blocking_questions"] == []
    assert result["reason_code"] == "S2_V13_PLAN_CLOSED"


def test_chain_preflights_all_tasks_before_first_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = _state(tmp_path, blocked=False)
    approval_path = _receipts(tmp_path, Path.cwd(), state_path)
    events: list[str] = []

    class OrderedAdapter(Adapter):
        def static_preflight(self) -> None:
            events.append(f"preflight:{self.task}")

        def input_preflight(self) -> None:
            events.append(f"input:{self.task}")

        def run_or_resume(self) -> TaskHandoff:
            events.append(f"run:{self.task}")
            return super().run_or_resume()

    adapters = {task: OrderedAdapter(task) for task in TASKS}
    monkeypatch.setattr(
        "era100x.research.stage_2.rerun.orchestrator.repository_clean", lambda _: True
    )
    supervisor = SuccessorSupervisor(
        root=tmp_path / "chain",
        approval_path=approval_path,
        repository_root=Path.cwd(),
        adapters=adapters,
        state_path=state_path,
    )
    result = supervisor.run_or_resume()
    assert result["status"] == "COMPLETE"
    assert events[: len(TASKS)] == [f"preflight:{task}" for task in TASKS]
    assert events[len(TASKS) :] == [
        event for task in TASKS for event in (f"input:{task}", f"run:{task}")
    ]


def test_retryable_interruption_resumes_but_terminal_failure_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = _state(tmp_path, blocked=False)
    approval_path = _receipts(tmp_path, Path.cwd(), state_path)
    adapters = {task: Adapter(task) for task in TASKS}
    adapters[TASKS[0]].interruption = True
    monkeypatch.setattr(
        "era100x.research.stage_2.rerun.orchestrator.repository_clean", lambda _: True
    )
    supervisor = SuccessorSupervisor(
        root=tmp_path / "retry",
        approval_path=approval_path,
        repository_root=Path.cwd(),
        adapters=adapters,
        state_path=state_path,
    )
    assert supervisor.run_or_resume()["status"] == "RETRYABLE_INTERRUPTED"
    assert supervisor.run_or_resume()["status"] == "COMPLETE"

    failed = {task: Adapter(task) for task in TASKS}
    failed[TASKS[0]].failure = True
    terminal = SuccessorSupervisor(
        root=tmp_path / "terminal",
        approval_path=approval_path,
        repository_root=Path.cwd(),
        adapters=failed,
        state_path=state_path,
    )
    with pytest.raises(ValueError, match="contract drift"):
        terminal.run_or_resume()
    with pytest.raises(RuntimeError, match="approved successor"):
        terminal.run_or_resume()
