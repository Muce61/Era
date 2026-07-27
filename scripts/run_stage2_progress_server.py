#!/usr/bin/env python3
# ruff: noqa: E501
"""Serve the local, read-only Stage 2 Runtime V2 progress dashboard."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import re
import subprocess
import threading
import webbrowser
from collections.abc import Sequence
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from era100x.research.stage_2.runtime_v2.checkpoint import SAFE_RUN_ID
from era100x.research.stage_2.runtime_v2.progress import read_progress_status
from era100x.research.stage_2.paths.extraction import read_path_extraction_receipts
from era100x.foundation.governance import load_current_development_state
from era100x.research.stage_2.funding import (
    FundingEvidenceError,
    verify_funding_acceptance,
    verify_funding_evidence,
)
from era100x.research.stage_2.rerun.orchestrator import TASKS as V13_TASKS
from era100x.research.stage_2.rerun.lightweight_governance import (
    load_policy,
    validate_approval,
)
from era100x.research.stage_2.baselines.placebo.contracts import canonical_hash as placebo_hash
from era100x.research.stage_2.baselines.placebo.governance import (
    audit_t16_source as audit_placebo_t16_source,
    load_policy as load_placebo_policy,
)
from era100x.research.stage_2.statistics.bootstrap.formatting import (
    canonical_hash as bootstrap_hash,
)
from era100x.research.stage_2.statistics.bootstrap.governance import (
    audit_sources as audit_bootstrap_sources,
    load_policy as load_bootstrap_policy,
    validate_approval as validate_bootstrap_approval,
)


def _exclusive_lock_is_held(path: Path) -> bool:
    """Read-only process liveness check for a flock-backed task lock."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return False


DEFAULT_ROOT = Path("/Volumes/FuckingLife/era100x_stage2")
REPOSITORY_ROOT = Path(__file__).parents[1]
CANONICAL_REPOSITORY_ROOT = Path("/Users/muce/PycharmProjects/20260710/Era")
S2T12_RUN_PREFIX = "stage2-s2t12-metrics-"
S2T12_RUN_ID = re.compile(r"^stage2-s2t12-metrics-\d{8}T\d{6}Z-[0-9a-f]{12}$")
S2T12_SUMMARY_RELATIVE_PATH = Path("artifacts/manifests/stage_2/s2_t12_path_metrics_summary.json")
S2T12_VALIDATION_RELATIVE_PATH = Path("docs/development/validations/stage_2/S2-T12.md")
S2T13_RUN_PREFIX = "stage2-s2t13-first-passage-"
S2T13_RUN_ID = re.compile(r"^stage2-s2t13-first-passage-\d{8}T\d{6}Z-[0-9a-f]{12}$")
S2T13_SUMMARY_RELATIVE_PATH = Path("artifacts/manifests/stage_2/s2_t13_first_passage_summary.json")
S2T13_VALIDATION_RELATIVE_PATH = Path("docs/development/validations/stage_2/S2-T13.md")
S2T14_RUN_PREFIX = "stage2-s2t14-ambiguity-bounds-"
S2T14_RUN_ID = re.compile(r"^stage2-s2t14-ambiguity-bounds-\d{8}T\d{6}Z-[0-9a-f]{12}$")
S2T14_SUMMARY_RELATIVE_PATH = Path(
    "artifacts/manifests/stage_2/s2_t14_ambiguity_bounds_summary.json"
)
S2T14_VALIDATION_RELATIVE_PATH = Path("docs/development/validations/stage_2/S2-T14.md")
S2T15_RUN_PREFIX = "stage2-s2t15-conditional-"
S2T15_VALIDATION_RELATIVE_PATH = Path("docs/development/validations/stage_2/S2-T15.md")
REASON_CODE_SCHEMA_VERSION = 2
_SOURCE_REASON_UNSET = object()
REASON_MESSAGES = {
    "FORMAL_VERIFIED_PREFIX_ADOPTED_PASS": "旧链结果已完整核验，并被当前正式链只读接收。",
    "FORMAL_TASK_VERIFIED_PASS": "当前正式链已完成生产，完整核验通过。",
    "FORMAL_CHAIN_COMPLETE": "Plan v1.3 正式链已全部完成并通过核验。",
    "SEVEN_DAY_REHEARSAL_PASS_NOT_FORMAL": "七天短跑已通过，但它不是正式全历史结果。",
    "FUNDING_EVIDENCE_VERIFY_PASS_AWAITING_ACCEPTANCE": (
        "资金费证据已核验通过，正在等待正式只读接收。"
    ),
}

_PAGE_PATH = Path(__file__).with_name("stage2_progress_ui.html")
RUNTIME_TASK_RECEIPTS = {
    "foundation_btc": "staging/receipts/foundation/BTCUSDT.json",
    "foundation_eth": "staging/receipts/foundation/ETHUSDT.json",
    "group1_btc_price": "staging/receipts/group1/BTCUSDT/V1_PRICE.json",
    "group1_btc_flow": "staging/receipts/group1/BTCUSDT/V1_FLOW.json",
    "group1_eth_price": "staging/receipts/group1/ETHUSDT/V1_PRICE.json",
    "group1_eth_flow": "staging/receipts/group1/ETHUSDT/V1_FLOW.json",
}
RUNTIME_GROUP1_COMPONENTS = {
    "group1_btc_price": "staging/evidence/group1-components/group1-btcusdt-v1_price.json",
    "group1_btc_flow": "staging/evidence/group1-components/group1-btcusdt-v1_flow.json",
    "group1_eth_price": "staging/evidence/group1-components/group1-ethusdt-v1_price.json",
    "group1_eth_flow": "staging/evidence/group1-components/group1-ethusdt-v1_flow.json",
}


def _safe_file_count(root: Path, pattern: str = "*") -> int:
    if not root.is_dir() or root.is_symlink():
        return 0
    return sum(
        1
        for path in root.rglob(pattern)
        if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
    )


def _safe_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _self_hash_matches(value: dict[str, Any], field: str) -> bool:
    expected = value.get(field)
    if not isinstance(expected, str):
        return False
    payload = dict(value)
    payload.pop(field, None)
    return expected == _json_hash(payload)


def _t16_coverage_projection(artifact_root_value: object) -> dict[str, Any]:
    if not isinstance(artifact_root_value, str):
        return {"status": "NOT_AVAILABLE"}
    artifact_root = Path(artifact_root_value)
    if not artifact_root.is_absolute() or artifact_root.is_symlink() or not artifact_root.is_dir():
        return {"status": "EVIDENCE_INVALID"}
    reports = tuple(
        path
        for path in artifact_root.rglob("post-selection.json")
        if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
    )
    if len(reports) != 1:
        return {"status": "NOT_AVAILABLE" if not reports else "EVIDENCE_INVALID"}
    report = _safe_json_object(reports[0])
    if not report or not _self_hash_matches(report, "report_hash"):
        return {"status": "EVIDENCE_INVALID"}
    coverage_contract = report.get("coverage_contract_id")
    if coverage_contract != "H2_WINDOW_INTERNAL_GAP_BEFORE_DECISION_V1":
        return {
            "status": "RESEARCH_REJECTED",
            "reason_code": "CONTROL_EVENT_COVERAGE_CONTRACT_ASYMMETRY",
            "coverage_contract_id": coverage_contract,
            "mechanical_verify_unchanged": True,
        }
    return {
        "status": str(report.get("coverage_comparability_status", "REPORTED")),
        "coverage_contract_id": coverage_contract,
        "event_gap_affected_matrix_count": report.get("event_gap_affected_matrix_count"),
        "event_gap_affected_matrix_rate": report.get("event_gap_affected_matrix_rate"),
        "matched_event_gap_affected_matrix_rate": report.get(
            "matched_event_gap_affected_matrix_rate"
        ),
        "control_gap_affected_matrix_count": report.get("control_gap_affected_matrix_count"),
        "control_gap_affected_matrix_rate": report.get("control_gap_affected_matrix_rate"),
        "control_gap_affected_assignment_rate": report.get("control_gap_affected_assignment_rate"),
    }


def _reason_message(reason_code: str) -> str:
    """Return a plain-language projection without changing source evidence."""

    return REASON_MESSAGES.get(reason_code, f"当前状态：{reason_code}。")


def _project_reason(
    payload: dict[str, Any],
    *,
    reason_code: str,
    evidence_origin: str,
    source_plan_version: str,
    source_task_id: str | None,
    source_reason_code: object = _SOURCE_REASON_UNSET,
) -> dict[str, Any]:
    """Add the v2 read-only reason projection to one status payload."""

    projected = dict(payload)
    raw_reason = (
        projected.get("reason_code")
        if source_reason_code is _SOURCE_REASON_UNSET
        else source_reason_code
    )
    projected.update(
        {
            "reason_code": reason_code,
            "source_reason_code": (str(raw_reason) if raw_reason not in {None, ""} else None),
            "reason_message": _reason_message(reason_code),
            "reason_code_schema_version": REASON_CODE_SCHEMA_VERSION,
            "evidence_origin": evidence_origin,
            "source_plan_version": source_plan_version,
            "source_task_id": source_task_id,
        }
    )
    return projected


def _approval_order(approval: dict[str, Any]) -> tuple[str, str]:
    """Order approvals by their declared time, then by stable identity."""

    return (
        str(approval.get("approved_at") or ""),
        str(approval.get("approval_hash") or ""),
    )


def _read_projection_approval(
    approval_path: Path,
    *,
    policy: Any,
    repository_root: Path,
) -> dict[str, Any]:
    """Read an approval for display without authorizing a new execution."""

    try:
        return validate_approval(
            approval_path,
            policy=policy,
            repository_root=repository_root,
        )
    except (OSError, ValueError):
        approval = _safe_json_object(approval_path)
        if (
            approval.get("schema_name") != "stage2-formal-approval-v2"
            or approval.get("schema_version") != "2.0"
            or approval.get("status") != "APPROVED"
            or approval.get("stage_plan_version") != "1.3"
            or approval.get("stage3_locked") is not True
            or approval.get("policy_hash") != policy.policy_hash
            or approval.get("evidence_root") != str(policy.evidence_root)
            or tuple(approval.get("tasks") or ()) != tuple(V13_TASKS)
            or not _self_hash_matches(approval, "approval_hash")
        ):
            return {}
        return approval


