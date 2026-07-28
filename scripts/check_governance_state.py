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
CURRENT_POLICY_PATH = ROOT / "configs/governance/stage2_active_policy_v6.json"

READ_ONLY_OPERATIONS = (
    "READ_ONLY_AUDIT",
    "VERIFY_EXISTING_EVIDENCE",
    "READ_ONLY_UI",
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
POLICY_LOADERS: tuple[tuple[int, Callable[..., Any], str, str], ...] = (
    (2, load_v2_policy, "1.3", "S2P13-T16"),
    (3, load_v3_policy, "1.4", "S2P14-T17"),
    (4, load_v4_policy, "1.5", "S2P15-T18"),
    (5, load_v5_policy, "1.6", "S2P16-T19"),
    (6, load_v6_policy, "1.7", "S2P17-T20"),
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
        "current_stage": "S2",
        "current_plan": "stage_2_plan_v1.7",
        "current_task": "S2P17-T20",
        "current_task_version": "1.0",
        "task_status": "FORMAL_ENGINEERING_PASS_RECONCILIATION_PASS_VERIFY_PASS",
        "stage_status": "BLOCKED",
        "research_decision": "STAGE2_NO_GO_CURRENT_EVIDENCE",
        "current_policy_path": "configs/governance/stage2_active_policy_v6.json",
        "approved_execution_limit": "S2P17-T20",
    }
    for field, expected in expected_scalars.items():
        if getattr(state, field) != expected:
            errors.append(f"current machine governance {field} drift")
    if state.formal_successor_result_exists is not True:
        errors.append("current machine governance must bind the formal T20 result")
    if state.stage3_locked is not True:
        errors.append("current machine governance must keep Stage 3 locked")
    if state.formal_run_receipt_required is not False:
        errors.append("closed Stage 2 state cannot advertise a pending formal run")
    if state.allowed_operations != READ_ONLY_OPERATIONS:
        errors.append("closed Stage 2 allowed operations drift")
    if state.blocked_operations != BLOCKED_OPERATIONS:
        errors.append("closed Stage 2 blocked operations drift")
    if state.blocking_questions:
        errors.append("closed T20 state cannot retain a synthetic blocking question")
    if set(state.sealed_tasks) != SEALED_STAGE2_TASKS:
        errors.append("closed Stage 2 sealed task set drift")
    if (ROOT / state.current_policy_path).resolve() != CURRENT_POLICY_PATH.resolve():
        errors.append("current machine governance does not point to the v6/T20 policy")

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
    except OSError as exc:
        errors.append(f"governance projection unreadable: {exc}")
        return

    current_markers = (
        "Current Stage: Stage 2",
        "Current Plan: stage_2_plan_v1.7 — CLOSED AT T20",
        "Current Task: S2P17-T20 v1.0 — final evidence acceptance",
        "STAGE2_NO_GO_CURRENT_EVIDENCE",
        "T21 was not executed",
        "Stage 3 remains locked",
    )
    for marker in current_markers:
        if marker not in current_stage:
            errors.append(f"CURRENT_STAGE projection missing: {marker}")

    registry_markers = (
        "| Stage 2 | 1.7 | BLOCKED |",
        "| NONE | STAGE2_NO_GO_CURRENT_EVIDENCE |",
        "S2P17-T20 passed engineering, publication, reconciliation and independent Verify",
        "This is not Stage 2 research PASS",
        "T21 was not executed and Stage 3 remains locked",
    )
    for marker in registry_markers:
        if marker not in registry:
            errors.append(f"Stage Registry projection missing: {marker}")
    if "| Stage 2 | 1.3 |" in registry or "S2P13-T17～T21 were not executed" in registry:
        errors.append("Stage Registry retains the superseded Plan v1.3 current-state projection")

    traceability_markers = (
        "current_plan_version: '1.7'",
        "current_task: S2P17-T20",
        "current_stage_status: BLOCKED",
        "current_research_decision: STAGE2_NO_GO_CURRENT_EVIDENCE",
        "current_policy: configs/governance/stage2_active_policy_v6.json",
        "next_task_status: T21_NOT_EXECUTED_NOT_APPROVED",
        "stage3_locked: true",
    )
    for marker in traceability_markers:
        if marker not in traceability:
            errors.append(f"Traceability Stage 2 governance missing: {marker}")

    dependency_markers = (
        "Stage 2 Plans v1.4–v1.7 successor DAG and current closure",
        "STAGE2_NO_GO_CURRENT_EVIDENCE",
        "Stage 2 is `BLOCKED`, not research PASS",
        "Stage 3 remains locked",
    )
    for marker in dependency_markers:
        if marker not in dependency_graph:
            errors.append(f"Dependency Graph current Stage 2 projection missing: {marker}")

    operations_markers = (
        "current_development_state.json",
        "v6/T20",
        "STAGE2_NO_GO_CURRENT_EVIDENCE",
        "T21 was not executed and Stage 3 remains locked",
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


def validate_current_governance_state() -> tuple[list[str], dict[int, Any]]:
    """Check every Stage 2 policy plus the current machine and prose projections."""

    errors: list[str] = []
    policies = _validate_policies(errors)
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
    current_policy = policies[6]
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
