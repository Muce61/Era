#!/usr/bin/env python3
"""Validate the single current governance state and its fail-closed projections."""

from __future__ import annotations

import argparse
from pathlib import Path

from era100x.foundation.governance import load_current_development_state

ROOT = Path(__file__).resolve().parents[1]

_EXPECTED_STATE = {
    "current_stage": "S2",
    "current_plan": "stage_2_plan_v1.2",
    "current_task": "S2-T15",
    "current_task_version": "1.4",
    "task_status": "STOPPED",
    "formal_t15_result_exists": False,
    "stage3_locked": True,
    "srp_execution_status": "NOT_EXECUTABLE",
}
_EXPECTED_ALLOWED = {
    "READ_ONLY_AUDIT",
    "VERIFY_EXISTING_EVIDENCE",
    "READ_ONLY_UI",
}
_EXPECTED_BLOCKED = {
    "BUILD_AUDIT_SUPPLEMENT",
    "FREEZE_AUTHORITY",
    "FREEZE_BINS",
    "PREFLIGHT",
    "RUN",
    "RESUME",
    "PUBLISH",
}
_EXPECTED_QUESTIONS = {"OQ-S2-009", "OQ-S2-010", "OQ-S2-011"}
_EXPECTED_SEALED_TASKS = {"S2-T10", "S2-T11", "S2-T12", "S2-T13", "S2-T14"}

_DOCUMENT_MARKERS: dict[str, tuple[str, ...]] = {
    "docs/development/CURRENT_STAGE.md": (
        "Current Task: S2-T15 v1.4",
        "S2_T15_STOPPED_SRP_S2_001_EXEMPTIONS_APPROVED_NOT_EXECUTABLE",
    ),
    "docs/development/STAGE_REGISTRY.md": (
        "S2_T15_STOPPED",
        "S2-T01～S2-T14 are PASSED",
        "Stage 3 remains locked",
    ),
    "docs/development/TRACEABILITY.md": (
        "S2_T15_STOPPED_SRP_S2_001_EXEMPTIONS_APPROVED_NOT_EXECUTABLE",
        "No code, Authority, Run, S2-T16+ or Stage 3 is authorized.",
    ),
    "docs/development/DEPENDENCY_GRAPH.md": (
        "S2-T19 and S2-T01～S2-T14 are PASSED",
        "S2-T15 is STOPPED",
        "Stage 3 remains locked",
    ),
    "docs/development/OPEN_QUESTIONS.md": (
        "OQ-S2-009",
        "OQ-S2-010",
        "OQ-S2-011",
    ),
    "docs/development/tasks/stage_2/S2-T15-task.md": (
        "status: STOPPED / READ-ONLY AUDIT ONLY / NO AUTHORITY OR RUN",
        "OQ-S2-009",
        "configs/governance/current_development_state.json",
    ),
    "docs/development/validations/stage_2/S2-T15.md": (
        "STOPPED / 7-DAY RAW PATH PASS / FULL LIFECYCLE BLOCKED",
        "NO FORMAL RESEARCH RESULT PUBLISHED",
        "Stage 3: `LOCKED`",
    ),
    "docs/development/changes/CR-2026-031.md": (
        "status: APPROVED / READ-ONLY AVAILABILITY AUDIT AUTHORIZED",
        "INCORPORATED_ACTIVE_SAFETY_CONTRACT",
    ),
    "docs/development/changes/CR-2026-032.md": (
        "status: APPROVED DIRECTION / IMPLEMENTATION BLOCKED BY OQ-S2-010",
        "INCORPORATED_SOURCE_AUTHORITY",
    ),
    "docs/development/changes/CR-2026-033.md": (
        "status: DRAFT / AWAITING HUMAN APPROVAL",
        "implementation_authorized: false",
    ),
    "docs/development/changes/CR-2026-034.md": (
        "status: APPROVED / IMPLEMENTATION AUTHORIZED / NO RESEARCH RUN",
        "current-state authority and fail-closed S2-T15 operation gate",
    ),
    "docs/development/decisions/ADR-S2-010-historical-missingness.md": (
        "APPROVED — 2026-07-22T16:27:27Z by Muce",
        "INCORPORATED_ACTIVE_SAFETY_CONTRACT",
    ),
    "docs/development/decisions/ADR-S2-011-event-path-and-strategy-lifecycle-separation.md": (
        "APPROVED DIRECTION — 2026-07-22T16:27:27Z by Muce",
        "implementation blocked by OQ-S2-010",
    ),
    "docs/development/decisions/ADR-S2-012-special-research-point.md": (
        "PROPOSED — awaiting Muce approval and OQ-S2-011 resolution",
        "EXPLORATORY_NONCOMPLIANT",
    ),
    "docs/development/decisions/ADR-S2-013-current-governance-state.md": (
        "APPROVED — current-state authority and fail-closed operation gate",
        "configs/governance/current_development_state.json",
    ),
    "docs/development/special_research_points/SRP-S2-001.md": (
        "execution_status: BLOCKED_BY_OQ-S2-009_AND_OQ-S2-010",
        "evidence_class: `EXPLORATORY_NONCOMPLIANT`",
        "eligible_for_authority: false",
    ),
}

