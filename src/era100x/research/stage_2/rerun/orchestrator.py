"""Fail-closed Plan v1.3 successor-chain orchestration primitives."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from era100x.foundation.governance import (
    CurrentDevelopmentState,
    load_current_development_state,
)

TASKS = (
    "S2P13-T11",
    "S2P13-T12",
    "S2P13-T13",
    "S2P13-T14",
    "S2P13-T15",
    "S2P13-T16",
)
SCHEMA = "stage2-plan-v13-successor-checkpoint-v1"
APPROVAL_SCHEMA = "stage2-plan-v13-formal-run-approval-v1"
REHEARSAL_SCHEMA = "stage2-plan-v13-seven-day-rehearsal-v1"


def canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _safe_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.parent.is_symlink():
        raise ValueError(f"unsafe or missing JSON evidence: {path}")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("JSON evidence root must be an object")
    return cast(dict[str, Any], value)


def _self_hash_valid(payload: Mapping[str, Any], field: str) -> bool:
    claimed = payload.get(field)
    body = {key: value for key, value in payload.items() if key != field}
    return isinstance(claimed, str) and claimed == canonical_hash(body)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def current_commit(repository_root: Path) -> str:
    value = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository_root, text=True
    ).strip()
    if len(value) != 40:
        raise ValueError("formal successor requires an exact Git commit")
    return value


def repository_clean(repository_root: Path) -> bool:
    value = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=repository_root, text=True
    )
    return not value.strip()


def validate_rehearsal_receipt(path: Path, *, code_commit: str) -> dict[str, Any]:
    payload = _safe_json(path)
    if not _self_hash_valid(payload, "receipt_hash"):
        raise ValueError("seven-day rehearsal receipt hash mismatch")
    required = (
        payload.get("schema_name") == REHEARSAL_SCHEMA
        and payload.get("status") == "PASS"
        and tuple(payload.get("tasks", ())) == TASKS
        and payload.get("code_commit") == code_commit
        and payload.get("producer_serialization") == "PASS"
        and payload.get("strict_consumer_readback") == "PASS"
        and payload.get("reconciliation") == "PASS"
        and payload.get("verify") == "PASS"
        and payload.get("ui_projection") == "PASS"
        and payload.get("day_count") == 7
    )
    if not required:
        raise ValueError("seven-day rehearsal receipt is incomplete or not PASS")
    return payload


def approval_readiness(
    *,
    state: CurrentDevelopmentState,
    rehearsal_path: Path | None,
    repository_root: Path,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "BLOCKED",
        "reason_code": "S2_V13_GOVERNANCE_BLOCKED",
        "blocking_questions": list(state.blocking_questions),
        "formal_run_created": False,
    }
    if state.current_plan != "stage_2_plan_v1.3" or state.stage3_locked is not True:
        result["reason_code"] = "S2_V13_STATE_CONTRACT_DRIFT"
        return result
    if state.blocking_questions:
        return result
    required_operations = {"FREEZE_AUTHORITY", "FREEZE_BINS", "PREFLIGHT", "RUN", "PUBLISH"}
    if not required_operations.issubset(state.allowed_operations):
        result["reason_code"] = "S2_V13_WRITE_OPERATIONS_NOT_AUTHORIZED"
        return result
    if rehearsal_path is None:
        result["reason_code"] = "S2_V13_REHEARSAL_RECEIPT_MISSING"
        return result
    try:
        validate_rehearsal_receipt(rehearsal_path, code_commit=current_commit(repository_root))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        result["reason_code"] = "S2_V13_REHEARSAL_RECEIPT_INVALID"
        result["reason"] = str(exc)
        return result
    if not repository_clean(repository_root):
        result["reason_code"] = "S2_V13_REPOSITORY_NOT_CLEAN"
        return result
    result.update({"status": "READY", "reason_code": "S2_V13_FORMAL_APPROVAL_READY"})
    return result


def validate_formal_approval(
    path: Path, *, state: CurrentDevelopmentState, repository_root: Path
) -> dict[str, Any]:
    payload = _safe_json(path)
    if not _self_hash_valid(payload, "approval_hash"):
        raise ValueError("formal run approval hash mismatch")
    if payload.get("schema_name") != APPROVAL_SCHEMA or payload.get("status") != "APPROVED":
        raise ValueError("formal run approval is not approved v1 evidence")
    if tuple(payload.get("tasks", ())) != TASKS:
        raise ValueError("formal run approval task order drift")
    if payload.get("governance_state_hash") != state.state_hash:
        raise ValueError("formal run approval governance hash drift")
    commit = current_commit(repository_root)
    if payload.get("code_commit") != commit:
        raise ValueError("formal run approval code commit drift")
    rehearsal_path = Path(str(payload.get("rehearsal_receipt_path", "")))
    rehearsal = validate_rehearsal_receipt(rehearsal_path, code_commit=commit)
    if payload.get("rehearsal_receipt_hash") != rehearsal["receipt_hash"]:
        raise ValueError("formal run approval rehearsal binding drift")
    readiness = approval_readiness(
        state=state,
        rehearsal_path=rehearsal_path,
        repository_root=repository_root,
    )
    if readiness["status"] != "READY":
        raise ValueError(f"formal run approval is not currently ready: {readiness['reason_code']}")
    return payload


class RetryableInterruption(RuntimeError):
    """An interruption that may continue from the last verified checkpoint."""


@dataclass(frozen=True)
class TaskHandoff:
    task_id: str
    run_id: str
    output_hash: str
    row_count: int
    consumer_readback: str
    reconciliation: str
    verify_status: str

    def __post_init__(self) -> None:
        if self.task_id not in TASKS:
            raise ValueError("handoff task is outside the approved chain")
        if len(self.output_hash) != 64:
            raise ValueError("handoff requires SHA-256 output binding")
        if self.row_count < 0:
            raise ValueError("handoff row count cannot be negative")
        if (
            self.consumer_readback,
            self.reconciliation,
            self.verify_status,
        ) != ("PASS", "PASS", "PASS"):
            raise ValueError("handoff requires read-back, reconciliation and Verify PASS")

    def payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "run_id": self.run_id,
            "output_hash": self.output_hash,
            "row_count": self.row_count,
            "consumer_readback": self.consumer_readback,
            "reconciliation": self.reconciliation,
            "verify_status": self.verify_status,
        }


class TaskAdapter(Protocol):
    def preflight(self) -> None: ...

    def run_or_resume(self) -> TaskHandoff: ...


def _initial_checkpoint(approval: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_name": SCHEMA,
        "stage_plan_version": "1.3",
        "status": "NOT_STARTED",
        "reason_code": "S2_V13_CHAIN_READY",
        "approval_hash": approval["approval_hash"],
        "code_commit": approval["code_commit"],
        "current_task": TASKS[0],
        "tasks": {
            task: {
                "status": "NOT_STARTED",
                "reason_code": "WAITING",
                "handoff": None,
            }
            for task in TASKS
        },
        "event_sequence": 0,
        "stage3_locked": True,
        "later_tasks_executed": False,
        "updated_at": datetime.now(UTC).isoformat(),
    }


class SuccessorSupervisor:
    def __init__(
        self,
        *,
        root: Path,
        approval_path: Path,
        repository_root: Path,
        adapters: Mapping[str, TaskAdapter],
        state_path: Path | None = None,
    ) -> None:
        if set(adapters) != set(TASKS):
            raise ValueError("supervisor requires one exact adapter for every approved task")
        self.root = root
        self.repository_root = repository_root
        self.state = (
            load_current_development_state()
            if state_path is None
            else load_current_development_state(state_path)
        )
        self.approval = validate_formal_approval(
            approval_path, state=self.state, repository_root=repository_root
        )
        self.adapters = adapters
        self.checkpoint_path = root / "checkpoint.json"
        self.lock_path = root / "chain.lock"

    def _checkpoint(self) -> dict[str, Any]:
        if self.checkpoint_path.exists():
            checkpoint = _safe_json(self.checkpoint_path)
            if (
                checkpoint.get("schema_name") != SCHEMA
                or checkpoint.get("approval_hash") != self.approval["approval_hash"]
            ):
                raise ValueError("successor checkpoint contract drift")
            return checkpoint
        checkpoint = _initial_checkpoint(self.approval)
        _atomic_json(self.checkpoint_path, checkpoint)
        return checkpoint

    def run_or_resume(self) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("S2_V13_SUCCESSOR_CHAIN_ALREADY_RUNNING") from exc
            checkpoint = self._checkpoint()
            if checkpoint["status"] == "COMPLETE":
                return checkpoint
            if checkpoint["status"] == "TERMINAL_FAILED":
                raise RuntimeError("terminal failed chain requires approved successor")
            try:
                for task in TASKS:
                    task_state = checkpoint["tasks"][task]
                    if task_state["status"] == "PASS":
                        continue
                    checkpoint.update(
                        {
                            "status": "PREFLIGHT",
                            "current_task": task,
                            "reason_code": f"{task}_PREFLIGHT",
                            "updated_at": datetime.now(UTC).isoformat(),
                        }
                    )
                    _atomic_json(self.checkpoint_path, checkpoint)
                    self.adapters[task].preflight()
                checkpoint["status"] = "IN_PROGRESS"
                for task in TASKS:
                    task_state = checkpoint["tasks"][task]
                    if task_state["status"] == "PASS":
                        continue
                    checkpoint.update(
                        {
                            "current_task": task,
                            "reason_code": f"{task}_RUNNING",
                            "updated_at": datetime.now(UTC).isoformat(),
                        }
                    )
                    task_state.update({"status": "IN_PROGRESS", "reason_code": f"{task}_RUNNING"})
                    _atomic_json(self.checkpoint_path, checkpoint)
                    handoff = self.adapters[task].run_or_resume()
                    if handoff.task_id != task:
                        raise ValueError("adapter returned another task handoff")
                    task_state.update(
                        {
                            "status": "PASS",
                            "reason_code": f"{task}_PASS",
                            "handoff": handoff.payload(),
                        }
                    )
                    checkpoint["event_sequence"] = int(checkpoint["event_sequence"]) + 1
                    _atomic_json(self.checkpoint_path, checkpoint)
            except RetryableInterruption as exc:
                checkpoint.update(
                    {
                        "status": "RETRYABLE_INTERRUPTED",
                        "reason_code": "S2_V13_RETRYABLE_INTERRUPTION",
                        "reason": str(exc),
                        "updated_at": datetime.now(UTC).isoformat(),
                    }
                )
                _atomic_json(self.checkpoint_path, checkpoint)
                return checkpoint
            except Exception as exc:
                checkpoint.update(
                    {
                        "status": "TERMINAL_FAILED",
                        "reason_code": "S2_V13_TERMINAL_FAILURE",
                        "reason": str(exc),
                        "updated_at": datetime.now(UTC).isoformat(),
                    }
                )
                _atomic_json(self.checkpoint_path, checkpoint)
                raise
            checkpoint.update(
                {
                    "status": "COMPLETE",
                    "reason_code": "S2_V13_CHAIN_COMPLETE",
                    "current_task": TASKS[-1],
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
            _atomic_json(self.checkpoint_path, checkpoint)
            return checkpoint
