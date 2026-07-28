"""Fail-closed Plan v1.8 repair policy and source-audit bindings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from era100x.research.stage_2.acceptance.canonical_json import (
    canonical_content_hash,
    sha256_file,
)
from era100x.research.stage_2.statistics.bootstrap.formatting import read_json

from .source_audit import LifecycleSourceAudit


@dataclass(frozen=True, slots=True)
class LifecycleRepairPolicy:
    """Validated implementation authority; it does not authorize a formal Run."""

    path: Path
    payload: dict[str, Any]
    policy_hash: str
    preregistration_hash: str
    source_audit_hash: str
    contract_hashes: dict[str, str]


def load_source_audit(path: Path, *, expected_hash: str) -> LifecycleSourceAudit:
    read_json(path)
    audit = LifecycleSourceAudit.model_validate_json(path.read_bytes(), strict=True)
    if audit.status != "PASS" or audit.audit_hash != expected_hash:
        raise ValueError("Plan v1.8 source audit is not the frozen PASS artifact")
    return audit


def load_policy(path: Path, *, repository_root: Path) -> LifecycleRepairPolicy:
    payload = read_json(path)
    required = {
        "schema_name",
        "schema_version",
        "stage",
        "stage_plan_version",
        "execution_limit",
        "stage3_locked",
        "code_commit_mode",
        "formal_run_authorization",
        "contract_paths",
        "preregistration_path",
        "source_audit_path",
        "source_audit_hash",
        "task_dag",
        "allowed_operations",
        "blocked_operations",
        "required_gates",
    }
    if set(payload) != required:
        raise ValueError("Plan v1.8 policy fields drift")
    expected_dag = {
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
    if (
        payload["schema_name"] != "stage2-active-policy-v7"
        or payload["schema_version"] != "7.0"
        or payload["stage"] != "S2"
        or payload["stage_plan_version"] != "1.8"
        or payload["execution_limit"] != "S2P18-T20"
        or payload["stage3_locked"] is not True
        or payload["code_commit_mode"] != "CURRENT_CLEAN_HEAD_FOR_FORMAL_RUN"
        or payload["formal_run_authorization"] != "SEPARATE_COMMIT_BOUND_APPROVAL_REQUIRED"
        or payload["task_dag"] != expected_dag
    ):
        raise ValueError("Plan v1.8 policy contract drift")

    hashes: dict[str, str] = {}
    for raw in cast(list[object], payload["contract_paths"]):
        relative = Path(str(raw))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe Plan v1.8 contract path")
        hashes[str(relative)] = sha256_file(repository_root / relative)

    preregistration_path = repository_root / str(payload["preregistration_path"])
    preregistration = read_json(preregistration_path)
    claimed_preregistration_hash = str(preregistration.get("preregistration_hash"))
    calculated_preregistration_hash = canonical_content_hash(
        {
            key: value
            for key, value in preregistration.items()
            if key != "preregistration_hash"
        }
    )
    if (
        claimed_preregistration_hash != calculated_preregistration_hash
        or preregistration.get("formal_run_status")
        != "BLOCKED_PENDING_CLEAN_COMMIT_AND_SEPARATE_HUMAN_APPROVAL"
        or preregistration.get("stage3_locked") is not True
    ):
        raise ValueError("Plan v1.8 preregistration drift")

    source_audit_hash = str(payload["source_audit_hash"])
    audit_path = repository_root / str(payload["source_audit_path"])
    load_source_audit(audit_path, expected_hash=source_audit_hash)
    if preregistration.get("source_audit_hash") != source_audit_hash:
        raise ValueError("Plan v1.8 policy/preregistration source-audit drift")

    return LifecycleRepairPolicy(
        path=path,
        payload=payload,
        policy_hash=canonical_content_hash(
            {
                "policy": payload,
                "contract_hashes": hashes,
                "preregistration_hash": claimed_preregistration_hash,
                "source_audit_hash": source_audit_hash,
            }
        ),
        preregistration_hash=claimed_preregistration_hash,
        source_audit_hash=source_audit_hash,
        contract_hashes=hashes,
    )
