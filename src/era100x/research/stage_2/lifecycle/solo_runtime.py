"""Plan v1.10 solo formal runtime.

The runtime keeps the non-negotiable research gates while replacing task-local
governance bundles with one fsynced event ledger and one final verification.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import signal
import subprocess
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, cast

from era100x.research.stage_2.acceptance.canonical_json import (
    canonical_content_hash,
    canonical_json_bytes,
    read_canonical_json,
    sha256_file,
    write_canonical_json_exclusive,
)

from .solo_governance import TASK_DAG, TASK_ORDER, SoloRuntimePolicy
from .solo_inputs import InputsLock, load_inputs_lock

AUTHORITY_SCHEMA: Final = "s2p110-run-authority-v1"
RUN_SCHEMA: Final = "s2p110-run-v1"
EVENT_SCHEMA: Final = "s2p110-event-v1"
CHECKPOINT_SCHEMA: Final = "s2p110-task-checkpoint-v2"
TASK_FILES_SCHEMA: Final = "s2p110-task-files-v1"
MANIFEST_SCHEMA: Final = "s2p110-final-manifest-v1"
VERIFY_SCHEMA: Final = "s2p110-final-verify-v1"
RUN_ID: Final = re.compile(r"^stage2-s2p110-\d{8}T\d{6}Z-[0-9a-f]{12}$")
EVENT_TYPES: Final = frozenset(
    {
        "RUN_STARTED",
        "TASK_STARTED",
        "TASK_CHECKPOINTED",
        "TASK_COMPLETED",
        "TASK_INTERRUPTED",
        "RUN_FAILED",
        "RUN_COMPLETE_PRE_VERIFY",
    }
)
TASK_RESULT_FIELDS: Final = (
    "task_id",
    "attempt",
    "upstream_task_hashes",
    "output_root",
    "output_tree_hash",
    "row_count",
    "metrics",
    "checkpoint_tip_hash",
    "research_status",
    "execution_mode",
    "source_run_id",
    "source_verify_hash",
    "source_output_tree_hash",
    "adoption_binding_hash",
)


class RetryableTaskInterruption(RuntimeError):
    """A Task may resume from append-only checkpoints in a new attempt."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def repository_commit(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def repository_clean(root: Path) -> bool:
    return not subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=root, text=True
    ).strip()


def _self_hash(payload: Mapping[str, object], field: str) -> str:
    return canonical_content_hash({key: value for key, value in payload.items() if key != field})


def _verified_self_hash(payload: Mapping[str, object], field: str) -> str:
    claimed = payload.get(field)
    if not isinstance(claimed, str) or claimed != _self_hash(payload, field):
        raise ValueError(f"{field} mismatch")
    return claimed


