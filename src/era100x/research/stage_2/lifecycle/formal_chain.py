"""Append-only formal orchestration for the Plan v1.8 successor chain.

The orchestrator owns governance, ordering and evidence integrity.  Research
producers remain separate executables and must satisfy the frozen adapter
contract before a Run ID can exist.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, cast

from era100x.research.stage_2.acceptance.canonical_json import (
    canonical_content_hash,
    read_canonical_json,
    sha256_file,
    write_canonical_json_exclusive,
)

from .governance import LifecycleRepairPolicy

APPROVAL_SCHEMA: Final = "s2p18-formal-approval-v1"
AUTHORITY_SCHEMA: Final = "s2p18-chain-authority-v1"
RUN_SCHEMA: Final = "s2p18-formal-run-v1"
CHECKPOINT_SCHEMA: Final = "s2p18-chain-checkpoint-v1"
TASK_RECEIPT_SCHEMA: Final = "s2p18-task-receipt-v1"
MANIFEST_SCHEMA: Final = "s2p18-chain-manifest-v1"
CATALOG_SCHEMA: Final = "s2p18-chain-catalog-v1"
VERIFY_SCHEMA: Final = "s2p18-chain-verify-v1"
ADAPTER_SCHEMA: Final = "s2p18-task-adapter-plan-v1"
TASK_ORDER: Final = tuple(f"S2P18-T{number:02d}" for number in range(11, 21))
RUN_ID = re.compile(r"^stage2-s2p18-\d{8}T\d{6}Z-[0-9a-f]{12}$")
REQUIRED_INPUT_BINDINGS: Final = frozenset(
    {
        "btc_stage1_logical_hash",
        "eth_stage1_logical_hash",
        "canonical_trades_catalog_hash",
        "canonical_trades_verify_hash",
        "contract_price_catalog_hash",
        "funding_acceptance_hash",
        "t10_manifest_hash",
        "primary_config_hash",
        "matching_contract_hash",
        "cluster_contract_hash",
        "fixed_seed_hash",
        "historical_t20_verify_hash",
    }
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _self_hash(payload: Mapping[str, object], field: str) -> str:
    return canonical_content_hash({key: value for key, value in payload.items() if key != field})


def _verified_self_hash(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or value != _self_hash(payload, field):
        raise ValueError(f"{field} mismatch")
    return value


def _safe_relative(value: object) -> Path:
    path = Path(str(value))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe relative path: {value}")
    return path


def _write(path: Path, payload: object) -> Path:
    write_canonical_json_exclusive(path, payload)
    return path


def repository_commit(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def repository_clean(root: Path) -> bool:
    return not subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=root, text=True
    ).strip()


@dataclass(frozen=True, slots=True)
class TaskAdapter:
    task_id: str
    argv: tuple[str, ...]
    executable_paths: tuple[Path, ...]
    executable_hashes: tuple[str, ...]
    timeout_seconds: int


@dataclass(frozen=True, slots=True)
class AdapterPlan:
    path: Path
    plan_hash: str
    adapters: dict[str, TaskAdapter]


def load_adapter_plan(path: Path, *, repository_root: Path) -> AdapterPlan:
    payload = read_canonical_json(path)
    if (
        payload.get("schema_name") != ADAPTER_SCHEMA
        or payload.get("schema_version") != "1.0"
        or payload.get("stage_plan_version") != "1.8"
        or payload.get("task_order") != list(TASK_ORDER)
    ):
        raise ValueError("Plan v1.8 adapter plan identity drift")
    plan_hash = _verified_self_hash(payload, "adapter_plan_hash")
    raw_adapters = cast(list[dict[str, Any]], payload.get("adapters"))
    if not isinstance(raw_adapters, list):
        raise ValueError("adapter plan adapters must be a list")
    adapters: dict[str, TaskAdapter] = {}
    for raw in raw_adapters:
        if set(raw) != {
            "task_id",
            "argv",
            "executable_paths",
            "executable_hashes",
            "timeout_seconds",
        }:
            raise ValueError("adapter fields drift")
        task_id = str(raw["task_id"])
        argv = tuple(str(item) for item in cast(list[object], raw["argv"]))
        paths = tuple(
            repository_root / _safe_relative(item)
            for item in cast(list[object], raw["executable_paths"])
        )
        hashes = tuple(str(item) for item in cast(list[object], raw["executable_hashes"]))
        if (
            task_id in adapters
            or task_id not in TASK_ORDER
            or not argv
            or len(paths) != len(hashes)
            or not paths
            or not isinstance(raw["timeout_seconds"], int)
            or int(raw["timeout_seconds"]) <= 0
        ):
            raise ValueError(f"invalid adapter: {task_id}")
        for executable, expected_hash in zip(paths, hashes, strict=True):
            if sha256_file(executable) != expected_hash:
                raise ValueError(f"adapter executable Hash drift: {task_id}:{executable}")
        adapters[task_id] = TaskAdapter(
            task_id=task_id,
            argv=argv,
            executable_paths=paths,
            executable_hashes=hashes,
            timeout_seconds=int(raw["timeout_seconds"]),
        )
    if tuple(adapters) != TASK_ORDER:
        raise ValueError("adapter plan must bind all ten Tasks in frozen order")
    return AdapterPlan(path=path, plan_hash=plan_hash, adapters=adapters)


def record_approval(
    *,
    policy: LifecycleRepairPolicy,
    adapter_plan: AdapterPlan,
    repository_root: Path,
    operations_root: Path,
    approved_by: str,
    approval_source: str,
    approved_commit: str,
    approved_at: str | None = None,
) -> Path:
    if not repository_clean(repository_root):
        raise ValueError("formal approval requires a clean repository")
    current_commit = repository_commit(repository_root)
    if current_commit != approved_commit:
        raise ValueError("approval commit does not match current clean HEAD")
    payload: dict[str, object] = {
        "schema_name": APPROVAL_SCHEMA,
        "schema_version": "1.0",
        "stage_plan_version": "1.8",
        "approved_commit": approved_commit,
        "policy_hash": policy.policy_hash,
        "adapter_plan_hash": adapter_plan.plan_hash,
        "source_audit_hash": policy.source_audit_hash,
        "preregistration_hash": policy.preregistration_hash,
        "approved_by": approved_by,
        "approval_source": approval_source,
        "approved_at": approved_at or _now(),
        "scope": "ONE_NEW_S2P18_T11_T20_SUCCESSOR_CHAIN",
        "stage3_locked": True,
    }
    payload["approval_hash"] = _self_hash(payload, "approval_hash")
    target = operations_root / "approvals" / f"{payload['approval_hash']}.json"
    return _write(target, payload)


def validate_approval(
    path: Path,
    *,
    policy: LifecycleRepairPolicy,
    adapter_plan: AdapterPlan,
    repository_root: Path,
) -> dict[str, Any]:
    payload = read_canonical_json(path)
    _verified_self_hash(payload, "approval_hash")
    if (
        payload.get("schema_name") != APPROVAL_SCHEMA
        or payload.get("stage_plan_version") != "1.8"
        or payload.get("approved_commit") != repository_commit(repository_root)
        or payload.get("policy_hash") != policy.policy_hash
        or payload.get("adapter_plan_hash") != adapter_plan.plan_hash
        or payload.get("source_audit_hash") != policy.source_audit_hash
        or payload.get("preregistration_hash") != policy.preregistration_hash
        or payload.get("scope") != "ONE_NEW_S2P18_T11_T20_SUCCESSOR_CHAIN"
        or payload.get("stage3_locked") is not True
        or not repository_clean(repository_root)
    ):
        raise ValueError("formal approval binding drift")
    return payload


def freeze_authority(
    *,
    policy: LifecycleRepairPolicy,
    adapter_plan: AdapterPlan,
    approval_path: Path,
    repository_root: Path,
    evidence_root: Path,
    input_bindings: Mapping[str, str],
) -> Path:
    approval = validate_approval(
        approval_path,
        policy=policy,
        adapter_plan=adapter_plan,
        repository_root=repository_root,
    )
    if set(input_bindings) != REQUIRED_INPUT_BINDINGS or any(
        not key or not re.fullmatch(r"[0-9a-f]{64}", value)
        for key, value in input_bindings.items()
    ):
        raise ValueError("Authority input Hash set is incomplete or malformed")
    for existing in (evidence_root / "authorities").glob("authority-*.json"):
        existing_payload = read_canonical_json(existing)
        if existing_payload.get("approval_hash") == approval["approval_hash"]:
            raise ValueError("one approval can freeze only one Plan v1.8 Authority")
    payload: dict[str, object] = {
        "schema_name": AUTHORITY_SCHEMA,
        "schema_version": "1.0",
        "stage_plan_version": "1.8",
        "execution_limit": "S2P18-T20",
        "code_commit": repository_commit(repository_root),
        "approval_hash": approval["approval_hash"],
        "policy_hash": policy.policy_hash,
        "adapter_plan_hash": adapter_plan.plan_hash,
        "preregistration_hash": policy.preregistration_hash,
        "source_audit_hash": policy.source_audit_hash,
        "contract_hashes": dict(sorted(policy.contract_hashes.items())),
        "adapter_executable_hashes": {
            task_id: list(adapter.executable_hashes)
            for task_id, adapter in adapter_plan.adapters.items()
        },
        "input_bindings": dict(sorted(input_bindings.items())),
        "task_order": list(TASK_ORDER),
        "task_dag": policy.payload["task_dag"],
        "created_at": _now(),
        "historical_execution_claim": False,
        "stage3_locked": True,
    }
    payload["authority_hash"] = _self_hash(payload, "authority_hash")
    target = evidence_root / "authorities" / f"authority-{payload['authority_hash']}.json"
    return _write(target, payload)


def validate_authority(
    path: Path,
    *,
    policy: LifecycleRepairPolicy,
    adapter_plan: AdapterPlan,
    approval_path: Path,
    repository_root: Path,
) -> dict[str, Any]:
    payload = read_canonical_json(path)
    _verified_self_hash(payload, "authority_hash")
    approval = validate_approval(
        approval_path,
        policy=policy,
        adapter_plan=adapter_plan,
        repository_root=repository_root,
    )
    raw_inputs = payload.get("input_bindings")
    expected_executable_hashes = {
        task_id: list(adapter.executable_hashes)
        for task_id, adapter in adapter_plan.adapters.items()
    }
    if (
        payload.get("schema_name") != AUTHORITY_SCHEMA
        or payload.get("code_commit") != repository_commit(repository_root)
        or payload.get("approval_hash") != approval["approval_hash"]
        or payload.get("policy_hash") != policy.policy_hash
        or payload.get("adapter_plan_hash") != adapter_plan.plan_hash
        or payload.get("preregistration_hash") != policy.preregistration_hash
        or payload.get("source_audit_hash") != policy.source_audit_hash
        or payload.get("contract_hashes")
        != dict(sorted(policy.contract_hashes.items()))
        or payload.get("adapter_executable_hashes") != expected_executable_hashes
        or not isinstance(raw_inputs, dict)
        or set(raw_inputs) != REQUIRED_INPUT_BINDINGS
        or any(
            not isinstance(value, str)
            or not re.fullmatch(r"[0-9a-f]{64}", value)
            for value in raw_inputs.values()
        )
        or payload.get("task_order") != list(TASK_ORDER)
        or payload.get("task_dag") != policy.payload["task_dag"]
        or payload.get("historical_execution_claim") is not False
        or payload.get("stage3_locked") is not True
        or not repository_clean(repository_root)
    ):
        raise ValueError("formal Authority binding drift")
    return payload


@contextmanager
def unique_run_lock(evidence_root: Path) -> Iterator[None]:
    path = evidence_root / "operations" / "run.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Plan v1.8 unique Run lock is held") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _checkpoint_files(run_root: Path) -> tuple[Path, ...]:
    return tuple(sorted((run_root / "checkpoints").glob("*.json")))


def _last_checkpoint(run_root: Path) -> dict[str, Any] | None:
    files = _checkpoint_files(run_root)
    if not files:
        return None
    previous: str | None = None
    last: dict[str, Any] | None = None
    for ordinal, path in enumerate(files, start=1):
        payload = read_canonical_json(path)
        checkpoint_hash = _verified_self_hash(payload, "checkpoint_hash")
        if (
            payload.get("schema_name") != CHECKPOINT_SCHEMA
            or payload.get("ordinal") != ordinal
            or payload.get("previous_checkpoint_hash") != previous
        ):
            raise ValueError("checkpoint chain drift")
        previous, last = checkpoint_hash, payload
    return last


def _write_checkpoint(
    run_root: Path,
    *,
    run_id: str,
    authority_hash: str,
    completed_tasks: Sequence[str],
    current_task: str | None,
    status: str,
    reason_code: str | None = None,
) -> Path:
    previous = _last_checkpoint(run_root)
    ordinal = int(previous["ordinal"]) + 1 if previous else 1
    run_contract = read_canonical_json(run_root / "run.json")
    started_at = datetime.fromisoformat(str(run_contract["created_at"]))
    elapsed = max(Decimal("0"), Decimal(str((datetime.now(UTC) - started_at).total_seconds())))
    processed = len(completed_tasks)
    throughput = Decimal(processed) / elapsed if processed and elapsed else Decimal("0")
    remaining = len(TASK_ORDER) - processed
    eta = Decimal(remaining) / throughput if throughput else None
    payload: dict[str, object] = {
        "schema_name": CHECKPOINT_SCHEMA,
        "schema_version": "1.0",
        "ordinal": ordinal,
        "previous_checkpoint_hash": previous["checkpoint_hash"] if previous else None,
        "run_id": run_id,
        "authority_hash": authority_hash,
        "completed_tasks": list(completed_tasks),
        "current_task": current_task,
        "status": status,
        "reason_code": reason_code,
        "processed_units": processed,
        "total_units": len(TASK_ORDER),
        "percentage": str(processed * 10),
        "elapsed_seconds": format(elapsed, "f"),
        "throughput_tasks_per_second": format(throughput, "f"),
        "eta_seconds": format(eta, "f") if eta is not None else None,
        "phase": current_task or "CHAIN",
        "subphase": status,
        "heartbeat_at": _now(),
        "verify_state": "PASS" if status == "COMPLETE" else "PENDING",
    }
    payload["checkpoint_hash"] = _self_hash(payload, "checkpoint_hash")
    return _write(
        run_root / "checkpoints" / f"{ordinal:06d}.json", payload
    )


def _task_receipt(
    run_root: Path,
    task_id: str,
    *,
    authority_hash: str,
    adapter_plan_hash: str,
    code_commit: str,
    upstream_receipt_hashes: Mapping[str, str],
) -> dict[str, Any]:
    path = run_root / "receipts" / f"{task_id}.json"
    payload = read_canonical_json(path)
    _verified_self_hash(payload, "task_receipt_hash")
    if (
        payload.get("schema_name") != TASK_RECEIPT_SCHEMA
        or payload.get("task_id") != task_id
        or payload.get("run_id") != run_root.name
        or payload.get("authority_hash") != authority_hash
        or payload.get("adapter_plan_hash") != adapter_plan_hash
        or payload.get("code_commit") != code_commit
        or payload.get("upstream_receipt_hashes")
        != dict(sorted(upstream_receipt_hashes.items()))
        or payload.get("status") != "PASS"
        or payload.get("historical_execution_claim") is not False
    ):
        raise ValueError(f"invalid Task receipt: {task_id}")
    output_files = cast(list[dict[str, object]], payload.get("output_files"))
    if not isinstance(output_files, list) or not output_files:
        raise ValueError(f"Task receipt has no outputs: {task_id}")
    task_root = run_root / "staging" / task_id
    for item in output_files:
        relative = _safe_relative(item.get("relative_path"))
        if sha256_file(task_root / relative) != item.get("sha256"):
            raise ValueError(f"Task output Hash drift: {task_id}:{relative}")
    return payload


def _execute_task(
    *,
    adapter: TaskAdapter,
    run_root: Path,
    authority_path: Path,
    approval_path: Path,
    policy_path: Path,
    adapter_plan_path: Path,
    repository_root: Path,
    authority_hash: str,
    adapter_plan_hash: str,
    code_commit: str,
    upstream_receipt_hashes: Mapping[str, str],
) -> dict[str, Any]:
    task_root = run_root / "staging" / adapter.task_id
    if task_root.exists():
        raise ValueError(f"Task staging already exists without accepted receipt: {adapter.task_id}")
    task_root.mkdir(parents=True)
    env = os.environ.copy()
    env.update(
        {
            "ERA_S2P18_TASK_ID": adapter.task_id,
            "ERA_S2P18_RUN_ROOT": str(run_root),
            "ERA_S2P18_TASK_ROOT": str(task_root),
            "ERA_S2P18_AUTHORITY_PATH": str(authority_path),
            "ERA_S2P18_APPROVAL_PATH": str(approval_path),
            "ERA_S2P18_POLICY_PATH": str(policy_path),
            "ERA_S2P18_ADAPTER_PLAN_PATH": str(adapter_plan_path),
            "ERA_S2P18_REPOSITORY_ROOT": str(repository_root),
            "ERA_S2P18_AUTHORITY_HASH": authority_hash,
            "ERA_S2P18_ADAPTER_PLAN_HASH": adapter_plan_hash,
            "ERA_S2P18_CODE_COMMIT": code_commit,
            "ERA_S2P18_UPSTREAM_RECEIPT_HASHES": json.dumps(
                dict(sorted(upstream_receipt_hashes.items())),
                sort_keys=True,
                separators=(",", ":"),
            ),
            "PYTHONPATH": str(repository_root),
        }
    )
    completed = subprocess.run(
        adapter.argv,
        cwd=repository_root,
        env=env,
        check=False,
        text=True,
        capture_output=True,
        timeout=adapter.timeout_seconds,
    )
    log_payload: dict[str, object] = {
        "task_id": adapter.task_id,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    log_payload["log_hash"] = _self_hash(log_payload, "log_hash")
    _write(
        run_root / "logs" / f"{adapter.task_id}.json", log_payload
    )
    if completed.returncode:
        raise ValueError(f"Task producer failed: {adapter.task_id}")
    return _task_receipt(
        run_root,
        adapter.task_id,
        authority_hash=authority_hash,
        adapter_plan_hash=adapter_plan_hash,
        code_commit=code_commit,
        upstream_receipt_hashes=upstream_receipt_hashes,
    )


def _reserve_run(
    *,
    evidence_root: Path,
    authority: Mapping[str, Any],
    approval: Mapping[str, Any],
) -> Path:
    evidence_root = evidence_root.resolve()
    for existing in (evidence_root / "runs").glob("stage2-s2p18-*"):
        contract_path = existing / "run.json"
        if contract_path.is_file() and read_canonical_json(contract_path).get(
            "authority_hash"
        ) == authority["authority_hash"]:
            raise ValueError("one Authority can reserve only one Run")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"stage2-s2p18-{stamp}-{str(authority['authority_hash'])[:12]}"
    if not RUN_ID.fullmatch(run_id):
        raise AssertionError("generated invalid Run ID")
    run_root = evidence_root / "runs" / run_id
    payload: dict[str, object] = {
        "schema_name": RUN_SCHEMA,
        "schema_version": "1.0",
        "run_id": run_id,
        "stage_plan_version": "1.8",
        "authority_hash": authority["authority_hash"],
        "approval_hash": approval["approval_hash"],
        "code_commit": authority["code_commit"],
        "created_at": _now(),
        "publication_status": "UNPUBLISHED",
        "stage3_locked": True,
    }
    payload["run_contract_hash"] = _self_hash(payload, "run_contract_hash")
    _write(run_root / "run.json", payload)
    return run_root


def run_formal_chain(
    *,
    policy: LifecycleRepairPolicy,
    adapter_plan: AdapterPlan,
    approval_path: Path,
    authority_path: Path,
    repository_root: Path,
    evidence_root: Path,
    resume_run_root: Path | None = None,
) -> Path:
    with unique_run_lock(evidence_root):
        approval = validate_approval(
            approval_path,
            policy=policy,
            adapter_plan=adapter_plan,
            repository_root=repository_root,
        )
        authority = validate_authority(
            authority_path,
            policy=policy,
            adapter_plan=adapter_plan,
            approval_path=approval_path,
            repository_root=repository_root,
        )
        run_root = resume_run_root or _reserve_run(
            evidence_root=evidence_root,
            authority=authority,
            approval=approval,
        )
        run_contract = read_canonical_json(run_root / "run.json")
        _verified_self_hash(run_contract, "run_contract_hash")
        if (
            run_contract.get("authority_hash") != authority["authority_hash"]
            or run_contract.get("publication_status") != "UNPUBLISHED"
        ):
            raise ValueError("Run contract drift")
        last = _last_checkpoint(run_root)
        if last and last.get("status") in {"FAILED", "COMPLETE"}:
            raise ValueError("terminal Run cannot resume")
        completed_tasks = list(cast(list[str], last.get("completed_tasks", []))) if last else []
        receipts: dict[str, dict[str, Any]] = {}
        try:
            for task_id in TASK_ORDER:
                dependencies = cast(list[str], policy.payload["task_dag"][task_id])
                upstream_receipt_hashes = {
                    item: str(receipts[item]["task_receipt_hash"]) for item in dependencies
                }
                if task_id in completed_tasks:
                    receipts[task_id] = _task_receipt(
                        run_root,
                        task_id,
                        authority_hash=str(authority["authority_hash"]),
                        adapter_plan_hash=adapter_plan.plan_hash,
                        code_commit=str(authority["code_commit"]),
                        upstream_receipt_hashes=upstream_receipt_hashes,
                    )
                    continue
                if any(item not in completed_tasks for item in dependencies):
                    raise ValueError(f"Task dependency not verified: {task_id}")
                _write_checkpoint(
                    run_root,
                    run_id=str(run_contract["run_id"]),
                    authority_hash=str(authority["authority_hash"]),
                    completed_tasks=completed_tasks,
                    current_task=task_id,
                    status="IN_PROGRESS",
                )
                receipts[task_id] = _execute_task(
                    adapter=adapter_plan.adapters[task_id],
                    run_root=run_root,
                    authority_path=authority_path,
                    approval_path=approval_path,
                    policy_path=policy.path,
                    adapter_plan_path=adapter_plan.path,
                    repository_root=repository_root,
                    authority_hash=str(authority["authority_hash"]),
                    adapter_plan_hash=adapter_plan.plan_hash,
                    code_commit=str(authority["code_commit"]),
                    upstream_receipt_hashes=upstream_receipt_hashes,
                )
                completed_tasks.append(task_id)
                _write_checkpoint(
                    run_root,
                    run_id=str(run_contract["run_id"]),
                    authority_hash=str(authority["authority_hash"]),
                    completed_tasks=completed_tasks,
                    current_task=task_id,
                    status="TASK_VERIFIED",
                )
            _write_checkpoint(
                run_root,
                run_id=str(run_contract["run_id"]),
                authority_hash=str(authority["authority_hash"]),
                completed_tasks=completed_tasks,
                current_task=None,
                status="COMPLETE",
            )
            catalog_path, manifest_path = build_catalog_and_manifest(
                run_root=run_root,
                authority_path=authority_path,
            )
            publish_candidate_chain(
                run_root=run_root,
                catalog_path=catalog_path,
                manifest_path=manifest_path,
            )
            verify_path = verify_formal_chain(
                run_root=run_root,
                authority_path=authority_path,
                full_hash_scan=True,
            )
            seal_publication(run_root=run_root, verify_path=verify_path)
        except BaseException as exc:
            _write_checkpoint(
                run_root,
                run_id=str(run_contract["run_id"]),
                authority_hash=str(authority["authority_hash"]),
                completed_tasks=completed_tasks,
                current_task=(
                    TASK_ORDER[len(completed_tasks)]
                    if len(completed_tasks) < len(TASK_ORDER)
                    else None
                ),
                status="FAILED",
                reason_code=type(exc).__name__,
            )
            raise
        return run_root


def build_catalog_and_manifest(
    *,
    run_root: Path,
    authority_path: Path,
) -> tuple[Path, Path]:
    checkpoint = _last_checkpoint(run_root)
    if not checkpoint or checkpoint.get("status") != "COMPLETE":
        raise ValueError("cannot reconcile an incomplete Run")
    authority = read_canonical_json(authority_path)
    authority_hash = _verified_self_hash(authority, "authority_hash")
    files: list[dict[str, object]] = []
    for path in sorted((run_root / "staging").rglob("*")):
        if path.is_file() and not path.is_symlink() and not path.name.startswith("._"):
            files.append(
                {
                    "relative_path": str(path.relative_to(run_root / "staging")),
                    "sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
            )
    if not files:
        raise ValueError("formal Run has no staging outputs")
    catalog: dict[str, object] = {
        "schema_name": CATALOG_SCHEMA,
        "schema_version": "1.0",
        "run_id": run_root.name,
        "authority_hash": authority_hash,
        "files": files,
    }
    catalog["catalog_hash"] = _self_hash(catalog, "catalog_hash")
    catalog_path = _write(run_root / "reconcile" / "catalog.json", catalog)
    authority_code_commit = str(authority["code_commit"])
    adapter_plan_hash = str(authority["adapter_plan_hash"])
    receipts: list[dict[str, Any]] = []
    receipt_by_task: dict[str, dict[str, Any]] = {}
    for task_id in TASK_ORDER:
        dependencies = cast(list[str], authority["task_dag"][task_id])
        receipt = _task_receipt(
            run_root,
            task_id,
            authority_hash=authority_hash,
            adapter_plan_hash=adapter_plan_hash,
            code_commit=authority_code_commit,
            upstream_receipt_hashes={
                item: str(receipt_by_task[item]["task_receipt_hash"])
                for item in dependencies
            },
        )
        receipts.append(receipt)
        receipt_by_task[task_id] = receipt
    manifest: dict[str, object] = {
        "schema_name": MANIFEST_SCHEMA,
        "schema_version": "1.0",
        "run_id": run_root.name,
        "authority_hash": authority_hash,
        "catalog_hash": catalog["catalog_hash"],
        "task_receipt_hashes": {
            receipt["task_id"]: receipt["task_receipt_hash"] for receipt in receipts
        },
        "file_count": len(files),
        "reconciliation_status": "PASS",
        "publication_status": "UNPUBLISHED",
        "historical_execution_claim": False,
        "stage3_locked": True,
    }
    manifest["manifest_hash"] = _self_hash(manifest, "manifest_hash")
    manifest_path = _write(
        run_root / "reconcile" / "manifest.json", manifest
    )
    return catalog_path, manifest_path


def verify_formal_chain(
    *,
    run_root: Path,
    authority_path: Path,
    full_hash_scan: bool,
) -> Path:
    checkpoint = _last_checkpoint(run_root)
    catalog = read_canonical_json(run_root / "reconcile" / "catalog.json")
    manifest = read_canonical_json(run_root / "reconcile" / "manifest.json")
    authority = read_canonical_json(authority_path)
    authority_hash = _verified_self_hash(authority, "authority_hash")
    catalog_hash = _verified_self_hash(catalog, "catalog_hash")
    manifest_hash = _verified_self_hash(manifest, "manifest_hash")
    if (
        not checkpoint
        or checkpoint.get("status") != "COMPLETE"
        or catalog.get("authority_hash") != authority_hash
        or manifest.get("authority_hash") != authority_hash
        or manifest.get("catalog_hash") != catalog_hash
        or manifest.get("reconciliation_status") != "PASS"
        or manifest.get("stage3_locked") is not True
    ):
        raise ValueError("formal chain reconciliation drift")
    receipt_by_task: dict[str, dict[str, Any]] = {}
    for task_id in TASK_ORDER:
        dependencies = cast(list[str], authority["task_dag"][task_id])
        receipt_by_task[task_id] = _task_receipt(
            run_root,
            task_id,
            authority_hash=authority_hash,
            adapter_plan_hash=str(authority["adapter_plan_hash"]),
            code_commit=str(authority["code_commit"]),
            upstream_receipt_hashes={
                item: str(receipt_by_task[item]["task_receipt_hash"])
                for item in dependencies
            },
        )
    published_outputs = run_root / "published" / "outputs"
    if not published_outputs.is_dir() or published_outputs.is_symlink():
        raise ValueError("Verify requires candidate publication outputs")
    if full_hash_scan:
        for item in cast(list[dict[str, object]], catalog["files"]):
            relative = _safe_relative(item["relative_path"])
            if sha256_file(published_outputs / relative) != item["sha256"]:
                raise ValueError(f"Catalog file Hash drift: {relative}")
    payload: dict[str, object] = {
        "schema_name": VERIFY_SCHEMA,
        "schema_version": "1.0",
        "run_id": run_root.name,
        "authority_hash": authority_hash,
        "catalog_hash": catalog_hash,
        "manifest_hash": manifest_hash,
        "checkpoint_hash": checkpoint["checkpoint_hash"],
        "full_hash_scan": full_hash_scan,
        "status": "PASS",
        "verified_at": _now(),
        "stage3_locked": True,
    }
    payload["verify_hash"] = _self_hash(payload, "verify_hash")
    return _write(
        run_root / "verify" / f"{payload['verify_hash']}.json", payload
    )


def publish_candidate_chain(
    *,
    run_root: Path,
    catalog_path: Path,
    manifest_path: Path,
) -> Path:
    """Create a same-volume immutable candidate publication before independent Verify."""

    target = run_root / "published"
    if target.exists():
        raise ValueError("published root already exists")
    outputs = target / "outputs"
    outputs.mkdir(parents=True)
    catalog = read_canonical_json(catalog_path)
    manifest = read_canonical_json(manifest_path)
    _verified_self_hash(catalog, "catalog_hash")
    _verified_self_hash(manifest, "manifest_hash")
    for item in cast(list[dict[str, object]], catalog["files"]):
        relative = _safe_relative(item["relative_path"])
        source = run_root / "staging" / relative
        destination = outputs / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.link(source, destination)
    _write(target / "catalog.json", catalog)
    _write(target / "manifest.json", manifest)
    pending: dict[str, object] = {
        "schema_name": "s2p18-candidate-publication-v1",
        "schema_version": "1.0",
        "run_id": run_root.name,
        "catalog_hash": catalog["catalog_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "status": "PENDING_INDEPENDENT_VERIFY",
        "created_at": _now(),
        "stage3_locked": True,
    }
    pending["candidate_publication_hash"] = _self_hash(
        pending, "candidate_publication_hash"
    )
    return _write(
        target / "candidate-publication.json", pending
    )


def seal_publication(*, run_root: Path, verify_path: Path) -> Path:
    verify = read_canonical_json(verify_path)
    verify_hash = _verified_self_hash(verify, "verify_hash")
    if verify.get("status") != "PASS" or verify.get("run_id") != run_root.name:
        raise ValueError("publication requires the matching PASS Verify")
    target = run_root / "published"
    publication: dict[str, object] = {
        "schema_name": "s2p18-publication-v1",
        "schema_version": "1.0",
        "run_id": run_root.name,
        "verify_hash": verify_hash,
        "published_at": _now(),
        "stage3_locked": True,
    }
    publication["publication_hash"] = _self_hash(publication, "publication_hash")
    return _write(target / "publication.json", publication)


def producer_receipt(
    *,
    task_id: str,
    run_root: Path,
    output_files: Sequence[Path],
    row_count: int,
    result_status: str,
    authority_hash: str,
    adapter_plan_hash: str,
    code_commit: str,
    upstream_receipt_hashes: Mapping[str, str],
) -> Path:
    """Helper used by each separately bound Task producer executable."""

    if task_id not in TASK_ORDER or row_count < 0 or result_status != "PASS":
        raise ValueError("Task producer cannot seal a non-PASS receipt")
    task_root = run_root / "staging" / task_id
    entries = []
    for path in sorted(output_files):
        if not path.is_file() or path.is_symlink() or task_root not in path.parents:
            raise ValueError("Task output is outside its staging root")
        entries.append(
            {
                "relative_path": str(path.relative_to(task_root)),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    if not entries:
        raise ValueError("Task producer must emit at least one output")
    payload: dict[str, object] = {
        "schema_name": TASK_RECEIPT_SCHEMA,
        "schema_version": "1.0",
        "task_id": task_id,
        "run_id": run_root.name,
        "authority_hash": authority_hash,
        "adapter_plan_hash": adapter_plan_hash,
        "code_commit": code_commit,
        "upstream_receipt_hashes": dict(sorted(upstream_receipt_hashes.items())),
        "status": "PASS",
        "row_count": row_count,
        "output_files": entries,
        "completed_at": _now(),
        "historical_execution_claim": False,
    }
    payload["task_receipt_hash"] = _self_hash(payload, "task_receipt_hash")
    return _write(
        run_root / "receipts" / f"{task_id}.json", payload
    )
