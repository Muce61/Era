"""Checkpointed orchestration primitives for the S2-T11 through S2-T15 rerun.

The module deliberately separates preparation from execution.  Merely importing it, inspecting
readiness, or serving its projection cannot create an Authority, Binning Set, or Run ID.  Formal
execution requires a self-hashed approval receipt that binds the clean code commit and the exact
governance documents.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

RERUN_TASKS = ("S2-T11", "S2-T12", "S2-T13", "S2-T14", "S2-T15")
STAGE2_ROOT = Path("/Volumes/FuckingLife/era100x_stage2")
OPERATIONS_ROOT = STAGE2_ROOT / "operations" / "s2-t11-t15-rerun"
REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
SAFE_CHAIN_ID = re.compile(r"^s2-t11-t15-rerun-\d{8}T\d{6}Z-[0-9a-f]{12}$")
SAFE_HASH = re.compile(r"^[0-9a-f]{64}$")
APPROVAL_SCHEMA = "stage2-s2t11-t15-rerun-approval-v1"
CHECKPOINT_SCHEMA = "stage2-s2t11-t15-rerun-checkpoint-v1"
HANDOFF_SCHEMA = "stage2-s2t11-t15-rerun-handoff-v1"

GOVERNANCE_PATHS = {
    "cr_2026_031": Path("docs/development/changes/CR-2026-031.md"),
    "cr_2026_032": Path("docs/development/changes/CR-2026-032.md"),
    "adr_s2_010": Path("docs/development/decisions/ADR-S2-010-historical-missingness.md"),
    "adr_s2_011": Path(
        "docs/development/decisions/ADR-S2-011-event-path-and-strategy-lifecycle-separation.md"
    ),
    "open_questions": Path("docs/development/OPEN_QUESTIONS.md"),
    "current_stage": Path("docs/development/CURRENT_STAGE.md"),
    "traceability": Path("docs/development/TRACEABILITY.md"),
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.parent.is_symlink():
        raise ValueError(f"unsafe or missing JSON evidence: {path}")
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError(f"JSON evidence must be an object: {path}")
    return cast(dict[str, Any], payload)


def _self_hash_matches(payload: Mapping[str, Any], field: str) -> bool:
    expected = payload.get(field)
    body = {key: value for key, value in payload.items() if key != field}
    return isinstance(expected, str) and expected == canonical_hash(body)


def current_code_commit(repository_root: Path = REPOSITORY_ROOT) -> str:
    value = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError("rerun orchestration requires an exact Git commit")
    return value


def repository_is_clean(repository_root: Path = REPOSITORY_ROOT) -> bool:
    output = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return not output.strip()


def governance_hashes(repository_root: Path = REPOSITORY_ROOT) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, relative in GOVERNANCE_PATHS.items():
        path = repository_root / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"missing governance file: {relative}")
        result[name] = sha256_file(path)
    return result


def governance_projection(repository_root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    cr31 = (repository_root / GOVERNANCE_PATHS["cr_2026_031"]).read_text(encoding="utf-8")
    cr32 = (repository_root / GOVERNANCE_PATHS["cr_2026_032"]).read_text(encoding="utf-8")
    adr10 = (repository_root / GOVERNANCE_PATHS["adr_s2_010"]).read_text(encoding="utf-8")
    adr11 = (repository_root / GOVERNANCE_PATHS["adr_s2_011"]).read_text(encoding="utf-8")
    oq = (repository_root / GOVERNANCE_PATHS["open_questions"]).read_text(encoding="utf-8")
    oq9_line = next((line for line in oq.splitlines() if "| OQ-S2-009 |" in line), "")
    oq10_line = next((line for line in oq.splitlines() if "| OQ-S2-010 |" in line), "")
    return {
        "cr_2026_031": "status: APPROVED" in cr31,
        "adr_s2_010": "APPROVED" in adr10.split("## Context", 1)[0],
        "cr_2026_032_direction": "status: APPROVED DIRECTION" in cr32,
        "adr_s2_011_direction": "APPROVED DIRECTION" in adr11.split("## Context", 1)[0],
        "oq_s2_009_status": (
            "RESOLVED" if "| RESOLVED" in oq9_line else "OPEN" if oq9_line else "UNKNOWN"
        ),
        "oq_s2_010_status": (
            "RESOLVED" if "| RESOLVED" in oq10_line else "OPEN" if oq10_line else "UNKNOWN"
        ),
        "t15_successor_authorized": (
            "S2-T11-T15 SUCCESSOR AUTHORIZED" in cr31
            and "OQ-S2-009 |" in oq
            and "| RESOLVED" in oq9_line
        ),
        "lifecycle_implementation_authorized": False,
        "seven_day_audit": "SKIPPED_BY_USER_FOR_THIS_RERUN",
        "governance_hashes": governance_hashes(repository_root),
    }


def validate_approval_receipt(
    path: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
    require_clean: bool = True,
) -> dict[str, Any]:
    payload = _safe_json(path)
    if not _self_hash_matches(payload, "approval_hash"):
        raise ValueError("rerun approval receipt self-hash mismatch")
    if payload.get("schema_name") != APPROVAL_SCHEMA or payload.get("status") != "APPROVED":
        raise ValueError("rerun approval receipt is not APPROVED v1 evidence")
    if tuple(payload.get("tasks", ())) != RERUN_TASKS:
        raise ValueError("rerun approval receipt task order changed")
    if payload.get("formal_successor_authorized") is not True:
        raise ValueError("formal T11-T15 successor is not authorized")
    if payload.get("skip_seven_day_audit") is not True:
        raise ValueError("this rerun approval must record the explicit seven-day-audit exception")
    if payload.get("lifecycle_implementation_authorized") is not False:
        raise ValueError("CR-2026-032 lifecycle implementation remains forbidden")
    availability_path_value = payload.get("availability_audit_path")
    if not isinstance(availability_path_value, str) or not availability_path_value:
        raise ValueError("rerun approval lacks the CR-2026-031 availability audit path")
    availability = _safe_json(Path(availability_path_value))
    if (
        availability.get("schema_name") != "stage2-s2t15-availability-audit-v1"
        or availability.get("status") != "PASS"
        or not _self_hash_matches(availability, "audit_hash")
        or payload.get("availability_audit_hash") != availability.get("audit_hash")
    ):
        raise ValueError("CR-2026-031 whole-range availability audit is not valid PASS evidence")
    projection = governance_projection(repository_root)
    if projection["oq_s2_009_status"] != "RESOLVED":
        raise ValueError("OQ-S2-009 must be RESOLVED before formal rerun")
    if projection["t15_successor_authorized"] is not True:
        raise ValueError("an explicit T15 successor authorization is missing")
    if payload.get("governance_hashes") != projection["governance_hashes"]:
        raise ValueError("rerun approval governance Hashes drifted")
    commit = current_code_commit(repository_root)
    if payload.get("code_commit") != commit:
        raise ValueError("rerun approval does not bind the current code commit")
    if require_clean and not repository_is_clean(repository_root):
        raise ValueError("formal rerun requires a clean repository")
    return payload


def create_approval_receipt(
    *,
    availability_audit_path: Path,
    approved_by: str,
    output_root: Path,
    repository_root: Path = REPOSITORY_ROOT,
) -> tuple[dict[str, Any], Path]:
    """Create one append-only operator approval after every governance gate is satisfied."""

    if not approved_by.strip():
        raise ValueError("approved_by must identify the human approver")
    if not repository_is_clean(repository_root):
        raise ValueError("rerun approval requires a clean repository")
    projection = governance_projection(repository_root)
    if projection["oq_s2_009_status"] != "RESOLVED":
        raise ValueError("OQ-S2-009 must be RESOLVED before approval")
    if projection["t15_successor_authorized"] is not True:
        raise ValueError("an explicit T15 successor authorization is missing")
    availability = _safe_json(availability_audit_path)
    if (
        availability.get("schema_name") != "stage2-s2t15-availability-audit-v1"
        or availability.get("status") != "PASS"
        or not _self_hash_matches(availability, "audit_hash")
    ):
        raise ValueError("CR-2026-031 whole-range availability audit is not valid PASS evidence")
    payload: dict[str, Any] = {
        "schema_name": APPROVAL_SCHEMA,
        "status": "APPROVED",
        "tasks": list(RERUN_TASKS),
        "formal_successor_authorized": True,
        "skip_seven_day_audit": True,
        "lifecycle_implementation_authorized": False,
        "availability_audit_path": str(availability_audit_path.resolve()),
        "availability_audit_hash": availability["audit_hash"],
        "governance_hashes": projection["governance_hashes"],
        "code_commit": current_code_commit(repository_root),
        "approved_by": approved_by.strip(),
        "approved_at": datetime.now(UTC).isoformat(),
    }
    payload["approval_hash"] = canonical_hash(payload)
    path = output_root / "approvals" / f"{payload['approval_hash']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    if path.exists():
        if path.is_symlink() or path.read_text(encoding="utf-8") != encoded:
            raise ValueError("rerun approval append-only conflict")
    else:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    validate_approval_receipt(path, repository_root=repository_root)
    return payload, path


def approval_readiness(
    approval_path: Path | None = None,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    governance = governance_projection(repository_root)
    result: dict[str, Any] = {
        "status": "BLOCKED",
        "reason_code": "S2_RERUN_SUCCESSOR_AUTHORIZATION_MISSING",
        "governance": governance,
        "approval_path": str(approval_path) if approval_path is not None else None,
        "formal_run_created": False,
    }
    if governance["oq_s2_009_status"] != "RESOLVED":
        result["reason_code"] = "S2_RERUN_OQ_S2_009_OPEN"
        return result
    if not governance["t15_successor_authorized"]:
        return result
    if approval_path is None:
        result["reason_code"] = "S2_RERUN_APPROVAL_RECEIPT_MISSING"
        return result
    try:
        approval = validate_approval_receipt(
            approval_path, repository_root=repository_root, require_clean=False
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        result["reason_code"] = "S2_RERUN_APPROVAL_RECEIPT_INVALID"
        result["reason"] = str(exc)
        return result
    result.update(
        {
            "status": "READY",
            "reason_code": "S2_RERUN_APPROVAL_READY",
            "approval_hash": approval["approval_hash"],
        }
    )
    return result


def new_chain_id(approval_hash: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    chain_id = f"s2-t11-t15-rerun-{timestamp}-{approval_hash[:12]}"
    if SAFE_CHAIN_ID.fullmatch(chain_id) is None:
        raise AssertionError("generated unsafe rerun chain ID")
    return chain_id


def initial_checkpoint(chain_id: str, approval: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_name": CHECKPOINT_SCHEMA,
        "chain_id": chain_id,
        "status": "NOT_STARTED",
        "reason_code": "S2_RERUN_READY",
        "approval_hash": approval["approval_hash"],
        "code_commit": approval["code_commit"],
        "current_task": "S2-T11",
        "current_action": "preflight",
        "tasks": {
            task: {
                "status": "NOT_STARTED",
                "action": "pending",
                "run_id": None,
                "snapshot_id": None,
                "verify_status": "NOT_RUN",
                "reason_code": f"{task.replace('-', '_')}_WAITING",
            }
            for task in RERUN_TASKS
        },
        "handoffs": {},
        "seven_day_audit": "SKIPPED_BY_USER_FOR_THIS_RERUN",
        "lifecycle_implementation_executed": False,
        "stage3_locked": True,
        "updated_at": datetime.now(UTC).isoformat(),
        "event_sequence": 0,
    }


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def append_event(chain_root: Path, checkpoint: dict[str, Any], event: Mapping[str, Any]) -> None:
    sequence = int(checkpoint.get("event_sequence", 0)) + 1
    payload = {
        "schema_name": "stage2-s2t11-t15-rerun-event-v1",
        "chain_id": checkpoint["chain_id"],
        "sequence": sequence,
        "created_at": datetime.now(UTC).isoformat(),
        **event,
    }
    payload["event_hash"] = canonical_hash(payload)
    path = chain_root / "events" / f"{sequence:06d}-{payload['event_hash']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    checkpoint["event_sequence"] = sequence
    checkpoint["updated_at"] = payload["created_at"]
    _atomic_write_json(chain_root / "checkpoint.json", checkpoint)


def create_chain(
    approval_path: Path,
    *,
    operations_root: Path = OPERATIONS_ROOT,
    repository_root: Path = REPOSITORY_ROOT,
) -> tuple[dict[str, Any], Path]:
    approval = validate_approval_receipt(approval_path, repository_root=repository_root)
    chain_id = new_chain_id(str(approval["approval_hash"]))
    chain_root = operations_root / chain_id
    chain_root.mkdir(parents=True, exist_ok=False)
    checkpoint = initial_checkpoint(chain_id, approval)
    _atomic_write_json(chain_root / "approval.json", approval)
    append_event(
        chain_root,
        checkpoint,
        {
            "event": "CHAIN_CREATED",
            "task_id": None,
            "action": "preflight",
            "status": "NOT_STARTED",
            "reason_code": "S2_RERUN_READY",
        },
    )
    return checkpoint, chain_root


def seal_handoff(
    chain_root: Path,
    *,
    task_id: str,
    evidence: Mapping[str, Any],
) -> tuple[dict[str, Any], Path]:
    if task_id not in RERUN_TASKS:
        raise ValueError("unknown rerun task")
    payload = {
        "schema_name": HANDOFF_SCHEMA,
        "chain_id": chain_root.name,
        "task_id": task_id,
        "status": "VERIFY_PASS",
        "historical_evidence_only": True,
        "stage3_locked": True,
        **evidence,
    }
    payload["handoff_hash"] = canonical_hash(payload)
    path = chain_root / "handoffs" / f"{task_id.lower()}-{payload['handoff_hash']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    return payload, path


def validate_handoff(path: Path, *, expected_task: str | None = None) -> dict[str, Any]:
    payload = _safe_json(path)
    if not _self_hash_matches(payload, "handoff_hash"):
        raise ValueError("rerun handoff self-hash mismatch")
    if payload.get("schema_name") != HANDOFF_SCHEMA or payload.get("status") != "VERIFY_PASS":
        raise ValueError("invalid rerun handoff contract")
    if expected_task is not None and payload.get("task_id") != expected_task:
        raise ValueError("rerun handoff task mismatch")
    if (
        payload.get("historical_evidence_only") is not True
        or payload.get("stage3_locked") is not True
    ):
        raise ValueError("rerun handoff crossed the historical/Stage-3 boundary")
    for field in ("run_id", "snapshot_id", "manifest_hash", "catalog_hash", "authority_hash"):
        value = payload.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"rerun handoff lacks {field}")
    return payload


def _chain_directories(operations_root: Path) -> tuple[Path, ...]:
    if not operations_root.is_dir() or operations_root.is_symlink():
        return ()
    return tuple(
        path
        for path in operations_root.iterdir()
        if path.is_dir() and not path.is_symlink() and SAFE_CHAIN_ID.fullmatch(path.name)
    )


def read_latest_chain_projection(
    stage2_root: Path = STAGE2_ROOT,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    readiness = approval_readiness(repository_root=repository_root)
    operations_root = stage2_root / "operations" / "s2-t11-t15-rerun"
    chains = _chain_directories(operations_root)
    if not chains:
        return {
            "chain_id": None,
            "status": readiness["status"],
            "reason_code": readiness["reason_code"],
            "current_task": None,
            "current_action": None,
            "tasks": {
                task: {"status": "BLOCKED", "reason_code": readiness["reason_code"]}
                for task in RERUN_TASKS
            },
            "governance": readiness["governance"],
            "seven_day_audit": "SKIPPED_BY_USER_FOR_THIS_RERUN",
            "historical_evidence_only": True,
            "lifecycle_implementation_executed": False,
            "stage3_locked": True,
        }
    newest = max(chains, key=lambda path: (path.stat().st_mtime_ns, path.name))
    checkpoint_path = newest / "checkpoint.json"
    try:
        checkpoint = _safe_json(checkpoint_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "chain_id": newest.name,
            "status": "EVIDENCE_INVALID",
            "reason_code": "S2_RERUN_CHECKPOINT_INVALID",
            "reason": str(exc),
            "tasks": {},
            "governance": readiness["governance"],
            "seven_day_audit": "SKIPPED_BY_USER_FOR_THIS_RERUN",
            "historical_evidence_only": True,
            "lifecycle_implementation_executed": False,
            "stage3_locked": True,
        }
    if (
        checkpoint.get("schema_name") != CHECKPOINT_SCHEMA
        or checkpoint.get("chain_id") != newest.name
    ):
        checkpoint["status"] = "EVIDENCE_INVALID"
        checkpoint["reason_code"] = "S2_RERUN_CHECKPOINT_CONTRACT_INVALID"
    checkpoint["governance"] = readiness["governance"]
    checkpoint["historical_evidence_only"] = True
    checkpoint["stage3_locked"] = True
    return checkpoint


def render_status(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


ProgressCallback = Callable[[str, str, Mapping[str, Any]], None]


def _snapshot_binding(run_root: Path, task_id: str, verify: Mapping[str, Any]) -> dict[str, Any]:
    snapshots_root = run_root / "published" / "snapshots"
    snapshots = (
        tuple(path for path in snapshots_root.iterdir() if path.is_dir() and not path.is_symlink())
        if snapshots_root.is_dir() and not snapshots_root.is_symlink()
        else ()
    )
    if len(snapshots) != 1:
        raise ValueError(f"{task_id} must publish exactly one snapshot")
    snapshot = snapshots[0]
    manifest = _safe_json(snapshot / "manifest.json")
    catalog = _safe_json(snapshot / "catalog.json")
    preflight = _safe_json(run_root / "manifests" / "preflight-authority.json")
    completion = _safe_json(run_root / "reports" / "completion.json")
    if verify.get("status") != "PASS" or completion.get("status") != "PASS":
        raise ValueError(f"{task_id} cannot hand off without Run and Verify PASS")
    run_id = run_root.name
    if manifest.get("run_id") != run_id or catalog.get("run_id") != run_id:
        raise ValueError(f"{task_id} published Run binding drift")
    snapshot_id = str(manifest.get("snapshot_id") or manifest.get("manifest_hash") or snapshot.name)
    if snapshot_id != snapshot.name:
        raise ValueError(f"{task_id} snapshot directory binding drift")
    result: dict[str, Any] = {
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "manifest_hash": manifest.get("manifest_hash"),
        "catalog_hash": catalog.get("catalog_hash"),
        "authority_hash": preflight.get("authority_hash"),
        "authority_path": str(run_root / "manifests" / "preflight-authority.json"),
        "code_commit": manifest.get("code_commit") or preflight.get("code_commit"),
        "run_root": str(run_root),
        "snapshot_root": str(snapshot),
        "verify_status": "PASS",
    }
    if any(
        not isinstance(result[field], str) or not result[field]
        for field in (
            "snapshot_id",
            "manifest_hash",
            "catalog_hash",
            "authority_hash",
            "code_commit",
        )
    ):
        raise ValueError(f"{task_id} terminal evidence lacks a required binding")
    instruments = catalog.get("instruments", {})
    if isinstance(instruments, dict):
        result["instruments"] = instruments
    if task_id == "S2-T13":
        result["total_path_rows"] = sum(
            int(item.get("first_passage", {}).get("row_count", 0))
            for item in instruments.values()
            if isinstance(item, dict)
        )
        result["total_classification_count"] = sum(
            int(item.get("first_passage", {}).get("classification_count", 0))
            for item in instruments.values()
            if isinstance(item, dict)
        )
    return result


class ProductionStageDriver:
    """Invoke the existing append-only runners with explicit successor handoffs."""

    def __init__(
        self,
        *,
        stage2_root: Path = STAGE2_ROOT,
        repository_root: Path = REPOSITORY_ROOT,
    ) -> None:
        self.stage2_root = stage2_root
        self.repository_root = repository_root

    @staticmethod
    def _configure_t11_source(binding: Mapping[str, Any]) -> Any:
        from era100x.research.stage_2.metrics.path import full_run as metrics

        metrics.SOURCE_S2T11_RUN_ID = str(binding["run_id"])
        metrics.SOURCE_S2T11_SNAPSHOT_ID = str(binding["snapshot_id"])
        metrics.SOURCE_S2T11_RUN_ROOT = metrics.RUNS_ROOT / metrics.SOURCE_S2T11_RUN_ID
        metrics.SOURCE_S2T11_SNAPSHOT_ROOT = Path(str(binding["snapshot_root"]))
        return metrics

    def _module(self, task_id: str, handoffs: Mapping[str, Mapping[str, Any]]) -> Any:
        if task_id == "S2-T11":
            from era100x.research.stage_2.paths.extraction import full_run as path_full_run

            return path_full_run
        if task_id == "S2-T12":
            return self._configure_t11_source(handoffs["S2-T11"])
        if task_id == "S2-T13":
            metrics = self._configure_t11_source(handoffs["S2-T11"])
            from era100x.research.stage_2.labels.first_passage import (
                full_run as passage_full_run,
            )

            for name in (
                "SOURCE_S2T11_RUN_ID",
                "SOURCE_S2T11_SNAPSHOT_ID",
                "SOURCE_S2T11_RUN_ROOT",
                "SOURCE_S2T11_SNAPSHOT_ROOT",
            ):
                setattr(passage_full_run, name, getattr(metrics, name))
            return passage_full_run
        if task_id == "S2-T14":
            from era100x.research.stage_2.labels.ambiguity import (
                full_run as ambiguity_full_run,
            )

            source = handoffs["S2-T13"]
            attributes = {
                "SOURCE_RUN_ID": str(source["run_id"]),
                "SOURCE_AUTHORITY_HASH": str(source["authority_hash"]),
                "SOURCE_SNAPSHOT_ID": str(source["snapshot_id"]),
                "SOURCE_MANIFEST_HASH": str(source["manifest_hash"]),
                "SOURCE_CATALOG_HASH": str(source["catalog_hash"]),
                "SOURCE_CODE_COMMIT": str(source["code_commit"]),
                "SOURCE_TOTAL_PATH_ROWS": int(source["total_path_rows"]),
                "SOURCE_TOTAL_CLASSIFICATIONS": int(source["total_classification_count"]),
                "SOURCE_RUN_ROOT": Path(str(source["run_root"])),
                "SOURCE_SNAPSHOT_ROOT": Path(str(source["snapshot_root"])),
                "SOURCE_HANDOFF_RECEIPT": Path(str(source["handoff_path"])),
            }
            for name, value in attributes.items():
                setattr(ambiguity_full_run, name, value)
            return ambiguity_full_run
        raise ValueError(f"unsupported task module: {task_id}")

    def _configure_t15(
        self,
        handoffs: Mapping[str, Mapping[str, Any]],
        approval_path: Path,
    ) -> Any:
        from era100x.research.stage_2.baselines.conditional import full_run
        from era100x.research.stage_2.baselines.conditional import successor_policy

        t11 = handoffs["S2-T11"]
        t13 = handoffs["S2-T13"]
        t14 = handoffs["S2-T14"]
        full_run.T11_RUN_ID = str(t11["run_id"])
        full_run.T11_SNAPSHOT_ID = str(t11["snapshot_id"])
        full_run.T11_AUTHORITY_HASH = str(t11["authority_hash"])
        full_run.T11_SNAPSHOT = Path(str(t11["snapshot_root"]))
        full_run.T11_AUTHORITY = Path(str(t11["authority_path"]))
        full_run.T13_RUN_ID = str(t13["run_id"])
        full_run.T13_SNAPSHOT_ID = str(t13["snapshot_id"])
        full_run.T13_SNAPSHOT = Path(str(t13["snapshot_root"]))
        full_run.T14_RUN_ID = str(t14["run_id"])
        full_run.T14_SNAPSHOT_ID = str(t14["snapshot_id"])
        full_run.T14_SNAPSHOT = Path(str(t14["snapshot_root"]))
        successor_policy.configure_rerun_successor_approval(approval_path)
        return full_run

    @staticmethod
    def _run_prefix(task_id: str) -> str:
        return {
            "S2-T11": "stage2-s2t11-paths-",
            "S2-T12": "stage2-s2t12-metrics-",
            "S2-T13": "stage2-s2t13-first-passage-",
            "S2-T14": "stage2-s2t14-ambiguity-bounds-",
            "S2-T15": "stage2-s2t15-conditional-",
        }[task_id]

    def _find_run(self, task_id: str, authority_hash: str) -> Path | None:
        candidates = tuple(
            path
            for path in (self.stage2_root / "runs").glob(f"{self._run_prefix(task_id)}*")
            if path.is_dir() and not path.is_symlink()
        )
        matches: list[Path] = []
        for path in candidates:
            authority_paths = (
                path / "manifests" / "preflight-authority.json",
                path / "manifests" / "authority.json",
            )
            for candidate in authority_paths:
                if candidate.is_file() and not candidate.is_symlink():
                    if _safe_json(candidate).get("authority_hash") == authority_hash:
                        matches.append(path)
                        break
        if len(matches) > 1:
            raise ValueError(f"multiple {task_id} Runs bind the same Authority")
        return matches[0] if matches else None

    def execute_task(
        self,
        task_id: str,
        *,
        handoffs: Mapping[str, Mapping[str, Any]],
        chain_root: Path,
        approval_path: Path,
        task_state: dict[str, Any],
        progress: ProgressCallback,
    ) -> dict[str, Any]:
        if task_id == "S2-T15":
            return self._execute_t15(
                handoffs=handoffs,
                chain_root=chain_root,
                approval_path=approval_path,
                task_state=task_state,
                progress=progress,
            )
        module = self._module(task_id, handoffs)
        authority_path_value = task_state.get("authority_path")
        if authority_path_value:
            authority_path = Path(str(authority_path_value))
            authority = _safe_json(authority_path)
        else:
            progress("preflight", "IN_PROGRESS", {})
            authority, authority_path = module.create_preflight_manifest(
                code_commit=module.current_code_commit()
            )
            progress(
                "preflight",
                "PASS",
                {
                    "authority_hash": authority["authority_hash"],
                    "authority_path": str(authority_path),
                },
            )
        authority_hash = str(authority["authority_hash"])
        run_root = self._find_run(task_id, authority_hash)
        if run_root is None:
            progress("run", "IN_PROGRESS", {"authority_hash": authority_hash})
            run_root = module.execute_run(preflight_path=authority_path, run_id=None)
        elif not (run_root / "reports" / "completion.json").is_file():
            progress("resume", "IN_PROGRESS", {"run_id": run_root.name})
            run_root = module.resume_run(run_root)
        progress("verify", "IN_PROGRESS", {"run_id": run_root.name})
        verify = module.verify_run(run_root)
        if verify.get("status") != "PASS":
            raise ValueError(f"{task_id} Verify failed: {verify}")
        binding = _snapshot_binding(run_root, task_id, verify)
        handoff, path = seal_handoff(chain_root, task_id=task_id, evidence=binding)
        binding = {**binding, "handoff_hash": handoff["handoff_hash"], "handoff_path": str(path)}
        progress("verify", "PASS", binding)
        return binding

    def _execute_t15(
        self,
        *,
        handoffs: Mapping[str, Mapping[str, Any]],
        chain_root: Path,
        approval_path: Path,
        task_state: dict[str, Any],
        progress: ProgressCallback,
    ) -> dict[str, Any]:
        full_run = self._configure_t15(handoffs, approval_path)
        from era100x.research.stage_2.baselines.conditional.binning_run import (
            freeze_binning_snapshots,
        )
        from era100x.research.stage_2.baselines.conditional.context_receipt_supplement import (
            build_context_receipt_supplement,
        )
        from era100x.research.stage_2.baselines.conditional.execution_run import (
            run_full_execution,
            verify_published_run,
        )
        from era100x.research.stage_2.baselines.conditional.receipt_supplement import (
            build_receipt_distribution_supplement,
        )

        progress("audit", "IN_PROGRESS", {})
        build_receipt_distribution_supplement()
        build_context_receipt_supplement()
        audit = full_run.audit_upstream()
        if audit.get("status") != "PASS":
            raise ValueError(f"S2-T15 upstream audit blocked: {audit.get('reason_code')}")
        audit_path = full_run.AUDIT_ROOT / f"{audit['audit_report_hash']}.json"
        progress("audit", "PASS", {"audit_path": str(audit_path)})
        authority_path_value = task_state.get("authority_path")
        if authority_path_value:
            authority_path = Path(str(authority_path_value))
            authority = _safe_json(authority_path)
        else:
            progress("freeze-authority", "IN_PROGRESS", {})
            authority_model, authority_path = full_run.freeze_authority(
                audit_path=audit_path,
                successor_approval_path=approval_path,
            )
            authority = authority_model.model_dump(mode="json")
            progress(
                "freeze-authority",
                "PASS",
                {
                    "authority_hash": authority["authority_hash"],
                    "authority_path": str(authority_path),
                },
            )
        binning_path_value = task_state.get("binning_set_path")
        if binning_path_value:
            binning_path = Path(str(binning_path_value))
            binning = _safe_json(binning_path)
        else:
            progress("freeze-bins", "IN_PROGRESS", {})
            binning, binning_path = freeze_binning_snapshots(
                authority_path=authority_path,
                bin_root=full_run.BIN_ROOT,
                t10_snapshot=full_run.T10_SNAPSHOT,
                t10_snapshot_id=full_run.T10_SNAPSHOT_ID,
                current_commit=full_run.current_code_commit(),
                repository_clean=full_run.repository_is_clean(),
            )
            progress(
                "freeze-bins",
                "PASS",
                {
                    "binning_set_hash": binning["binning_set_hash"],
                    "binning_set_path": str(binning_path),
                },
            )
        progress("preflight", "IN_PROGRESS", {})
        preflight = full_run.preflight(authority_path=authority_path, binning_set_path=binning_path)
        progress("preflight", "PASS", preflight)
        authority_hash = str(authority["authority_hash"])
        run_root = self._find_run("S2-T15", authority_hash)
        progress(
            "resume" if run_root is not None else "run",
            "IN_PROGRESS",
            {"run_id": run_root.name if run_root is not None else None},
        )
        manifest, published_path = run_full_execution(
            authority_path=authority_path,
            binning_set_path=binning_path,
            runs_root=full_run.RUNS_ROOT,
            t10_snapshot=full_run.T10_SNAPSHOT,
            t10_snapshot_id=full_run.T10_SNAPSHOT_ID,
            t13_snapshot=full_run.T13_SNAPSHOT,
            current_commit=full_run.current_code_commit(),
            repository_clean=full_run.repository_is_clean(),
            resume_run_id=run_root.name if run_root is not None else None,
        )
        run_root = full_run.RUNS_ROOT / str(manifest["run_id"])
        progress("verify", "IN_PROGRESS", {"run_id": run_root.name})
        verify, verify_path = verify_published_run(run_root=run_root)
        if verify.get("status") != "PASS":
            raise ValueError(f"S2-T15 Verify failed: {verify}")
        snapshot_id = str(manifest["snapshot_id"])
        evidence = {
            "run_id": run_root.name,
            "snapshot_id": snapshot_id,
            "manifest_hash": str(manifest.get("manifest_hash") or snapshot_id),
            "catalog_hash": str(verify.get("catalog_hash") or manifest.get("catalog_hash")),
            "authority_hash": authority_hash,
            "authority_path": str(authority_path),
            "code_commit": full_run.current_code_commit(),
            "run_root": str(run_root),
            "snapshot_root": str(published_path),
            "binning_set_hash": str(binning["binning_set_hash"]),
            "verify_path": str(verify_path),
            "verify_status": "PASS",
        }
        handoff, path = seal_handoff(
            chain_root,
            task_id="S2-T15",
            evidence=evidence,
        )
        evidence.update({"handoff_hash": handoff["handoff_hash"], "handoff_path": str(path)})
        progress("verify", "PASS", evidence)
        return evidence


def _newest_chain_root(operations_root: Path) -> Path:
    chains = _chain_directories(operations_root)
    if not chains:
        raise ValueError("no rerun chain exists")
    return max(chains, key=lambda path: (path.stat().st_mtime_ns, path.name))


def resume_chain(
    *,
    approval_path: Path,
    operations_root: Path = OPERATIONS_ROOT,
    repository_root: Path = REPOSITORY_ROOT,
    driver: ProductionStageDriver | None = None,
) -> dict[str, Any]:
    approval = validate_approval_receipt(approval_path, repository_root=repository_root)
    chain_root = _newest_chain_root(operations_root)
    checkpoint = _safe_json(chain_root / "checkpoint.json")
    if checkpoint.get("approval_hash") != approval.get("approval_hash"):
        raise ValueError("rerun chain approval receipt drift")
    if checkpoint.get("status") in {"PASS", "FAILED", "BLOCKED", "EVIDENCE_INVALID"}:
        return checkpoint
    stage_driver = driver or ProductionStageDriver(
        stage2_root=operations_root.parents[1], repository_root=repository_root
    )
    handoffs = cast(dict[str, dict[str, Any]], checkpoint.get("handoffs", {}))
    for task_id in RERUN_TASKS:
        task_state = cast(dict[str, Any], checkpoint["tasks"][task_id])
        if task_state.get("status") == "PASS":
            continue

        def progress(
            action: str,
            status: str,
            details: Mapping[str, Any],
            current_state: dict[str, Any] = task_state,
            current_task: str = task_id,
        ) -> None:
            current_state.update(details)
            current_state["status"] = status
            current_state["action"] = action
            action_code = action.upper().replace("-", "_")
            current_state["reason_code"] = (
                f"{current_task.replace('-', '_')}_{action_code}_{status}"
            )
            current_state["chain_id"] = checkpoint["chain_id"]
            checkpoint["status"] = "IN_PROGRESS"
            checkpoint["current_task"] = current_task
            checkpoint["current_action"] = action
            append_event(
                chain_root,
                checkpoint,
                {
                    "event": "TASK_PROGRESS",
                    "task_id": current_task,
                    "action": action,
                    "status": status,
                    "reason_code": current_state["reason_code"],
                    "details": dict(details),
                },
            )

        try:
            binding = stage_driver.execute_task(
                task_id,
                handoffs=handoffs,
                chain_root=chain_root,
                approval_path=approval_path,
                task_state=task_state,
                progress=progress,
            )
        except Exception as exc:
            task_state["status"] = "FAILED"
            task_state["reason_code"] = f"{task_id.replace('-', '_')}_FAILED_UNPUBLISHED"
            task_state["reason"] = str(exc)
            checkpoint["status"] = "FAILED"
            checkpoint["reason_code"] = task_state["reason_code"]
            append_event(
                chain_root,
                checkpoint,
                {
                    "event": "TASK_FAILED",
                    "task_id": task_id,
                    "action": task_state.get("action"),
                    "status": "FAILED",
                    "reason_code": task_state["reason_code"],
                    "reason": str(exc),
                },
            )
            raise
        handoffs[task_id] = binding
        checkpoint["handoffs"] = handoffs
        task_state.update(binding)
        task_state["status"] = "PASS"
        task_state["verify_status"] = "PASS"
        task_state["reason_code"] = f"{task_id.replace('-', '_')}_VERIFY_PASS"
        append_event(
            chain_root,
            checkpoint,
            {
                "event": "TASK_HANDOFF_SEALED",
                "task_id": task_id,
                "action": "handoff",
                "status": "PASS",
                "reason_code": task_state["reason_code"],
                "handoff_hash": binding["handoff_hash"],
            },
        )
    checkpoint["status"] = "PASS"
    checkpoint["reason_code"] = "S2_T11_T15_RERUN_VERIFY_PASS"
    checkpoint["current_task"] = None
    checkpoint["current_action"] = None
    append_event(
        chain_root,
        checkpoint,
        {
            "event": "CHAIN_COMPLETE",
            "task_id": None,
            "action": "complete",
            "status": "PASS",
            "reason_code": checkpoint["reason_code"],
        },
    )
    return checkpoint


def run_chain(
    *,
    approval_path: Path,
    operations_root: Path = OPERATIONS_ROOT,
    repository_root: Path = REPOSITORY_ROOT,
    driver: ProductionStageDriver | None = None,
) -> dict[str, Any]:
    """Create-or-resume the one approved chain from a single repeatable command."""

    approval = validate_approval_receipt(approval_path, repository_root=repository_root)
    chains = _chain_directories(operations_root)
    if not chains:
        create_chain(
            approval_path,
            operations_root=operations_root,
            repository_root=repository_root,
        )
    else:
        chain_root = _newest_chain_root(operations_root)
        checkpoint = _safe_json(chain_root / "checkpoint.json")
        if checkpoint.get("approval_hash") != approval.get("approval_hash"):
            raise ValueError("an existing rerun chain binds a different approval")
    return resume_chain(
        approval_path=approval_path,
        operations_root=operations_root,
        repository_root=repository_root,
        driver=driver,
    )


def parser_arguments(
    argv: Sequence[str] | None = None,
) -> tuple[str, Path | None, Path, Path, Path | None, str | None]:
    import argparse

    parser = argparse.ArgumentParser(description="Automatic S2-T11 through S2-T15 rerun")
    parser.add_argument(
        "mode",
        choices=("inspect", "audit-availability", "approve", "run", "start", "resume", "status"),
    )
    parser.add_argument("--approval-receipt", type=Path)
    parser.add_argument("--availability-audit", type=Path)
    parser.add_argument("--approved-by")
    parser.add_argument("--operations-root", type=Path, default=OPERATIONS_ROOT)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    args = parser.parse_args(argv)
    return (
        args.mode,
        args.approval_receipt,
        args.operations_root,
        args.repository_root,
        args.availability_audit,
        args.approved_by,
    )


def main(argv: Sequence[str] | None = None) -> int:
    mode, approval_path, operations_root, repository_root, availability_audit, approved_by = (
        parser_arguments(argv)
    )
    if mode == "inspect":
        print(render_status(approval_readiness(approval_path, repository_root=repository_root)))
        return 0
    if mode == "audit-availability":
        from .availability import run_availability_audit

        audit, path = run_availability_audit()
        print(render_status({**audit, "report_path": str(path)}))
        return 0
    if mode == "status":
        stage2_root = operations_root.parents[1]
        print(
            render_status(
                read_latest_chain_projection(stage2_root, repository_root=repository_root)
            )
        )
        return 0
    if mode == "approve":
        if availability_audit is None or approved_by is None:
            raise SystemExit("approve requires --availability-audit and --approved-by")
        approval, path = create_approval_receipt(
            availability_audit_path=availability_audit,
            approved_by=approved_by,
            output_root=operations_root,
            repository_root=repository_root,
        )
        print(render_status({**approval, "approval_path": str(path)}))
        return 0
    if mode == "run":
        if approval_path is None:
            raise SystemExit("run requires --approval-receipt")
        print(
            render_status(
                run_chain(
                    approval_path=approval_path,
                    operations_root=operations_root,
                    repository_root=repository_root,
                )
            )
        )
        return 0
    if mode == "start":
        if approval_path is None:
            raise SystemExit("start requires --approval-receipt")
        checkpoint, chain_root = create_chain(
            approval_path, operations_root=operations_root, repository_root=repository_root
        )
        print(render_status({**checkpoint, "chain_root": str(chain_root)}))
        return 0
    if approval_path is None:
        raise SystemExit("resume requires --approval-receipt")
    print(
        render_status(
            resume_chain(
                approval_path=approval_path,
                operations_root=operations_root,
                repository_root=repository_root,
            )
        )
    )
    return 0