def _safe_relative(value: object) -> Path:
    path = Path(str(value))
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe relative path: {value}")
    return path


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def output_tree(root: Path) -> tuple[str, list[dict[str, object]]]:
    """Hash one Task output tree, excluding mutable UI cache and scratch files."""

    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"Task output root is not a regular directory: {root}")
    paths = sorted(root.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ValueError(f"Task output tree contains a symlink: {root}")
    entries = [
        {
            "relative_path": str(path.relative_to(root)),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in paths
        if path.is_file()
        and not path.is_symlink()
        and not path.name.startswith("._")
        and "scratch" not in path.relative_to(root).parts
        and "checkpoints" not in path.relative_to(root).parts
    ]
    if not entries:
        raise ValueError("Task completed without immutable output")
    return canonical_content_hash(entries), entries


def seal_task_files(root: Path) -> tuple[str, list[dict[str, object]], str]:
    """Hash immutable Task files once and freeze their reusable descriptor."""

    tree_hash, entries = output_tree(root)
    payload: dict[str, object] = {
        "schema_name": TASK_FILES_SCHEMA,
        "schema_version": "1.0",
        "output_tree_hash": tree_hash,
        "files": entries,
    }
    payload["task_files_hash"] = _self_hash(payload, "task_files_hash")
    path = root / "task-files.json"
    write_canonical_json_exclusive(path, payload)
    return tree_hash, entries, str(payload["task_files_hash"])


def read_task_files(
    root: Path,
    *,
    expected_tree_hash: object,
    verify_contents: bool,
) -> tuple[dict[str, Any], ...]:
    """Validate a frozen descriptor; only final Verify rereads file contents."""

    path = root / "task-files.json"
    payload = read_canonical_json(path)
    _verified_self_hash(payload, "task_files_hash")
    files = payload.get("files")
    if (
        payload.get("schema_name") != TASK_FILES_SCHEMA
        or payload.get("output_tree_hash") != expected_tree_hash
        or not isinstance(files, list)
        or canonical_content_hash(files) != expected_tree_hash
    ):
        raise ValueError("Task files descriptor drift")
    rows = tuple(cast(dict[str, Any], item) for item in files)
    if verify_contents:
        for item in rows:
            target = root / _safe_relative(item["relative_path"])
            if (
                target.is_symlink()
                or not target.is_file()
                or sha256_file(target) != item["sha256"]
                or target.stat().st_size != item["size_bytes"]
            ):
                raise ValueError(f"Task output file Hash drift: {target}")
    return rows


@dataclass(frozen=True, slots=True)
class TaskResult:
    task_id: str
    attempt: int
    output_root: str
    output_tree_hash: str
    row_count: int
    metrics: dict[str, Any]
    checkpoint_tip_hash: str | None
    research_status: str
    execution_mode: str
    source_run_id: str | None
    source_verify_hash: str | None
    source_output_tree_hash: str | None
    adoption_binding_hash: str | None


TaskHandler = Callable[["TaskExecutionContext"], dict[str, Any]]


class EventLedger:
    """Fsynced append-only JSONL Hash chain."""

    def __init__(self, path: Path, *, run_id: str, authority_hash: str) -> None:
        self.path = path
        self.run_id = run_id
        self.authority_hash = authority_hash
        self._cache: list[dict[str, Any]] | None = None

    def read(self) -> tuple[dict[str, Any], ...]:
        if self._cache is not None:
            return tuple(self._cache)
        if not self.path.exists():
            self._cache = []
            return ()
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError("event ledger is not a regular file")
        events: list[dict[str, Any]] = []
        previous: str | None = None
        with self.path.open("rb") as handle:
            for ordinal, line in enumerate(handle, start=1):
                if not line.endswith(b"\n") or line == b"\n":
                    raise ValueError("event ledger line is not terminal-LF canonical JSON")
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError("event ledger entry must be an object")
                if canonical_json_bytes(payload) + b"\n" != line:
                    raise ValueError("event ledger line is not canonical JSON")
                event_hash = _verified_self_hash(payload, "event_hash")
                if (
                    payload.get("schema_name") != EVENT_SCHEMA
                    or payload.get("ordinal") != ordinal
                    or payload.get("previous_event_hash") != previous
                    or payload.get("run_id") != self.run_id
                    or payload.get("authority_hash") != self.authority_hash
                    or payload.get("event_type") not in EVENT_TYPES
                ):
                    raise ValueError("event ledger Hash chain or identity drift")
                previous = event_hash
                events.append(cast(dict[str, Any], payload))
        self._cache = events
        return tuple(events)

    def append(self, event_type: str, **fields: object) -> dict[str, Any]:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unsupported event type: {event_type}")
        prior = self.read()
        payload: dict[str, object] = {
            "schema_name": EVENT_SCHEMA,
            "schema_version": "1.0",
            "ordinal": len(prior) + 1,
            "previous_event_hash": prior[-1]["event_hash"] if prior else None,
            "run_id": self.run_id,
            "authority_hash": self.authority_hash,
            "event_type": event_type,
            "recorded_at": _now(),
            **fields,
        }
        payload["event_hash"] = _self_hash(payload, "event_hash")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as handle:
            handle.write(canonical_json_bytes(payload) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        if self._cache is None:
            self._cache = list(prior)
        self._cache.append(cast(dict[str, Any], payload))
        return payload


class TaskExecutionContext:
    """Governance-free interface supplied to one fixed research handler."""

    def __init__(
        self,
        *,
        task_id: str,
        attempt: int,
        run_root: Path,
        repository_root: Path,
        authority: dict[str, Any],
        inputs_lock: InputsLock,
        completed: dict[str, dict[str, Any]],
        ledger: EventLedger,
    ) -> None:
        if task_id not in TASK_ORDER:
            raise ValueError("unknown Plan v1.10 Task identity")
        self.task_id = task_id
        self.attempt = attempt
        self.run_root = run_root
        self.repository_root = repository_root
        self.authority = authority
        self.authority_hash = str(authority["authority_hash"])
        self.code_commit = str(authority["code_commit"])
        self.inputs_lock = inputs_lock
        self.completed = completed
        self.upstream_hashes = {
            task: str(completed[task]["output_tree_hash"]) for task in TASK_DAG[task_id]
        }
        self.attempt_root = run_root / "tasks" / task_id / f"attempt-{attempt:04d}"
        self.data_root = self.attempt_root / "data"
        self.checkpoints = self.attempt_root / "checkpoints"
        self.resume_root = run_root / "resume" / task_id
        self._ledger = ledger
        self._checkpoint_tip_hash: str | None = None
        self.resume_state = self._load_resume_state()

    @property
    def checkpoint_tip_hash(self) -> str | None:
        return self._checkpoint_tip_hash

    def upstream_root(self, task_id: str) -> Path:
        event = self.completed.get(task_id)
        if event is None or task_id not in TASK_DAG[self.task_id]:
            raise ValueError(f"Task missing declared upstream: {task_id}")
        root = self.run_root / _safe_relative(event["output_root"])
        read_task_files(
            root,
            expected_tree_hash=event["output_tree_hash"],
            verify_contents=False,
        )
        return root

    def upstream_output(self, task_id: str) -> dict[str, Any]:
        return read_canonical_json(self.upstream_root(task_id) / "output.json")

    def resolve_run_path(self, value: object) -> Path:
        """Resolve one stored run-relative path and reject paths outside the Run."""

        path = Path(str(value))
        target = path if path.is_absolute() else self.run_root / path
        resolved = target.resolve()
        try:
            resolved.relative_to(self.run_root.resolve())
        except ValueError as exc:
            raise ValueError(f"Task output path escapes the Run: {value}") from exc
        return resolved

    def adopted_binding(self, task_id: str) -> dict[str, Any]:
        matches = [
            item
            for item in self.inputs_lock.adopted_task_bindings
            if item.get("task_id") == task_id
        ]
        if len(matches) != 1:
            raise ValueError(f"sealed adoption binding missing or duplicated: {task_id}")
        return dict(matches[0])

    def resolve_adopted_path(self, task_id: str, value: object) -> Path:
        binding = self.adopted_binding(task_id)
        root_value = binding.get("source_artifact_root")
        if not isinstance(root_value, str):
            raise ValueError(f"sealed adoption has no artifact root: {task_id}")
        root = Path(root_value).resolve()
        path = Path(str(value))
        target = path.resolve() if path.is_absolute() else (root / path).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"adopted path escapes sealed artifact: {task_id}") from exc
        if target.is_symlink() or not target.exists():
            raise ValueError(f"adopted path is missing or symlinked: {target}")
        return target

    def _load_resume_state(self) -> dict[str, Any] | None:
        interrupted = [
            event
            for event in self._ledger.read()
            if event.get("event_type") == "TASK_INTERRUPTED"
            and event.get("task_id") == self.task_id
        ]
        if not interrupted:
            return None
        prior = interrupted[-1]
        checkpoint_hash = prior.get("checkpoint_tip_hash")
        if not isinstance(checkpoint_hash, str):
            raise ValueError("interrupted Task lacks a checkpoint tip")
        prior_attempt = int(prior["attempt"])
        root = (
            self.run_root / "tasks" / self.task_id / f"attempt-{prior_attempt:04d}" / "checkpoints"
        )
        matches = []
        for path in sorted(root.glob("*.json")):
            payload = read_canonical_json(path)
            if payload.get("checkpoint_hash") == checkpoint_hash:
                matches.append(payload)
        if len(matches) != 1:
            raise ValueError("interrupted checkpoint tip cannot be uniquely recovered")
        payload = matches[0]
        _verified_self_hash(payload, "checkpoint_hash")
        if (
            payload.get("schema_name") != CHECKPOINT_SCHEMA
            or payload.get("authority_hash") != self.authority_hash
            or payload.get("code_commit") != self.code_commit
            or payload.get("task_id") != self.task_id
        ):
            raise ValueError("checkpoint resume binding drift")
        return payload

    def progress(self, payload: dict[str, Any]) -> None:
        ordinal = len(tuple(self.checkpoints.glob("*.json"))) + 1
        body: dict[str, Any] = {
            "schema_name": CHECKPOINT_SCHEMA,
            "schema_version": "2.0",
            "task_id": self.task_id,
            "attempt": self.attempt,
            "ordinal": ordinal,
            "previous_checkpoint_hash": self._checkpoint_tip_hash,
            "authority_hash": self.authority_hash,
            "code_commit": self.code_commit,
            "resume_cursor": payload.get("resume_cursor"),
            "completed_partition_ids": payload.get("completed_partition_ids", []),
            "completed_partition_hashes": payload.get("completed_partition_hashes", {}),
            "producer_state_hash": payload.get("producer_state_hash"),
            "deterministic_merge_order": payload.get(
                "deterministic_merge_order", "INSTRUMENT_DATE_EPISODE_ID"
            ),
            "remaining_units": payload.get(
                "remaining_units",
                max(
                    int(payload.get("total_units", 0)) - int(payload.get("processed_units", 0)),
                    0,
                ),
            ),
            **payload,
        }
        body["checkpoint_hash"] = _self_hash(body, "checkpoint_hash")
        write_canonical_json_exclusive(
            self.checkpoints / f"{ordinal:06d}.json",
            body,
        )
        self._checkpoint_tip_hash = str(body["checkpoint_hash"])
        self._ledger.append(
            "TASK_CHECKPOINTED",
            task_id=self.task_id,
            attempt=self.attempt,
            checkpoint_hash=self._checkpoint_tip_hash,
            metrics=payload,
        )
        progress_root = self.run_root / "progress"
        progress_root.mkdir(parents=True, exist_ok=True)
        temporary = progress_root / "latest.tmp"
        temporary.write_bytes(canonical_json_bytes(body) + b"\n")
        os.replace(temporary, progress_root / "latest.json")


def freeze_authority(
    *,
    policy: SoloRuntimePolicy,
    inputs_lock: InputsLock,
    repository_root: Path,
    evidence_root: Path,
    approved_by: str,
    approval_source: str,
    approved_commit: str,
    approved_inputs_lock_hash: str,
    approved_adoption_bundle_hash: str | None = None,
    approved_at: str | None = None,
) -> Path:
    """Fsync the human-approved Authority before any Run ID may exist."""

    if not repository_clean(repository_root):
        raise ValueError("formal Authority requires a clean repository")
    if repository_commit(repository_root) != approved_commit:
        raise ValueError("approved commit does not match current clean HEAD")
    verified_inputs = load_inputs_lock(inputs_lock.path, verify_files=True)
    if (
        verified_inputs.inputs_lock_hash != inputs_lock.inputs_lock_hash
        or approved_inputs_lock_hash != inputs_lock.inputs_lock_hash
    ):
        raise ValueError("approved inputs lock Hash mismatch")
    if approved_adoption_bundle_hash != inputs_lock.adoption_bundle_hash:
        raise ValueError("approved adoption bundle Hash mismatch")
    authorities = evidence_root / "authorities"
    approval_identity = {
        "approved_by": approved_by,
        "approval_source": approval_source,
        "approved_commit": approved_commit,
        "inputs_lock_hash": inputs_lock.inputs_lock_hash,
        "adoption_bundle_hash": inputs_lock.adoption_bundle_hash,
        "policy_hash": policy.policy_hash,
        "preregistration_hash": policy.preregistration_hash,
        "contract_bundle_hash": policy.contract_bundle_hash,
    }
    for existing in sorted(authorities.glob("authority-*.json")):
        existing_payload = read_canonical_json(existing)
        if all(existing_payload.get(key) == value for key, value in approval_identity.items()):
            _verified_self_hash(existing_payload, "authority_hash")
            if _authority_has_run(evidence_root, str(existing_payload["authority_hash"])):
                raise ValueError("one Authority can create at most one Run")
            return existing
    payload: dict[str, object] = {
        "schema_name": AUTHORITY_SCHEMA,
        "schema_version": "1.0",
        "stage_plan_version": "1.10",
        **approval_identity,
        "code_commit": approved_commit,
        "approval_time": approved_at or _now(),
        "input_content_hash_verification": "PASS_ONCE_BEFORE_AUTHORITY",
        "input_content_hash_verified_at": _now(),
        "inputs_lock_path": str(inputs_lock.path),
        "preregistration_path": str(policy.payload["preregistration_path"]),
        "contract_hashes": dict(sorted(policy.contract_hashes.items())),
        "task_order": list(TASK_ORDER),
        "task_dag": {task: list(dependencies) for task, dependencies in TASK_DAG.items()},
        "handler_registry": "FIXED_COMMIT_BOUND_S2P110_T11_T20",
        "execution_limit": "S2P110-T20",
        "historical_execution_claim": False,
        "stage3_locked": True,
    }
    payload["authority_hash"] = _self_hash(payload, "authority_hash")
    target = authorities / f"authority-{payload['authority_hash']}.json"
    write_canonical_json_exclusive(target, payload)
    _fsync_directory(target.parent)
    return target


def validate_authority(
    path: Path,
    *,
    policy: SoloRuntimePolicy,
    repository_root: Path,
) -> tuple[dict[str, Any], InputsLock]:
    payload = read_canonical_json(path)
    _verified_self_hash(payload, "authority_hash")
    inputs_path = Path(str(payload.get("inputs_lock_path", "")))
    if not inputs_path.is_absolute():
        raise ValueError("Authority inputs lock path must be absolute")
    inputs_lock = load_inputs_lock(inputs_path)
    if (
        payload.get("schema_name") != AUTHORITY_SCHEMA
        or payload.get("stage_plan_version") != "1.10"
        or payload.get("code_commit") != repository_commit(repository_root)
        or payload.get("approved_commit") != repository_commit(repository_root)
        or payload.get("policy_hash") != policy.policy_hash
        or payload.get("preregistration_hash") != policy.preregistration_hash
        or payload.get("contract_bundle_hash") != policy.contract_bundle_hash
        or payload.get("contract_hashes") != dict(sorted(policy.contract_hashes.items()))
        or payload.get("inputs_lock_hash") != inputs_lock.inputs_lock_hash
        or payload.get("adoption_bundle_hash") != inputs_lock.adoption_bundle_hash
        or payload.get("task_order") != list(TASK_ORDER)
        or payload.get("task_dag")
        != {task: list(dependencies) for task, dependencies in TASK_DAG.items()}
        or payload.get("execution_limit") != "S2P110-T20"
        or payload.get("historical_execution_claim") is not False
        or payload.get("input_content_hash_verification") != "PASS_ONCE_BEFORE_AUTHORITY"
        or payload.get("stage3_locked") is not True
        or not repository_clean(repository_root)
    ):
        raise ValueError("Plan v1.10 Authority binding drift")
    return payload, inputs_lock


def _all_run_roots(evidence_root: Path) -> Iterator[Path]:
    for state in ("runs", "candidates", "published", "failed"):
        root = evidence_root / state
        if root.is_dir():
            yield from (path for path in root.iterdir() if path.is_dir())


def _authority_has_run(evidence_root: Path, authority_hash: str) -> bool:
    for root in _all_run_roots(evidence_root):
        run_path = root / "run.json"
        if (
            run_path.is_file()
            and read_canonical_json(run_path).get("authority_hash") == authority_hash
        ):
            return True
    return False


@contextmanager
def unique_run_lock(evidence_root: Path) -> Iterator[None]:
    path = evidence_root / "operations" / "run.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Plan v1.10 unique Run lock is held") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _reserve_run(
    *,
    evidence_root: Path,
    authority: dict[str, Any],
) -> Path:
    authority_hash = str(authority["authority_hash"])
    if _authority_has_run(evidence_root, authority_hash):
        raise ValueError("one Authority can reserve only one Run")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"stage2-s2p110-{stamp}-{authority_hash[:12]}"
    if not RUN_ID.fullmatch(run_id):
        raise AssertionError("generated invalid Plan v1.10 Run ID")
    run_root = evidence_root / "runs" / run_id
    payload: dict[str, object] = {
        "schema_name": RUN_SCHEMA,
        "schema_version": "1.0",
        "run_id": run_id,
        "stage_plan_version": "1.10",
        "authority_hash": authority_hash,
        "created_at": _now(),
        "historical_execution_claim": False,
        "stage3_locked": True,
    }
    payload["run_hash"] = _self_hash(payload, "run_hash")
    write_canonical_json_exclusive(run_root / "run.json", payload)
    _fsync_directory(run_root)
    return run_root


def _validate_run(run_root: Path, authority_hash: str) -> dict[str, Any]:
    payload = read_canonical_json(run_root / "run.json")
    if (
        payload.get("schema_name") != RUN_SCHEMA
        or payload.get("run_id") != run_root.name
        or payload.get("authority_hash") != authority_hash
        or payload.get("stage3_locked") is not True
    ):
        raise ValueError("Plan v1.10 Run identity drift")
    _verified_self_hash(payload, "run_hash")
    return payload


def _completed_events(
    events: tuple[dict[str, Any], ...],
    *,
    run_root: Path,
) -> dict[str, dict[str, Any]]:
    completed: dict[str, dict[str, Any]] = {}
    for event in events:
        if event["event_type"] != "TASK_COMPLETED":
            continue
        task_id = str(event["task_id"])
        if task_id in completed:
            raise ValueError(f"duplicate Task completion: {task_id}")
        expected_dependencies = {
            task: completed[task]["output_tree_hash"] for task in TASK_DAG[task_id]
        }
        if event.get("upstream_task_hashes") != expected_dependencies:
            raise ValueError(f"Task upstream completion drift: {task_id}")
        root = run_root / _safe_relative(event["output_root"])
        read_task_files(
            root,
            expected_tree_hash=event.get("output_tree_hash"),
            verify_contents=False,
        )
        completed[task_id] = event
    return completed


def _attempt_number(events: tuple[dict[str, Any], ...], task_id: str) -> int:
    attempts = [
        int(event["attempt"])
        for event in events
        if event.get("task_id") == task_id and "attempt" in event
    ]
    return max(attempts, default=0) + 1


def _task_results(
    completed: Mapping[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [{key: event[key] for key in TASK_RESULT_FIELDS} for event in completed.values()]


def _normalize_handler_payload(payload: dict[str, Any]) -> dict[str, Any]:
    from era100x.research.stage_2.rerun.strict_json import strict_json_value

    value = strict_json_value(payload)
    if not isinstance(value, dict):
        raise TypeError("Task handler result must normalize to an object")
    return cast(dict[str, Any], value)


def _run_relative_paths(value: object, *, run_root: Path) -> object:
    """Make every output path under the active Run stable across atomic moves."""

    if isinstance(value, dict):
        return {
            str(key): _run_relative_paths(item, run_root=run_root) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_run_relative_paths(item, run_root=run_root) for item in value]
    if isinstance(value, str):
        path = Path(value)
        if path.is_absolute():
            try:
                return str(path.relative_to(run_root))
            except ValueError:
                return value
    return value


def _append_attempt_log(
    run_root: Path,
    *,
    task_id: str,
    attempt: int,
    status: str,
    reason_code: str | None = None,
) -> None:
    path = run_root / "logs" / task_id / f"attempt-{attempt:04d}.jsonl"
    payload = {
        "task_id": task_id,
        "attempt": attempt,
        "status": status,
        "reason_code": reason_code,
        "recorded_at": _now(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(canonical_json_bytes(payload) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def _retryable_task_signal_boundary() -> Iterator[None]:
    """Turn an operator SIGTERM into the same checkpointed path as Ctrl-C."""

    prior = signal.getsignal(signal.SIGTERM)

    def interrupt(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, prior)


def _execute_task(
    *,
    handler: TaskHandler,
    task_id: str,
    attempt: int,
    run_root: Path,
    repository_root: Path,
    authority: dict[str, Any],
    inputs_lock: InputsLock,
    completed: dict[str, dict[str, Any]],
    ledger: EventLedger,
) -> dict[str, Any]:
    ctx = TaskExecutionContext(
        task_id=task_id,
        attempt=attempt,
        run_root=run_root,
        repository_root=repository_root,
        authority=authority,
        inputs_lock=inputs_lock,
        completed=completed,
        ledger=ledger,
    )
    ctx.attempt_root.mkdir(parents=True, exist_ok=False)
    ledger.append(
        "TASK_STARTED",
        task_id=task_id,
        attempt=attempt,
        upstream_task_hashes=dict(sorted(ctx.upstream_hashes.items())),
    )
    _append_attempt_log(
        run_root,
        task_id=task_id,
        attempt=attempt,
        status="STARTED",
    )
    try:
        with _retryable_task_signal_boundary():
            payload = _normalize_handler_payload(handler(ctx))
    except KeyboardInterrupt as exc:
        if ctx.checkpoint_tip_hash is None:
            _append_attempt_log(
                run_root,
                task_id=task_id,
                attempt=attempt,
                status="FAILED",
                reason_code="INTERRUPTED_BEFORE_CHECKPOINT",
            )
            raise
        _append_attempt_log(
            run_root,
            task_id=task_id,
            attempt=attempt,
            status="INTERRUPTED",
            reason_code="OPERATOR_SIGNAL_AFTER_CHECKPOINT",
        )
        ledger.append(
            "TASK_INTERRUPTED",
            task_id=task_id,
            attempt=attempt,
            checkpoint_tip_hash=ctx.checkpoint_tip_hash,
            reason_code="OPERATOR_SIGNAL_AFTER_CHECKPOINT",
        )
        raise RetryableTaskInterruption("operator interrupted a checkpointed Task") from exc
    except RetryableTaskInterruption:
        _append_attempt_log(
            run_root,
            task_id=task_id,
            attempt=attempt,
            status="INTERRUPTED",
            reason_code="RETRYABLE_TASK_INTERRUPTION",
        )
        ledger.append(
            "TASK_INTERRUPTED",
            task_id=task_id,
            attempt=attempt,
            checkpoint_tip_hash=ctx.checkpoint_tip_hash,
            reason_code="RETRYABLE_TASK_INTERRUPTION",
        )
        raise
    except BaseException as exc:
        _append_attempt_log(
            run_root,
            task_id=task_id,
            attempt=attempt,
            status="FAILED",
            reason_code=type(exc).__name__,
        )
        raise
    payload.update(
        {
            "task_id": task_id,
            "stage_plan_version": "1.10",
            "attempt": attempt,
            "historical_execution_claim": False,
            "stage3_locked": True,
        }
    )
    payload.setdefault("artifact_attempt_root", str(ctx.attempt_root))
    payload.setdefault("artifact_data_root", str(ctx.data_root))
    output_path = ctx.attempt_root / "output.json"
    payload.setdefault("artifact_output_path", str(output_path))
    payload = cast(
        dict[str, Any],
        _run_relative_paths(payload, run_root=run_root),
    )
    write_canonical_json_exclusive(output_path, payload)
    tree_hash, _, task_files_hash = seal_task_files(ctx.attempt_root)
    execution_mode = str(payload.get("execution_mode", "EXECUTED_NEW"))
    result = TaskResult(
        task_id=task_id,
        attempt=attempt,
        output_root=str(ctx.attempt_root.relative_to(run_root)),
        output_tree_hash=tree_hash,
        row_count=int(payload.get("row_count", 0)),
        metrics=cast(dict[str, Any], payload.get("metrics", {})),
        checkpoint_tip_hash=ctx.checkpoint_tip_hash,
        research_status=str(
            payload.get("research_status", payload.get("research_result", "COMPLETE"))
        ),
        execution_mode=execution_mode,
        source_run_id=cast(str | None, payload.get("source_run_id")),
        source_verify_hash=cast(str | None, payload.get("source_verify_hash")),
        source_output_tree_hash=cast(str | None, payload.get("source_output_tree_hash")),
        adoption_binding_hash=cast(str | None, payload.get("adoption_binding_hash")),
    )
    _append_attempt_log(
        run_root,
        task_id=task_id,
        attempt=attempt,
        status="COMPLETED",
    )
    return ledger.append(
        "TASK_COMPLETED",
        task_id=result.task_id,
        attempt=result.attempt,
        upstream_task_hashes=dict(sorted(ctx.upstream_hashes.items())),
        output_root=result.output_root,
        output_tree_hash=result.output_tree_hash,
        row_count=result.row_count,
        metrics=result.metrics,
        checkpoint_tip_hash=result.checkpoint_tip_hash,
        research_status=result.research_status,
        execution_mode=result.execution_mode,
        source_run_id=result.source_run_id,
        source_verify_hash=result.source_verify_hash,
        source_output_tree_hash=result.source_output_tree_hash,
        adoption_binding_hash=result.adoption_binding_hash,
        task_files_hash=task_files_hash,
    )


def _build_final_manifest(
    *,
    run_root: Path,
    authority: dict[str, Any],
    inputs_lock: InputsLock,
    events: tuple[dict[str, Any], ...],
) -> Path:
    completed = _completed_events(events, run_root=run_root)
    if tuple(completed) != TASK_ORDER:
        raise ValueError("final Manifest requires exactly ten completed Tasks")
    attempts = [
        {
            "event_type": event["event_type"],
            "task_id": event.get("task_id"),
            "attempt": event.get("attempt"),
            "event_hash": event["event_hash"],
            "reason_code": event.get("reason_code"),
        }
        for event in events
        if event["event_type"] in {"TASK_STARTED", "TASK_INTERRUPTED", "TASK_COMPLETED"}
    ]
    output_files: list[dict[str, object]] = []
    for task_id, event in completed.items():
        root = run_root / _safe_relative(event["output_root"])
        entries = read_task_files(
            root,
            expected_tree_hash=event["output_tree_hash"],
            verify_contents=False,
        )
        output_files.extend(
            {
                **entry,
                "relative_path": str(root.relative_to(run_root) / str(entry["relative_path"])),
                "task_id": task_id,
            }
            for entry in entries
        )
    t20 = read_canonical_json(
        run_root / _safe_relative(completed["S2P110-T20"]["output_root"]) / "output.json"
    )
    payload: dict[str, object] = {
        "schema_name": MANIFEST_SCHEMA,
        "schema_version": "1.0",
        "stage_plan_version": "1.10",
        "experiment_id": run_root.name,
        "strategy_variant": "STAGE2_SUCCESSOR_H2_UNCHANGED_LIFECYCLE_DUAL_TRACK",
        "primary_hypothesis": "BTC_T2_20BP_TARGET_FIRST_VS_25BP_STOP_FIRST_INCREMENTAL_EDGE",
        "primary_instrument": "BTCUSDT",
        "frozen_data_ranges": ["2020-01-01/2026-07-04"],
        "locked_historical_replay_range": "2020-01-01/2026-07-04",
        "forward_holdout_start": "FROZEN_EXISTING_STAGE2_SPLIT",
        "feature_config_hash": inputs_lock.binding_hashes["matching_contract_hash"],
        "event_config_hash": inputs_lock.binding_hashes["primary_config_hash"],
        "cost_scenario_id": "NOT_EXECUTED_STAGE3_LOCKED",
        "primary_metric": "MATCHED_EVENT_MINUS_CONTROL_TARGET_FIRST_RATE",
        "probability_metric_name": "CLUSTER_BOOTSTRAP_INCREMENTAL_DELTA",
        "execution_scenario_definition": "HISTORICAL_RESEARCH_NOT_EXECUTION",
        "execution_scenario_distribution_source": "NOT_APPLICABLE_STAGE2",
        "cluster_definition": inputs_lock.binding_hashes["cluster_contract_hash"],
        "pass_rule": "ALL_PREREGISTERED_F1_F10_PASS_INCLUDING_OVERALL_CI_LOWER_GT_0",
        "fail_rule": "ANY_PREREGISTERED_F1_F10_FAIL_INCLUDING_OVERALL_CI_LOWER_LTE_0",
        "all_parameter_values_attempted": {
            "primary": {
                "instrument": "BTCUSDT",
                "time_combination": "T2",
                "target_bp": 20,
                "stop_bp": 25,
                "ambiguous": "FAILURE",
            },
            "conditional_matrix": {
                "cell_count": 30,
                "matching": "EXISTING_FROZEN_CONTRACT",
                "quintile_fit": "TRAIN_ONLY",
                "seed_hash": inputs_lock.binding_hashes["fixed_seed_hash"],
                "cluster_hash": inputs_lock.binding_hashes["cluster_contract_hash"],
            },
            "lifecycle": {
                "tracks": [
                    "PURE_TRADES_COMPARATOR",
                    "CONTRACT_PRICE_OHLC_PRIMARY",
                ],
                "max_horizon": "SEVEN_DAYS_RIGHT_CENSORED",
                "intrasecond_order_known": False,
                "synthetic_execution": False,
            },
        },
        "code_commit": authority["code_commit"],
        "data_manifest_hash": inputs_lock.inputs_lock_hash,
        "result": t20.get("research_decision", "STAGE2_REVIEW_REQUIRED_NO_STAGE3_AUTHORITY"),
        "researcher_decision": t20.get(
            "research_decision", "STAGE2_REVIEW_REQUIRED_NO_STAGE3_AUTHORITY"
        ),
        "authority_hash": authority["authority_hash"],
        "policy_hash": authority["policy_hash"],
        "preregistration_hash": authority["preregistration_hash"],
        "contract_bundle_hash": authority["contract_bundle_hash"],
        "inputs_lock_path": str(inputs_lock.path),
        "inputs_lock_hash": inputs_lock.inputs_lock_hash,
        "adoption_bundle_hash": inputs_lock.adoption_bundle_hash,
        "adopted_task_bindings": list(inputs_lock.adopted_task_bindings),
        "evidence_mode": inputs_lock.evidence_mode,
        "input_bindings": inputs_lock.binding_hashes,
        "contract_price_source_audit": inputs_lock.source_audit,
        "task_order": list(TASK_ORDER),
        "task_results": _task_results(completed),
        "execution_mode_counts": {
            mode: sum(event["execution_mode"] == mode for event in completed.values())
            for mode in ("SEALED_ADOPTION", "EXECUTED_NEW")
        },
        "all_attempts": attempts,
        "output_files": output_files,
        "event_chain_tip_hash": events[-1]["event_hash"],
        "historical_h2_primary": "PRIMARY_FAILED",
        "historical_lifecycle": "INCONCLUSIVE_SOURCE_GAP_CENSORING",
        "historical_execution_claim": False,
        "stage3_locked": True,
    }
    payload["manifest_hash"] = _self_hash(payload, "manifest_hash")
    path = run_root / "final" / "final-manifest.json"
    write_canonical_json_exclusive(path, payload)
    report = run_root / "final" / "final-report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("xb") as handle:
        handle.write(
            (
                "# Stage 2 Plan v1.10 Final Report\n\n"
                f"- Run: `{run_root.name}`\n"
                f"- Result: `{payload['result']}`\n"
                "- Historical H2 Primary: `PRIMARY_FAILED` (unchanged)\n"
                "- Historical lifecycle: `INCONCLUSIVE_SOURCE_GAP_CENSORING` (unchanged)\n"
                "- Stage 3: `LOCKED`\n"
            ).encode()
        )
        handle.flush()
        os.fsync(handle.fileno())
    return path


def _verify_attempt_topology(
    *,
    candidate_root: Path,
    events: tuple[dict[str, Any], ...],
) -> tuple[int, int]:
    start_rows = [
        (str(event["task_id"]), int(event["attempt"]))
        for event in events
        if event["event_type"] == "TASK_STARTED"
    ]
    terminal_rows = [
        (str(event["task_id"]), int(event["attempt"]))
        for event in events
        if event["event_type"] in {"TASK_COMPLETED", "TASK_INTERRUPTED"}
    ]
    starts = set(start_rows)
    terminals = set(terminal_rows)
    if (
        len(start_rows) != len(starts)
        or len(terminal_rows) != len(terminals)
        or starts != terminals
    ):
        raise ValueError("candidate contains unterminated or terminal-without-start Task attempt")
    task_root = candidate_root / "tasks"
    disk_attempts: set[tuple[str, int]] = set()
    for task_path in sorted(task_root.iterdir()):
        if not task_path.is_dir() or task_path.name not in TASK_ORDER:
            raise ValueError(f"candidate orphan Task directory: {task_path.name}")
        for attempt_path in sorted(task_path.iterdir()):
            match = re.fullmatch(r"attempt-(\d{4})", attempt_path.name)
            if not attempt_path.is_dir() or match is None:
                raise ValueError(f"candidate orphan Task attempt: {attempt_path}")
            identity = (task_path.name, int(match.group(1)))
            disk_attempts.add(identity)
            previous: str | None = None
            for ordinal, checkpoint_path in enumerate(
                sorted((attempt_path / "checkpoints").glob("*.json")),
                start=1,
            ):
                checkpoint = read_canonical_json(checkpoint_path)
                checkpoint_hash = _verified_self_hash(checkpoint, "checkpoint_hash")
                if (
                    checkpoint.get("schema_name") != CHECKPOINT_SCHEMA
                    or checkpoint.get("task_id") != task_path.name
                    or checkpoint.get("attempt") != identity[1]
                    or checkpoint.get("ordinal") != ordinal
                    or checkpoint.get("previous_checkpoint_hash") != previous
                    or "resume_cursor" not in checkpoint
                    or not isinstance(checkpoint.get("completed_partition_ids"), list)
                    or not isinstance(checkpoint.get("completed_partition_hashes"), dict)
                    or "producer_state_hash" not in checkpoint
                    or "deterministic_merge_order" not in checkpoint
                    or "remaining_units" not in checkpoint
                ):
                    raise ValueError("candidate Task checkpoint chain drift")
                previous = checkpoint_hash
    if disk_attempts != starts:
        raise ValueError("candidate Task attempt directories and event ledger disagree")
    for task_id, attempt in starts:
        log_path = candidate_root / "logs" / task_id / f"attempt-{attempt:04d}.jsonl"
        if log_path.is_symlink() or not log_path.is_file():
            raise ValueError("candidate Task attempt log is missing")
        rows = log_path.read_bytes().splitlines(keepends=True)
        if not rows:
            raise ValueError("candidate Task attempt log is empty")
        parsed: list[dict[str, Any]] = []
        for row in rows:
            value = json.loads(row)
            if (
                not isinstance(value, dict)
                or canonical_json_bytes(value) + b"\n" != row
                or value.get("task_id") != task_id
                or value.get("attempt") != attempt
            ):
                raise ValueError("candidate Task attempt log drift")
            parsed.append(cast(dict[str, Any], value))
        terminal_type = next(
            event["event_type"]
            for event in events
            if event.get("task_id") == task_id
            and event.get("attempt") == attempt
            and event["event_type"] in {"TASK_COMPLETED", "TASK_INTERRUPTED"}
        )
        expected_log_status = "COMPLETED" if terminal_type == "TASK_COMPLETED" else "INTERRUPTED"
        if parsed[0].get("status") != "STARTED" or parsed[-1].get("status") != expected_log_status:
            raise ValueError("candidate Task attempt log terminal state drift")
    interrupted = sum(event["event_type"] == "TASK_INTERRUPTED" for event in events)
    return len(disk_attempts), interrupted


def verify_candidate(
    *,
    candidate_root: Path,
    authority_path: Path,
    policy: SoloRuntimePolicy,
    repository_root: Path,
) -> Path:
    authority, inputs_lock = validate_authority(
        authority_path,
        policy=policy,
        repository_root=repository_root,
    )
    _validate_run(candidate_root, str(authority["authority_hash"]))
    ledger = EventLedger(
        candidate_root / "events.jsonl",
        run_id=candidate_root.name,
        authority_hash=str(authority["authority_hash"]),
    )
    events = ledger.read()
    if (
        not events
        or events[0]["event_type"] != "RUN_STARTED"
        or events[-1]["event_type"] != "RUN_COMPLETE_PRE_VERIFY"
        or any(event["event_type"] == "RUN_FAILED" for event in events)
    ):
        raise ValueError("candidate event chain is not complete")
    completed = _completed_events(events, run_root=candidate_root)
    if tuple(completed) != TASK_ORDER:
        raise ValueError("candidate Task DAG is incomplete")
    for task_id, event in completed.items():
        root = candidate_root / _safe_relative(event["output_root"])
        read_task_files(
            root,
            expected_tree_hash=event["output_tree_hash"],
            verify_contents=False,
        )
        descriptor = read_canonical_json(root / "task-files.json")
        if descriptor.get("task_files_hash") != event.get("task_files_hash"):
            raise ValueError(f"candidate Task descriptor Hash drift: {task_id}")
    manifest = read_canonical_json(candidate_root / "final/final-manifest.json")
    manifest_hash = _verified_self_hash(manifest, "manifest_hash")
    expected_task_results = _task_results(completed)
    if (
        manifest.get("authority_hash") != authority["authority_hash"]
        or manifest.get("inputs_lock_hash") != inputs_lock.inputs_lock_hash
        or manifest.get("adoption_bundle_hash") != inputs_lock.adoption_bundle_hash
        or manifest.get("task_order") != list(TASK_ORDER)
        or manifest.get("event_chain_tip_hash") != events[-1]["event_hash"]
        or manifest.get("stage3_locked") is not True
        or manifest.get("task_results") != expected_task_results
        or len(cast(list[object], manifest.get("output_files"))) == 0
    ):
        raise ValueError("candidate final Manifest drift")
    attempt_count, interrupted_count = _verify_attempt_topology(
        candidate_root=candidate_root,
        events=events,
    )
    output_count = 0
    for item in cast(list[dict[str, object]], manifest["output_files"]):
        relative = _safe_relative(item["relative_path"])
        target = candidate_root / relative
        if (
            target.is_symlink()
            or sha256_file(target) != item["sha256"]
            or target.stat().st_size != item["size_bytes"]
        ):
            raise ValueError(f"candidate final output Hash drift: {relative}")
        output_count += 1
    payload: dict[str, object] = {
        "schema_name": VERIFY_SCHEMA,
        "schema_version": "1.0",
        "run_id": candidate_root.name,
        "authority_hash": authority["authority_hash"],
        "inputs_lock_hash": inputs_lock.inputs_lock_hash,
        "event_chain_tip_hash": events[-1]["event_hash"],
        "manifest_hash": manifest_hash,
        "final_report_sha256": sha256_file(candidate_root / "final/final-report.md"),
        "task_count": len(completed),
        "task_attempt_count": attempt_count,
        "interrupted_attempt_count": interrupted_count,
        "output_file_count": output_count,
        "orphan_task_count": 0,
        "duplicate_task_completion_count": 0,
        "unterminated_task_count": 0,
        "full_hash_scan": True,
        "status": "PASS",
        "verified_at": _now(),
        "stage3_locked": True,
    }
    payload["verify_hash"] = _self_hash(payload, "verify_hash")
    path = candidate_root / "final/final-verify.json"
    write_canonical_json_exclusive(path, payload)
    return path


def _atomic_move(source: Path, destination: Path) -> Path:
    if destination.exists():
        raise ValueError(f"atomic publication destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, destination)
    _fsync_directory(destination.parent)
    return destination


def execute_run(
    *,
    policy: SoloRuntimePolicy,
    authority_path: Path,
    repository_root: Path,
    evidence_root: Path,
    handlers: Mapping[str, TaskHandler],
    resume_run_root: Path | None = None,
) -> Path:
    """Execute or resume one Authority-bound chain and atomically publish it."""

    if tuple(handlers) != TASK_ORDER:
        raise ValueError("fixed handler registry must bind all ten Tasks in order")
    with unique_run_lock(evidence_root):
        authority, inputs_lock = validate_authority(
            authority_path,
            policy=policy,
            repository_root=repository_root,
        )
        if resume_run_root is None:
            run_root = _reserve_run(evidence_root=evidence_root, authority=authority)
            run_contract = _validate_run(run_root, str(authority["authority_hash"]))
            ledger = EventLedger(
                run_root / "events.jsonl",
                run_id=str(run_contract["run_id"]),
                authority_hash=str(authority["authority_hash"]),
            )
            ledger.append("RUN_STARTED", status="IN_PROGRESS")
        else:
            run_root = resume_run_root
            if run_root.parent.resolve() != (evidence_root / "runs").resolve():
                raise ValueError("resume accepts only an active runs/<run_id> directory")
            run_contract = _validate_run(run_root, str(authority["authority_hash"]))
            ledger = EventLedger(
                run_root / "events.jsonl",
                run_id=str(run_contract["run_id"]),
                authority_hash=str(authority["authority_hash"]),
            )
            existing = ledger.read()
            if (
                not existing
                or existing[-1]["event_type"] != "TASK_INTERRUPTED"
                or any(
                    event["event_type"] in {"RUN_FAILED", "RUN_COMPLETE_PRE_VERIFY"}
                    for event in existing
                )
            ):
                raise ValueError("resume is allowed only after a retryable interruption")
        events = ledger.read()
        completed: dict[str, dict[str, Any]] = {}
        try:
            completed = _completed_events(events, run_root=run_root)
            for task_id in TASK_ORDER:
                if task_id in completed:
                    continue
                if any(dependency not in completed for dependency in TASK_DAG[task_id]):
                    raise ValueError(f"Task dependency not completed: {task_id}")
                completed[task_id] = _execute_task(
                    handler=handlers[task_id],
                    task_id=task_id,
                    attempt=_attempt_number(ledger.read(), task_id),
                    run_root=run_root,
                    repository_root=repository_root,
                    authority=authority,
                    inputs_lock=inputs_lock,
                    completed=completed,
                    ledger=ledger,
                )
            ledger.append(
                "RUN_COMPLETE_PRE_VERIFY",
                status="COMPLETE_PRE_VERIFY",
                completed_task_count=len(completed),
            )
            manifest_path = _build_final_manifest(
                run_root=run_root,
                authority=authority,
                inputs_lock=inputs_lock,
                events=ledger.read(),
            )
            if not manifest_path.is_file():
                raise AssertionError("final Manifest was not written")
            candidate = _atomic_move(
                run_root,
                evidence_root / "candidates" / run_root.name,
            )
            try:
                verify_candidate(
                    candidate_root=candidate,
                    authority_path=authority_path,
                    policy=policy,
                    repository_root=repository_root,
                )
            except BaseException as exc:
                failed_ledger = EventLedger(
                    candidate / "events.jsonl",
                    run_id=candidate.name,
                    authority_hash=str(authority["authority_hash"]),
                )
                failed_ledger.append(
                    "RUN_FAILED",
                    status="FAILED",
                    reason_code=type(exc).__name__,
                    completed_task_count=len(completed),
                )
                failure: dict[str, object] = {
                    "schema_name": VERIFY_SCHEMA,
                    "schema_version": "1.0",
                    "run_id": candidate.name,
                    "status": "FAIL",
                    "reason_code": type(exc).__name__,
                    "verified_at": _now(),
                    "stage3_locked": True,
                }
                failure["verify_hash"] = _self_hash(failure, "verify_hash")
                failure_path = candidate / "final/final-verify.json"
                if not failure_path.exists():
                    write_canonical_json_exclusive(failure_path, failure)
                _atomic_move(candidate, evidence_root / "failed" / candidate.name)
                raise
            return _atomic_move(
                candidate,
                evidence_root / "published" / candidate.name,
            )
        except RetryableTaskInterruption:
            raise
        except BaseException as exc:
            if run_root.exists():
                current_events = ledger.read()
                if not current_events or current_events[-1]["event_type"] not in {
                    "RUN_FAILED",
                    "RUN_COMPLETE_PRE_VERIFY",
                }:
                    ledger.append(
                        "RUN_FAILED",
                        status="FAILED",
                        reason_code=type(exc).__name__,
                        completed_task_count=len(completed),
                    )
                _atomic_move(run_root, evidence_root / "failed" / run_root.name)
            raise


def runtime_status(evidence_root: Path) -> dict[str, Any]:
    """Read-only status projection for the CLI and Web UI."""

    authorities = tuple(sorted((evidence_root / "authorities").glob("authority-*.json")))
    locks = tuple(sorted((evidence_root / "inputs").glob("inputs-*.lock.json")))
    runs = list(_all_run_roots(evidence_root))
    latest = max(runs, key=lambda path: path.stat().st_mtime_ns) if runs else None
    payload: dict[str, Any] = {
        "stage_plan_version": "1.10",
        "inputs_lock_count": len(locks),
        "authority_count": len(authorities),
        "run_count": len(runs),
        "current_run": None,
        "stage3_locked": True,
    }
    if latest is None:
        return payload
    run = read_canonical_json(latest / "run.json")
    ledger = EventLedger(
        latest / "events.jsonl",
        run_id=latest.name,
        authority_hash=str(run["authority_hash"]),
    )
    events = ledger.read()
    completed = [event for event in events if event["event_type"] == "TASK_COMPLETED"]
    current = next(
        (
            event
            for event in reversed(events)
            if event["event_type"] in {"TASK_STARTED", "TASK_INTERRUPTED", "TASK_COMPLETED"}
        ),
        None,
    )
    verify_path = latest / "final/final-verify.json"
    verify = read_canonical_json(verify_path) if verify_path.is_file() else None
    started = next(
        (event for event in events if event["event_type"] == "RUN_STARTED"),
        None,
    )
    elapsed = Decimal("0")
    if started is not None:
        elapsed = max(
            Decimal("0"),
            Decimal(
                str(
                    (
                        datetime.now(UTC) - datetime.fromisoformat(str(started["recorded_at"]))
                    ).total_seconds()
                )
            ),
        )
    throughput = Decimal(len(completed)) / elapsed if completed and elapsed else Decimal("0")
    eta = Decimal(len(TASK_ORDER) - len(completed)) / throughput if throughput else None
    latest_checkpoint = next(
        (event for event in reversed(events) if event["event_type"] == "TASK_CHECKPOINTED"),
        None,
    )
    checkpoint_metrics = (
        cast(dict[str, Any], latest_checkpoint.get("metrics", {})) if latest_checkpoint else {}
    )
    payload["current_run"] = {
        "run_id": latest.name,
        "location": latest.parent.name,
        "current_task": current.get("task_id") if current else None,
        "processed_units": len(completed),
        "total_units": len(TASK_ORDER),
        "percentage": len(completed) * 10,
        "last_event": events[-1]["event_type"] if events else None,
        "heartbeat_at": events[-1]["recorded_at"] if events else None,
        "verify_state": verify.get("status") if verify else "PENDING",
        "elapsed_seconds": format(elapsed, "f"),
        "throughput_tasks_per_second": format(throughput, "f"),
        "eta_seconds": format(eta, "f") if eta is not None else None,
        "phase": current.get("task_id") if current else "PREPARE",
        "subphase": checkpoint_metrics.get(
            "subphase", events[-1]["event_type"] if events else "NOT_STARTED"
        ),
        "checkpoint_metrics": checkpoint_metrics,
        "task_execution_modes": {
            str(event["task_id"]): str(event["execution_mode"]) for event in completed
        },
    }
    return payload