_CODE_MARKERS: dict[str, tuple[str, ...]] = {
    "scripts/run_stage2_conditional_baseline.py": (
        "require_operation_allowed",
        '"BUILD_AUDIT_SUPPLEMENT"',
        '"FREEZE_AUTHORITY"',
        '"FREEZE_BINS"',
        '"PREFLIGHT"',
        '"RUN"',
        '"RESUME"',
        '"VERIFY_EXISTING_EVIDENCE"',
    ),
    "src/era100x/research/stage_2/baselines/conditional/full_run.py": (
        'require_operation_allowed("FREEZE_AUTHORITY")',
        'require_operation_allowed("PREFLIGHT")',
    ),
    "src/era100x/research/stage_2/baselines/conditional/binning_run.py": (
        'require_operation_allowed("FREEZE_BINS")',
    ),
    "src/era100x/research/stage_2/baselines/conditional/successor_policy.py": (
        'require_operation_allowed("RUN")',
        'require_operation_allowed("RESUME")',
    ),
    "src/era100x/research/stage_2/baselines/conditional/receipt_supplement.py": (
        'require_operation_allowed("BUILD_AUDIT_SUPPLEMENT")',
    ),
    "src/era100x/research/stage_2/baselines/conditional/context_receipt_supplement.py": (
        'require_operation_allowed("BUILD_AUDIT_SUPPLEMENT")',
    ),
}


def _check_markers(path: Path, markers: tuple[str, ...]) -> list[str]:
    if path.is_symlink() or not path.is_file():
        return [f"missing or unsafe governance projection: {path.relative_to(ROOT)}"]
    content = path.read_text(encoding="utf-8")
    return [
        f"{path.relative_to(ROOT)} missing marker: {marker}"
        for marker in markers
        if marker not in content
    ]


def validate_current_governance_state() -> list[str]:
    errors: list[str] = []
    try:
        state = load_current_development_state()
    except (OSError, ValueError) as exc:
        return [str(exc)]

    for field, expected in _EXPECTED_STATE.items():
        actual = getattr(state, field)
        if actual != expected:
            errors.append(f"current state {field} drift: {actual!r} != {expected!r}")
    if set(state.allowed_operations) != _EXPECTED_ALLOWED:
        errors.append("current state allowed_operations drift")
    if set(state.blocked_operations) != _EXPECTED_BLOCKED:
        errors.append("current state blocked_operations drift")
    if set(state.blocking_questions) != _EXPECTED_QUESTIONS:
        errors.append("current state blocking_questions drift")
    if set(state.sealed_tasks) != _EXPECTED_SEALED_TASKS:
        errors.append("current state sealed_tasks drift")

    expected_records = set(_DOCUMENT_MARKERS)
    if set(state.source_records) != expected_records:
        errors.append("current state source_records drift from the governed document set")

    for relative, markers in _DOCUMENT_MARKERS.items():
        errors.extend(_check_markers(ROOT / relative, markers))
    for relative, markers in _CODE_MARKERS.items():
        errors.extend(_check_markers(ROOT / relative, markers))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true")
    parser.parse_args()
    errors = validate_current_governance_state()
    if errors:
        print("Governance state validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    state = load_current_development_state()
    print(
        "Governance state PASS: "
        f"{state.current_stage}/{state.current_task} {state.task_status}; "
        f"state_hash={state.state_hash}; Stage3 locked={state.stage3_locked}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
