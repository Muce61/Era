"""Machine-readable current governance state and fail-closed operation gate."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping, cast

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parents[4]
DEFAULT_CURRENT_STATE_PATH: Final[Path] = (
    REPOSITORY_ROOT / "configs/governance/current_development_state.json"
)

KNOWN_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
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
    }
)
_REQUIRED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_name",
        "schema_version",
        "current_stage",
        "current_plan",
        "current_task",
        "current_task_version",
        "task_status",
        "formal_t15_result_exists",
        "stage3_locked",
        "srp_execution_status",
        "allowed_operations",
        "blocked_operations",
        "blocking_questions",
        "sealed_tasks",
        "source_records",
        "state_hash",
    }
)


class GovernanceBlockedError(RuntimeError):
    """Raised before a governance-blocked write or execution operation can start."""

    def __init__(
        self,
        *,
        reason_code: str,
        operation: str,
        state: CurrentDevelopmentState,
    ) -> None:
        self.reason_code = reason_code
        self.operation = operation
        self.state_hash = state.state_hash
        self.blocking_questions = state.blocking_questions
        blockers = ",".join(state.blocking_questions) or "NONE"
        super().__init__(
            f"{reason_code}: operation={operation} current_task={state.current_task} "
            f"task_status={state.task_status} blockers={blockers} state_hash={state.state_hash}"
        )


def canonical_state_hash(payload: Mapping[str, object]) -> str:
    """Hash a state payload after removing its self-referential ``state_hash`` field."""

    normalized = {key: value for key, value in payload.items() if key != "state_hash"}
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _string_tuple(payload: Mapping[str, object], field: str) -> tuple[str, ...]:
    value = payload.get(field)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"current governance state {field} must be a non-empty string list")
    items = cast(list[str], value)
    if len(items) != len(set(items)):
        raise ValueError(f"current governance state {field} contains duplicates")
    return tuple(items)


def _required_string(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"current governance state {field} must be a non-empty string")
    return value


def _required_bool(payload: Mapping[str, object], field: str) -> bool:
    value = payload.get(field)
    if not isinstance(value, bool):
        raise ValueError(f"current governance state {field} must be boolean")
    return value


@dataclass(frozen=True)
class CurrentDevelopmentState:
    """The single machine-readable authority for currently permitted repository operations."""

    schema_name: str
    schema_version: str
    current_stage: str
    current_plan: str
    current_task: str
    current_task_version: str
    task_status: str
    formal_t15_result_exists: bool
    stage3_locked: bool
    srp_execution_status: str
    allowed_operations: tuple[str, ...]
    blocked_operations: tuple[str, ...]
    blocking_questions: tuple[str, ...]
    sealed_tasks: tuple[str, ...]
    source_records: tuple[str, ...]
    state_hash: str

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "current_stage": self.current_stage,
            "current_plan": self.current_plan,
            "current_task": self.current_task,
            "current_task_version": self.current_task_version,
            "task_status": self.task_status,
            "formal_t15_result_exists": self.formal_t15_result_exists,
            "stage3_locked": self.stage3_locked,
            "srp_execution_status": self.srp_execution_status,
            "allowed_operations": list(self.allowed_operations),
            "blocked_operations": list(self.blocked_operations),
            "blocking_questions": list(self.blocking_questions),
            "sealed_tasks": list(self.sealed_tasks),
            "source_records": list(self.source_records),
            "state_hash": self.state_hash,
        }

    def computed_hash(self) -> str:
        return canonical_state_hash(self.to_payload())

    def require_operation(self, operation: str) -> None:
        if operation not in KNOWN_OPERATIONS:
            raise ValueError(f"unknown governance operation: {operation}")
        if operation in self.blocked_operations or operation not in self.allowed_operations:
            reason_code = (
                "GOVERNANCE_CURRENT_TASK_STOPPED"
                if self.task_status == "STOPPED"
                else "GOVERNANCE_OPERATION_NOT_AUTHORIZED"
            )
            raise GovernanceBlockedError(
                reason_code=reason_code,
                operation=operation,
                state=self,
            )


def load_current_development_state(
    path: Path = DEFAULT_CURRENT_STATE_PATH,
) -> CurrentDevelopmentState:
    """Load and strictly validate the current governance state without modifying the repository."""

    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or unsafe current governance state: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("current governance state must be a JSON object")
    payload = cast(dict[str, object], raw)
    if set(payload) != _REQUIRED_FIELDS:
        missing = sorted(_REQUIRED_FIELDS.difference(payload))
        extra = sorted(set(payload).difference(_REQUIRED_FIELDS))
        raise ValueError(f"current governance state fields drift: missing={missing} extra={extra}")

    state = CurrentDevelopmentState(
        schema_name=_required_string(payload, "schema_name"),
        schema_version=_required_string(payload, "schema_version"),
        current_stage=_required_string(payload, "current_stage"),
        current_plan=_required_string(payload, "current_plan"),
        current_task=_required_string(payload, "current_task"),
        current_task_version=_required_string(payload, "current_task_version"),
        task_status=_required_string(payload, "task_status"),
        formal_t15_result_exists=_required_bool(payload, "formal_t15_result_exists"),
        stage3_locked=_required_bool(payload, "stage3_locked"),
        srp_execution_status=_required_string(payload, "srp_execution_status"),
        allowed_operations=_string_tuple(payload, "allowed_operations"),
        blocked_operations=_string_tuple(payload, "blocked_operations"),
        blocking_questions=_string_tuple(payload, "blocking_questions"),
        sealed_tasks=_string_tuple(payload, "sealed_tasks"),
        source_records=_string_tuple(payload, "source_records"),
        state_hash=_required_string(payload, "state_hash"),
    )
    if state.schema_name != "era-current-development-state" or state.schema_version != "1.0":
        raise ValueError("unsupported current governance state schema")
    if set(state.allowed_operations).intersection(state.blocked_operations):
        raise ValueError("governance operations cannot be both allowed and blocked")
    if not set(state.allowed_operations).union(state.blocked_operations).issubset(KNOWN_OPERATIONS):
        raise ValueError("current governance state contains an unknown operation")
    if state.state_hash != state.computed_hash():
        raise ValueError("current governance state hash mismatch")
    for record in state.source_records:
        record_path = Path(record)
        if record_path.is_absolute() or ".." in record_path.parts:
            raise ValueError(f"unsafe governance source record path: {record}")
    return state


def require_operation_allowed(
    operation: str,
    *,
    state_path: Path = DEFAULT_CURRENT_STATE_PATH,
) -> CurrentDevelopmentState:
    """Fail closed before an operation that the current state does not explicitly allow."""

    state = load_current_development_state(state_path)
    state.require_operation(operation)
    return state
