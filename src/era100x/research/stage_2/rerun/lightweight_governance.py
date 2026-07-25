"""Small, receipt-driven Stage 2 governance for a single-developer workflow."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import fcntl
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast

from .orchestrator import (
    TASKS,
    RetryableInterruption,
    TaskAdapter,
    TaskHandoff,
    canonical_hash,
    current_commit,
    repository_clean,
)
from .production_adapters import (
    PLAN_SCHEMA,
    RECEIPT_SCHEMA,
    UPSTREAM_TASKS,
    VERIFIED_PREFIX_ADOPTION_SCHEMA,
    build_production_adapters,
    load_adapter_plan,
)
from .trade_supplement import verify_trade_supplement

POLICY_SCHEMA: Final = "stage2-active-policy-v2"
APPROVAL_SCHEMA: Final = "stage2-formal-approval-v2"
CHAIN_AUTHORITY_SCHEMA: Final = "stage2-chain-authority-v2"
T16_AUTHORITY_SCHEMA: Final = "stage2-s2p13-t16-binning-authority-v2"
REHEARSAL_SCHEMA: Final = "stage2-plan-v13-seven-day-rehearsal-v1"
REHEARSAL_PASS_MODE: Final = "FINAL_CODE_7_DAY_REHEARSAL_PASS"
BACKGROUND_WAIVER_MODE: Final = "EXPLICIT_BACKGROUND_RUNTIME_WAIVER"
BACKGROUND_WAIVER_SCOPE: Final = "UNATTENDED_NON_RESEARCH_HOURS"
VERIFIED_PREFIX_SCHEMA: Final = "stage2-verified-prefix-adoption-v1"
VERIFIED_PREFIX_TASKS: Final = ("S2P13-T11", "S2P13-T12")


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.parent.is_symlink():
        raise ValueError(f"unsafe or missing Stage 2 evidence: {path}")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Stage 2 evidence root must be an object")
    return cast(dict[str, Any], value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _self_hash_valid(payload: dict[str, Any], field: str) -> bool:
    claimed = payload.get(field)
    body = {key: value for key, value in payload.items() if key != field}
    return isinstance(claimed, str) and claimed == canonical_hash(body)


def _write_exclusive(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    with path.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return path


@dataclass(frozen=True, slots=True)
class Stage2ActivePolicy:
    path: Path
    payload: dict[str, Any]
    policy_hash: str
    contract_hashes: dict[str, str]
    preregistration_path: Path
    preregistration_hash: str
    evidence_root: Path
    trade_supplement_path: Path
    trade_supplement_file_hash: str
    trade_supplement_acceptance_hash: str

    @property
    def operations_root(self) -> Path:
        return self.evidence_root / "operations"


def load_policy(path: Path, *, repository_root: Path) -> Stage2ActivePolicy:
    payload = _read_json(path)
    required = {
        "schema_name",
        "schema_version",
        "stage",
        "stage_plan_version",
        "execution_limit",
        "stage3_locked",
        "code_commit_mode",
        "contract_paths",
        "preregistration_path",
        "evidence_root",
        "task_dag",
        "full_history_scope",
        "required_gates",
        "rehearsal_gate_policy",
        "trade_supplement_acceptance_path",
    }
    if set(payload) != required:
        raise ValueError("Stage 2 active policy fields drift")
    if (
        payload["schema_name"] != POLICY_SCHEMA
        or payload["schema_version"] != "2.0"
        or payload["stage"] != "S2"
        or payload["stage_plan_version"] != "1.3"
        or payload["execution_limit"] != "S2P13-T16"
        or payload["stage3_locked"] is not True
        or payload["code_commit_mode"] != "CURRENT_CLEAN_HEAD"
        or payload["task_dag"] != {task: list(UPSTREAM_TASKS[task]) for task in TASKS}
        or payload["full_history_scope"]
        != {"start_date": "2020-01-01", "end_date_exclusive": "2026-07-04"}
        or payload["rehearsal_gate_policy"]
        != {
            "default_required": True,
            "explicit_background_waiver_allowed": True,
            "waiver_scope": BACKGROUND_WAIVER_SCOPE,
            "waiver_must_bind_current_commit": True,
        }
    ):
        raise ValueError("Stage 2 active policy contract drift")
    contract_hashes: dict[str, str] = {}
    for relative_value in cast(list[object], payload["contract_paths"]):
        relative = Path(str(relative_value))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe Stage 2 contract path")
        target = repository_root / relative
        if target.is_symlink() or not target.is_file():
            raise ValueError(f"missing Stage 2 contract: {relative}")
        contract_hashes[str(relative)] = _sha256_file(target)
    preregistration_relative = Path(str(payload["preregistration_path"]))
    if preregistration_relative.is_absolute() or ".." in preregistration_relative.parts:
        raise ValueError("unsafe Stage 2 preregistration path")
    preregistration_path = repository_root / preregistration_relative
    if preregistration_path.is_symlink() or not preregistration_path.is_file():
        raise ValueError("missing Stage 2 preregistration")
    evidence_root = Path(str(payload["evidence_root"]))
    if not evidence_root.is_absolute() or evidence_root.is_symlink():
        raise ValueError("unsafe Stage 2 evidence root")
    preregistration_hash = _sha256_file(preregistration_path)
    trade_supplement_path = Path(str(payload["trade_supplement_acceptance_path"]))
    if not trade_supplement_path.is_absolute() or trade_supplement_path.is_symlink():
        raise ValueError("unsafe Trade supplement acceptance path")
    trade_supplement = verify_trade_supplement(trade_supplement_path)
    trade_supplement_file_hash = _sha256_file(trade_supplement_path)
    resolved = {
        "policy": payload,
        "contract_hashes": contract_hashes,
        "preregistration_hash": preregistration_hash,
        "trade_supplement_file_hash": trade_supplement_file_hash,
        "trade_supplement_acceptance_hash": trade_supplement["acceptance_hash"],
    }
    return Stage2ActivePolicy(
        path=path,
        payload=payload,
        policy_hash=canonical_hash(resolved),
        contract_hashes=contract_hashes,
        preregistration_path=preregistration_path,
        preregistration_hash=preregistration_hash,
        evidence_root=evidence_root,
        trade_supplement_path=trade_supplement_path,
        trade_supplement_file_hash=trade_supplement_file_hash,
        trade_supplement_acceptance_hash=str(trade_supplement["acceptance_hash"]),
    )


def validate_rehearsal(path: Path, *, commit: str) -> dict[str, Any]:
    payload = _read_json(path)
    if (
        not _self_hash_valid(payload, "receipt_hash")
        or payload.get("schema_name") != REHEARSAL_SCHEMA
        or payload.get("status") != "PASS"
        or payload.get("code_commit") != commit
        or tuple(payload.get("tasks", ())) != TASKS
        or payload.get("ui_projection") != "PASS"
        or payload.get("verify") != "PASS"
        or payload.get("authority_created") is not False
        or payload.get("formal_binning_snapshot_created") is not False
        or payload.get("formal_run_id_created") is not False
    ):
        raise ValueError("final-code seven-day rehearsal is not valid for this commit")
    return payload


def record_approval(
    *,
    policy: Stage2ActivePolicy,
    repository_root: Path,
    rehearsal_path: Path | None,
    approved_by: str,
    approval_source: str,
    approved_at: str | None = None,
    background_runtime_waiver: bool = False,
    waiver_reason: str | None = None,
) -> Path:
    """Write one append-only approval without changing the repository."""

    if not repository_clean(repository_root):
        raise ValueError("formal approval requires a clean repository")
    commit = current_commit(repository_root)
    if background_runtime_waiver:
        if rehearsal_path is not None:
            raise ValueError("background waiver and rehearsal receipt are mutually exclusive")
        normalized_reason = (waiver_reason or "").strip()
        if not normalized_reason:
            raise ValueError("background waiver requires an explicit reason")
        rehearsal = None
        rehearsal_gate_mode = BACKGROUND_WAIVER_MODE
        waiver = {
            "scope": BACKGROUND_WAIVER_SCOPE,
            "reason": normalized_reason,
            "explicitly_approved": True,
            "does_not_waive": [
                "COMMIT_BOUND_HUMAN_APPROVAL",
                "CHAIN_AUTHORITY",
                "INPUT_HASH_VALIDATION",
                "UNIQUE_RUN_LOCK",
                "FULL_RECONCILIATION",
                "FULL_VERIFY",
                "STAGE3_LOCK",
            ],
        }
    else:
        if rehearsal_path is None:
            raise ValueError("formal approval requires rehearsal by default")
        if waiver_reason is not None:
            raise ValueError("waiver reason is forbidden without background waiver")
        rehearsal = validate_rehearsal(rehearsal_path, commit=commit)
        rehearsal_gate_mode = REHEARSAL_PASS_MODE
        waiver = None
    existing = [
        path
        for path in policy.operations_root.glob("approvals/approval-*.json")
        if (
            (_read_json(path).get("code_commit"), _read_json(path).get("policy_hash"))
            == (commit, policy.policy_hash)
        )
    ]
    if existing:
        if len(existing) == 1:
            return existing[0]
        raise ValueError("multiple formal approvals already bind this commit and Policy")
    payload: dict[str, Any] = {
        "schema_name": APPROVAL_SCHEMA,
        "schema_version": "2.0",
        "status": "APPROVED",
        "stage_plan_version": "1.3",
        "tasks": list(TASKS),
        "code_commit": commit,
        "policy_path": str(policy.path),
        "policy_hash": policy.policy_hash,
        "contract_hashes": policy.contract_hashes,
        "preregistration_hash": policy.preregistration_hash,
        "trade_supplement_acceptance_path": str(policy.trade_supplement_path),
        "trade_supplement_file_hash": policy.trade_supplement_file_hash,
        "trade_supplement_acceptance_hash": policy.trade_supplement_acceptance_hash,
        "rehearsal_gate_mode": rehearsal_gate_mode,
        "rehearsal_receipt_path": str(rehearsal_path) if rehearsal_path is not None else None,
        "rehearsal_receipt_hash": rehearsal["receipt_hash"] if rehearsal is not None else None,
        "background_runtime_waiver": waiver,
        "full_history_scope": policy.payload["full_history_scope"],
        "evidence_root": str(policy.evidence_root),
        "approved_by": approved_by,
        "approved_at": approved_at or datetime.now(UTC).isoformat(),
        "approval_source": approval_source,
        "stage3_locked": True,
    }
    payload["approval_hash"] = canonical_hash(payload)
    return _write_exclusive(
        policy.operations_root / "approvals" / f"approval-{payload['approval_hash']}.json",
        payload,
    )


def validate_approval(
    path: Path, *, policy: Stage2ActivePolicy, repository_root: Path
) -> dict[str, Any]:
    payload = _read_json(path)
    commit = current_commit(repository_root)
    if (
        not _self_hash_valid(payload, "approval_hash")
        or payload.get("schema_name") != APPROVAL_SCHEMA
        or payload.get("status") != "APPROVED"
        or payload.get("code_commit") != commit
        or payload.get("policy_hash") != policy.policy_hash
        or payload.get("contract_hashes") != policy.contract_hashes
        or payload.get("preregistration_hash") != policy.preregistration_hash
        or payload.get("trade_supplement_acceptance_path") != str(policy.trade_supplement_path)
        or payload.get("trade_supplement_file_hash") != policy.trade_supplement_file_hash
        or payload.get("trade_supplement_acceptance_hash")
        != policy.trade_supplement_acceptance_hash
        or payload.get("full_history_scope") != policy.payload["full_history_scope"]
        or payload.get("evidence_root") != str(policy.evidence_root)
        or tuple(payload.get("tasks", ())) != TASKS
        or payload.get("stage3_locked") is not True
    ):
        raise ValueError("formal approval binding drift")
    rehearsal_gate_mode = payload.get("rehearsal_gate_mode")
    if rehearsal_gate_mode == REHEARSAL_PASS_MODE:
        if payload.get("background_runtime_waiver") is not None:
            raise ValueError("formal approval rehearsal gate drift")
        rehearsal = validate_rehearsal(
            Path(str(payload["rehearsal_receipt_path"])),
            commit=commit,
        )
        if payload.get("rehearsal_receipt_hash") != rehearsal["receipt_hash"]:
            raise ValueError("formal approval rehearsal receipt drift")
    elif rehearsal_gate_mode == BACKGROUND_WAIVER_MODE:
        waiver = payload.get("background_runtime_waiver")
        if (
            payload.get("rehearsal_receipt_path") is not None
            or payload.get("rehearsal_receipt_hash") is not None
            or not isinstance(waiver, dict)
            or waiver.get("scope") != BACKGROUND_WAIVER_SCOPE
            or waiver.get("explicitly_approved") is not True
            or not str(waiver.get("reason", "")).strip()
            or waiver.get("does_not_waive")
            != [
                "COMMIT_BOUND_HUMAN_APPROVAL",
                "CHAIN_AUTHORITY",
                "INPUT_HASH_VALIDATION",
                "UNIQUE_RUN_LOCK",
                "FULL_RECONCILIATION",
                "FULL_VERIFY",
                "STAGE3_LOCK",
            ]
        ):
            raise ValueError("formal approval background waiver drift")
    else:
        raise ValueError("formal approval rehearsal gate drift")
    if not repository_clean(repository_root):
        raise ValueError("formal approval cannot authorize a dirty repository")
    return payload


def freeze_chain_authority(
    *, approval_path: Path, policy: Stage2ActivePolicy, repository_root: Path
) -> Path:
    approval = validate_approval(approval_path, policy=policy, repository_root=repository_root)
    payload: dict[str, Any] = {
        "schema_name": CHAIN_AUTHORITY_SCHEMA,
        "schema_version": "2.0",
        "status": "SEALED",
        "code_commit": approval["code_commit"],
        "policy_hash": policy.policy_hash,
        "approval_hash": approval["approval_hash"],
        "rehearsal_gate_mode": approval["rehearsal_gate_mode"],
        "background_runtime_waiver": approval["background_runtime_waiver"],
        "contract_hashes": policy.contract_hashes,
        "preregistration_hash": policy.preregistration_hash,
        "trade_supplement_acceptance_path": str(policy.trade_supplement_path),
        "trade_supplement_file_hash": policy.trade_supplement_file_hash,
        "trade_supplement_acceptance_hash": policy.trade_supplement_acceptance_hash,
        "task_dag": policy.payload["task_dag"],
        "full_history_scope": policy.payload["full_history_scope"],
        "stage3_locked": True,
    }
    payload["authority_hash"] = canonical_hash(payload)
    return _write_exclusive(
        policy.operations_root
        / "authorities"
        / f"chain-authority-{payload['authority_hash']}.json",
        payload,
    )


def freeze_t16_authority(
    *,
    chain_authority_path: Path,
    handoffs: dict[str, dict[str, Any]],
    policy: Stage2ActivePolicy,
) -> Path:
    chain = _read_json(chain_authority_path)
    if (
        not _self_hash_valid(chain, "authority_hash")
        or chain.get("schema_name") != CHAIN_AUTHORITY_SCHEMA
        or chain.get("policy_hash") != policy.policy_hash
        or chain.get("stage3_locked") is not True
    ):
        raise ValueError("ChainAuthority drift before T16")
    required = ("S2P13-T11", "S2P13-T13", "S2P13-T15")
    if set(handoffs) != set(required):
        raise ValueError("T16 Authority requires exact dynamic upstream handoffs")
    bindings: dict[str, Any] = {}
    for task in required:
        handoff = handoffs[task]
        if (
            handoff.get("task_id") != task
            or handoff.get("execution_mode") != "FORMAL"
            or handoff.get("verify_status") != "PASS"
            or not handoff.get("run_id")
        ):
            raise ValueError(f"T16 upstream is not a formal PASS handoff: {task}")
        bindings[task] = handoff
    payload: dict[str, Any] = {
        "schema_name": T16_AUTHORITY_SCHEMA,
        "schema_version": "2.0",
        "status": "SEALED",
        "chain_authority_hash": chain["authority_hash"],
        "code_commit": chain["code_commit"],
        "policy_hash": policy.policy_hash,
        "preregistration_hash": policy.preregistration_hash,
        "trade_supplement_acceptance_path": str(policy.trade_supplement_path),
        "trade_supplement_file_hash": policy.trade_supplement_file_hash,
        "trade_supplement_acceptance_hash": policy.trade_supplement_acceptance_hash,
        "upstream_handoffs": bindings,
        "bin_source_roles": ["TRAIN"],
        "outcome_fields_read_before_matching": [],
        "stage3_locked": True,
    }
    payload["authority_hash"] = canonical_hash(payload)
    return _write_exclusive(
        policy.operations_root / "authorities" / f"t16-authority-{payload['authority_hash']}.json",
        payload,
    )


def prepare_adapter_plan(
    *,
    approval_path: Path,
    chain_authority_path: Path,
    policy: Stage2ActivePolicy,
    repository_root: Path,
    adopted_prefix: dict[str, TaskHandoff] | None = None,
    adopted_source_chain_root: Path | None = None,
) -> tuple[Path, Path]:
    """Create one immutable argv plan underneath the approved evidence root."""

    approval = validate_approval(approval_path, policy=policy, repository_root=repository_root)
    chain = _read_json(chain_authority_path)
    if (
        not _self_hash_valid(chain, "authority_hash")
        or chain.get("approval_hash") != approval["approval_hash"]
    ):
        raise ValueError("adapter plan ChainAuthority binding drift")
    chain_root = policy.evidence_root / "chains" / str(approval["approval_hash"])
    operations_root = chain_root / "operations"
    evidence_root = chain_root / "tasks"
    evidence_root.mkdir(parents=True, exist_ok=False)
    producer = repository_root / "scripts/run_stage2_v13_producer.py"
    scope = cast(dict[str, str], policy.payload["full_history_scope"])
    if adopted_prefix is not None and (
        tuple(adopted_prefix) != VERIFIED_PREFIX_TASKS
        or adopted_source_chain_root is None
        or not adopted_source_chain_root.is_absolute()
        or adopted_source_chain_root.is_symlink()
        or not adopted_source_chain_root.is_dir()
    ):
        raise ValueError("verified prefix adoption must bind exact T11-T12 source evidence")
    tasks: dict[str, Any] = {}
    for task in TASKS:
        task_root = evidence_root / task
        artifact_root = task_root / "artifacts"
        artifact_root.mkdir(parents=True)
        allowed_artifact_root = (
            Path(adopted_prefix[task].artifact_root)
            if adopted_prefix is not None and task in adopted_prefix
            else artifact_root
        )

        def command(mode: str, *, task_id: str = task) -> list[str]:
            return [
                sys.executable,
                str(producer),
                task_id,
                mode,
                "--execution-mode",
                "FORMAL",
                "--scope-mode",
                "FULL_HISTORY",
                "--start-date",
                scope["start_date"],
                "--end-date-exclusive",
                scope["end_date_exclusive"],
                "--repository-root",
                str(repository_root),
            ]

        tasks[task] = {
            "required_upstream_tasks": list(UPSTREAM_TASKS[task]),
            "static_preflight_command": command("static-preflight"),
            "input_preflight_command": command("input-preflight"),
            "run_command": command("run"),
            "resume_command": command("resume"),
            "allowed_artifact_root": str(allowed_artifact_root),
            "checkpoint_path": str(task_root / "checkpoint.json"),
            "receipt_path": str(task_root / "receipt.json"),
        }
    payload: dict[str, Any] = {
        "schema_name": PLAN_SCHEMA,
        "status": "APPROVED",
        "stage_plan_version": "1.3",
        "code_commit": approval["code_commit"],
        "evidence_root": str(evidence_root),
        "preregistration_path": str(policy.preregistration_path),
        "preregistration_hash": policy.preregistration_hash,
        "trade_supplement_acceptance_path": str(policy.trade_supplement_path),
        "trade_supplement_file_hash": policy.trade_supplement_file_hash,
        "trade_supplement_acceptance_hash": policy.trade_supplement_acceptance_hash,
        "chain_authority_path": str(chain_authority_path),
        "chain_authority_hash": chain["authority_hash"],
        "tasks": tasks,
        "verified_prefix_source": (
            {
                "source_chain_root": str(adopted_source_chain_root),
                "tasks": {
                    task: {
                        "source_run_id": adopted_prefix[task].run_id,
                        "source_receipt_hash": adopted_prefix[task].producer_receipt_hash,
                        "output_hash": adopted_prefix[task].output_hash,
                        "row_count": adopted_prefix[task].row_count,
                    }
                    for task in VERIFIED_PREFIX_TASKS
                },
            }
            if adopted_prefix is not None
            else None
        ),
        "formal_run_created": False,
    }
    payload["adapter_plan_hash"] = canonical_hash(payload)
    plan_path = chain_root / f"adapter-plan-{payload['adapter_plan_hash']}.json"
    _write_exclusive(plan_path, payload)
    return plan_path, operations_root


def _producer_handoff_payload(handoff: TaskHandoff) -> dict[str, object]:
    payload = handoff.payload()
    for field in ("consumer_readback", "reconciliation", "verify_status"):
        payload.pop(field)
    return payload


def _load_verified_prefix(
    *,
    source_chain_root: Path,
    repository_root: Path,
) -> tuple[dict[str, TaskHandoff], dict[str, Path]]:
    if (
        not source_chain_root.is_absolute()
        or source_chain_root.is_symlink()
        or not source_chain_root.is_dir()
    ):
        raise ValueError("verified-prefix source chain is unsafe or missing")
    plans = sorted(source_chain_root.glob("adapter-plan-*.json"))
    if len(plans) != 1:
        raise ValueError("verified-prefix source requires one exact adapter plan")
    source_checkpoint = _read_json(source_chain_root / "operations" / "checkpoint.json")
    if (
        source_checkpoint.get("status") != "TERMINAL_FAILED"
        or source_checkpoint.get("stage3_locked") is not True
    ):
        raise ValueError("verified-prefix source must be a preserved terminal chain")
    source_commit = str(source_checkpoint.get("code_commit", ""))
    source_plan = load_adapter_plan(plans[0], code_commit=source_commit)
    source_adapters = build_production_adapters(
        source_plan,
        supervisor_root=source_chain_root / "operations",
        repository_root=repository_root,
    )
    handoffs: dict[str, TaskHandoff] = {}
    receipt_paths: dict[str, Path] = {}
    for task in VERIFIED_PREFIX_TASKS:
        spec = source_plan.tasks[task]
        if not spec.receipt_path.is_file():
            raise ValueError(f"verified-prefix source receipt is missing: {task}")
        adapter = source_adapters[task]
        handoff = adapter.run_or_resume()
        if (
            handoff.task_id != task
            or handoff.execution_mode != "FORMAL"
            or handoff.consumer_readback != "PASS"
            or handoff.reconciliation != "PASS"
            or handoff.verify_status != "PASS"
        ):
            raise ValueError(f"verified-prefix source is not a formal PASS: {task}")
        handoffs[task] = handoff
        receipt_paths[task] = spec.receipt_path
    if handoffs["S2P13-T12"].row_count != 532_708:
        raise ValueError("verified-prefix T12 row count drift")
    return handoffs, receipt_paths


def _write_adopted_receipt(
    *,
    task: str,
    source_handoff: TaskHandoff,
    source_receipt_path: Path,
    source_chain_root: Path,
    destination_receipt_path: Path,
    destination_plan_hash: str,
    destination_commit: str,
    destination_chain_id: str,
    upstream_handoffs: dict[str, dict[str, object]],
) -> TaskHandoff:
    source_receipt = _read_json(source_receipt_path)
    receipt: dict[str, Any] = {
        "schema_name": RECEIPT_SCHEMA,
        "status": "PASS",
        "stage_plan_version": "1.3",
        "execution_mode": "FORMAL",
        "task_id": task,
        "code_commit": destination_commit,
        "chain_id": destination_chain_id,
        "run_id": source_handoff.run_id,
        "evidence_id": source_handoff.run_id,
        "artifact_root": source_handoff.artifact_root,
        "snapshot_id": source_handoff.snapshot_id,
        "manifest_path": source_handoff.manifest_path,
        "manifest_hash": source_handoff.manifest_hash,
        "catalog_path": source_handoff.catalog_path,
        "catalog_hash": source_handoff.catalog_hash,
        "adapter_plan_hash": destination_plan_hash,
        "upstream_handoffs": upstream_handoffs,
        "execution_scope": source_receipt["execution_scope"],
        "output_hash": source_handoff.output_hash,
        "row_count": source_handoff.row_count,
        "consumer_readback": "PASS",
        "reconciliation": "PASS",
        "verify_status": "PASS",
        "verified_prefix_adoption": {
            "schema_name": VERIFIED_PREFIX_ADOPTION_SCHEMA,
            "mode": "READ_ONLY",
            "source_chain_root": str(source_chain_root),
            "source_code_commit": source_receipt["code_commit"],
            "source_receipt_path": str(source_receipt_path),
            "source_receipt_hash": source_receipt["receipt_hash"],
            "source_run_id": source_handoff.run_id,
            "source_task_id": task,
        },
    }
    receipt["receipt_hash"] = canonical_hash(receipt)
    _write_exclusive(destination_receipt_path, receipt)
    return TaskHandoff(
        task_id=task,
        execution_mode="FORMAL",
        chain_id=destination_chain_id,
        run_id=source_handoff.run_id,
        evidence_id=str(source_handoff.run_id),
        artifact_root=source_handoff.artifact_root,
        snapshot_id=source_handoff.snapshot_id,
        manifest_path=source_handoff.manifest_path,
        manifest_hash=source_handoff.manifest_hash,
        catalog_path=source_handoff.catalog_path,
        catalog_hash=source_handoff.catalog_hash,
        output_hash=source_handoff.output_hash,
        row_count=source_handoff.row_count,
        execution_scope_hash=source_handoff.execution_scope_hash,
        producer_receipt_hash=str(receipt["receipt_hash"]),
        consumer_readback="PASS",
        reconciliation="PASS",
        verify_status="PASS",
    )


def adopt_verified_prefix(
    *,
    approval_path: Path,
    source_chain_root: Path,
    policy: Stage2ActivePolicy,
    repository_root: Path,
) -> dict[str, Any]:
    """Create one append-only successor seeded by verified T11-T12 receipts."""

    approval = validate_approval(
        approval_path,
        policy=policy,
        repository_root=repository_root,
    )
    source_handoffs, source_receipt_paths = _load_verified_prefix(
        source_chain_root=source_chain_root,
        repository_root=repository_root,
    )
    chain_path = freeze_chain_authority(
        approval_path=approval_path,
        policy=policy,
        repository_root=repository_root,
    )
    plan_path, operations_root = prepare_adapter_plan(
        approval_path=approval_path,
        chain_authority_path=chain_path,
        policy=policy,
        repository_root=repository_root,
        adopted_prefix=source_handoffs,
        adopted_source_chain_root=source_chain_root,
    )
    plan = load_adapter_plan(plan_path, code_commit=str(approval["code_commit"]))
    destination_chain_id = f"stage2-s2p13-successor-{plan.plan_hash[:12]}"
    adopted: dict[str, TaskHandoff] = {}
    for task in VERIFIED_PREFIX_TASKS:
        upstream = (
            {}
            if task == "S2P13-T11"
            else {"S2P13-T11": _producer_handoff_payload(adopted["S2P13-T11"])}
        )
        adopted[task] = _write_adopted_receipt(
            task=task,
            source_handoff=source_handoffs[task],
            source_receipt_path=source_receipt_paths[task],
            source_chain_root=source_chain_root,
            destination_receipt_path=plan.tasks[task].receipt_path,
            destination_plan_hash=plan.plan_hash,
            destination_commit=str(approval["code_commit"]),
            destination_chain_id=destination_chain_id,
            upstream_handoffs=upstream,
        )
    adapters = build_production_adapters(
        plan,
        supervisor_root=operations_root,
        repository_root=repository_root,
    )
    chain_authority_hash = _read_json(chain_path)["authority_hash"]
    checkpoint_path = operations_root / "checkpoint.json"
    preliminary_checkpoint = {
        "schema_name": "stage2-lightweight-chain-checkpoint-v2",
        "status": "NOT_STARTED",
        "code_commit": approval["code_commit"],
        "approval_hash": approval["approval_hash"],
        "chain_authority_hash": chain_authority_hash,
        "current_task": "S2P13-T12",
        "tasks": {
            task: (
                {"status": "PASS", "handoff": adopted[task].payload()}
                if task == "S2P13-T11"
                else {"status": "NOT_STARTED", "handoff": None}
            )
            for task in TASKS
        },
        "stage3_locked": True,
    }
    if checkpoint_path.exists():
        raise ValueError("verified-prefix destination checkpoint already exists")
    _write_checkpoint(checkpoint_path, preliminary_checkpoint)
    verified = {task: adapters[task].run_or_resume() for task in VERIFIED_PREFIX_TASKS}
    if verified != adopted:
        raise ValueError("verified-prefix destination read-back drift")
    adoption_payload: dict[str, Any] = {
        "schema_name": VERIFIED_PREFIX_SCHEMA,
        "status": "PASS",
        "mode": "READ_ONLY",
        "approval_hash": approval["approval_hash"],
        "chain_authority_hash": chain_authority_hash,
        "adapter_plan_hash": plan.plan_hash,
        "code_commit": approval["code_commit"],
        "source_chain_root": str(source_chain_root),
        "tasks": {
            task: {
                "source_receipt_path": str(source_receipt_paths[task]),
                "source_receipt_hash": source_handoffs[task].producer_receipt_hash,
                "adoption_receipt_path": str(plan.tasks[task].receipt_path),
                "adoption_receipt_hash": adopted[task].producer_receipt_hash,
                "run_id": adopted[task].run_id,
                "row_count": adopted[task].row_count,
                "output_hash": adopted[task].output_hash,
                "verify_status": adopted[task].verify_status,
            }
            for task in VERIFIED_PREFIX_TASKS
        },
        "next_task": "S2P13-T13",
        "stage3_locked": True,
    }
    adoption_payload["adoption_hash"] = canonical_hash(adoption_payload)
    adoption_path = (
        operations_root
        / "adoptions"
        / (f"verified-prefix-{adoption_payload['adoption_hash']}.json")
    )
    _write_exclusive(adoption_path, adoption_payload)
    checkpoint = {
        "schema_name": "stage2-lightweight-chain-checkpoint-v2",
        "status": "NOT_STARTED",
        "code_commit": approval["code_commit"],
        "approval_hash": approval["approval_hash"],
        "chain_authority_hash": adoption_payload["chain_authority_hash"],
        "current_task": "S2P13-T13",
        "tasks": {
            task: (
                {
                    "status": "PASS",
                    "handoff": adopted[task].payload(),
                    "adoption_receipt_hash": adopted[task].producer_receipt_hash,
                }
                if task in adopted
                else {"status": "NOT_STARTED", "handoff": None}
            )
            for task in TASKS
        },
        "verified_prefix_adoption_path": str(adoption_path),
        "verified_prefix_adoption_hash": adoption_payload["adoption_hash"],
        "stage3_locked": True,
    }
    _write_checkpoint(checkpoint_path, checkpoint)
    return {
        "status": "PASS",
        "approval_hash": approval["approval_hash"],
        "chain_authority_path": str(chain_path),
        "adapter_plan_path": str(plan_path),
        "operations_root": str(operations_root),
        "verified_prefix_adoption_path": str(adoption_path),
        "verified_prefix_adoption_hash": adoption_payload["adoption_hash"],
        "next_task": "S2P13-T13",
        "stage3_locked": True,
    }


def _write_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


class LightweightSupervisor:
    """One lock and one checkpoint; task state comes only from receipts."""

    def __init__(
        self,
        *,
        root: Path,
        approval: dict[str, Any],
        chain_authority_path: Path,
        adapters: dict[str, TaskAdapter],
    ) -> None:
        if set(adapters) != set(TASKS):
            raise ValueError("lightweight supervisor requires the exact Stage 2 DAG")
        self.root = root
        self.approval = approval
        self.chain_authority_path = chain_authority_path
        self.adapters = adapters
        self.checkpoint_path = root / "checkpoint.json"
        self.lock_path = root / "chain.lock"

    def _initial(self) -> dict[str, Any]:
        chain = _read_json(self.chain_authority_path)
        return {
            "schema_name": "stage2-lightweight-chain-checkpoint-v2",
            "status": "NOT_STARTED",
            "code_commit": self.approval["code_commit"],
            "approval_hash": self.approval["approval_hash"],
            "chain_authority_hash": chain["authority_hash"],
            "current_task": TASKS[0],
            "tasks": {task: {"status": "NOT_STARTED", "handoff": None} for task in TASKS},
            "stage3_locked": True,
        }

    def run_or_resume(self) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("STAGE2_CHAIN_ALREADY_RUNNING") from exc
            checkpoint = (
                _read_json(self.checkpoint_path)
                if self.checkpoint_path.exists()
                else self._initial()
            )
            if checkpoint.get("approval_hash") != self.approval["approval_hash"]:
                raise ValueError("lightweight checkpoint approval drift")
            if checkpoint["status"] == "COMPLETE":
                return checkpoint
            if checkpoint["status"] == "TERMINAL_FAILED":
                raise RuntimeError("terminal chain requires a separately approved successor")
            try:
                for task in TASKS:
                    if checkpoint["tasks"][task]["status"] == "PASS":
                        continue
                    checkpoint.update({"status": "PREFLIGHT", "current_task": task})
                    _write_checkpoint(self.checkpoint_path, checkpoint)
                    self.adapters[task].static_preflight()
                checkpoint["status"] = "IN_PROGRESS"
                for task in TASKS:
                    task_state = checkpoint["tasks"][task]
                    if task_state["status"] == "PASS":
                        continue
                    checkpoint["current_task"] = task
                    task_state["status"] = "IN_PROGRESS"
                    _write_checkpoint(self.checkpoint_path, checkpoint)
                    self.adapters[task].input_preflight()
                    handoff = self.adapters[task].run_or_resume()
                    if handoff.task_id != task:
                        raise ValueError("adapter returned another task")
                    task_state.update({"status": "PASS", "handoff": handoff.payload()})
                    _write_checkpoint(self.checkpoint_path, checkpoint)
            except RetryableInterruption as exc:
                current = str(checkpoint.get("current_task", ""))
                if current in checkpoint["tasks"]:
                    checkpoint["tasks"][current]["status"] = "RETRYABLE_INTERRUPTED"
                checkpoint.update({"status": "RETRYABLE_INTERRUPTED", "reason": str(exc)})
                _write_checkpoint(self.checkpoint_path, checkpoint)
                return checkpoint
            except Exception as exc:
                current = str(checkpoint.get("current_task", ""))
                if current in checkpoint["tasks"]:
                    checkpoint["tasks"][current]["status"] = "TERMINAL_FAILED"
                checkpoint.update({"status": "TERMINAL_FAILED", "reason": str(exc)})
                _write_checkpoint(self.checkpoint_path, checkpoint)
                raise
            checkpoint.update({"status": "COMPLETE", "current_task": TASKS[-1]})
            _write_checkpoint(self.checkpoint_path, checkpoint)
            return checkpoint


def run_formal_chain(
    *,
    approval_path: Path,
    policy: Stage2ActivePolicy,
    repository_root: Path,
) -> dict[str, Any]:
    approval = validate_approval(approval_path, policy=policy, repository_root=repository_root)
    authorities = sorted(policy.operations_root.glob("authorities/chain-authority-*.json"))
    matching = [
        path
        for path in authorities
        if _read_json(path).get("approval_hash") == approval["approval_hash"]
    ]
    chain_path = (
        matching[0]
        if len(matching) == 1
        else freeze_chain_authority(
            approval_path=approval_path,
            policy=policy,
            repository_root=repository_root,
        )
        if not matching
        else None
    )
    if chain_path is None:
        raise ValueError("multiple ChainAuthority objects bind one approval")
    plans = sorted(
        (policy.evidence_root / "chains" / str(approval["approval_hash"])).glob(
            "adapter-plan-*.json"
        )
    )
    if plans:
        if len(plans) != 1:
            raise ValueError("multiple adapter plans bind one approval")
        plan_path = plans[0]
        operations_root = plan_path.parent / "operations"
    else:
        plan_path, operations_root = prepare_adapter_plan(
            approval_path=approval_path,
            chain_authority_path=chain_path,
            policy=policy,
            repository_root=repository_root,
        )
    plan = load_adapter_plan(plan_path, code_commit=str(approval["code_commit"]))
    adapters = build_production_adapters(
        plan,
        supervisor_root=operations_root,
        repository_root=repository_root,
    )
    bound_environment = {
        "ERA_S2P13_CHAIN_AUTHORITY_PATH": str(chain_path),
        "ERA_S2P13_POLICY_PATH": str(policy.path),
        "ERA_S2P13_TRADE_SUPPLEMENT_ACCEPTANCE_PATH": str(policy.trade_supplement_path),
        "ERA_S2P13_TRADE_SUPPLEMENT_ACCEPTANCE_HASH": policy.trade_supplement_file_hash,
    }
    old_environment = {name: os.environ.get(name) for name in bound_environment}
    os.environ.update(bound_environment)
    try:
        return LightweightSupervisor(
            root=operations_root,
            approval=approval,
            chain_authority_path=chain_path,
            adapters=adapters,
        ).run_or_resume()
    finally:
        for name, value in old_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def verify_formal_chain(
    *,
    approval_path: Path,
    policy: Stage2ActivePolicy,
    repository_root: Path,
) -> dict[str, Any]:
    """Strictly read every final receipt without starting missing work."""

    approval = validate_approval(approval_path, policy=policy, repository_root=repository_root)
    chain_root = policy.evidence_root / "chains" / str(approval["approval_hash"])
    plans = sorted(chain_root.glob("adapter-plan-*.json"))
    if len(plans) != 1:
        raise ValueError("formal Verify requires one exact adapter plan")
    operations_root = chain_root / "operations"
    checkpoint = _read_json(operations_root / "checkpoint.json")
    if (
        checkpoint.get("status") != "COMPLETE"
        or checkpoint.get("approval_hash") != approval["approval_hash"]
        or checkpoint.get("stage3_locked") is not True
    ):
        raise ValueError("formal chain is not complete")
    adoption_path_value = checkpoint.get("verified_prefix_adoption_path")
    adoption_hash = checkpoint.get("verified_prefix_adoption_hash")
    adoption: dict[str, Any] | None = None
    if adoption_path_value is not None or adoption_hash is not None:
        adoption_path = Path(str(adoption_path_value))
        if (
            not adoption_path.is_absolute()
            or adoption_path.is_symlink()
            or not adoption_path.is_file()
            or not adoption_path.resolve().is_relative_to(operations_root.resolve())
        ):
            raise ValueError("formal Verify verified-prefix path drift")
        adoption = _read_json(adoption_path)
        if (
            not _self_hash_valid(adoption, "adoption_hash")
            or adoption.get("schema_name") != VERIFIED_PREFIX_SCHEMA
            or adoption.get("status") != "PASS"
            or adoption.get("mode") != "READ_ONLY"
            or adoption.get("approval_hash") != approval["approval_hash"]
            or adoption.get("code_commit") != approval["code_commit"]
            or adoption.get("adoption_hash") != adoption_hash
            or adoption.get("next_task") != "S2P13-T13"
            or adoption.get("stage3_locked") is not True
            or tuple(cast(dict[str, Any], adoption.get("tasks", {}))) != VERIFIED_PREFIX_TASKS
        ):
            raise ValueError("formal Verify verified-prefix adoption drift")
    plan = load_adapter_plan(plans[0], code_commit=str(approval["code_commit"]))
    adapters = build_production_adapters(
        plan,
        supervisor_root=operations_root,
        repository_root=repository_root,
    )
    verified: dict[str, Any] = {}
    for task in TASKS:
        if not plan.tasks[task].receipt_path.is_file():
            raise ValueError(f"formal Verify is missing receipt: {task}")
        handoff = adapters[task].run_or_resume()
        recorded = cast(dict[str, Any], checkpoint["tasks"])[task]["handoff"]
        if handoff.payload() != recorded:
            raise ValueError(f"formal Verify checkpoint drift: {task}")
        if adoption is not None and task in VERIFIED_PREFIX_TASKS:
            adopted_task = cast(dict[str, Any], adoption["tasks"])[task]
            if (
                adopted_task.get("adoption_receipt_hash") != handoff.producer_receipt_hash
                or adopted_task.get("run_id") != handoff.run_id
                or adopted_task.get("row_count") != handoff.row_count
                or adopted_task.get("output_hash") != handoff.output_hash
                or adopted_task.get("verify_status") != "PASS"
            ):
                raise ValueError(f"formal Verify adopted handoff drift: {task}")
        verified[task] = {
            "run_id": handoff.run_id,
            "row_count": handoff.row_count,
            "output_hash": handoff.output_hash,
            "verify_status": handoff.verify_status,
        }
    result: dict[str, Any] = {
        "schema_name": "stage2-lightweight-chain-verify-v2",
        "status": "PASS",
        "approval_hash": approval["approval_hash"],
        "code_commit": approval["code_commit"],
        "tasks": verified,
        "verified_prefix_adoption_hash": adoption_hash,
        "stage3_locked": True,
    }
    result["verify_hash"] = canonical_hash(result)
    return result


def repository_head(repository_root: Path) -> dict[str, Any]:
    return {
        "commit": current_commit(repository_root),
        "clean": repository_clean(repository_root),
        "branch": subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=repository_root, text=True
        ).strip(),
    }