def _safe_text(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _repository_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def _funding_evidence_projection(stage2_root: Path) -> dict[str, Any]:
    evidence_root = stage2_root / "funding-evidence"
    if not evidence_root.is_dir() or evidence_root.is_symlink():
        return {
            "status": "NOT_STARTED",
            "reason_code": "FUNDING_EVIDENCE_MISSING",
            "full_history_accepted": False,
        }
    candidates = sorted(
        (
            path
            for path in evidence_root.iterdir()
            if path.is_dir() and not path.is_symlink() and not path.name.startswith(".")
        ),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
    )
    if not candidates:
        return {
            "status": "NOT_STARTED",
            "reason_code": "FUNDING_EVIDENCE_MISSING",
            "full_history_accepted": False,
        }
    selected = candidates[-1]
    manifest = _safe_json_object(selected / "manifest.json")
    catalog = _safe_json_object(selected / "catalog.json")
    stored_verify = _safe_json_object(selected / "verify.json")
    try:
        verify = verify_funding_evidence(selected)
    except (OSError, ValueError, FundingEvidenceError) as exc:
        return {
            "status": "EVIDENCE_INVALID",
            "reason_code": "FUNDING_EVIDENCE_VERIFY_FAILED",
            "reason": str(exc),
            "evidence_id": selected.name,
            "full_history_accepted": False,
        }
    stored_verify_valid = (
        stored_verify.get("verify_hash")
        == _json_hash({key: value for key, value in stored_verify.items() if key != "verify_hash"})
        and stored_verify.get("status") == verify.get("status")
        and stored_verify.get("manifest_hash") == verify.get("manifest_hash")
        and stored_verify.get("catalog_hash") == verify.get("catalog_hash")
    )
    status = (
        "PASS" if verify.get("status") == "PASS" and stored_verify_valid else "EVIDENCE_INVALID"
    )
    instruments = catalog.get("instruments", {})
    difference_count = (
        sum(
            int(entry.get("difference_count", 0))
            for entry in instruments.values()
            if isinstance(entry, dict)
        )
        if isinstance(instruments, dict)
        else 0
    )
    scope = manifest.get("scope")
    acceptance_status = "NOT_PRESENT"
    historical_funding_bound = False
    if (selected / "acceptance.json").is_file() and not (selected / "acceptance.json").is_symlink():
        try:
            acceptance_verify = verify_funding_acceptance(selected)
        except (OSError, ValueError, FundingEvidenceError):
            acceptance_status = "FAIL"
        else:
            acceptance_status = str(acceptance_verify.get("status", "FAIL"))
            historical_funding_bound = acceptance_verify.get("historical_funding_bound") is True
    full_history_accepted = historical_funding_bound
    return {
        "status": status,
        "reason_code": (
            "FUNDING_LOCAL_HISTORY_HUMAN_ACCEPTED"
            if full_history_accepted
            else "FUNDING_SEVEN_DAY_REHEARSAL_PASS"
            if status == "PASS"
            else "FUNDING_EVIDENCE_INVALID"
        ),
        "evidence_id": manifest.get("evidence_id", selected.name),
        "scope": scope,
        "start_date": manifest.get("start_date"),
        "end_date_exclusive": manifest.get("end_date_exclusive"),
        "comparison_status": manifest.get("comparison_status"),
        "total_row_count": catalog.get("total_row_count", 0),
        "difference_count": difference_count,
        "verify_status": verify.get("status"),
        "acceptance_status": acceptance_status,
        "historical_funding_bound": historical_funding_bound,
        "manifest_hash": manifest.get("manifest_hash"),
        "catalog_hash": catalog.get("catalog_hash"),
        "full_history_accepted": full_history_accepted,
        "legacy_sources_modified": manifest.get("legacy_sources_modified"),
        "lifecycle_run_created": manifest.get("lifecycle_run_created"),
        "stage3_locked": True,
    }


def _stage2_v13_projection(stage2_root: Path) -> dict[str, Any]:
    """Project Plan v1.3 governance and append-only successor evidence."""

    try:
        state = load_current_development_state()
    except (OSError, ValueError) as exc:
        return {
            "stage_plan_version": "1.3",
            "status": "BLOCKED",
            "reason_code": "S2_V13_GOVERNANCE_STATE_INVALID",
            "reason": str(exc),
            "stage3_locked": True,
        }
    repo_root = REPOSITORY_ROOT.resolve()
    canonical_root = CANONICAL_REPOSITORY_ROOT.resolve()
    stale_server = repo_root != canonical_root
    repo_commit = _repository_commit()
    operations_root = stage2_root / "operations/stage2-plan-v1.3-successor"
    checkpoint = _safe_json_object(operations_root / "checkpoint.json")
    rehearsal_progress = _safe_json_object(
        operations_root / f"seven-day-rehearsal-progress.{repo_commit}.json"
    )
    rehearsal_progress_valid = (
        rehearsal_progress.get("schema_name") == "stage2-plan-v13-rehearsal-progress-v1"
        and rehearsal_progress.get("code_commit") == repo_commit
        and rehearsal_progress.get("stage3_locked") is True
        and _self_hash_matches(rehearsal_progress, "checkpoint_hash")
        and rehearsal_progress.get("status")
        in {"IN_PROGRESS", "VERIFYING", "PENDING_UI_CHECK", "FAILED"}
    )
    if rehearsal_progress_valid and rehearsal_progress.get("status") in {
        "IN_PROGRESS",
        "VERIFYING",
    }:
        try:
            heartbeat = datetime.fromisoformat(str(rehearsal_progress["heartbeat_at"]))
            heartbeat_age = (datetime.now(UTC) - heartbeat).total_seconds()
        except (KeyError, TypeError, ValueError):
            heartbeat_age = float("inf")
        if heartbeat_age > 300:
            rehearsal_progress = {**rehearsal_progress, "status": "STALLED"}
    rehearsal_receipt = _safe_json_object(
        operations_root / f"seven-day-rehearsal-receipt.{repo_commit}.json"
    )
    if not rehearsal_receipt:
        rehearsal_receipt = _safe_json_object(operations_root / "seven-day-rehearsal-receipt.json")
    pending_rehearsal = _safe_json_object(
        operations_root / f"seven-day-rehearsal-receipt.{repo_commit}.pending.json"
    )
    if not pending_rehearsal:
        pending_rehearsal = _safe_json_object(
            operations_root / "seven-day-rehearsal-receipt.pending.json"
        )
    trade_supplement_rehearsal = _safe_json_object(
        operations_root / f"trade-supplement-rehearsal-receipt.{repo_commit}.json"
    )
    trade_supplement_rehearsal_pass = (
        trade_supplement_rehearsal.get("schema_name") == "stage2-trade-supplement-rehearsal-v1"
        and trade_supplement_rehearsal.get("status") == "PASS"
        and _self_hash_matches(trade_supplement_rehearsal, "receipt_hash")
        and trade_supplement_rehearsal.get("code_commit") == repo_commit
        and trade_supplement_rehearsal.get("purpose") == "TRADE_SUPPLEMENT_COVERAGE"
        and trade_supplement_rehearsal.get("producer_serialization") == "PASS"
        and trade_supplement_rehearsal.get("strict_consumer_readback") == "PASS"
        and trade_supplement_rehearsal.get("reconciliation") == "PASS"
        and trade_supplement_rehearsal.get("verify") == "PASS"
    )
    rehearsal_pass = (
        rehearsal_receipt.get("schema_name") == "stage2-plan-v13-seven-day-rehearsal-v1"
        and rehearsal_receipt.get("status") == "PASS"
        and _self_hash_matches(rehearsal_receipt, "receipt_hash")
        and rehearsal_receipt.get("day_count") == 7
        and tuple(rehearsal_receipt.get("tasks", ())) == V13_TASKS
        and rehearsal_receipt.get("code_commit") == repo_commit
        and rehearsal_receipt.get("producer_serialization") == "PASS"
        and rehearsal_receipt.get("strict_consumer_readback") == "PASS"
        and rehearsal_receipt.get("reconciliation") == "PASS"
        and rehearsal_receipt.get("verify") == "PASS"
        and rehearsal_receipt.get("ui_projection") == "PASS"
    )
    rehearsal_pending = (
        pending_rehearsal.get("schema_name") == "stage2-plan-v13-seven-day-rehearsal-v1"
        and pending_rehearsal.get("status") == "PENDING_UI_CHECK"
        and _self_hash_matches(pending_rehearsal, "receipt_hash")
        and pending_rehearsal.get("day_count") == 7
        and tuple(pending_rehearsal.get("tasks", ())) == V13_TASKS
        and pending_rehearsal.get("code_commit") == repo_commit
        and pending_rehearsal.get("producer_serialization") == "PASS"
        and pending_rehearsal.get("strict_consumer_readback") == "PASS"
        and pending_rehearsal.get("reconciliation") == "PASS"
        and pending_rehearsal.get("verify") == "PASS"
        and pending_rehearsal.get("ui_projection") == "PENDING"
    )
    active_rehearsal_receipt = (
        rehearsal_receipt if rehearsal_pass else pending_rehearsal if rehearsal_pending else {}
    )
    rehearsal_report_path = Path(str(active_rehearsal_receipt.get("report_path", "")))
    rehearsal_report = (
        _safe_json_object(rehearsal_report_path)
        if rehearsal_report_path.is_absolute()
        and rehearsal_report_path.resolve().is_relative_to((stage2_root / "rehearsals").resolve())
        else {}
    )
    rehearsal_report_valid = (
        bool(rehearsal_report)
        and _self_hash_matches(rehearsal_report, "report_hash")
        and rehearsal_report.get("report_hash") == active_rehearsal_receipt.get("report_hash")
        and rehearsal_report.get("code_commit") == repo_commit
        and rehearsal_report.get("status") == "PASS"
    )
    rehearsal_lifecycle = (
        cast(list[dict[str, Any]], rehearsal_report.get("lifecycle", []))
        if rehearsal_report_valid
        else []
    )
    rehearsal_policy_results = [
        cast(dict[str, Any], result.get("continue_holding", {}))
        for item in rehearsal_lifecycle
        for result in cast(list[dict[str, Any]], item.get("funding_tracks", []))
    ]
    rehearsal_right_censored = sum(
        result.get("terminal_state") == "RIGHT_CENSORED" for result in rehearsal_policy_results
    )
    rehearsal_scenario_liquidations = sum(
        result.get("exit_reason") == "SCENARIO_LIQUIDATION_BOUNDARY_CROSSED"
        for result in rehearsal_policy_results
    )
    rehearsal_t16 = (
        cast(list[dict[str, Any]], rehearsal_report.get("conditional_baseline_probe", []))
        if rehearsal_report_valid
        else []
    )
    rehearsal_handoffs = {
        str(item.get("task_id")): item
        for item in cast(list[dict[str, Any]], rehearsal_report.get("handoffs", []))
        if isinstance(item, dict)
    }
    pending_execution_gates = [] if rehearsal_pass else ["FINAL_CODE_7_DAY_REHEARSAL"]
    checkpoint_valid = (
        checkpoint.get("schema_name") == "stage2-plan-v13-successor-checkpoint-v1"
        and checkpoint.get("stage_plan_version") == "1.3"
    )
    default_status = (
        "IN_PROGRESS" if state.task_status == "IMPLEMENTATION_IN_PROGRESS" else "BLOCKED"
    )
    tasks: dict[str, Any] = {
        task: {
            "status": (
                default_status
                if task == state.current_task
                else "BLOCKED"
                if state.blocking_questions or pending_execution_gates
                else "NOT_STARTED"
            ),
            "reason_code": (
                "IMPLEMENTATION_IN_PROGRESS"
                if task == state.current_task
                else (
                    "WAITING_FOR_GOVERNANCE"
                    if state.blocking_questions
                    else "WAITING_FOR_EXECUTION_GATE"
                )
            ),
        }
        for task in V13_TASKS
    }
    if checkpoint_valid:
        for task, task_state in cast(dict[str, Any], checkpoint.get("tasks", {})).items():
            if task in tasks and isinstance(task_state, dict):
                tasks[task] = task_state
    elif rehearsal_pass:
        tasks = {
            task: {
                "status": "PASS",
                "reason_code": "SEVEN_DAY_REHEARSAL_PASS_NOT_FORMAL",
                "row_count": rehearsal_handoffs.get(task, {}).get("row_count"),
                "output_hash": rehearsal_handoffs.get(task, {}).get("output_hash"),
                "verify_status": rehearsal_handoffs.get(task, {}).get("verify_status"),
            }
            for task in V13_TASKS
        }
    elif rehearsal_pending:
        tasks = {
            task: {
                "status": "PASS",
                "reason_code": "SEVEN_DAY_REHEARSAL_PASS_PENDING_UI_CHECK",
                "row_count": rehearsal_handoffs.get(task, {}).get("row_count"),
                "output_hash": rehearsal_handoffs.get(task, {}).get("output_hash"),
                "verify_status": rehearsal_handoffs.get(task, {}).get("verify_status"),
            }
            for task in V13_TASKS
        }
    elif rehearsal_progress_valid:
        live_tasks = cast(dict[str, Any], rehearsal_progress.get("tasks", {}))
        tasks = {
            task: (
                cast(dict[str, Any], live_tasks[task])
                if isinstance(live_tasks.get(task), dict)
                else {
                    "status": "NOT_STARTED",
                    "reason_code": "WAITING_FOR_REHEARSAL",
                    "progress_percent": 0,
                }
            )
            for task in V13_TASKS
        }
    status = (
        str(checkpoint.get("status", default_status))
        if checkpoint_valid
        else "REHEARSAL_PASS_AWAITING_FORMAL_APPROVAL"
        if rehearsal_pass
        else "REHEARSAL_UI_CHECK"
        if rehearsal_pending
        else str(rehearsal_progress.get("status"))
        if rehearsal_progress_valid
        else default_status
    )
    if stale_server:
        status = "STALE_SERVER"
    funding_evidence = _funding_evidence_projection(stage2_root)
    funding_blockers = (
        [] if funding_evidence.get("full_history_accepted") is True else ["HISTORICAL_FUNDING"]
    )
    lightweight_policy_path = repo_root / "configs/governance/stage2_active_policy_v2.json"
    lightweight_policy_hash = None
    lightweight_approval = {}
    lightweight_authority_count = 0
    lightweight_chain_checkpoint = {}
    lightweight_historical_chain_checkpoint = {}
    lightweight_historical_chain_root: Path | None = None
    lightweight_trade_supplement_hash = None
    selected_approval_hash = None
    approval_selection_basis = None
    t16_coverage = {"status": "NOT_AVAILABLE"}
    formal_progress_percent = 0.0
    formal_heartbeat_at = None
    try:
        lightweight_policy = load_policy(lightweight_policy_path, repository_root=repo_root)
        lightweight_policy_hash = lightweight_policy.policy_hash
        lightweight_trade_supplement_hash = lightweight_policy.trade_supplement_acceptance_hash
        valid_approvals: list[dict[str, Any]] = []
        for approval_path in sorted(
            lightweight_policy.operations_root.glob("approvals/approval-*.json")
        ):
            candidate_approval = _read_projection_approval(
                approval_path,
                policy=lightweight_policy,
                repository_root=repo_root,
            )
            if candidate_approval:
                valid_approvals.append(candidate_approval)
        if valid_approvals:
            lightweight_approval = max(valid_approvals, key=_approval_order)
            selected_approval_hash = lightweight_approval.get("approval_hash")
            approval_selection_basis = "MAX_APPROVED_AT_THEN_APPROVAL_HASH"
        lightweight_authority_count = sum(
            _safe_json_object(path).get("policy_hash") == lightweight_policy.policy_hash
            and _safe_json_object(path).get("code_commit") == repo_commit
            for path in lightweight_policy.operations_root.glob(
                "authorities/chain-authority-*.json"
            )
        )
        checkpoints = sorted(
            lightweight_policy.evidence_root.glob("chains/*/operations/checkpoint.json")
        )
        if checkpoints:
            latest_checkpoint = max(checkpoints, key=lambda path: path.stat().st_mtime_ns)
            lightweight_historical_chain_checkpoint = _safe_json_object(latest_checkpoint)
            lightweight_historical_chain_root = latest_checkpoint.parents[1]
        if valid_approvals:
            current_chain_root = (
                lightweight_policy.evidence_root
                / "chains"
                / str(lightweight_approval["approval_hash"])
            )
            current_checkpoint = current_chain_root / "operations/checkpoint.json"
            lightweight_chain_checkpoint = _safe_json_object(current_checkpoint)
            chain_tasks = cast(dict[str, Any], lightweight_chain_checkpoint.get("tasks") or {})
            adopted_tasks: set[str] = set()
            adoption_path_value = lightweight_chain_checkpoint.get("verified_prefix_adoption_path")
            if adoption_path_value:
                adoption_path = Path(str(adoption_path_value))
                if (
                    adoption_path.is_absolute()
                    and adoption_path.is_file()
                    and not adoption_path.is_symlink()
                    and adoption_path.resolve().is_relative_to(
                        lightweight_policy.operations_root.resolve()
                    )
                ):
                    adoption = _safe_json_object(adoption_path)
                    adoption_task_payload = adoption.get("tasks")
                    if (
                        adoption.get("status") == "PASS"
                        and adoption.get("mode") == "READ_ONLY"
                        and adoption.get("approval_hash")
                        == lightweight_approval.get("approval_hash")
                        and _self_hash_matches(adoption, "adoption_hash")
                        and isinstance(adoption_task_payload, dict)
                    ):
                        adopted_tasks = {
                            str(task) for task in adoption_task_payload if task in V13_TASKS
                        }
            formal_fractions: list[float] = []
            for task in V13_TASKS:
                chain_task = cast(dict[str, Any], chain_tasks.get(task) or {})
                task_checkpoint = _safe_json_object(
                    current_chain_root / "tasks" / task / "checkpoint.json"
                )
                checkpoint_valid_for_task = (
                    task_checkpoint.get("schema_name") == "stage2-plan-v13-producer-checkpoint-v2"
                    and task_checkpoint.get("task_id") == task
                    and task_checkpoint.get("code_commit")
                    == lightweight_approval.get("code_commit")
                    and _self_hash_matches(task_checkpoint, "checkpoint_hash")
                )
                projected = dict(tasks.get(task) or {})
                source_reason_code = projected.get("reason_code")
                if checkpoint_valid_for_task:
                    projected.update(task_checkpoint)
                    source_reason_code = task_checkpoint.get("reason_code")
                    formal_heartbeat_value = task_checkpoint.get("heartbeat_at")
                    if isinstance(formal_heartbeat_value, str):
                        formal_heartbeat_at = formal_heartbeat_value
                if chain_task:
                    chain_status = str(chain_task.get("status", "NOT_STARTED"))
                    if not checkpoint_valid_for_task and chain_status in {
                        "PASS",
                        "TERMINAL_FAILED",
                        "RETRYABLE_INTERRUPTED",
                    }:
                        projected["status"] = chain_status
                    handoff = chain_task.get("handoff")
                    if isinstance(handoff, dict):
                        adoption_receipt_hash = chain_task.get("adoption_receipt_hash")
                        if (
                            isinstance(adoption_receipt_hash, str)
                            and adoption_receipt_hash == handoff.get("producer_receipt_hash")
                            and handoff.get("verify_status") == "PASS"
                        ):
                            adopted_tasks.add(task)
                        projected.update(
                            {
                                "row_count": handoff.get("row_count"),
                                "output_hash": handoff.get("output_hash"),
                                "verify_status": handoff.get("verify_status"),
                            }
                        )
                        if task == "S2P13-T16":
                            t16_coverage = _t16_coverage_projection(handoff.get("artifact_root"))
                    effective_status = str(projected.get("status", "NOT_STARTED"))
                    if effective_status == "PASS":
                        if checkpoint_valid_for_task:
                            projected = _project_reason(
                                projected,
                                reason_code="FORMAL_TASK_VERIFIED_PASS",
                                evidence_origin="PRODUCED",
                                source_plan_version="1.3",
                                source_task_id=task,
                                source_reason_code=source_reason_code,
                            )
                        elif task in adopted_tasks:
                            projected = _project_reason(
                                projected,
                                reason_code="FORMAL_VERIFIED_PREFIX_ADOPTED_PASS",
                                evidence_origin="ADOPTED_VERIFIED_PREFIX",
                                source_plan_version="1.3",
                                source_task_id=task,
                                source_reason_code=chain_task.get("reason_code"),
                            )
                        else:
                            projected = _project_reason(
                                projected,
                                reason_code="FORMAL_TASK_VERIFIED_PASS",
                                evidence_origin="PRODUCED",
                                source_plan_version="1.3",
                                source_task_id=task,
                                source_reason_code=chain_task.get("reason_code"),
                            )
                tasks[task] = projected
                if projected.get("status") == "PASS":
                    formal_fractions.append(1.0)
                else:
                    formal_fractions.append(
                        max(
                            0.0,
                            min(
                                1.0,
                                float(projected.get("progress_percent", 0) or 0) / 100,
                            ),
                        )
                    )
            formal_progress_percent = round(sum(formal_fractions) * 100 / len(V13_TASKS), 2)
        if (
            t16_coverage.get("status") == "NOT_AVAILABLE"
            and lightweight_historical_chain_root is not None
        ):
            historical_tasks = cast(
                dict[str, Any],
                lightweight_historical_chain_checkpoint.get("tasks") or {},
            )
            historical_t16 = cast(dict[str, Any], historical_tasks.get("S2P13-T16") or {})
            historical_handoff = historical_t16.get("handoff")
            if isinstance(historical_handoff, dict):
                t16_coverage = _t16_coverage_projection(historical_handoff.get("artifact_root"))
    except (OSError, ValueError):
        pass
    rehearsal_gate_mode = str(
        lightweight_approval.get("rehearsal_gate_mode", "DEFAULT_REHEARSAL_REQUIRED")
    )
    rehearsal_gate_waived = (
        rehearsal_gate_mode == "EXPLICIT_BACKGROUND_RUNTIME_WAIVER"
        and isinstance(lightweight_approval.get("background_runtime_waiver"), dict)
    )
    execution_gate_status = (
        "PASS" if rehearsal_pass else "WAIVED" if rehearsal_gate_waived else "PENDING"
    )
    pending_execution_gates = (
        [] if execution_gate_status in {"PASS", "WAIVED"} else ["FINAL_CODE_7_DAY_REHEARSAL"]
    )
    projected_current_task = (
        rehearsal_progress.get("current_task") if rehearsal_progress_valid else state.current_task
    )
    projected_task_status = state.task_status
    projected_formal_result_exists = state.formal_successor_result_exists
    projected_reason_code = str(checkpoint.get("reason_code", "S2_V13_IMPLEMENTATION_GATED"))
    formal_chain_status = str(lightweight_chain_checkpoint.get("status", "NOT_STARTED"))
    formal_chain_current_task = lightweight_chain_checkpoint.get("current_task")
    if not stale_server and formal_chain_status == "COMPLETE":
        status = "PASS"
        projected_current_task = "S2P13-T16"
        projected_task_status = "PASS"
        projected_formal_result_exists = True
        projected_reason_code = "FORMAL_CHAIN_COMPLETE"
    elif not stale_server and formal_chain_status == "IN_PROGRESS":
        status = "IN_PROGRESS"
        projected_current_task = formal_chain_current_task or projected_current_task
        projected_task_status = "IN_PROGRESS"
        projected_reason_code = "FORMAL_CHAIN_IN_PROGRESS"
    elif not stale_server and formal_chain_status == "TERMINAL_FAILED":
        status = "FAILED"
        projected_current_task = formal_chain_current_task or projected_current_task
        projected_task_status = "TERMINAL_FAILED"
        projected_reason_code = str(
            lightweight_chain_checkpoint.get("reason") or "FORMAL_CHAIN_TERMINAL_FAILED"
        )
    elif (
        not stale_server
        and t16_coverage.get("status") == "RESEARCH_REJECTED"
        and lightweight_historical_chain_checkpoint.get("status") == "COMPLETE"
    ):
        status = "RESEARCH_REJECTED"
        projected_current_task = "S2P13-T16"
        projected_task_status = "COVERAGE_REPAIR_SUCCESSOR_GATED"
        projected_formal_result_exists = True
        projected_reason_code = str(
            t16_coverage.get("reason_code") or "CONTROL_EVENT_COVERAGE_CONTRACT_ASYMMETRY"
        )
    for task, task_payload in tasks.items():
        if not isinstance(task_payload, dict):
            continue
        if task_payload.get("reason_code_schema_version") == REASON_CODE_SCHEMA_VERSION:
            continue
        raw_reason = str(task_payload.get("reason_code") or "UNKNOWN")
        if raw_reason in {
            "SEVEN_DAY_REHEARSAL_PASS_NOT_FORMAL",
            "SEVEN_DAY_REHEARSAL_PASS_PENDING_UI_CHECK",
            "WAITING_FOR_REHEARSAL",
        }:
            origin = "REHEARSAL"
            source_plan_version = "1.3"
        elif checkpoint_valid:
            origin = "PRODUCED"
            source_plan_version = "1.3"
        else:
            origin = "LEGACY_V12"
            source_plan_version = "1.2"
        tasks[task] = _project_reason(
            task_payload,
            reason_code=raw_reason,
            evidence_origin=origin,
            source_plan_version=source_plan_version,
            source_task_id=task,
        )
    source_plan_reason_code = "S2_V13_STALE_SERVER" if stale_server else projected_reason_code
    plan_reason = _project_reason(
        {},
        reason_code=source_plan_reason_code,
        evidence_origin=(
            "PRODUCED"
            if formal_chain_status not in {"NOT_STARTED", "NOT_PRESENT"}
            else "REHEARSAL"
            if rehearsal_pass or rehearsal_pending or rehearsal_progress_valid
            else "LEGACY_V12"
        ),
        source_plan_version="1.3",
        source_task_id=projected_current_task,
        source_reason_code=projected_reason_code,
    )
    return {
        "stage_plan_version": "1.3",
        "status": status,
        **plan_reason,
        "repo_root": str(repo_root),
        "repo_commit": repo_commit,
        "server_stale": stale_server,
        "current_task": projected_current_task,
        "task_status": projected_task_status,
        "blocking_questions": list(state.blocking_questions),
        "execution_gates": {"FINAL_CODE_7_DAY_REHEARSAL": execution_gate_status},
        "rehearsal_status": (
            "PASS"
            if rehearsal_pass
            else "PENDING_UI_CHECK"
            if rehearsal_pending
            else str(rehearsal_progress.get("status"))
            if rehearsal_progress_valid
            else "NOT_STARTED"
        ),
        "rehearsal_progress_percent": (
            rehearsal_progress.get("overall_progress_percent")
            if rehearsal_progress_valid
            else 100
            if rehearsal_pass or rehearsal_pending
            else 0
        ),
        "rehearsal_heartbeat_at": (
            rehearsal_progress.get("heartbeat_at") if rehearsal_progress_valid else None
        ),
        "rehearsal_progress_failure_reason": (
            rehearsal_progress.get("failure_reason") if rehearsal_progress_valid else None
        ),
        "rehearsal_report_path": active_rehearsal_receipt.get("report_path"),
        "rehearsal_report_hash": (
            rehearsal_receipt.get("report_hash")
            if rehearsal_pass
            else pending_rehearsal.get("report_hash")
            if rehearsal_pending
            else None
        ),
        "pending_execution_gates": pending_execution_gates,
        "srp_execution_status": state.srp_execution_status,
        "formal_successor_result_exists": projected_formal_result_exists,
        "stage3_locked": state.stage3_locked,
        "approved_execution_limit": state.approved_execution_limit,
        "checkpoint_present": checkpoint_valid,
        "tasks": tasks,
        "rehearsal_report_valid": rehearsal_report_valid,
        "rehearsal_t16_match_levels": {
            str(item.get("instrument")): item.get("match_level") for item in rehearsal_t16
        },
        "right_censored_count": int(
            checkpoint.get("right_censored_count", rehearsal_right_censored)
        ),
        "scenario_liquidation_count": int(
            checkpoint.get("scenario_liquidation_count", rehearsal_scenario_liquidations)
        ),
        "ticket_double_probability_delta": checkpoint.get("ticket_double_probability_delta"),
        "ticket_equity_per_day_delta": checkpoint.get("ticket_equity_per_day_delta"),
        "price_proxy_source": "CONTRACT_PRICE_1S",
        "historical_mark_price_claim": False,
        "lifecycle_target_contract": "DYNAMIC_NET_TICKET_DOUBLE_APPROX_136BP",
        "auxiliary_first_passage_target_bps": 20,
        "funding_tracks": [
            "PRIMARY_HISTORICAL_ACTUAL",
            "STRESS_ADVERSE_1_5X",
            "STRESS_ADVERSE_2X",
            "STRESS_NO_FUNDING_CREDIT",
        ],
        "funding_evidence": funding_evidence,
        "liquidation_contract": "CONTRACT_PRICE_NET_MARGIN_DEPLETION_MINUS_8U",
        "remaining_input_blockers": funding_blockers,
        "governance_model": "STAGE2_ACTIVE_POLICY_V2",
        "policy_hash": lightweight_policy_hash,
        "external_approval_status": (lightweight_approval.get("status", "NOT_PRESENT")),
        "selected_approval_hash": selected_approval_hash,
        "approval_selection_basis": approval_selection_basis,
        "formal_rehearsal_gate_mode": rehearsal_gate_mode,
        "background_runtime_waiver_reason": cast(
            dict[str, Any],
            lightweight_approval.get("background_runtime_waiver") or {},
        ).get("reason"),
        "chain_authority_count": lightweight_authority_count,
        "formal_chain_status": lightweight_chain_checkpoint.get("status", "NOT_STARTED"),
        "formal_chain_current_task": lightweight_chain_checkpoint.get("current_task"),
        "formal_chain_reason": lightweight_chain_checkpoint.get("reason"),
        "formal_progress_percent": formal_progress_percent,
        "formal_heartbeat_at": formal_heartbeat_at,
        "historical_formal_chain_status": lightweight_historical_chain_checkpoint.get(
            "status", "NOT_PRESENT"
        ),
        "historical_formal_chain_reason": lightweight_historical_chain_checkpoint.get("reason"),
        "trade_supplement_status": ("PASS" if lightweight_trade_supplement_hash else "NOT_PRESENT"),
        "trade_supplement_acceptance_hash": lightweight_trade_supplement_hash,
        "trade_supplement_rehearsal_status": (
            "PASS" if trade_supplement_rehearsal_pass else "NOT_STARTED"
        ),
        "t16_coverage": t16_coverage,
        "updated_at": (
            rehearsal_progress.get("heartbeat_at")
            if rehearsal_progress_valid
            else checkpoint.get("updated_at")
        ),
    }


def _stage2_v14_projection(stage2_root: Path) -> dict[str, Any]:
    """Project Plan v1.4/T17 from policy and append-only evidence only."""

    del stage2_root
    phases = (
        "AUDIT",
        "BLIND_SELECTION",
        "GROUP_MATCHING",
        "OUTCOME_ATTACH",
        "SUMMARY",
        "PUBLISH",
        "VERIFY",
    )
    base: dict[str, Any] = {
        "schema_name": "s2p14-t17-ui-projection",
        "stage_plan_version": "1.4",
        "task_id": "S2P14-T17",
        "status": "BLOCKED",
        "reason_code": "POLICY_OR_SOURCE_NOT_VERIFIED",
        "repo_root": str(REPOSITORY_ROOT.resolve()),
        "repo_commit": _repository_commit(),
        "source_t16_status": "CHECKING",
        "approval_count": 0,
        "authority_count": 0,
        "run_count": 0,
        "phase": "AUDIT",
        "subphase": None,
        "progress_percent": 0.0,
        "processed_units": 0,
        "total_units": 456,
        "rows_per_second": None,
        "eta_seconds": None,
        "heartbeat_at": None,
        "phases": [],
        "evidence_label": "H2 historical placebo evidence",
        "research_status": "DESCRIPTIVE_ONLY_CLUSTERING_BOOTSTRAP_PENDING",
        "stage3_locked": True,
    }
    try:
        policy = load_placebo_policy(
            REPOSITORY_ROOT / "configs/governance/stage2_active_policy_v3.json",
            repository_root=REPOSITORY_ROOT,
        )
        binding = audit_placebo_t16_source(policy, full_hash_scan=False)
    except (OSError, ValueError) as exc:
        base["reason"] = str(exc)
        base["phases"] = [
            {"name": name, "status": "BLOCKED", "progress_percent": 0.0} for name in phases
        ]
        return base
    approvals = tuple(
        path
        for path in (policy.operations_root / "approvals").glob("approval-*.json")
        if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
    )
    authorities = tuple(
        path
        for path in (policy.evidence_root / "authorities").glob("authority-*.json")
        if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
    )
    runs = tuple(
        sorted(
            path
            for path in (policy.evidence_root / "runs").glob("stage2-s2p14-t17-*")
            if path.is_dir() and not path.is_symlink()
        )
    )
    checkpoint: dict[str, Any] = {}
    verify: dict[str, Any] = {}
    run_contract: dict[str, Any] = {}
    run_id = None
    if runs:
        run_id = runs[-1].name
        run_contract = _safe_json_object(runs[-1] / "run-contract.json")
        checkpoint = _safe_json_object(runs[-1] / "checkpoint.json")
        verify_files = tuple(
            path
            for path in (runs[-1] / "verify").glob("*.json")
            if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
        )
        if len(verify_files) == 1:
            candidate = _safe_json_object(verify_files[0])
            claimed = candidate.get("verify_hash")
            if (
                isinstance(claimed, str)
                and placebo_hash(
                    {key: value for key, value in candidate.items() if key != "verify_hash"}
                )
                == claimed
                and candidate.get("status") == "PASS"
            ):
                verify = candidate
    current_phase = str(checkpoint.get("phase") or ("VERIFY" if verify else "AUDIT"))
    progress_value = float(checkpoint.get("percent") or 0.0)
    now_epoch = datetime.now(UTC).timestamp()
    active_root = runs[-1] if runs else None

    def first_mtime(paths: Sequence[Path]) -> float | None:
        values = [
            path.stat().st_mtime
            for path in paths
            if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
        ]
        return min(values) if values else None

    run_started_epoch = (
        (active_root / "run-contract.json").stat().st_mtime
        if active_root is not None
        and (active_root / "run-contract.json").is_file()
        and not (active_root / "run-contract.json").is_symlink()
        else None
    )
    blind_files = (
        tuple((active_root / "work/blind-selections").rglob("*.parquet"))
        if active_root is not None
        else ()
    )
    match_files = (
        tuple((active_root / "work/results/matches").rglob("*.parquet"))
        if active_root is not None
        else ()
    )
    blind_started_epoch = first_mtime(blind_files)
    outcome_started_epoch = first_mtime(match_files)
    summary_started_epoch = (
        first_mtime(
            (
                active_root / "work/results/descriptive_summaries.parquet",
                active_root / "work/results/matches/descriptive_summaries.parquet",
            )
        )
        if active_root is not None
        else None
    )
    publish_started_epoch = (
        first_mtime(tuple((active_root / "published").rglob("*")))
        if active_root is not None and (active_root / "published").is_dir()
        else None
    )
    verify_started_epoch = (
        first_mtime(tuple((active_root / "verify").glob("*.json")))
        if active_root is not None and (active_root / "verify").is_dir()
        else None
    )
    phase_start_epochs: dict[str, float | None] = {
        "AUDIT": run_started_epoch,
        "BLIND_SELECTION": blind_started_epoch,
        "GROUP_MATCHING": blind_started_epoch,
        "OUTCOME_ATTACH": outcome_started_epoch,
        "SUMMARY": summary_started_epoch,
        "PUBLISH": publish_started_epoch,
        "VERIFY": verify_started_epoch,
    }
    phase_end_epochs: dict[str, float | None] = {
        "AUDIT": blind_started_epoch,
        "BLIND_SELECTION": outcome_started_epoch,
        "GROUP_MATCHING": outcome_started_epoch,
        "OUTCOME_ATTACH": summary_started_epoch or publish_started_epoch or verify_started_epoch,
        "SUMMARY": publish_started_epoch,
        "PUBLISH": verify_started_epoch,
        "VERIFY": now_epoch if verify_started_epoch is not None else None,
    }
    later_phases = {
        "AUDIT": {"BLIND_SELECTION", "OUTCOME_ATTACH", "VERIFY"},
        "BLIND_SELECTION": {"OUTCOME_ATTACH", "VERIFY"},
        "GROUP_MATCHING": {"OUTCOME_ATTACH", "VERIFY"},
        "OUTCOME_ATTACH": {"VERIFY"},
        "SUMMARY": {"VERIFY"},
        "PUBLISH": {"VERIFY"},
        "VERIFY": set(),
    }
    phase_rows: list[dict[str, Any]] = []
    for name in phases:
        phase_is_current = name == current_phase or (
            current_phase == "BLIND_SELECTION" and name == "GROUP_MATCHING"
        )
        phase_has_started = phase_start_epochs[name] is not None
        phase_is_complete = bool(verify) or current_phase in later_phases[name]
        if name == "AUDIT" and checkpoint:
            phase_is_complete = True
        if phase_is_complete:
            state, percent = "PASS", 100.0
        elif phase_is_current and checkpoint:
            state, percent = "IN_PROGRESS", progress_value
        elif phase_has_started:
            state, percent = "IN_PROGRESS", progress_value
        else:
            state, percent = "NOT_STARTED", 0.0
        if name == "AUDIT":
            processed, total = (1 if checkpoint else 0), 1
        elif name in {"BLIND_SELECTION", "GROUP_MATCHING"}:
            processed = (
                int(checkpoint.get("processed_units", 0))
                if current_phase == "BLIND_SELECTION"
                else (456 if phase_is_complete else 0)
            )
            total = 456
        elif name == "OUTCOME_ATTACH":
            processed = (
                int(checkpoint.get("processed_units", 0))
                if current_phase == name
                else (456 if phase_is_complete else 0)
            )
            total = int(checkpoint.get("total_units", 456)) if current_phase == name else 456
        elif name == "SUMMARY":
            processed = int(verify.get("summary_row_count") or 0)
            total = int(binding.counts.get("summaries", 0))
        else:
            processed, total = (1 if phase_is_complete else 0), 1
        started_epoch = phase_start_epochs[name]
        ended_epoch = phase_end_epochs[name]
        elapsed_seconds = (
            max(0, int((ended_epoch or now_epoch) - started_epoch))
            if started_epoch is not None
            else 0
        )
        units_per_second = processed / elapsed_seconds if processed and elapsed_seconds else None
        eta_seconds = (
            max(0, int((total - processed) / units_per_second))
            if state == "IN_PROGRESS" and units_per_second and total > processed
            else None
        )
        phase_rows.append(
            {
                "name": name,
                "status": state,
                "progress_percent": percent,
                "processed_units": processed,
                "total_units": total,
                "elapsed_seconds": elapsed_seconds,
                "units_per_second": units_per_second,
                "eta_seconds": eta_seconds,
                "started_at": (
                    datetime.fromtimestamp(started_epoch, UTC).isoformat()
                    if started_epoch is not None
                    else None
                ),
                "subphase": checkpoint.get("subphase") if phase_is_current else None,
                "heartbeat_at": checkpoint.get("heartbeat_at") if phase_is_current else None,
            }
        )
    authority_without_run = bool(authorities) and not runs
    empty_run_prefix = bool(runs) and not checkpoint and not verify
    run_lock_held = _exclusive_lock_is_held(policy.operations_root / "run.lock")
    stopped_checkpoint = bool(checkpoint) and not verify and not run_lock_held
    status = (
        "PASS"
        if verify
        else ("BLOCKED" if stopped_checkpoint else ("IN_PROGRESS" if checkpoint else "BLOCKED"))
    )
    reason_code = (
        "FORMAL_TASK_VERIFIED_PASS"
        if verify
        else (
            "PRE_BLIND_PREFIX_FAILED"
            if stopped_checkpoint
            else (
                "RUN_IN_PROGRESS"
                if checkpoint
                else (
                    "AUTHORITY_SEALED_WITHOUT_RUN"
                    if authority_without_run
                    else (
                        "EMPTY_RUN_PREFIX_BLOCKED"
                        if empty_run_prefix
                        else "FORMAL_APPROVAL_REQUIRED"
                    )
                )
            )
        )
    )
    current_phase_row = next(
        (row for row in phase_rows if row["name"] == current_phase),
        phase_rows[0],
    )
    base.update(
        {
            "status": status,
            "reason_code": reason_code,
            "policy_hash": policy.policy_hash,
            "source_t16_status": "PASS",
            "source_t16_verify_hash": binding.verify_hash,
            "source_counts": binding.counts,
            "approval_count": len(approvals),
            "authority_count": len(authorities),
            "run_count": len(runs),
            "run_id": run_id,
            "run_code_commit": run_contract.get("code_commit"),
            "observer_repo_commit": _repository_commit(),
            "observer_changes_do_not_mutate_run": True,
            "phase": current_phase,
            "subphase": checkpoint.get("subphase"),
            "progress_percent": 100.0 if verify else progress_value,
            "processed_units": checkpoint.get("processed_units", 0),
            "total_units": checkpoint.get("total_units", 456),
            "rows_per_second": checkpoint.get("rows_per_second"),
            "units_per_second": current_phase_row.get("units_per_second"),
            "eta_seconds": checkpoint.get("eta_seconds") or current_phase_row.get("eta_seconds"),
            "elapsed_seconds": checkpoint.get("elapsed_seconds")
            or current_phase_row.get("elapsed_seconds"),
            "started_at": (
                datetime.fromtimestamp(run_started_epoch, UTC).isoformat()
                if run_started_epoch is not None
                else None
            ),
            "heartbeat_at": checkpoint.get("heartbeat_at"),
            "phases": phase_rows,
            "verify_hash": verify.get("verify_hash"),
            "placebo_slot_count": verify.get("placebo_slot_count"),
            "placebo_matched": verify.get("placebo_matched"),
            "placebo_unmatched": verify.get("placebo_unmatched"),
            "summary_row_count": verify.get("summary_row_count"),
        }
    )
    return base


def _stage2_v15_projection(stage2_root: Path) -> dict[str, Any]:
    """Project Plan v1.5/T18 without mutating research evidence."""

    del stage2_root
    phase_names = (
        "AUDIT",
        "FORMAT_SMOKE",
        "CLUSTER_AGGREGATION",
        "REAL_BOOTSTRAP",
        "PLACEBO_BOOTSTRAP",
        "PAIRED_CONTRAST",
        "BH_FDR",
        "PUBLISH",
        "VERIFY",
    )
    totals = {
        "AUDIT": 1,
        "FORMAT_SMOKE": 1,
        "CLUSTER_AGGREGATION": 456,
        "REAL_BOOTSTRAP": 608,
        "PLACEBO_BOOTSTRAP": 608,
        "PAIRED_CONTRAST": 608,
        "BH_FDR": 96,
        "PUBLISH": 1,
        "VERIFY": 1,
    }
    base: dict[str, Any] = {
        "schema_name": "s2p15-t18-ui-projection",
        "schema_version": "1.0",
        "stage_plan_version": "1.5",
        "task_id": "S2P15-T18",
        "status": "BLOCKED",
        "reason_code": "POLICY_OR_SOURCE_NOT_VERIFIED",
        "repo_root": str(REPOSITORY_ROOT.resolve()),
        "repo_commit": _repository_commit(),
        "observer_repo_commit": _repository_commit(),
        "source_t16_status": "CHECKING",
        "source_t17_status": "CHECKING",
        "format_smoke_count": 0,
        "approval_count": 0,
        "authority_count": 0,
        "run_count": 0,
        "phase": "AUDIT",
        "subphase": None,
        "progress_percent": 0.0,
        "processed_units": 0,
        "total_units": 1,
        "rows_per_second": None,
        "clusters_per_second": None,
        "eta_seconds": None,
        "heartbeat_at": None,
        "phases": [],
        "evidence_label": "H2 historical cluster-bootstrap evidence",
        "research_status": "STATISTICAL_EVIDENCE_ONLY_FINAL_GATE_PENDING",
        "stage3_locked": True,
    }
    try:
        policy = load_bootstrap_policy(
            REPOSITORY_ROOT / "configs/governance/stage2_active_policy_v4.json",
            repository_root=REPOSITORY_ROOT,
        )
        sources = audit_bootstrap_sources(
            policy,
            repository_root=REPOSITORY_ROOT,
            full_hash_scan=False,
        )
    except (OSError, ValueError) as exc:
        base["reason"] = str(exc)
        base["phases"] = [
            {
                "name": name,
                "status": "BLOCKED",
                "progress_percent": 0.0,
                "processed_units": 0,
                "total_units": totals[name],
                "elapsed_seconds": 0,
                "units_per_second": None,
                "eta_seconds": None,
                "subphase": None,
                "heartbeat_at": None,
            }
            for name in phase_names
        ]
        return base

    def safe_files(root: Path, pattern: str) -> tuple[Path, ...]:
        return tuple(
            sorted(
                path
                for path in root.glob(pattern)
                if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
            )
        )

    smokes = safe_files(policy.operations_root / "format-smokes", "*.json")
    valid_smokes = []
    current_commit = _repository_commit()
    for path in smokes:
        payload = _safe_json_object(path)
        claimed = payload.get("format_smoke_hash")
        if (
            isinstance(claimed, str)
            and bootstrap_hash(
                {key: value for key, value in payload.items() if key != "format_smoke_hash"}
            )
            == claimed
            and payload.get("status") == "PASS"
            and payload.get("code_commit") == current_commit
            and payload.get("policy_hash") == policy.policy_hash
            and payload.get("source_t16_verify_hash") == sources.t16.verify_hash
            and payload.get("source_t17_verify_hash") == sources.t17.verify_hash
        ):
            valid_smokes.append(payload)
    approval_candidates = safe_files(policy.operations_root / "approvals", "approval-*.json")
    approvals: list[Path] = []
    for path in approval_candidates:
        try:
            validate_bootstrap_approval(
                path,
                policy=policy,
                repository_root=REPOSITORY_ROOT,
            )
        except (OSError, ValueError):
            continue
        approvals.append(path)
    authorities = safe_files(policy.evidence_root / "authorities", "authority-*.json")
    runs = tuple(
        sorted(
            path
            for path in (policy.evidence_root / "runs").glob("stage2-s2p15-t18-*")
            if path.is_dir() and not path.is_symlink()
        )
    )
    checkpoint: dict[str, Any] = {}
    run_contract: dict[str, Any] = {}
    verify: dict[str, Any] = {}
    if runs:
        run_contract = _safe_json_object(runs[-1] / "run-contract.json")
        checkpoint = _safe_json_object(runs[-1] / "checkpoint.json")
        verify_files = safe_files(runs[-1] / "verify", "*.json")
        if len(verify_files) == 1:
            candidate = _safe_json_object(verify_files[0])
            claimed = candidate.get("verify_hash")
            if (
                isinstance(claimed, str)
                and bootstrap_hash(
                    {key: value for key, value in candidate.items() if key != "verify_hash"}
                )
                == claimed
                and candidate.get("status") == "PASS"
            ):
                verify = candidate
    current_phase = str(
        checkpoint.get("phase")
        or ("VERIFY" if verify else ("FORMAT_SMOKE" if valid_smokes else "AUDIT"))
    )
    current_index = phase_names.index(current_phase) if current_phase in phase_names else 0
    phase_rows: list[dict[str, Any]] = []
    for index, name in enumerate(phase_names):
        total = totals[name]
        if verify or index < current_index:
            state, processed, percent = "PASS", total, 100.0
        elif name == "AUDIT":
            state, processed, percent = "PASS", 1, 100.0
        elif name == "FORMAT_SMOKE" and valid_smokes:
            state, processed, percent = "PASS", 1, 100.0
        elif checkpoint and index == current_index:
            state = "IN_PROGRESS"
            processed = int(checkpoint.get("processed_units") or 0)
            total = int(checkpoint.get("total_units") or total)
            percent = float(checkpoint.get("percent") or 0.0)
        else:
            state, processed, percent = "NOT_STARTED", 0, 0.0
        phase_rows.append(
            {
                "name": name,
                "status": state,
                "progress_percent": percent,
                "processed_units": processed,
                "total_units": total,
                "elapsed_seconds": (
                    int(float(checkpoint.get("elapsed_seconds") or 0))
                    if checkpoint and index == current_index
                    else 0
                ),
                "units_per_second": checkpoint.get("units_per_second")
                or checkpoint.get("rows_per_second"),
                "eta_seconds": checkpoint.get("eta_seconds"),
                "subphase": checkpoint.get("subphase") if index == current_index else None,
                "heartbeat_at": checkpoint.get("heartbeat_at") if index == current_index else None,
            }
        )
    if verify:
        status, reason_code = "PASS", "FORMAL_TASK_VERIFIED_PASS"
    elif checkpoint:
        status, reason_code = (
            ("IN_PROGRESS", "RUN_IN_PROGRESS")
            if _exclusive_lock_is_held(policy.operations_root / "run.lock")
            else ("BLOCKED", "INTERRUPTED_PREFIX_REVIEW_REQUIRED")
        )
    elif authorities or runs:
        status, reason_code = "BLOCKED", "UNFINISHED_FORMAL_PREFIX"
    elif approvals:
        status, reason_code = "NOT_STARTED", "FORMAL_APPROVAL_PRESENT"
    elif valid_smokes:
        status, reason_code = "BLOCKED", "COMMIT_BOUND_APPROVAL_REQUIRED"
    else:
        status, reason_code = "BLOCKED", "FORMAT_SMOKE_REQUIRED"
    current_row = phase_rows[current_index]
    base.update(
        {
            "status": status,
            "reason_code": reason_code,
            "policy_hash": policy.policy_hash,
            "source_t16_status": "PASS",
            "source_t17_status": "PASS",
            "source_t16_verify_hash": sources.t16.verify_hash,
            "source_t17_verify_hash": sources.t17.verify_hash,
            "source_counts": sources.t17.counts,
            "format_smoke_count": len(valid_smokes),
            "latest_format_smoke_hash": (
                valid_smokes[-1].get("format_smoke_hash") if valid_smokes else None
            ),
            "approval_count": len(approvals),
            "authority_count": len(authorities),
            "run_count": len(runs),
            "run_id": runs[-1].name if runs else None,
            "run_code_commit": run_contract.get("code_commit"),
            "phase": current_phase,
            "subphase": checkpoint.get("subphase"),
            "progress_percent": 100.0 if verify else current_row["progress_percent"],
            "processed_units": current_row["processed_units"],
            "total_units": current_row["total_units"],
            "rows_per_second": checkpoint.get("rows_per_second"),
            "clusters_per_second": checkpoint.get("clusters_per_second"),
            "eta_seconds": checkpoint.get("eta_seconds"),
            "elapsed_seconds": checkpoint.get("elapsed_seconds"),
            "heartbeat_at": checkpoint.get("heartbeat_at"),
            "phases": phase_rows,
            "verify_hash": verify.get("verify_hash"),
            "cluster_rows": verify.get("cluster_rows"),
            "summary_rows": verify.get("summary_rows"),
            "fdr_family_rows": verify.get("fdr_family_rows"),
            "bootstrap_iterations": 5000,
        }
    )
    return base


def _execution_observability(run_root: Path) -> dict[str, Any]:
    """Project append-only execution evidence into compact UI counters."""

    amendment = _safe_json_object(run_root / "reports/release-only-authority-cr-2026-018.json")
    adoption: dict[str, Any] = {}
    resource_anomalies: dict[str, int] = {}
    adoption_paths = (
        [] if amendment else sorted((run_root / "manifests").glob("group1-monthly-adoption-*.json"))
    )
    if (
        len(adoption_paths) == 1
        and adoption_paths[0].is_file()
        and not adoption_paths[0].is_symlink()
    ):
        raw = json.loads(adoption_paths[0].read_bytes())
        if isinstance(raw, dict):
            adoption = {
                key: raw.get(key)
                for key in (
                    "adopted_file_count",
                    "adopted_byte_count",
                    "foundation_checkpoint_count",
                    "group1_month_count",
                    "group1_dataset_count",
                )
            }
    receipts = {
        name: (run_root / relative_path).is_file() and not (run_root / relative_path).is_symlink()
        for name, relative_path in RUNTIME_TASK_RECEIPTS.items()
    }
    components = {
        name: (run_root / relative_path).is_file() and not (run_root / relative_path).is_symlink()
        for name, relative_path in RUNTIME_GROUP1_COMPONENTS.items()
    }
    checkpoint_path = run_root / "checkpoint-v2.json"
    if checkpoint_path.is_file() and not checkpoint_path.is_symlink():
        checkpoint = json.loads(checkpoint_path.read_bytes())
        if isinstance(checkpoint, dict):
            for task in checkpoint.get("completed_tasks", []):
                if not isinstance(task, dict):
                    continue
                task_id = task.get("task_id")
                count = task.get("resource_anomaly_count", 0)
                if isinstance(task_id, str) and isinstance(count, int) and count >= 0:
                    resource_anomalies[task_id] = count
    preflight = _safe_json_object(run_root / "reports/release-only-preflight-cr-2026-018.json")
    publication = _safe_json_object(run_root / "reports/v2-publication-record.json")
    quality = _safe_json_object(run_root / "reports/v2-quality-report.json")
    compare_authority = _safe_json_object(
        run_root / "reports/compare-only-authority-cr-2026-019.json"
    )
    comparison = _safe_json_object(run_root / "reports/v2-run-a-comparison.json")
    comparison_report = comparison.get("report")
    if not isinstance(comparison_report, dict):
        comparison_report = {}
    differences = comparison_report.get("differences")
    missing = comparison_report.get("missing_in_v2")
    extra = comparison_report.get("extra_in_v2")
    return {
        "successor_created": not bool(amendment),
        "release_only": bool(amendment),
        "release_only_status": amendment.get("status"),
        "release_only_preflight_status": preflight.get("status"),
        "release_only_allowed_commands": amendment.get("allowed_commands", []),
        "sealed_object_count": amendment.get("object_count"),
        "sealed_seal_count": amendment.get("seal_count"),
        "sealed_partition_count": amendment.get("partition_count"),
        "superseded_run_id": amendment.get("superseded_run_id"),
        "adoption": adoption,
        "packed_seal_count": _safe_file_count(run_root / "staging/group1/packed-seals", "*.json"),
        "partial_file_count": _safe_file_count(run_root / "staging/group1/partials"),
        "group1_component_count": _safe_file_count(
            run_root / "staging/evidence/group1-components", "*.json"
        ),
        "group1_component_total": 4,
        "group1_components": components,
        "task_receipts": receipts,
        "resource_anomalies": resource_anomalies,
        "resource_anomaly_count": sum(resource_anomalies.values()),
        "publication_record_present": bool(publication),
        "publication_state": publication.get("publication_state"),
        "quality_report_present": bool(quality),
        "quality_status": quality.get("quality_status"),
        "compare_only_status": compare_authority.get("status"),
        "compare_only_allowed_commands": compare_authority.get("allowed_commands", []),
        "comparison_report_present": bool(comparison),
        "comparison_status": comparison_report.get("status"),
        "matched_partition_count": comparison_report.get("matched_partition_count"),
        "daily_row_hash_match_count": comparison_report.get("daily_row_hash_match_count"),
        "difference_count": len(differences) if isinstance(differences, list) else None,
        "missing_partition_count": len(missing) if isinstance(missing, list) else None,
        "extra_partition_count": len(extra) if isinstance(extra, list) else None,
        "global_distributions_equal": comparison_report.get("global_distributions_equal"),
    }


def _acceptance_projection(status: dict[str, Any], observability: dict[str, Any]) -> dict[str, Any]:
    """Derive S2-T10 acceptance from live append-only evidence, never UI constants."""

    subflows = {
        item.get("name"): item.get("status")
        for item in status.get("pipeline_subflows", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    checks = {
        "all_partitions_complete": status.get("overall_logical_partitions_done") == 80_784,
        "all_task_receipts_present": all(observability.get("task_receipts", {}).values()),
        "publication_pass": observability.get("publication_state")
        in {"PUBLISHED", "PUBLISHED_WITH_RESOURCE_ANOMALIES"},
        "quality_pass": observability.get("quality_status") == "PASS",
        "release_subflow_pass": subflows.get("RELEASE") == "PASS",
        "verify_subflow_pass": subflows.get("VERIFY") == "PASS",
        "compare_subflow_pass": subflows.get("RUN_A_RUN_B_COMPARE") == "PASS",
        "exact_partition_match": observability.get("matched_partition_count") == 61_776,
        "all_daily_hashes_match": observability.get("daily_row_hash_match_count") == 61_776,
        "no_missing_partitions": observability.get("missing_partition_count") == 0,
        "no_extra_partitions": observability.get("extra_partition_count") == 0,
        "no_differences": observability.get("difference_count") == 0,
        "global_distributions_equal": observability.get("global_distributions_equal") is True,
    }
    comparison_checks = (
        "exact_partition_match",
        "all_daily_hashes_match",
        "no_missing_partitions",
        "no_extra_partitions",
        "no_differences",
        "global_distributions_equal",
    )
    failed = any(
        subflows.get(name) == "FAILED" for name in ("RELEASE", "VERIFY", "RUN_A_RUN_B_COMPARE")
    ) or (
        observability.get("comparison_report_present") is True
        and not all(checks[name] for name in comparison_checks)
    )
    task_status = "PASS" if all(checks.values()) else "FAILED" if failed else "IN_PROGRESS"
    return {
        "s2_t10_status": task_status,
        "group1_status": task_status,
        "stage3_status": "LOCKED",
        "checks": checks,
    }


def _stage2_task_projection(stage2_root: Path) -> dict[str, Any]:
    """Read generic append-only task receipts; malformed evidence fails closed."""

    receipt_directory = stage2_root / "task-evidence" / "S2-T11"
    try:
        receipts = read_path_extraction_receipts(receipt_directory)
    except (OSError, ValueError) as exc:
        return {
            "task_id": "S2-T11",
            "task_version": "1.2",
            "status": "EVIDENCE_INVALID",
            "reason_code": "S2_T11_RECEIPT_CHAIN_INVALID",
            "reason": str(exc),
            "btc_done": 0,
            "btc_total": 0,
            "eth_done": 0,
            "eth_total": 0,
            "checks": {},
            "receipt_count": 0,
        }
    if not receipts:
        return {
            "task_id": "S2-T11",
            "task_version": "1.2",
            "status": "NOT_STARTED",
            "reason_code": "S2_T11_RECEIPT_MISSING",
            "btc_done": 0,
            "btc_total": 0,
            "eth_done": 0,
            "eth_total": 0,
            "checks": {},
            "receipt_count": 0,
        }
    latest = receipts[-1]
    pass_checks = {
        "receipt_declares_pass": latest.status == "PASS",
        "full_output_complete": latest.full_output_complete,
        "validation_pass": latest.validation_status == "PASS",
        "validation_hash_present": latest.validation_hash is not None,
        "btc_eth_inputs_separate": set(latest.input_hashes) == {"BTCUSDT", "ETHUSDT"},
        "btc_eth_outputs_separate": set(latest.output_hashes) == {"BTCUSDT", "ETHUSDT"},
        "btc_complete": latest.btc_episodes_total > 0
        and latest.btc_episodes_done == latest.btc_episodes_total,
        "eth_complete": latest.eth_episodes_total > 0
        and latest.eth_episodes_done == latest.eth_episodes_total,
        "registered_checks_pass": bool(latest.acceptance_checks)
        and all(latest.acceptance_checks.values()),
    }
    status: str = latest.status
    if status == "PASS" and not all(pass_checks.values()):
        status = "EVIDENCE_INVALID"
    return {
        "task_id": latest.task_id,
        "task_version": latest.task_version,
        "status": status,
        "reason_code": latest.reason_code,
        "btc_done": latest.btc_episodes_done,
        "btc_total": latest.btc_episodes_total,
        "eth_done": latest.eth_episodes_done,
        "eth_total": latest.eth_episodes_total,
        "checks": pass_checks,
        "acceptance_checks": latest.acceptance_checks,
        "full_output_complete": latest.full_output_complete,
        "validation_status": latest.validation_status,
        "human_accepted": latest.status == "PASS"
        and latest.reason_code.startswith("S2_T11_HUMAN_ACCEPTED_"),
        "receipt_hash": latest.receipt_hash,
        "code_commit": latest.code_commit,
        "validation_path": latest.validation_path,
        "receipt_count": len(receipts),
        "updated_at": latest.created_at,
    }


def _s2_t12_base(status: str, reason_code: str) -> dict[str, Any]:
    return {
        "task_id": "S2-T12",
        "task_version": "1.3",
        "status": status,
        "reason_code": reason_code,
        "run_id": None,
        "authority_hash": None,
        "snapshot_id": None,
        "manifest_hash": None,
        "catalog_hash": None,
        "instruments": {},
        "checks": {},
        "full_output_complete": False,
        "verify_status": "NOT_RUN",
        "validation_status": "NOT_RUN",
        "historical_evidence_only": True,
        "stage3_locked": True,
        "human_accepted": False,
    }


def _s2_t12_invalid(reason: str, *, run_id: str | None = None) -> dict[str, Any]:
    result = _s2_t12_base("EVIDENCE_INVALID", "S2_T12_EVIDENCE_INVALID")
    result["reason"] = reason
    result["run_id"] = run_id
    return result


def _s2_t12_instrument_projection(
    snapshot: Path,
    instrument: str,
    catalog_entry: Any,
) -> tuple[dict[str, Any], bool]:
    if not isinstance(catalog_entry, dict):
        return {}, False
    metrics = catalog_entry.get("path_metrics")
    if not isinstance(metrics, dict):
        return {}, False
    evidence_counts = metrics.get("evidence_level_counts")
    status_counts = metrics.get("metric_status_counts")
    if not isinstance(evidence_counts, dict) or not isinstance(status_counts, dict):
        return {}, False
    episodes = catalog_entry.get("episode_count")
    h1_rows = evidence_counts.get("H1")
    h2_rows = evidence_counts.get("H2")
    metric_rows = metrics.get("row_count")
    computed_rows = status_counts.get("COMPUTED")
    no_observation_rows = status_counts.get("NO_OBSERVATIONS", 0)
    output_sha256 = catalog_entry.get("sha256")
    byte_size = catalog_entry.get("byte_size")
    output_path = snapshot / instrument / "path_metrics.parquet"
    projection = {
        "episodes": episodes,
        "h1_rows": h1_rows,
        "h2_rows": h2_rows,
        "metric_rows": metric_rows,
        "computed_rows": computed_rows,
        "no_observation_rows": no_observation_rows,
        "output_sha256": output_sha256,
    }
    if not (
        isinstance(episodes, int)
        and not isinstance(episodes, bool)
        and episodes >= 0
        and isinstance(h1_rows, int)
        and not isinstance(h1_rows, bool)
        and h1_rows >= 0
        and isinstance(h2_rows, int)
        and not isinstance(h2_rows, bool)
        and h2_rows >= 0
        and isinstance(metric_rows, int)
        and not isinstance(metric_rows, bool)
        and metric_rows >= 0
        and isinstance(computed_rows, int)
        and not isinstance(computed_rows, bool)
        and computed_rows >= 0
        and isinstance(no_observation_rows, int)
        and not isinstance(no_observation_rows, bool)
        and no_observation_rows >= 0
        and isinstance(byte_size, int)
        and not isinstance(byte_size, bool)
        and byte_size >= 0
    ):
        return projection, False
    complete = (
        episodes > 0
        and h1_rows == episodes
        and h2_rows == episodes
        and metric_rows == h1_rows + h2_rows
        and metric_rows == computed_rows + no_observation_rows
        and isinstance(output_sha256, str)
        and len(output_sha256) == 64
        and output_path.is_file()
        and not output_path.is_symlink()
        and not output_path.parent.is_symlink()
        and output_path.stat().st_size == byte_size
    )
    return projection, complete


def _stage2_path_metrics_projection(
    stage2_root: Path,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Project the newest S2-T12 run; never fall back past newer evidence."""

    runs_root = stage2_root / "runs"
    if runs_root.is_symlink():
        return _s2_t12_invalid("S2-T12 runs root is a symlink")
    if not runs_root.is_dir():
        return _s2_t12_base("NOT_STARTED", "S2_T12_RUN_MISSING")
    try:
        candidates = sorted(
            path
            for path in runs_root.iterdir()
            if path.name.startswith(S2T12_RUN_PREFIX) and not path.name.startswith("._")
        )
    except OSError as exc:
        return _s2_t12_invalid(f"cannot enumerate S2-T12 runs: {exc}")
    if not candidates:
        return _s2_t12_base("NOT_STARTED", "S2_T12_RUN_MISSING")
    run_root = candidates[-1]
    run_id = run_root.name
    if S2T12_RUN_ID.fullmatch(run_id) is None or run_root.is_symlink() or not run_root.is_dir():
        return _s2_t12_invalid("newest S2-T12 run path is unsafe", run_id=run_id)

    completion_path = run_root / "reports/completion.json"
    failure_path = run_root / "reports/failure.json"
    completion_present = completion_path.is_file() and not completion_path.is_symlink()
    failure_present = failure_path.is_file() and not failure_path.is_symlink()
    if completion_present and failure_present:
        return _s2_t12_invalid("run has both completion and failure evidence", run_id=run_id)
    if failure_path.is_symlink() or completion_path.is_symlink():
        return _s2_t12_invalid("run terminal evidence is a symlink", run_id=run_id)
    if failure_present:
        failure = _safe_json_object(failure_path)
        if (
            failure.get("run_id") != run_id
            or failure.get("task_id") != "S2-T12"
            or failure.get("task_version") != "1.3"
            or failure.get("status") != "FAILED_UNPUBLISHED"
            or failure.get("resume_allowed") is not False
            or not isinstance(failure.get("reason"), str)
        ):
            return _s2_t12_invalid("malformed S2-T12 failure evidence", run_id=run_id)
        result = _s2_t12_base("FAILED", "S2_T12_FAILED_UNPUBLISHED")
        result.update(
            {
                "run_id": run_id,
                "reason": failure["reason"],
                "failure_class": failure.get("failure_class"),
                "resume_allowed": False,
            }
        )
        return result

    preflight_path = run_root / "manifests/preflight-authority.json"
    preflight = _safe_json_object(preflight_path)
    execution_paths = sorted((run_root / "manifests").glob("execution-*.json"))
    execution = _safe_json_object(execution_paths[0]) if len(execution_paths) == 1 else {}
    execution_valid = (
        len(execution_paths) == 1
        and not execution_paths[0].is_symlink()
        and execution.get("run_id") == run_id
        and execution.get("task_id") == "S2-T12"
        and execution.get("task_version") == "1.3"
        and _self_hash_matches(execution, "execution_manifest_hash")
    )
    preflight_valid = (
        bool(preflight)
        and not preflight_path.is_symlink()
        and preflight.get("task_id") == "S2-T12"
        and preflight.get("task_version") == "1.3"
        and _self_hash_matches(preflight, "authority_hash")
    )
    if not completion_present:
        if not preflight_valid or not execution_valid:
            return _s2_t12_invalid(
                "active run lacks valid Authority/execution evidence", run_id=run_id
            )
        result = _s2_t12_base("IN_PROGRESS", "S2_T12_RUN_IN_PROGRESS")
        result.update(
            {
                "run_id": run_id,
                "authority_hash": preflight.get("authority_hash"),
                "checks": {
                    "preflight_authority_valid": True,
                    "execution_manifest_valid": True,
                    "published_completion_present": False,
                },
            }
        )
        for instrument in ("BTCUSDT", "ETHUSDT"):
            partial = _safe_json_object(
                run_root / "reports" / f"{instrument.lower()}-completion.json"
            )
            if partial.get("instrument") == instrument:
                metrics = partial.get("path_metrics", {})
                result["instruments"][instrument] = {
                    "episodes": partial.get("episode_count"),
                    "h1_rows": metrics.get("evidence_level_counts", {}).get("H1"),
                    "h2_rows": metrics.get("evidence_level_counts", {}).get("H2"),
                    "metric_rows": metrics.get("row_count"),
                }
        return result

    completion = _safe_json_object(completion_path)
    snapshot_id = completion.get("snapshot_id")
    snapshot = run_root / "published/snapshots" / str(snapshot_id)
    manifest_path = snapshot / "manifest.json"
    catalog_path = snapshot / "catalog.json"
    manifest = _safe_json_object(manifest_path)
    catalog = _safe_json_object(catalog_path)
    raw_instruments = catalog.get("instruments")
    instruments: dict[str, Any] = raw_instruments if isinstance(raw_instruments, dict) else {}
    instrument_projection: dict[str, Any] = {}
    instrument_checks: dict[str, bool] = {}
    for instrument in ("BTCUSDT", "ETHUSDT"):
        projected, complete = _s2_t12_instrument_projection(
            snapshot,
            instrument,
            instruments.get(instrument),
        )
        instrument_projection[instrument] = projected
        instrument_checks[f"{instrument.lower()}_complete"] = complete

    authorities_root = stage2_root / "authorities/S2-T12"
    authority_candidates: list[Path] = []
    if authorities_root.is_dir() and not authorities_root.is_symlink():
        try:
            authority_candidates = [
                path for path in authorities_root.glob("*.json") if not path.name.startswith("._")
            ]
        except OSError:
            authority_candidates = []
    latest_authority: Path | None = None
    if authority_candidates:
        latest_authority = max(
            authority_candidates,
            key=lambda path: (path.lstat().st_mtime_ns, path.name),
        )
    authority = _safe_json_object(latest_authority) if latest_authority is not None else {}

    summary_path = repository_root / S2T12_SUMMARY_RELATIVE_PATH
    validation_path = repository_root / S2T12_VALIDATION_RELATIVE_PATH
    summary = _safe_json_object(summary_path)
    validation = _safe_text(validation_path)
    total_rows = sum(
        int(value.get("metric_rows", 0))
        for value in instrument_projection.values()
        if isinstance(value, dict)
    )
    raw_summary_instruments = summary.get("instruments")
    summary_instruments: dict[str, Any] = (
        raw_summary_instruments if isinstance(raw_summary_instruments, dict) else {}
    )
    summary_instruments_match = all(
        isinstance(summary_instruments.get(instrument), dict)
        and summary_instruments[instrument].get("episode_count")
        == instrument_projection[instrument].get("episodes")
        and summary_instruments[instrument].get("h1_rows")
        == instrument_projection[instrument].get("h1_rows")
        and summary_instruments[instrument].get("h2_rows")
        == instrument_projection[instrument].get("h2_rows")
        and summary_instruments[instrument].get("row_count")
        == instrument_projection[instrument].get("metric_rows")
        and summary_instruments[instrument].get("output_sha256")
        == instrument_projection[instrument].get("output_sha256")
        for instrument in ("BTCUSDT", "ETHUSDT")
    )
    checks = {
        "preflight_authority_valid": preflight_valid,
        "execution_manifest_valid": execution_valid,
        "newest_authority_matches_run": latest_authority is not None
        and not latest_authority.is_symlink()
        and authority == preflight
        and latest_authority.name == f"{preflight.get('authority_hash')}.json",
        "completion_pass": completion.get("status") == "PASS"
        and completion.get("run_id") == run_id,
        "immutable_snapshot_present": snapshot.is_dir() and not snapshot.is_symlink(),
        "manifest_self_hash_valid": not manifest_path.is_symlink()
        and _self_hash_matches(manifest, "manifest_hash"),
        "catalog_self_hash_valid": not catalog_path.is_symlink()
        and _self_hash_matches(catalog, "catalog_hash"),
        "terminal_evidence_bound": manifest.get("run_id") == run_id
        and catalog.get("run_id") == run_id
        and manifest.get("snapshot_id") == snapshot_id
        and catalog.get("snapshot_id") == snapshot_id
        and completion.get("manifest_hash") == manifest.get("manifest_hash")
        and completion.get("catalog_hash") == catalog.get("catalog_hash"),
        **instrument_checks,
        "btc_eth_h1_h2_separate": set(instruments) == {"BTCUSDT", "ETHUSDT"},
        "repository_summary_matches": not summary_path.is_symlink()
        and summary.get("schema_name") == "s2-t12-path-metrics-repository-summary"
        and summary.get("task_id") == "S2-T12"
        and summary.get("task_version") == "1.3"
        and summary.get("run_id") == run_id
        and summary.get("authority_hash") == preflight.get("authority_hash")
        and summary.get("snapshot_id") == snapshot_id
        and summary.get("manifest_hash") == manifest.get("manifest_hash")
        and summary.get("catalog_hash") == catalog.get("catalog_hash")
        and summary.get("total_metric_rows") == total_rows
        and summary_instruments_match,
        "verify_pass": summary.get("verify_status") == "PASS",
        "validation_pass": not validation_path.is_symlink()
        and bool(validation)
        and run_id in validation
        and ("VALIDATED" in validation or "PASSED / HUMAN ACCEPTED" in validation),
        "historical_evidence_only": completion.get("historical_evidence_only") is True
        and manifest.get("historical_evidence_only") is True
        and summary.get("historical_evidence_only") is True,
        "stage3_locked": completion.get("stage3_locked") is True
        and summary.get("stage3_locked") is True,
    }
    passed = all(checks.values())
    accepted_at = summary.get("accepted_at")
    human_accepted = (
        summary.get("status") == "PASSED_HUMAN_ACCEPTED"
        and summary.get("human_accepted") is True
        and summary.get("accepted_by") == "Muce"
        and isinstance(accepted_at, str)
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", accepted_at) is not None
    )
    result = _s2_t12_base(
        "PASS" if passed else "EVIDENCE_INVALID",
        "S2_T12_FULL_OUTPUT_VERIFIED_VALIDATION_PASS" if passed else "S2_T12_EVIDENCE_INVALID",
    )
    result.update(
        {
            "run_id": run_id,
            "authority_hash": preflight.get("authority_hash"),
            "snapshot_id": snapshot_id,
            "manifest_hash": manifest.get("manifest_hash"),
            "catalog_hash": catalog.get("catalog_hash"),
            "instruments": instrument_projection,
            "checks": checks,
            "full_output_complete": completion.get("status") == "PASS",
            "verify_status": summary.get("verify_status", "NOT_RUN"),
            "validation_status": "PASS" if checks["validation_pass"] else "FAIL",
            "historical_evidence_only": checks["historical_evidence_only"],
            "stage3_locked": True,
            "human_accepted": human_accepted,
            "total_metric_rows": total_rows,
            "updated_at": completion_path.stat().st_mtime,
        }
    )
    if not passed:
        result["reason"] = "one or more S2-T12 evidence checks failed"
    return result


def _s2_t13_base(status: str, reason_code: str) -> dict[str, Any]:
    return {
        "task_id": "S2-T13",
        "task_version": "1.3",
        "status": status,
        "reason_code": reason_code,
        "run_id": None,
        "authority_hash": None,
        "snapshot_id": None,
        "manifest_hash": None,
        "catalog_hash": None,
        "instruments": {},
        "checks": {},
        "full_output_complete": False,
        "verify_status": "NOT_RUN",
        "validation_status": "NOT_RUN",
        "historical_evidence_only": True,
        "stage3_locked": True,
        "human_accepted": False,
        "total_path_rows": 0,
        "total_classification_count": 0,
    }


def _s2_t13_invalid(reason: str, *, run_id: str | None = None) -> dict[str, Any]:
    result = _s2_t13_base("EVIDENCE_INVALID", "S2_T13_EVIDENCE_INVALID")
    result["reason"] = reason
    result["run_id"] = run_id
    return result


def _s2_t13_instrument_projection(
    snapshot: Path,
    instrument: str,
    catalog_entry: Any,
) -> tuple[dict[str, Any], bool]:
    if not isinstance(catalog_entry, dict):
        return {}, False
    passage = catalog_entry.get("first_passage")
    if not isinstance(passage, dict):
        return {}, False
    evidence = passage.get("evidence_level_counts")
    labels = passage.get("label_counts")
    timings = passage.get("timing_id_counts")
    if (
        not isinstance(evidence, dict)
        or not isinstance(labels, dict)
        or not isinstance(timings, dict)
    ):
        return {}, False
    episodes = catalog_entry.get("episode_count")
    h1_rows = evidence.get("H1")
    h2_rows = evidence.get("H2")
    path_rows = passage.get("row_count")
    classifications = passage.get("classification_count")
    byte_size = catalog_entry.get("byte_size")
    output_sha256 = catalog_entry.get("sha256")
    output_path = snapshot / instrument / "first_passage.parquet"
    projection = {
        "episodes": episodes,
        "h1_rows": h1_rows,
        "h2_rows": h2_rows,
        "path_rows": path_rows,
        "classification_count": classifications,
        "label_counts": labels,
        "timing_id_counts": timings,
        "output_sha256": output_sha256,
    }
    integer_values = (episodes, h1_rows, h2_rows, path_rows, classifications, byte_size)
    if not all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
        for value in integer_values
    ):
        return projection, False
    episodes = cast(int, episodes)
    h1_rows = cast(int, h1_rows)
    h2_rows = cast(int, h2_rows)
    path_rows = cast(int, path_rows)
    classifications = cast(int, classifications)
    byte_size = cast(int, byte_size)
    complete = (
        episodes > 0
        and h1_rows == episodes
        and h2_rows == episodes
        and path_rows == h1_rows + h2_rows
        and classifications == path_rows * 30
        and sum(value for value in labels.values() if isinstance(value, int)) == classifications
        and set(timings) == {"T1", "T2", "T3", "T4"}
        and isinstance(output_sha256, str)
        and len(output_sha256) == 64
        and output_path.is_file()
        and not output_path.is_symlink()
        and not output_path.parent.is_symlink()
        and output_path.stat().st_size == byte_size
    )
    return projection, complete


def _stage2_first_passage_projection(
    stage2_root: Path,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Project only the newest S2-T13 append-only run and fail closed."""

    runs_root = stage2_root / "runs"
    if runs_root.is_symlink():
        return _s2_t13_invalid("S2-T13 runs root is a symlink")
    if not runs_root.is_dir():
        return _s2_t13_base("NOT_STARTED", "S2_T13_RUN_MISSING")
    try:
        candidates = sorted(
            path
            for path in runs_root.iterdir()
            if path.name.startswith(S2T13_RUN_PREFIX) and not path.name.startswith("._")
        )
    except OSError as exc:
        return _s2_t13_invalid(f"cannot enumerate S2-T13 runs: {exc}")
    if not candidates:
        return _s2_t13_base("NOT_STARTED", "S2_T13_RUN_MISSING")
    run_root = candidates[-1]
    run_id = run_root.name
    if S2T13_RUN_ID.fullmatch(run_id) is None or run_root.is_symlink() or not run_root.is_dir():
        return _s2_t13_invalid("newest S2-T13 run path is unsafe", run_id=run_id)

    completion_path = run_root / "reports/completion.json"
    failure_path = run_root / "reports/failure.json"
    completion_present = completion_path.is_file() and not completion_path.is_symlink()
    failure_present = failure_path.is_file() and not failure_path.is_symlink()
    if completion_present and failure_present:
        return _s2_t13_invalid("run has both completion and failure evidence", run_id=run_id)
    if completion_path.is_symlink() or failure_path.is_symlink():
        return _s2_t13_invalid("run terminal evidence is a symlink", run_id=run_id)
    if failure_present:
        failure = _safe_json_object(failure_path)
        if (
            failure.get("run_id") != run_id
            or failure.get("task_id") != "S2-T13"
            or failure.get("task_version") != "1.3"
            or failure.get("status") != "FAILED_UNPUBLISHED"
            or failure.get("resume_allowed") is not False
            or not isinstance(failure.get("reason"), str)
        ):
            return _s2_t13_invalid("malformed S2-T13 failure evidence", run_id=run_id)
        result = _s2_t13_base("FAILED", "S2_T13_FAILED_UNPUBLISHED")
        result.update(
            {
                "run_id": run_id,
                "reason": failure["reason"],
                "failure_class": failure.get("failure_class"),
                "resume_allowed": False,
            }
        )
        return result

    preflight_path = run_root / "manifests/preflight-authority.json"
    preflight = _safe_json_object(preflight_path)
    execution_paths = sorted((run_root / "manifests").glob("execution-*.json"))
    execution = _safe_json_object(execution_paths[0]) if len(execution_paths) == 1 else {}
    preflight_valid = (
        bool(preflight)
        and not preflight_path.is_symlink()
        and preflight.get("task_id") == "S2-T13"
        and preflight.get("task_version") == "1.3"
        and _self_hash_matches(preflight, "authority_hash")
    )
    execution_valid = (
        len(execution_paths) == 1
        and not execution_paths[0].is_symlink()
        and execution.get("run_id") == run_id
        and execution.get("task_id") == "S2-T13"
        and execution.get("task_version") == "1.3"
        and _self_hash_matches(execution, "execution_manifest_hash")
    )
    if not completion_present:
        if not preflight_valid or not execution_valid:
            return _s2_t13_invalid(
                "active run lacks valid Authority/execution evidence",
                run_id=run_id,
            )
        result = _s2_t13_base("IN_PROGRESS", "S2_T13_RUN_IN_PROGRESS")
        result.update(
            {
                "run_id": run_id,
                "authority_hash": preflight.get("authority_hash"),
                "checks": {
                    "preflight_authority_valid": True,
                    "execution_manifest_valid": True,
                    "published_completion_present": False,
                },
            }
        )
        for instrument in ("BTCUSDT", "ETHUSDT"):
            partial = _safe_json_object(
                run_root / "reports" / f"{instrument.lower()}-completion.json"
            )
            passage = partial.get("first_passage", {})
            if partial.get("instrument") == instrument and isinstance(passage, dict):
                result["instruments"][instrument] = {
                    "episodes": partial.get("episode_count"),
                    "path_rows": passage.get("row_count"),
                    "classification_count": passage.get("classification_count"),
                }
        return result

    completion = _safe_json_object(completion_path)
    snapshot_id = completion.get("snapshot_id")
    snapshot = run_root / "published/snapshots" / str(snapshot_id)
    manifest_path = snapshot / "manifest.json"
    catalog_path = snapshot / "catalog.json"
    manifest = _safe_json_object(manifest_path)
    catalog = _safe_json_object(catalog_path)
    raw_instruments = catalog.get("instruments")
    instruments: dict[str, Any] = raw_instruments if isinstance(raw_instruments, dict) else {}
    projections: dict[str, Any] = {}
    instrument_checks: dict[str, bool] = {}
    for instrument in ("BTCUSDT", "ETHUSDT"):
        projected, complete = _s2_t13_instrument_projection(
            snapshot,
            instrument,
            instruments.get(instrument),
        )
        projections[instrument] = projected
        instrument_checks[f"{instrument.lower()}_complete"] = complete

    authorities_root = stage2_root / "authorities/S2-T13"
    authority_candidates = (
        [path for path in authorities_root.glob("*.json") if not path.name.startswith("._")]
        if authorities_root.is_dir() and not authorities_root.is_symlink()
        else []
    )
    latest_authority = (
        max(authority_candidates, key=lambda path: (path.lstat().st_mtime_ns, path.name))
        if authority_candidates
        else None
    )
    authority = _safe_json_object(latest_authority) if latest_authority is not None else {}
    summary_path = repository_root / S2T13_SUMMARY_RELATIVE_PATH
    validation_path = repository_root / S2T13_VALIDATION_RELATIVE_PATH
    summary = _safe_json_object(summary_path)
    validation = _safe_text(validation_path)
    total_rows = sum(int(value.get("path_rows", 0)) for value in projections.values())
    total_classifications = sum(
        int(value.get("classification_count", 0)) for value in projections.values()
    )
    summary_instruments = summary.get("instruments")
    summary_instruments_match = isinstance(summary_instruments, dict) and all(
        isinstance(summary_instruments.get(instrument), dict)
        and summary_instruments[instrument].get("episode_count")
        == projections[instrument].get("episodes")
        and summary_instruments[instrument].get("path_rows")
        == projections[instrument].get("path_rows")
        and summary_instruments[instrument].get("classification_count")
        == projections[instrument].get("classification_count")
        and summary_instruments[instrument].get("output_sha256")
        == projections[instrument].get("output_sha256")
        for instrument in ("BTCUSDT", "ETHUSDT")
    )
    checks = {
        "preflight_authority_valid": preflight_valid,
        "execution_manifest_valid": execution_valid,
        "newest_authority_matches_run": latest_authority is not None
        and not latest_authority.is_symlink()
        and authority == preflight
        and latest_authority.name == f"{preflight.get('authority_hash')}.json",
        "completion_pass": completion.get("status") == "PASS"
        and completion.get("run_id") == run_id,
        "immutable_snapshot_present": snapshot.is_dir() and not snapshot.is_symlink(),
        "manifest_self_hash_valid": not manifest_path.is_symlink()
        and _self_hash_matches(manifest, "manifest_hash"),
        "catalog_self_hash_valid": not catalog_path.is_symlink()
        and _self_hash_matches(catalog, "catalog_hash"),
        "terminal_evidence_bound": manifest.get("run_id") == run_id
        and catalog.get("run_id") == run_id
        and manifest.get("snapshot_id") == snapshot_id
        and catalog.get("snapshot_id") == snapshot_id
        and completion.get("manifest_hash") == manifest.get("manifest_hash")
        and completion.get("catalog_hash") == catalog.get("catalog_hash"),
        **instrument_checks,
        "btc_eth_h1_h2_separate": set(instruments) == {"BTCUSDT", "ETHUSDT"},
        "classification_domain_complete": total_classifications == total_rows * 30
        and catalog.get("combination_order") == preflight.get("combination_order"),
        "repository_summary_matches": not summary_path.is_symlink()
        and summary.get("schema_name") == "s2-t13-first-passage-repository-summary"
        and summary.get("task_id") == "S2-T13"
        and summary.get("task_version") == "1.3"
        and summary.get("run_id") == run_id
        and summary.get("authority_hash") == preflight.get("authority_hash")
        and summary.get("snapshot_id") == snapshot_id
        and summary.get("manifest_hash") == manifest.get("manifest_hash")
        and summary.get("catalog_hash") == catalog.get("catalog_hash")
        and summary.get("total_path_rows") == total_rows
        and summary.get("total_classification_count") == total_classifications
        and summary_instruments_match,
        "verify_pass": summary.get("verify_status") == "PASS",
        "validation_pass": not validation_path.is_symlink()
        and bool(validation)
        and run_id in validation
        and "VALIDATED" in validation,
        "historical_evidence_only": completion.get("historical_evidence_only") is True
        and manifest.get("historical_evidence_only") is True
        and summary.get("historical_evidence_only") is True,
        "stage3_locked": completion.get("stage3_locked") is True
        and manifest.get("stage3_locked") is True
        and summary.get("stage3_locked") is True,
    }
    passed = all(checks.values())
    accepted_at = summary.get("accepted_at")
    human_accepted = (
        summary.get("status") == "PASSED_HUMAN_ACCEPTED"
        and summary.get("human_accepted") is True
        and summary.get("accepted_by") == "Muce"
        and isinstance(accepted_at, str)
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", accepted_at) is not None
    )
    result = _s2_t13_base(
        "PASS" if passed else "EVIDENCE_INVALID",
        "S2_T13_FULL_OUTPUT_VERIFIED_VALIDATION_PASS" if passed else "S2_T13_EVIDENCE_INVALID",
    )
    result.update(
        {
            "run_id": run_id,
            "authority_hash": preflight.get("authority_hash"),
            "snapshot_id": snapshot_id,
            "manifest_hash": manifest.get("manifest_hash"),
            "catalog_hash": catalog.get("catalog_hash"),
            "instruments": projections,
            "checks": checks,
            "full_output_complete": completion.get("status") == "PASS",
            "verify_status": summary.get("verify_status", "NOT_RUN"),
            "validation_status": "PASS" if checks["validation_pass"] else "FAIL",
            "historical_evidence_only": checks["historical_evidence_only"],
            "stage3_locked": True,
            "human_accepted": human_accepted,
            "total_path_rows": total_rows,
            "total_classification_count": total_classifications,
            "updated_at": completion_path.stat().st_mtime,
        }
    )
    if not passed:
        result["reason"] = "one or more S2-T13 evidence checks failed"
    return result


def _s2_t14_base(status: str, reason_code: str) -> dict[str, Any]:
    return {
        "task_id": "S2-T14",
        "task_version": "1.3",
        "status": status,
        "reason_code": reason_code,
        "run_id": None,
        "authority_hash": None,
        "snapshot_id": None,
        "manifest_hash": None,
        "catalog_hash": None,
        "source_s2t13_run_id": None,
        "instruments": {},
        "checks": {},
        "full_output_complete": False,
        "verify_status": "NOT_RUN",
        "validation_status": "NOT_RUN",
        "historical_evidence_only": True,
        "stage3_locked": True,
        "human_accepted": False,
        "total_path_rows": 0,
        "total_classification_count": 0,
        "total_distribution_count": 0,
        "total_ambiguous_count": 0,
        "expected_distribution_count_per_instrument": 0,
    }


def _stage2_conditional_baseline_projection(stage2_root: Path) -> dict[str, Any]:
    """Project T15 only from governance and append-only evidence; never infer PASS."""

    task_path = REPOSITORY_ROOT / "docs/development/tasks/stage_2/S2-T15-task.md"
    oq_path = REPOSITORY_ROOT / "docs/development/OPEN_QUESTIONS.md"
    cr_path = REPOSITORY_ROOT / "docs/development/changes/CR-2026-026.md"
    governance = all(
        path.is_file() and not path.is_symlink() for path in (task_path, oq_path, cr_path)
    )
    approved = False
    if governance:
        approved = (
            "task_version: 1.4" in task_path.read_text()
            and "status: APPROVED" in cr_path.read_text()
            and "| RESOLVED | S2-T15 full conditional baseline" in oq_path.read_text()
        )
    audit_root = stage2_root / "authorities/S2-T15/v1.4/audits"
    audits = (
        tuple(
            path
            for path in audit_root.glob("*.json")
            if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
        )
        if audit_root.is_dir() and not audit_root.is_symlink()
        else ()
    )
    audit = (
        _safe_json_object(max(audits, key=lambda path: (path.stat().st_mtime_ns, path.name)))
        if audits
        else {}
    )
    audit_pass = (
        audit.get("status") == "PASS"
        and audit.get("authority_created") is False
        and audit.get("run_id_created") is False
        and audit.get("t13", {}).get("h2_path_count") == 532708
        and audit.get("t13", {}).get("h2_outcome_cell_count") == 15981240
        and audit.get("t14", {}).get("binding_mode") == "AGGREGATE_POLICY_ONLY_NO_EPISODE_JOIN"
    )
    authority_root = stage2_root / "authorities/S2-T15/v1.4"
    authorities = (
        tuple(
            path
            for path in authority_root.glob("authority-*.json")
            if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
        )
        if authority_root.is_dir() and not authority_root.is_symlink()
        else ()
    )
    runs_root = stage2_root / "runs"
    runs = (
        tuple(
            path
            for path in runs_root.glob(f"{S2T15_RUN_PREFIX}*")
            if path.is_dir() and not path.is_symlink()
        )
        if runs_root.is_dir() and not runs_root.is_symlink()
        else ()
    )
    status = "BLOCKED"
    reason = "S2_T15_GOVERNANCE_NOT_APPROVED"
    if approved:
        status = "NOT_STARTED"
        reason = "S2_T15_APPROVED_AWAITING_FINAL_CODE_AUTHORITY"
    if approved and audit_pass:
        reason = "S2_T15_AUDIT_PASS_AWAITING_FINAL_CODE_AUTHORITY"
    if approved and audit.get("status") == "BLOCKED":
        status = "BLOCKED"
        reason = str(audit.get("reason_code") or "S2_T15_UPSTREAM_AUDIT_BLOCKED")
    if authorities:
        reason = "S2_T15_AUTHORITY_FROZEN_AWAITING_BINS_AND_RUN"
    newest: Path | None = None
    verify_status = "NOT_RUN"
    validation_status = "NOT_RUN"
    if runs:
        newest = max(runs, key=lambda path: (path.stat().st_mtime_ns, path.name))
        failure = _safe_json_object(newest / "reports/failure.json")
        checkpoint = _safe_json_object(newest / "checkpoint.json")
        verify_files = (
            tuple(
                path
                for path in (newest / "verify").glob("*.json")
                if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
            )
            if (newest / "verify").is_dir() and not (newest / "verify").is_symlink()
            else ()
        )
        verify = (
            _safe_json_object(
                max(verify_files, key=lambda path: (path.stat().st_mtime_ns, path.name))
            )
            if verify_files
            else _safe_json_object(newest / "reports/verify.json")
        )
        validation_path = REPOSITORY_ROOT / S2T15_VALIDATION_RELATIVE_PATH
        validation = (
            validation_path.read_text(encoding="utf-8")
            if validation_path.is_file() and not validation_path.is_symlink()
            else ""
        )
        validation_pass = (
            "task_version: 1.4" in validation
            and "task_validation: PASS" in validation
            and str(newest.name) in validation
        )
        verify_pass = (
            verify.get("status") == "PASS"
            and (
                bool(verify.get("reconciliation_hash"))
                or verify.get("reconciliation_status") == "PASS"
            )
            and verify.get("historical_evidence_only") is True
            and verify.get("stage3_locked") is True
            and verify.get("run_id") == newest.name
            and (checkpoint.get("authority_hash") or verify.get("authority_hash"))
            in {path.stem.removeprefix("authority-") for path in authorities}
        )
        checkpoint_failed = checkpoint.get("status") in {
            "FAILED",
            "FAILED_UNPUBLISHED",
            "INVALIDATED",
        }
        verify_status = "PASS" if verify_pass else "FAIL" if verify else "NOT_RUN"
        validation_status = "PASS" if validation_pass else "FAIL" if validation else "NOT_RUN"
        status = (
            "FAILED"
            if failure or checkpoint_failed
            else "PASS"
            if verify_pass and validation_pass
            else "IN_PROGRESS"
        )
        reason = (
            "S2_T15_FAILED_UNPUBLISHED"
            if failure or checkpoint_failed
            else "S2_T15_FULL_VERIFY_PASS"
            if status == "PASS"
            else "S2_T15_RUN_IN_PROGRESS"
        )
    return {
        "task_id": "S2-T15",
        "task_version": "1.4",
        "status": status,
        "reason_code": reason,
        "governance_approved": approved,
        "audit_status": str(audit.get("status") or "NOT_RUN"),
        "upstream_binding_hash": audit.get("upstream_binding_hash"),
        "authority_count": len(authorities),
        "run_count": len(runs),
        "run_id": newest.name if newest is not None else None,
        "verify_status": verify_status,
        "validation_status": validation_status,
        "h2_path_count": audit.get("t13", {}).get("h2_path_count", 0),
        "h2_outcome_cell_count": audit.get("t13", {}).get("h2_outcome_cell_count", 0),
        "missing_distribution_partition_count": audit.get("t10", {}).get(
            "missing_distribution_partition_count", 0
        ),
        "historical_evidence_only": True,
        "research_result": "DESCRIPTIVE_ONLY / PRIMARY_PENDING_T18",
        "stage3_locked": True,
    }


def _s2_t14_invalid(reason: str, *, run_id: str | None = None) -> dict[str, Any]:
    result = _s2_t14_base("EVIDENCE_INVALID", "S2_T14_EVIDENCE_INVALID")
    result["reason"] = reason
    result["run_id"] = run_id
    return result


def _s2_t14_instrument_projection(
    snapshot: Path,
    instrument: str,
    catalog_entry: Any,
    expected_distribution_count: Any,
) -> tuple[dict[str, Any], bool]:
    if not isinstance(catalog_entry, dict):
        return {}, False
    label_counts = catalog_entry.get("label_counts")
    label_reason_counts = catalog_entry.get("label_reason_counts")
    if not isinstance(label_counts, dict) or not isinstance(label_reason_counts, dict):
        return {}, False
    episodes = catalog_entry.get("episode_count")
    path_rows = catalog_entry.get("path_rows")
    classifications = catalog_entry.get("classification_count")
    distributions = catalog_entry.get("distribution_count")
    primary = catalog_entry.get("primary_target_first_count")
    conditional_denominator = catalog_entry.get("conditional_denominator")
    theoretical_upper = catalog_entry.get("theoretical_upper_target_first_count")
    byte_size = catalog_entry.get("byte_size")
    output_sha256 = catalog_entry.get("sha256")
    ambiguous = label_counts.get("AMBIGUOUS")
    target_first = label_counts.get("TARGET_FIRST")
    output_path = snapshot / instrument / "ambiguity_distributions.json"
    projection = {
        "episodes": episodes,
        "path_rows": path_rows,
        "classification_count": classifications,
        "distribution_count": distributions,
        "label_counts": label_counts,
        "label_reason_counts": label_reason_counts,
        "ambiguous_count": ambiguous,
        "primary_target_first_count": primary,
        "conditional_denominator": conditional_denominator,
        "theoretical_upper_target_first_count": theoretical_upper,
        "output_sha256": output_sha256,
    }
    integers = (
        episodes,
        path_rows,
        classifications,
        distributions,
        primary,
        conditional_denominator,
        theoretical_upper,
        ambiguous,
        target_first,
        byte_size,
    )
    if not all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in integers
    ):
        return projection, False
    episodes = cast(int, episodes)
    path_rows = cast(int, path_rows)
    classifications = cast(int, classifications)
    distributions = cast(int, distributions)
    primary = cast(int, primary)
    conditional_denominator = cast(int, conditional_denominator)
    theoretical_upper = cast(int, theoretical_upper)
    ambiguous = cast(int, ambiguous)
    target_first = cast(int, target_first)
    byte_size = cast(int, byte_size)
    labels_accounted = (
        set(label_counts) == {"TARGET_FIRST", "STOP_FIRST", "EXPIRED", "AMBIGUOUS"}
        and all(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
            for value in label_counts.values()
        )
        and sum(cast(int, value) for value in label_counts.values()) == classifications
    )
    reasons_accounted = (
        all(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
            for value in label_reason_counts.values()
        )
        and sum(cast(int, value) for value in label_reason_counts.values()) == classifications
    )
    complete = (
        episodes > 0
        and path_rows == episodes * 2
        and classifications == path_rows * 30
        and isinstance(expected_distribution_count, int)
        and not isinstance(expected_distribution_count, bool)
        and expected_distribution_count > 0
        and distributions == expected_distribution_count
        and labels_accounted
        and reasons_accounted
        and primary == target_first
        and conditional_denominator == classifications - ambiguous
        and theoretical_upper == target_first + ambiguous
        and isinstance(output_sha256, str)
        and len(output_sha256) == 64
        and output_path.is_file()
        and not output_path.is_symlink()
        and not output_path.parent.is_symlink()
        and output_path.stat().st_size == byte_size
        and hashlib.sha256(output_path.read_bytes()).hexdigest() == output_sha256
    )
    return projection, complete


def _stage2_ambiguity_bounds_projection(
    stage2_root: Path,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Project only the newest S2-T14 append-only Run and fail closed."""

    runs_root = stage2_root / "runs"
    if runs_root.is_symlink():
        return _s2_t14_invalid("S2-T14 runs root is a symlink")
    if not runs_root.is_dir():
        return _s2_t14_base("NOT_STARTED", "S2_T14_RUN_MISSING")
    try:
        candidates = sorted(
            path
            for path in runs_root.iterdir()
            if path.name.startswith(S2T14_RUN_PREFIX) and not path.name.startswith("._")
        )
    except OSError as exc:
        return _s2_t14_invalid(f"cannot enumerate S2-T14 runs: {exc}")
    if not candidates:
        return _s2_t14_base("NOT_STARTED", "S2_T14_RUN_MISSING")
    run_root = candidates[-1]
    run_id = run_root.name
    if S2T14_RUN_ID.fullmatch(run_id) is None or run_root.is_symlink() or not run_root.is_dir():
        return _s2_t14_invalid("newest S2-T14 run path is unsafe", run_id=run_id)

    completion_path = run_root / "reports/completion.json"
    failure_path = run_root / "reports/failure.json"
    completion_present = completion_path.is_file() and not completion_path.is_symlink()
    failure_present = failure_path.is_file() and not failure_path.is_symlink()
    if completion_present and failure_present:
        return _s2_t14_invalid("run has both completion and failure evidence", run_id=run_id)
    if completion_path.is_symlink() or failure_path.is_symlink():
        return _s2_t14_invalid("run terminal evidence is a symlink", run_id=run_id)
    if failure_present:
        failure = _safe_json_object(failure_path)
        if (
            failure.get("run_id") != run_id
            or failure.get("task_id") != "S2-T14"
            or failure.get("task_version") != "1.3"
            or failure.get("status") != "FAILED_UNPUBLISHED"
            or failure.get("resume_allowed") is not False
            or not isinstance(failure.get("reason"), str)
        ):
            return _s2_t14_invalid("malformed S2-T14 failure evidence", run_id=run_id)
        result = _s2_t14_base("FAILED", "S2_T14_FAILED_UNPUBLISHED")
        result.update(
            {
                "run_id": run_id,
                "reason": failure["reason"],
                "failure_class": failure.get("failure_class"),
                "resume_allowed": False,
            }
        )
        return result

    preflight_path = run_root / "manifests/preflight-authority.json"
    preflight = _safe_json_object(preflight_path)
    execution_paths = sorted((run_root / "manifests").glob("execution-*.json"))
    execution = _safe_json_object(execution_paths[0]) if len(execution_paths) == 1 else {}
    preflight_valid = (
        bool(preflight)
        and not preflight_path.is_symlink()
        and preflight.get("task_id") == "S2-T14"
        and preflight.get("task_version") == "1.3"
        and _self_hash_matches(preflight, "authority_hash")
    )
    execution_valid = (
        len(execution_paths) == 1
        and not execution_paths[0].is_symlink()
        and execution.get("run_id") == run_id
        and execution.get("task_id") == "S2-T14"
        and execution.get("task_version") == "1.3"
        and execution.get("authority_hash") == preflight.get("authority_hash")
        and _self_hash_matches(execution, "execution_manifest_hash")
    )
    if not completion_present:
        if not preflight_valid or not execution_valid:
            return _s2_t14_invalid(
                "active run lacks valid Authority/execution evidence",
                run_id=run_id,
            )
        result = _s2_t14_base("IN_PROGRESS", "S2_T14_RUN_IN_PROGRESS")
        result.update(
            {
                "run_id": run_id,
                "authority_hash": preflight.get("authority_hash"),
                "source_s2t13_run_id": preflight.get("source_s2t13_run_id"),
                "expected_distribution_count_per_instrument": preflight.get(
                    "expected_distribution_count_per_instrument", 0
                ),
                "checks": {
                    "preflight_authority_valid": True,
                    "execution_manifest_valid": True,
                    "published_completion_present": False,
                },
            }
        )
        for instrument in ("BTCUSDT", "ETHUSDT"):
            partial = _safe_json_object(
                run_root / "reports" / f"{instrument.lower()}-completion.json"
            )
            if partial.get("instrument") == instrument:
                result["instruments"][instrument] = {
                    key: partial.get(key)
                    for key in (
                        "episode_count",
                        "path_rows",
                        "classification_count",
                        "distribution_count",
                        "ambiguous_count",
                    )
                }
        return result

    completion = _safe_json_object(completion_path)
    snapshot_id = completion.get("snapshot_id")
    snapshot = run_root / "published/snapshots" / str(snapshot_id)
    manifest_path = snapshot / "manifest.json"
    catalog_path = snapshot / "catalog.json"
    manifest = _safe_json_object(manifest_path)
    catalog = _safe_json_object(catalog_path)
    raw_instruments = catalog.get("instruments")
    instruments: dict[str, Any] = raw_instruments if isinstance(raw_instruments, dict) else {}
    projections: dict[str, Any] = {}
    instrument_checks: dict[str, bool] = {}
    for instrument in ("BTCUSDT", "ETHUSDT"):
        projected, complete = _s2_t14_instrument_projection(
            snapshot,
            instrument,
            instruments.get(instrument),
            preflight.get("expected_distribution_count_per_instrument"),
        )
        projections[instrument] = projected
        instrument_checks[f"{instrument.lower()}_complete"] = complete

    authorities_root = stage2_root / "authorities/S2-T14"
    authority_candidates = (
        [path for path in authorities_root.glob("*.json") if not path.name.startswith("._")]
        if authorities_root.is_dir() and not authorities_root.is_symlink()
        else []
    )
    latest_authority = (
        max(authority_candidates, key=lambda path: (path.lstat().st_mtime_ns, path.name))
        if authority_candidates
        else None
    )
    authority = _safe_json_object(latest_authority) if latest_authority is not None else {}
    summary_path = repository_root / S2T14_SUMMARY_RELATIVE_PATH
    validation_path = repository_root / S2T14_VALIDATION_RELATIVE_PATH
    summary = _safe_json_object(summary_path)
    validation = _safe_text(validation_path)

    def projected_total(key: str) -> int:
        total = 0
        for projection in projections.values():
            value = projection.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                total += value
        return total

    total_rows = projected_total("path_rows")
    total_classifications = projected_total("classification_count")
    total_distributions = projected_total("distribution_count")
    total_ambiguous = projected_total("ambiguous_count")
    summary_instruments = summary.get("instruments")
    summary_instruments_match = isinstance(summary_instruments, dict) and all(
        isinstance(summary_instruments.get(instrument), dict)
        and summary_instruments[instrument].get("episode_count")
        == projections[instrument].get("episodes")
        and all(
            summary_instruments[instrument].get(key) == projections[instrument].get(key)
            for key in (
                "path_rows",
                "classification_count",
                "distribution_count",
                "ambiguous_count",
                "output_sha256",
            )
        )
        for instrument in ("BTCUSDT", "ETHUSDT")
    )
    checks = {
        "preflight_authority_valid": preflight_valid,
        "execution_manifest_valid": execution_valid,
        "newest_authority_matches_run": latest_authority is not None
        and not latest_authority.is_symlink()
        and authority == preflight
        and latest_authority.name == f"{preflight.get('authority_hash')}.json",
        "completion_pass": completion.get("status") == "PASS"
        and completion.get("run_id") == run_id,
        "immutable_snapshot_present": snapshot.is_dir() and not snapshot.is_symlink(),
        "manifest_self_hash_valid": not manifest_path.is_symlink()
        and _self_hash_matches(manifest, "manifest_hash"),
        "catalog_self_hash_valid": not catalog_path.is_symlink()
        and _self_hash_matches(catalog, "catalog_hash"),
        "terminal_evidence_bound": manifest.get("run_id") == run_id
        and catalog.get("run_id") == run_id
        and manifest.get("snapshot_id") == snapshot_id
        and catalog.get("snapshot_id") == snapshot_id
        and completion.get("manifest_hash") == manifest.get("manifest_hash")
        and completion.get("catalog_hash") == catalog.get("catalog_hash"),
        "manifest_execution_bound": manifest.get("task_id") == "S2-T14"
        and manifest.get("task_version") == "1.3"
        and manifest.get("authority_hash") == preflight.get("authority_hash")
        and manifest.get("execution_manifest_hash") == execution.get("execution_manifest_hash"),
        "completion_counts_match": completion.get("authority_hash")
        == preflight.get("authority_hash")
        and completion.get("total_path_rows") == total_rows
        and completion.get("total_classification_count") == total_classifications
        and completion.get("total_distribution_count") == total_distributions
        and completion.get("total_ambiguous_count") == total_ambiguous,
        **instrument_checks,
        "btc_eth_separate": set(instruments) == {"BTCUSDT", "ETHUSDT"},
        "all_classifications_accounted": total_classifications == total_rows * 30,
        "distribution_domain_complete": isinstance(
            preflight.get("expected_distribution_count_per_instrument"), int
        )
        and not isinstance(preflight.get("expected_distribution_count_per_instrument"), bool)
        and total_distributions
        == 2 * cast(int, preflight.get("expected_distribution_count_per_instrument"))
        and all(
            catalog.get(key) == preflight.get(key)
            for key in (
                "combination_order",
                "parameter_set_ids",
                "parameter_set_timing_pairs",
                "timing_ids",
                "evidence_levels",
                "expected_distribution_count_per_instrument",
            )
        ),
        "source_s2t13_bound": isinstance(preflight.get("source_s2t13_run_id"), str)
        and all(
            preflight.get(key) == manifest.get(key)
            for key in (
                "source_s2t13_run_id",
                "source_s2t13_snapshot_id",
                "source_s2t13_authority_hash",
                "source_s2t13_manifest_hash",
                "source_s2t13_catalog_hash",
                "source_s2t13_code_commit",
            )
        ),
        "repository_summary_matches": not summary_path.is_symlink()
        and summary.get("schema_name") == "s2-t14-ambiguity-bounds-repository-summary"
        and summary.get("task_id") == "S2-T14"
        and summary.get("task_version") == "1.3"
        and summary.get("run_id") == run_id
        and summary.get("authority_hash") == preflight.get("authority_hash")
        and summary.get("snapshot_id") == snapshot_id
        and summary.get("manifest_hash") == manifest.get("manifest_hash")
        and summary.get("catalog_hash") == catalog.get("catalog_hash")
        and summary.get("source_s2t13_run_id") == preflight.get("source_s2t13_run_id")
        and summary.get("total_path_rows") == total_rows
        and summary.get("total_classification_count") == total_classifications
        and summary.get("total_distribution_count") == total_distributions
        and summary.get("total_ambiguous_count") == total_ambiguous
        and summary_instruments_match,
        "verify_pass": summary.get("verify_status") == "PASS",
        "validation_pass": not validation_path.is_symlink()
        and bool(validation)
        and run_id in validation
        and "VALIDATED" in validation,
        "historical_evidence_only": completion.get("historical_evidence_only") is True
        and manifest.get("historical_evidence_only") is True
        and summary.get("historical_evidence_only") is True,
        "stage3_locked": completion.get("stage3_locked") is True
        and manifest.get("stage3_locked") is True
        and summary.get("stage3_locked") is True,
    }
    passed = all(checks.values())
    accepted_at = summary.get("accepted_at")
    human_accepted = (
        summary.get("status") == "PASSED_HUMAN_ACCEPTED"
        and summary.get("human_accepted") is True
        and summary.get("accepted_by") == "Muce"
        and isinstance(accepted_at, str)
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", accepted_at) is not None
    )
    result = _s2_t14_base(
        "PASS" if passed else "EVIDENCE_INVALID",
        "S2_T14_FULL_OUTPUT_VERIFIED_VALIDATION_PASS" if passed else "S2_T14_EVIDENCE_INVALID",
    )
    result.update(
        {
            "run_id": run_id,
            "authority_hash": preflight.get("authority_hash"),
            "snapshot_id": snapshot_id,
            "manifest_hash": manifest.get("manifest_hash"),
            "catalog_hash": catalog.get("catalog_hash"),
            "source_s2t13_run_id": preflight.get("source_s2t13_run_id"),
            "instruments": projections,
            "checks": checks,
            "full_output_complete": completion.get("status") == "PASS",
            "verify_status": summary.get("verify_status", "NOT_RUN"),
            "validation_status": "PASS" if checks["validation_pass"] else "FAIL",
            "historical_evidence_only": checks["historical_evidence_only"],
            "stage3_locked": True,
            "human_accepted": human_accepted,
            "total_path_rows": total_rows,
            "total_classification_count": total_classifications,
            "total_distribution_count": total_distributions,
            "total_ambiguous_count": total_ambiguous,
            "expected_distribution_count_per_instrument": preflight.get(
                "expected_distribution_count_per_instrument", 0
            ),
            "updated_at": completion_path.stat().st_mtime,
        }
    )
    if not passed:
        result["reason"] = "one or more S2-T14 evidence checks failed"
    return result


class ProgressHandler(BaseHTTPRequestHandler):
    server: ProgressHTTPServer

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        if path == "/":
            self._reply(HTTPStatus.OK, "text/html; charset=utf-8", _PAGE_PATH.read_bytes())
        elif path == "/api/v13/status":
            try:
                self._reply_json(
                    HTTPStatus.OK,
                    {"stage2_plan_v13": _stage2_v13_projection(self.server.stage2_root)},
                )
            except (OSError, ValueError) as exc:
                self._reply_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
        elif path == "/api/v14/status":
            try:
                self._reply_json(
                    HTTPStatus.OK,
                    {"stage2_plan_v14": _stage2_v14_projection(self.server.stage2_root)},
                )
            except (OSError, ValueError) as exc:
                self._reply_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
        elif path == "/api/v15/status":
            try:
                self._reply_json(
                    HTTPStatus.OK,
                    {"stage2_plan_v15": _stage2_v15_projection(self.server.stage2_root)},
                )
            except (OSError, ValueError) as exc:
                self._reply_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
        elif path == "/api/status":
            try:
                payload = read_progress_status(self.server.run_root)
                observability = _execution_observability(self.server.run_root)
                observability["acceptance"] = _acceptance_projection(payload, observability)
                observability["stage2_tasks"] = {
                    "S2-T11": _stage2_task_projection(self.server.stage2_root),
                    "S2-T12": _stage2_path_metrics_projection(self.server.stage2_root),
                    "S2-T13": _stage2_first_passage_projection(self.server.stage2_root),
                    "S2-T14": _stage2_ambiguity_bounds_projection(self.server.stage2_root),
                    "S2-T15": _stage2_conditional_baseline_projection(self.server.stage2_root),
                }
                payload["execution_observability"] = observability
                payload["stage2_plan_v13"] = _stage2_v13_projection(self.server.stage2_root)
                payload["stage2_plan_v14"] = _stage2_v14_projection(self.server.stage2_root)
                payload["stage2_plan_v15"] = _stage2_v15_projection(self.server.stage2_root)
                self._reply_json(HTTPStatus.OK, payload)
            except (OSError, ValueError) as exc:
                self._reply_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
        elif path == "/healthz":
            try:
                payload = read_progress_status(self.server.run_root)
                self._reply_json(HTTPStatus.OK, {"status": "ok", "health": payload["health"]})
            except (OSError, ValueError) as exc:
                self._reply_json(
                    HTTPStatus.SERVICE_UNAVAILABLE, {"status": "unavailable", "error": str(exc)}
                )
        else:
            self._reply_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._reply_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "read-only server"})

    def log_message(self, format: str, *args: Any) -> None:
        del format, args

    def _reply_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        self._reply(
            status,
            "application/json; charset=utf-8",
            (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
        )

    def _reply(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # A browser may abandon the legacy deep-scan request after the fast
            # Plan v1.3 projection has already rendered.  This is not a server
            # or evidence failure and must not trigger a second HTTP response.
            return


class ProgressHTTPServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], run_root: Path, stage2_root: Path) -> None:
        super().__init__(address, ProgressHandler)
        self.run_root = run_root
        self.stage2_root = stage2_root


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Read-only Stage 2 Runtime V2 progress")
    root.add_argument("--run-id", required=True)
    root.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    root.add_argument("--bind", default="127.0.0.1")
    root.add_argument("--port", type=int, default=8765)
    root.add_argument("--open-browser", action="store_true")
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if SAFE_RUN_ID.fullmatch(args.run_id) is None:
        raise SystemExit("invalid Runtime V2 run id")
    run_root = (args.root / "runs" / args.run_id).resolve()
    approved = args.root.resolve()
    if not run_root.is_relative_to(approved) or not run_root.is_dir():
        raise SystemExit(f"run directory is unavailable: {run_root}")
    server = ProgressHTTPServer((args.bind, args.port), run_root, approved)
    url = f"http://{args.bind}:{args.port}"
    if args.open_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    print(url, flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
