#!/usr/bin/env python3
"""Validate the current Stage 2 machine authority and human-readable projections."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from era100x.foundation.governance import load_current_development_state
from era100x.research.stage_2.acceptance.evidence_gate.governance import (
    load_policy as load_v5_policy,
)
from era100x.research.stage_2.acceptance.final_acceptance.governance import (
    load_policy as load_v6_policy,
)
from era100x.research.stage_2.baselines.placebo.governance import (
    load_policy as load_v3_policy,
)
from era100x.research.stage_2.lifecycle.solo_governance import (
    load_policy as load_v8_policy,
)
from era100x.research.stage_2.rerun.lightweight_governance import (
    load_policy as load_v2_policy,
)
from era100x.research.stage_2.statistics.bootstrap.governance import (
    load_policy as load_v4_policy,
)

ROOT = Path(__file__).resolve().parents[1]
CURRENT_STAGE_PATH = ROOT / "docs/development/CURRENT_STAGE.md"
STAGE_REGISTRY_PATH = ROOT / "docs/development/STAGE_REGISTRY.md"
TRACEABILITY_PATH = ROOT / "docs/development/traceability/rules.yaml"
DEPENDENCY_GRAPH_PATH = ROOT / "docs/development/DEPENDENCY_GRAPH.md"
OPERATIONS_PATH = ROOT / "docs/development/STAGE2_OPERATIONS.md"
SRP_PATH = ROOT / "docs/development/special_research_points/SRP-S2-001.md"
S2T15_TASK_PATH = ROOT / "docs/development/tasks/stage_2/S2-T15-task.md"
S2T15_VALIDATION_PATH = ROOT / "docs/development/validations/stage_2/S2-T15.md"
STAGE2_UI_PATH = ROOT / "scripts/stage2_progress_ui.html"
CURRENT_POLICY_PATH = ROOT / "configs/governance/stage2_active_policy_v8.json"

READ_ONLY_OPERATIONS = (
    "READ_ONLY_AUDIT",
    "VERIFY_EXISTING_EVIDENCE",
    "READ_ONLY_UI",
    "PREPARE_REAL_INPUTS_LOCK",
)
BLOCKED_OPERATIONS = (
    "BUILD_AUDIT_SUPPLEMENT",
    "BUILD_FUNDING_AUDIT_SUPPLEMENT",
    "RUN_SEVEN_DAY_REHEARSAL",
    "FREEZE_AUTHORITY",
    "FREEZE_BINS",
    "PREFLIGHT",
    "RUN",
    "RESUME",
    "PUBLISH",
)
SEALED_STAGE2_TASKS = {
    "S2-T10",
    "S2-T11",
    "S2-T12",
    "S2-T13",
    "S2-T14",
    "S2-T15",
    "S2P13-T11",
    "S2P13-T12",
    "S2P13-T13",
    "S2P13-T14",
    "S2P13-T15",
    "S2P13-T16",
    "S2P14-T17",
    "S2P15-T18",
    "S2P16-T19",
    "S2P17-T20",
}
EXPECTED_HISTORICAL_TASK_STATE = {
    "stage_plan_version": "1.2",
    "task_id": "S2-T15",
    "task_version": "1.4",
    "terminal_status": "STOPPED_FAILED_UNPUBLISHED",
    "formal_result_exists": False,
    "evidence_disposition": "IMMUTABLE_HISTORICAL_ONLY",
    "successor_stage_plan_version": "1.3",
    "successor_task_id": "S2P13-T16",
    "successor_relationship": "CAPABILITY_REPLACEMENT_NOT_RESULT_PROMOTION",
    "authority_scope": "HISTORICAL_ONLY_NO_EXECUTION_AUTHORITY",
}
POLICY_LOADERS: tuple[tuple[int, Callable[..., Any], str, str], ...] = (
    (2, load_v2_policy, "1.3", "S2P13-T16"),
    (3, load_v3_policy, "1.4", "S2P14-T17"),
    (4, load_v4_policy, "1.5", "S2P15-T18"),
    (5, load_v5_policy, "1.6", "S2P16-T19"),
    (6, load_v6_policy, "1.7", "S2P17-T20"),
    (8, load_v8_policy, "1.9", "S2P19-T20"),
)


def _validate_policies(errors: list[str]) -> dict[int, Any]:
    policies: dict[int, Any] = {}
    for version, loader, expected_plan, expected_limit in POLICY_LOADERS:
        path = ROOT / f"configs/governance/stage2_active_policy_v{version}.json"
        try:
            policy = loader(path, repository_root=ROOT)
        except (OSError, ValueError) as exc:
            errors.append(f"Stage 2 policy v{version} invalid: {exc}")
            continue
        policies[version] = policy
        if policy.payload["stage_plan_version"] != expected_plan:
            errors.append(f"Stage 2 policy v{version} plan version drift")
        if policy.payload["execution_limit"] != expected_limit:
            errors.append(f"Stage 2 policy v{version} execution limit drift")
        if policy.payload["stage3_locked"] is not True:
            errors.append(f"Stage 2 policy v{version} must keep Stage 3 locked")
    return policies


def _validate_current_state(
    errors: list[str],
    *,
    state_path: Path | None = None,
    repository_root: Path = ROOT,
) -> None:
    try:
        state = (
            load_current_development_state()
            if state_path is None
            else load_current_development_state(state_path)
        )
    except (OSError, ValueError) as exc:
        errors.append(f"current machine governance state is invalid: {exc}")
        return

    expected_scalars = {
        "schema_version": "1.3",
        "current_stage": "S2",
        "current_plan": "stage_2_plan_v1.9",
        "current_task": "S2P19-T11",
        "current_task_version": "1.0",
        "task_status": "SOLO_RUNTIME_IMPLEMENTED_VALIDATED_PREPARE_GATED",
        "stage_status": "IN_PROGRESS",
        "research_decision": "STAGE2_NO_GO_CURRENT_EVIDENCE",
        "current_policy_path": "configs/governance/stage2_active_policy_v8.json",
        "approved_execution_limit": "S2P19-T20",
    }
    for field, expected in expected_scalars.items():
        if getattr(state, field) != expected:
            errors.append(f"current machine governance {field} drift")
    if state.formal_successor_result_exists is not True:
        errors.append("current machine governance must bind the formal T20 result")
    if state.stage3_locked is not True:
        errors.append("current machine governance must keep Stage 3 locked")
    if state.formal_run_receipt_required is not False:
        errors.append("Plan v1.9 must not require the removed per-Run receipt object")
    if state.allowed_operations != READ_ONLY_OPERATIONS:
        errors.append("Plan v1.9 implementation operations drift")
    if state.blocked_operations != BLOCKED_OPERATIONS:
        errors.append("Plan v1.9 formal operation block drift")
    if state.blocking_questions != (
        "FORMAL_RUN_REQUIRES_PREPARE_INPUTS_LOCK_AND_COMMIT_INPUT_LOCK_BOUND_APPROVAL",
    ):
        errors.append("Plan v1.9 formal approval blocker drift")
    if set(state.sealed_tasks) != SEALED_STAGE2_TASKS:
        errors.append("closed Stage 2 sealed task set drift")
    historical_task_states = [
        historical_state.to_payload() for historical_state in state.historical_task_states
    ]
    if historical_task_states != [EXPECTED_HISTORICAL_TASK_STATE]:
        errors.append("historical S2-T15 terminal lineage drift")
    if (ROOT / state.current_policy_path).resolve() != CURRENT_POLICY_PATH.resolve():
        errors.append("current machine governance does not point to the v8/Plan v1.9 policy")

    for record in state.source_records:
        if not (repository_root / record).is_file():
            errors.append(f"current machine governance source record missing: {record}")


def _validate_projections(
    errors: list[str],
    *,
    current_stage_path: Path = CURRENT_STAGE_PATH,
    stage_registry_path: Path = STAGE_REGISTRY_PATH,
) -> None:
    try:
        current_stage = current_stage_path.read_text(encoding="utf-8")
        registry = stage_registry_path.read_text(encoding="utf-8")
        traceability = TRACEABILITY_PATH.read_text(encoding="utf-8")
        dependency_graph = DEPENDENCY_GRAPH_PATH.read_text(encoding="utf-8")
        operations = OPERATIONS_PATH.read_text(encoding="utf-8")
        special_research_point = SRP_PATH.read_text(encoding="utf-8")
        s2_t15_task = S2T15_TASK_PATH.read_text(encoding="utf-8")
        s2_t15_validation = S2T15_VALIDATION_PATH.read_text(encoding="utf-8")
        stage2_ui = STAGE2_UI_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"governance projection unreadable: {exc}")
        return

    current_markers = (
        "Current Stage: Stage 2",
        "Current Plan: stage_2_plan_v1.9 — SOLO RUNTIME IMPLEMENTED",
        "Current Task: S2P19-T11 v1.0 — prepare inputs lock pending",
        "STAGE2_NO_GO_CURRENT_EVIDENCE",
        "one approval bound to the exact commit and inputs-lock Hash",
        "Stage 3 remains locked",
        "S2-T15` remains `STOPPED_FAILED_UNPUBLISHED`",
        "S2P13-T16",
    )
    for marker in current_markers:
        if marker not in current_stage:
            errors.append(f"CURRENT_STAGE projection missing: {marker}")

    registry_markers = (
        "| Stage 2 | 1.9 | IN_PROGRESS |",
        "STAGE2_NO_GO_CURRENT_EVIDENCE",
        "Formal prepare and Run remain gated by a clean implementation commit",
        "This is not Stage 2 research PASS",
        "Stage 3 remains locked",
        "S2-T15 remains historical `STOPPED_FAILED_UNPUBLISHED`",
        "S2P13-T16",
    )
    for marker in registry_markers:
        if marker not in registry:
            errors.append(f"Stage Registry projection missing: {marker}")
    if "| Stage 2 | 1.3 |" in registry or "S2P13-T17～T21 were not executed" in registry:
        errors.append("Stage Registry retains the superseded Plan v1.3 current-state projection")

    traceability_markers = (
        "current_plan_version: '1.9'",
        "current_task: S2P19-T11",
        "current_stage_status: IN_PROGRESS",
        "current_research_decision: STAGE2_NO_GO_CURRENT_EVIDENCE",
        "current_policy: configs/governance/stage2_active_policy_v8.json",
        "next_task_status: "
        "S2P19_PREPARE_GATED_PENDING_CLEAN_IMPLEMENTATION_COMMIT",
        "stage3_locked: true",
        "historical_s2_t15_status: STOPPED_FAILED_UNPUBLISHED",
        "historical_s2_t15_successor: S2P13-T16",
    )
    for marker in traceability_markers:
        if marker not in traceability:
            errors.append(f"Traceability Stage 2 governance missing: {marker}")

    dependency_markers = (
        "Stage 2 Plans v1.4–v1.9 successor DAG and solo runtime",
        "STAGE2_NO_GO_CURRENT_EVIDENCE",
        "Stage 2 is",
        "Stage 3 remains locked",
        "S2-T15` remains `STOPPED_FAILED_UNPUBLISHED`",
        "does not block its `S2P13-T16` successor",
    )
    for marker in dependency_markers:
        if marker not in dependency_graph:
            errors.append(f"Dependency Graph current Stage 2 projection missing: {marker}")

    operations_markers = (
        "current_development_state.json",
        "Policy v8 /",
        "STAGE2_NO_GO_CURRENT_EVIDENCE",
        "Stage 3 remains locked",
        "S2-T15` is the immutable Plan v1.2",
        "S2P13-T16",
    )
    for marker in operations_markers:
        if marker not in operations:
            errors.append(f"Stage 2 operations current projection missing: {marker}")

    srp_markers = (
        "Current projection addendum — 2026-07-28",
        "append-only historical",
        "Policy v6 / Plan v1.7",
        "STAGE2_NO_GO_CURRENT_EVIDENCE",
        "Stage 2 is `BLOCKED`, T21 was not executed",
        "Stage 3 remains locked",
    )
    for marker in srp_markers:
        if marker not in special_research_point:
            errors.append(f"Stage 2 SRP current projection missing: {marker}")

    task_markers = (
        "projection_scope: HISTORICAL_PLAN_V1_2_TERMINAL",
        "successor_task_id: S2P13-T16",
        "STOPPED_FAILED_UNPUBLISHED",
        "not the current Stage 2 Task",
        "scoped to its Plan v1.2 terminal snapshot",
    )
    for marker in task_markers:
        if marker not in s2_t15_task:
            errors.append(f"historical S2-T15 Task projection missing: {marker}")

    validation_markers = (
        "Plan v1.2 terminal conclusion",
        "STOPPED_FAILED_UNPUBLISHED",
        "S2P13-T16",
        "does not block the current T20 closure",
    )
    for marker in validation_markers:
        if marker not in s2_t15_validation:
            errors.append(f"historical S2-T15 Validation projection missing: {marker}")
    if "- Current conclusion:" in s2_t15_validation:
        errors.append("historical S2-T15 Validation still claims a current conclusion")
    if "Stage 2 is `IN_PROGRESS / S2_T15_STOPPED" in traceability:
        errors.append("Traceability still presents historical S2-T15 as current Stage 2")

    ui_markers = (
        "Plan v1.2 historical · STOPPED_FAILED_UNPUBLISHED",
        "Successor · S2P13-T16",
        "not current T20 dependency",
    )
    for marker in ui_markers:
        if marker not in stage2_ui:
            errors.append(f"Stage 2 UI historical lineage projection missing: {marker}")


def _validate_policy_lineage(errors: list[str], policies: dict[int, Any]) -> None:
    historical_t20_policy = policies.get(6)
    current_policy = policies.get(8)
    successor_policy = policies.get(2)
    if historical_t20_policy is not None:
        t20_dependencies = historical_t20_policy.payload.get("task_dag", {}).get(
            "S2P17-T20", []
        )
        if "S2-T15" in t20_dependencies:
            errors.append("Policy v6/T20 must not depend on historical S2-T15")
        if "S2P13-T16" not in t20_dependencies:
            errors.append("Policy v6/T20 must bind the S2P13-T16 successor")
    if current_policy is not None:
        t11_dependencies = current_policy.payload.get("task_dag", {}).get("S2P19-T11")
        if t11_dependencies != []:
            errors.append("Policy v8 T11 must be the successor DAG root")
        if current_policy.payload.get("formal_run_authorization") != (
            "ONE_COMMIT_AND_INPUTS_LOCK_BOUND_HUMAN_APPROVAL"
        ):
            errors.append("Policy v8 must keep formal execution separately gated")
    if successor_policy is not None:
        successor_dag = successor_policy.payload.get("task_dag", {})
        if "S2P13-T16" not in successor_dag:
            errors.append("Policy v2 does not contain the declared S2P13-T16 successor")


def validate_current_governance_state() -> tuple[list[str], dict[int, Any]]:
    """Check every Stage 2 policy plus the current machine and prose projections."""

    errors: list[str] = []
    policies = _validate_policies(errors)
    _validate_policy_lineage(errors, policies)
    _validate_current_state(errors)
    _validate_projections(errors)
    return errors, policies


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true")
    parser.parse_args()
    errors, policies = validate_current_governance_state()
    if errors:
        print("Governance policy validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    current_policy = policies[8]
    print(
        "Governance policy PASS: "
        f"S2/{current_policy.payload['execution_limit']} "
        f"policy_hash={current_policy.policy_hash}; "
        "research=STAGE2_NO_GO_CURRENT_EVIDENCE; Stage3 locked=True; "
        "machine/registry/current-stage=CONSISTENT"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
