"""Fail-closed adoption of immutable T12-T18 Stage 2 evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from era100x.research.stage_2.acceptance.canonical_json import (
    canonical_content_hash,
    read_canonical_json,
)

ADOPTION_RULES_PATH: Final = Path("configs/research/stage_2/s2p110_sealed_adoption_v1.json")
ADOPTED_TASKS: Final = tuple(f"S2P110-T{number:02d}" for number in range(12, 19))
HEX64: Final = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class SealedTaskBinding:
    task_id: str
    source_task_id: str
    source_kind: str
    source_path: Path
    source_hash: str
    source_run_id: str
    source_output_tree_hash: str
    row_count: int
    source_artifact_root: Path | None
    source_output_path: Path | None
    source_manifest_hash: str
    source_catalog_hash: str
    adoption_binding_hash: str

    def lock_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "source_task_id": self.source_task_id,
            "source_kind": self.source_kind,
            "source_path": str(self.source_path),
            "source_hash": self.source_hash,
            "source_run_id": self.source_run_id,
            "source_output_tree_hash": self.source_output_tree_hash,
            "row_count": self.row_count,
            "source_artifact_root": (
                str(self.source_artifact_root) if self.source_artifact_root else None
            ),
            "source_output_path": (
                str(self.source_output_path) if self.source_output_path else None
            ),
            "source_manifest_hash": self.source_manifest_hash,
            "source_catalog_hash": self.source_catalog_hash,
            "adoption_binding_hash": self.adoption_binding_hash,
        }


@dataclass(frozen=True, slots=True)
class SealedAdoptionBundle:
    rules_hash: str
    bundle_hash: str
    tasks: dict[str, SealedTaskBinding]
    compatibility_basis: dict[str, Any]

    def lock_payload(self) -> list[dict[str, object]]:
        return [self.tasks[task].lock_payload() for task in ADOPTED_TASKS]


def _safe_json(path: Path, *, label: str) -> dict[str, Any]:
    current = path
    while current != current.parent:
        if current.is_symlink():
            raise ValueError(f"BLOCKED_SEALED_ADOPTION_INCOMPATIBLE: {label} symlink")
        current = current.parent
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"BLOCKED_SEALED_ADOPTION_INCOMPATIBLE: {label} missing")
    value = read_canonical_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"BLOCKED_SEALED_ADOPTION_INCOMPATIBLE: {label} is not an object")
    return value


def _self_hash(payload: dict[str, Any], field: str, *, label: str) -> str:
    claimed = payload.get(field)
    calculated = canonical_content_hash(
        {key: value for key, value in payload.items() if key != field}
    )
    if claimed != calculated or not HEX64.fullmatch(str(claimed)):
        raise ValueError(f"BLOCKED_SEALED_ADOPTION_INCOMPATIBLE: {label} self Hash")
    return str(claimed)


def _artifact_json(path: Path, field: str, expected: str, *, label: str) -> str:
    payload = _safe_json(path, label=label)
    actual = _self_hash(payload, field, label=label)
    if actual != expected:
        raise ValueError(f"BLOCKED_SEALED_ADOPTION_INCOMPATIBLE: {label} binding")
    return actual


def _receipt_binding(task_id: str, rule: dict[str, Any]) -> SealedTaskBinding:
    path = Path(str(rule["source_path"]))
    receipt = _safe_json(path, label=f"{task_id} receipt")
    receipt_hash = _self_hash(receipt, "receipt_hash", label=f"{task_id} receipt")
    source_task_id = str(rule["source_task_id"])
    if (
        receipt_hash != rule["source_hash"]
        or receipt.get("status") != "PASS"
        or receipt.get("verify_status") != "PASS"
        or receipt.get("execution_mode") != "FORMAL"
        or receipt.get("stage_plan_version") != "1.3"
        or receipt.get("task_id") != source_task_id
        or receipt.get("run_id") != rule["source_run_id"]
        or receipt.get("row_count") != rule["row_count"]
        or receipt.get("execution_scope")
        != {
            "mode": "FULL_HISTORY",
            "start_date": "2020-01-01",
            "end_date_exclusive": "2026-07-04",
            "execution_scope_hash": (
                "22a200b815b912037c6c5cc8c823139de51ce25908d90a3336183b33a4b03ce3"
            ),
        }
    ):
        raise ValueError(f"BLOCKED_SEALED_ADOPTION_INCOMPATIBLE: {task_id} receipt")
    manifest_path = Path(str(receipt["manifest_path"]))
    catalog_path = Path(str(receipt["catalog_path"]))
    manifest_hash = _artifact_json(
        manifest_path,
        "manifest_hash",
        str(receipt["manifest_hash"]),
        label=f"{task_id} Manifest",
    )
    catalog_hash = _artifact_json(
        catalog_path,
        "catalog_hash",
        str(receipt["catalog_hash"]),
        label=f"{task_id} Catalog",
    )
    catalog = _safe_json(catalog_path, label=f"{task_id} Catalog")
    output_entries = [
        item
        for item in catalog.get("files", [])
        if isinstance(item, dict) and item.get("relative_path") == "output.json"
    ]
    if (
        catalog_hash != rule["source_output_tree_hash"]
        or len(output_entries) != 1
        or output_entries[0].get("content_hash") != receipt["output_hash"]
    ):
        raise ValueError(f"BLOCKED_SEALED_ADOPTION_INCOMPATIBLE: {task_id} Catalog tree")
    artifact_root = Path(str(receipt["artifact_root"]))
    output_path = (
        Path(str(rule["source_output_path"]))
        if rule.get("source_output_path")
        else artifact_root / "output.json"
    )
    if (
        not artifact_root.is_absolute()
        or artifact_root.is_symlink()
        or not output_path.is_file()
        or output_path.is_symlink()
        or canonical_content_hash(_safe_json(output_path, label=f"{task_id} output"))
        != receipt["output_hash"]
    ):
        raise ValueError(f"BLOCKED_SEALED_ADOPTION_INCOMPATIBLE: {task_id} output")
    binding_payload = {
        "task_id": task_id,
        "source_task_id": source_task_id,
        "source_kind": "PRODUCTION_TASK_RECEIPT",
        "source_path": str(path),
        "source_hash": receipt_hash,
        "source_run_id": str(receipt["run_id"]),
        "source_output_tree_hash": catalog_hash,
        "source_manifest_hash": manifest_hash,
        "source_catalog_hash": catalog_hash,
        "row_count": int(receipt["row_count"]),
    }
    return SealedTaskBinding(
        task_id=task_id,
        source_task_id=source_task_id,
        source_kind="PRODUCTION_TASK_RECEIPT",
        source_path=path,
        source_hash=receipt_hash,
        source_run_id=str(receipt["run_id"]),
        source_output_tree_hash=catalog_hash,
        row_count=int(receipt["row_count"]),
        source_artifact_root=artifact_root,
        source_output_path=output_path,
        source_manifest_hash=manifest_hash,
        source_catalog_hash=catalog_hash,
        adoption_binding_hash=canonical_content_hash(binding_payload),
    )


def _verify_binding(task_id: str, rule: dict[str, Any]) -> SealedTaskBinding:
    path = Path(str(rule["source_path"]))
    verify = _safe_json(path, label=f"{task_id} Verify")
    verify_hash = _self_hash(verify, "verify_hash", label=f"{task_id} Verify")
    source_task_id = str(rule["source_task_id"])
    artifact_root = Path(str(rule["source_artifact_root"]))
    if (
        verify_hash != rule["source_hash"]
        or verify.get("status") != "PASS"
        or verify.get("run_id") != rule["source_run_id"]
        or verify.get("stage3_locked") is not True
        or not artifact_root.is_absolute()
        or artifact_root.is_symlink()
        or not artifact_root.is_dir()
    ):
        raise ValueError(f"BLOCKED_SEALED_ADOPTION_INCOMPATIBLE: {task_id} Verify")
    manifest_path = artifact_root / "manifest.json"
    catalog_path = artifact_root / "catalog.json"
    manifest_hash = _artifact_json(
        manifest_path,
        "manifest_hash",
        str(verify["manifest_hash"]),
        label=f"{task_id} Manifest",
    )
    catalog_hash = _artifact_json(
        catalog_path,
        "catalog_hash",
        str(verify["catalog_hash"]),
        label=f"{task_id} Catalog",
    )
    if catalog_hash != rule["source_output_tree_hash"]:
        raise ValueError(f"BLOCKED_SEALED_ADOPTION_INCOMPATIBLE: {task_id} output tree")
    binding_payload = {
        "task_id": task_id,
        "source_task_id": source_task_id,
        "source_kind": "FORMAL_VERIFY",
        "source_path": str(path),
        "source_hash": verify_hash,
        "source_run_id": str(verify["run_id"]),
        "source_output_tree_hash": catalog_hash,
        "source_manifest_hash": manifest_hash,
        "source_catalog_hash": catalog_hash,
        "row_count": int(rule["row_count"]),
    }
    return SealedTaskBinding(
        task_id=task_id,
        source_task_id=source_task_id,
        source_kind="FORMAL_VERIFY",
        source_path=path,
        source_hash=verify_hash,
        source_run_id=str(verify["run_id"]),
        source_output_tree_hash=catalog_hash,
        row_count=int(rule["row_count"]),
        source_artifact_root=artifact_root,
        source_output_path=None,
        source_manifest_hash=manifest_hash,
        source_catalog_hash=catalog_hash,
        adoption_binding_hash=canonical_content_hash(binding_payload),
    )


def load_sealed_adoption_bundle(
    repository_root: Path,
    *,
    current_bindings: dict[str, str],
) -> SealedAdoptionBundle:
    """Validate every adopted source and bind it to the current frozen contracts."""

    rules_path = (repository_root / ADOPTION_RULES_PATH).resolve()
    rules = _safe_json(rules_path, label="sealed adoption rules")
    rules_hash = _self_hash(rules, "adoption_rules_hash", label="sealed adoption rules")
    tasks = rules.get("tasks")
    basis = rules.get("compatibility_basis")
    if (
        rules.get("schema_name") != "s2p110-sealed-adoption-rules"
        or rules.get("schema_version") != "1.0"
        or rules.get("stage_plan_version") != "1.10"
        or rules.get("scope_start_date") != "2020-01-01"
        or rules.get("scope_end_date_exclusive") != "2026-07-04"
        or rules.get("historical_execution_claim") is not False
        or rules.get("stage3_locked") is not True
        or not isinstance(tasks, dict)
        or set(tasks) != set(ADOPTED_TASKS)
        or not isinstance(basis, dict)
        or basis.get("h2_input") != "CANONICAL_TRADES_ONLY"
        or basis.get("lifecycle_ohlc_consumed_as_h2_label") is not False
        or basis.get("matching_authority_hash") != current_bindings.get("matching_contract_hash")
        or basis.get("cluster_authority_hash") != current_bindings.get("cluster_contract_hash")
    ):
        raise ValueError("BLOCKED_SEALED_ADOPTION_INCOMPATIBLE: contract basis")
    bindings: dict[str, SealedTaskBinding] = {}
    for task_id in ADOPTED_TASKS:
        raw = tasks[task_id]
        if not isinstance(raw, dict):
            raise ValueError(f"BLOCKED_SEALED_ADOPTION_INCOMPATIBLE: {task_id} rule")
        rule = cast(dict[str, Any], raw)
        bindings[task_id] = (
            _receipt_binding(task_id, rule)
            if rule.get("source_kind") == "PRODUCTION_TASK_RECEIPT"
            else _verify_binding(task_id, rule)
        )
    bundle_payload = {
        "rules_hash": rules_hash,
        "compatibility_basis": basis,
        "current_bindings": dict(sorted(current_bindings.items())),
        "tasks": [bindings[task].lock_payload() for task in ADOPTED_TASKS],
    }
    return SealedAdoptionBundle(
        rules_hash=rules_hash,
        bundle_hash=canonical_content_hash(bundle_payload),
        tasks=bindings,
        compatibility_basis=cast(dict[str, Any], basis),
    )


def validate_locked_adoptions(
    repository_root: Path,
    *,
    current_bindings: dict[str, str],
    expected_bundle_hash: str,
    locked_tasks: tuple[dict[str, Any], ...],
) -> SealedAdoptionBundle:
    bundle = load_sealed_adoption_bundle(
        repository_root,
        current_bindings=current_bindings,
    )
    if bundle.bundle_hash != expected_bundle_hash or tuple(bundle.lock_payload()) != locked_tasks:
        raise ValueError("BLOCKED_SEALED_ADOPTION_INCOMPATIBLE: inputs lock drift")
    return bundle
