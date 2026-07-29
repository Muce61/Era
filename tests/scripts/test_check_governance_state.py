from __future__ import annotations

import json
from pathlib import Path

from era100x.foundation.governance import (
    DEFAULT_CURRENT_STATE_PATH,
    canonical_state_hash,
)
from scripts.check_governance_state import (
    _validate_current_state,
    _validate_projections,
    validate_current_governance_state,
)


def test_repository_governance_policies_and_projections_are_consistent() -> None:
    errors, policies = validate_current_governance_state()

    assert errors == []
    assert set(policies) == {2, 3, 4, 5, 6, 8}
    assert policies[6].payload["execution_limit"] == "S2P17-T20"
    assert policies[8].payload["execution_limit"] == "S2P19-T20"
    assert policies[6].payload["stage3_locked"] is True


def test_stale_stage_registry_projection_fails_strict_check(tmp_path: Path) -> None:
    current_stage = tmp_path / "CURRENT_STAGE.md"
    registry = tmp_path / "STAGE_REGISTRY.md"
    current_stage.write_text(
        "\n".join(
            (
                "Current Stage: Stage 2",
                "Current Plan: stage_2_plan_v1.9 — SOLO RUNTIME IMPLEMENTED",
                (
                    "Current Task: S2P19-T11 v1.0 — production input builder validation "
                    "and prepare pending"
                ),
                "STAGE2_NO_GO_CURRENT_EVIDENCE",
                "T21 was not executed",
                "Stage 3 remains locked",
            )
        ),
        encoding="utf-8",
    )
    registry.write_text(
        "| Stage 2 | 1.3 | REVIEW | stale | NONE | PRIMARY_PENDING | "
        "S2P13-T17～T21 were not executed |\n",
        encoding="utf-8",
    )
    errors: list[str] = []

    _validate_projections(
        errors,
        current_stage_path=current_stage,
        stage_registry_path=registry,
    )

    assert "Stage Registry retains the superseded Plan v1.3 current-state projection" in errors


def test_machine_state_cannot_unlock_stage3(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_CURRENT_STATE_PATH.read_text(encoding="utf-8"))
    payload["stage3_locked"] = False
    payload["state_hash"] = canonical_state_hash(payload)
    state_path = tmp_path / "current-state.json"
    state_path.write_text(json.dumps(payload), encoding="utf-8")
    errors: list[str] = []

    _validate_current_state(errors, state_path=state_path)

    assert "current machine governance must keep Stage 3 locked" in errors


def test_machine_state_rejects_wrong_historical_successor(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_CURRENT_STATE_PATH.read_text(encoding="utf-8"))
    payload["historical_task_states"][0]["successor_stage_plan_version"] = "1.4"
    payload["historical_task_states"][0]["successor_task_id"] = "S2P14-T17"
    payload["state_hash"] = canonical_state_hash(payload)
    state_path = tmp_path / "wrong-successor.json"
    state_path.write_text(json.dumps(payload), encoding="utf-8")
    errors: list[str] = []

    _validate_current_state(errors, state_path=state_path)

    assert "historical S2-T15 terminal lineage drift" in errors


def test_machine_state_rejects_legacy_s2_t15_pass_promotion(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_CURRENT_STATE_PATH.read_text(encoding="utf-8"))
    payload["historical_task_states"][0]["terminal_status"] = "PASS"
    payload["historical_task_states"][0]["formal_result_exists"] = True
    payload["state_hash"] = canonical_state_hash(payload)
    state_path = tmp_path / "promoted-predecessor.json"
    state_path.write_text(json.dumps(payload), encoding="utf-8")
    errors: list[str] = []

    _validate_current_state(errors, state_path=state_path)

    assert "historical S2-T15 terminal lineage drift" in errors
