"""Plan v1.9 policy loader for the personal formal-run architecture."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from era100x.research.stage_2.acceptance.canonical_json import (
    canonical_content_hash,
    sha256_file,
)

TASK_ORDER: Final = tuple(f"S2P19-T{number:02d}" for number in range(11, 21))
TASK_DAG: Final = {
    "S2P19-T11": (),
    "S2P19-T12": ("S2P19-T11",),
    "S2P19-T13": ("S2P19-T12",),
    "S2P19-T14": ("S2P19-T12",),
    "S2P19-T15": ("S2P19-T14",),
    "S2P19-T16": ("S2P19-T11", "S2P19-T13", "S2P19-T15"),
    "S2P19-T17": ("S2P19-T16",),
    "S2P19-T18": ("S2P19-T16", "S2P19-T17"),
    "S2P19-T19": ("S2P19-T11", "S2P19-T16", "S2P19-T17", "S2P19-T18"),
    "S2P19-T20": ("S2P19-T19",),
}


@dataclass(frozen=True, slots=True)
class SoloRuntimePolicy:
    """Validated v1.9 contract bundle; it never authorizes a formal Run."""

    path: Path
    payload: dict[str, Any]
    policy_hash: str
    preregistration_hash: str
    contract_bundle_hash: str
    contract_hashes: dict[str, str]


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"unsafe or missing Plan v1.9 JSON contract: {path}")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"Plan v1.9 JSON contract root must be an object: {path}")
    return cast(dict[str, Any], value)


def load_policy(path: Path, *, repository_root: Path) -> SoloRuntimePolicy:
    payload = _read_json(path)
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
        "task_dag",
        "allowed_operations",
        "blocked_operations",
        "required_gates",
        "operator_commands",
        "historical_plan_v18_status",
    }
    expected_dag = {task: list(dependencies) for task, dependencies in TASK_DAG.items()}
    if set(payload) != required:
        raise ValueError("Plan v1.9 policy fields drift")
    if (
        payload["schema_name"] != "stage2-active-policy-v8"
        or payload["schema_version"] != "8.0"
        or payload["stage"] != "S2"
        or payload["stage_plan_version"] != "1.9"
        or payload["execution_limit"] != "S2P19-T20"
        or payload["stage3_locked"] is not True
        or payload["code_commit_mode"] != "CURRENT_CLEAN_HEAD_FOR_FORMAL_RUN"
        or payload["formal_run_authorization"] != "ONE_COMMIT_AND_INPUTS_LOCK_BOUND_HUMAN_APPROVAL"
        or payload["task_dag"] != expected_dag
        or payload["operator_commands"] != ["status", "prepare", "run", "resume"]
        or payload["allowed_operations"]
        != [
            "READ_ONLY_AUDIT",
            "VERIFY_EXISTING_EVIDENCE",
            "READ_ONLY_UI",
            "PREPARE_REAL_INPUTS_LOCK",
            "FREEZE_FORMAL_AUTHORITY",
            "RUN",
            "RESUME",
            "PUBLISH",
        ]
        or payload["blocked_operations"] != ["STAGE3"]
        or payload["historical_plan_v18_status"] != "SUPERSEDED_UNEXECUTED"
    ):
        raise ValueError("Plan v1.9 policy contract drift")
    hashes: dict[str, str] = {}
    for raw in cast(list[object], payload["contract_paths"]):
        relative = Path(str(raw))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe Plan v1.9 contract path")
        target = repository_root / relative
        if not target.is_file() or target.is_symlink():
            raise ValueError(f"missing Plan v1.9 contract: {relative}")
        hashes[str(relative)] = sha256_file(target)
    preregistration_path = repository_root / str(payload["preregistration_path"])
    preregistration = _read_json(preregistration_path)
    claimed_preregistration_hash = str(preregistration.get("preregistration_hash"))
    calculated_preregistration_hash = canonical_content_hash(
        {key: value for key, value in preregistration.items() if key != "preregistration_hash"}
    )
    if (
        preregistration.get("schema_name") != "stage2-plan-v19-solo-runtime-preregistration"
        or preregistration.get("stage_plan_version") != "1.9"
        or preregistration.get("task_dag") != expected_dag
        or preregistration.get("h2_primary_unchanged") is not True
        or preregistration.get("lifecycle_semantics_unchanged") is not True
        or preregistration.get("formal_run_status")
        != "BLOCKED_PENDING_PREPARE_AND_COMMIT_INPUT_LOCK_APPROVAL"
        or preregistration.get("stage3_locked") is not True
        or claimed_preregistration_hash != calculated_preregistration_hash
    ):
        raise ValueError("Plan v1.9 preregistration drift")
    semantics_relative = Path(str(preregistration.get("research_semantics_source")))
    if semantics_relative.is_absolute() or ".." in semantics_relative.parts:
        raise ValueError("unsafe Plan v1.9 research semantics source")
    semantics = _read_json(repository_root / semantics_relative)
    semantics_hash = canonical_content_hash(
        {key: value for key, value in semantics.items() if key != "preregistration_hash"}
    )
    if (
        semantics.get("preregistration_hash") != semantics_hash
        or preregistration.get("research_semantics_source_hash") != semantics_hash
    ):
        raise ValueError("Plan v1.9 research semantics source drift")
    contract_bundle_hash = canonical_content_hash(dict(sorted(hashes.items())))
    policy_hash = canonical_content_hash(
        {
            "policy": payload,
            "contract_hashes": dict(sorted(hashes.items())),
            "contract_bundle_hash": contract_bundle_hash,
            "preregistration_hash": claimed_preregistration_hash,
        }
    )
    return SoloRuntimePolicy(
        path=path,
        payload=payload,
        policy_hash=policy_hash,
        preregistration_hash=claimed_preregistration_hash,
        contract_bundle_hash=contract_bundle_hash,
        contract_hashes=hashes,
    )
