from __future__ import annotations

import json
from pathlib import Path

import pytest

from era100x.foundation.governance import (
    DEFAULT_CURRENT_STATE_PATH,
    GovernanceBlockedError,
    canonical_state_hash,
    load_current_development_state,
    require_operation_allowed,
)


def test_repository_current_state_is_plan_v110_prepare_gated_and_hash_valid() -> None:
    state = load_current_development_state()

    assert state.schema_version == "1.3"
    assert state.current_stage == "S2"
    assert state.current_plan == "stage_2_plan_v1.10"
    assert state.current_task == "S2P110-T11"
    assert state.current_task_version == "1.1"
    assert (
        state.task_status == "ZERO_TRADE_CONTRACT_PRICE_PROXY_IMPLEMENTED_VALIDATED_PREPARE_GATED"
    )
    assert state.stage_status == "IN_PROGRESS"
    assert state.research_decision == "STAGE2_NO_GO_CURRENT_EVIDENCE"
    assert state.current_policy_path == "configs/governance/stage2_active_policy_v9.json"
    assert state.formal_successor_result_exists is True
    assert state.stage3_locked is True
    assert state.srp_execution_status == "SOLO_RUNTIME_PREPARE_ALLOWED_FORMAL_RUN_FORBIDDEN"
    assert state.approved_execution_limit == "S2P110-T20"
    assert state.formal_run_receipt_required is False
    assert state.blocking_questions == (
        "FORMAL_RUN_REQUIRES_PREPARE_INPUTS_LOCK_AND_COMMIT_INPUT_LOCK_BOUND_APPROVAL",
    )
    assert "S2-T15" in state.sealed_tasks
    assert len(state.historical_task_states) == 1
    historical = state.historical_task_states[0]
    assert historical.stage_plan_version == "1.2"
    assert historical.task_id == "S2-T15"
    assert historical.task_version == "1.4"
    assert historical.terminal_status == "STOPPED_FAILED_UNPUBLISHED"
    assert historical.formal_result_exists is False
    assert historical.evidence_disposition == "IMMUTABLE_HISTORICAL_ONLY"
    assert historical.successor_stage_plan_version == "1.3"
    assert historical.successor_task_id == "S2P13-T16"
    assert historical.successor_relationship == "CAPABILITY_REPLACEMENT_NOT_RESULT_PROMOTION"
    assert historical.authority_scope == "HISTORICAL_ONLY_NO_EXECUTION_AUTHORITY"
    assert state.state_hash == state.computed_hash()


@pytest.mark.parametrize(
    "operation",
    [
        "READ_ONLY_AUDIT",
        "VERIFY_EXISTING_EVIDENCE",
        "READ_ONLY_UI",
        "PREPARE_REAL_INPUTS_LOCK",
    ],
)
def test_current_state_allows_only_scoped_audit_operations(operation: str) -> None:
    state = require_operation_allowed(operation)
    assert operation in state.allowed_operations


@pytest.mark.parametrize(
    "operation",
    [
        "BUILD_AUDIT_SUPPLEMENT",
        "BUILD_FUNDING_AUDIT_SUPPLEMENT",
        "RUN_SEVEN_DAY_REHEARSAL",
        "FREEZE_AUTHORITY",
        "FREEZE_BINS",
        "PREFLIGHT",
        "RUN",
        "RESUME",
        "PUBLISH",
    ],
)
def test_current_state_blocks_every_write_or_run_operation(operation: str) -> None:
    with pytest.raises(GovernanceBlockedError) as error:
        require_operation_allowed(operation)

    assert error.value.reason_code == "GOVERNANCE_OPERATION_NOT_AUTHORIZED"
    assert error.value.operation == operation
    assert error.value.blocking_questions == (
        "FORMAL_RUN_REQUIRES_PREPARE_INPUTS_LOCK_AND_COMMIT_INPUT_LOCK_BOUND_APPROVAL",
    )


def test_state_hash_drift_fails_closed(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_CURRENT_STATE_PATH.read_text(encoding="utf-8"))
    payload["task_status"] = "IN_PROGRESS"
    path = tmp_path / "state.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="state hash mismatch"):
        load_current_development_state(path)


def test_resealed_state_can_be_loaded_but_does_not_change_repository_authority(
    tmp_path: Path,
) -> None:
    payload = json.loads(DEFAULT_CURRENT_STATE_PATH.read_text(encoding="utf-8"))
    payload["task_status"] = "IN_PROGRESS"
    payload["state_hash"] = canonical_state_hash(payload)
    path = tmp_path / "state.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    state = load_current_development_state(path)
    assert state.task_status == "IN_PROGRESS"
    assert (
        load_current_development_state().task_status
        == "ZERO_TRADE_CONTRACT_PRICE_PROXY_IMPLEMENTED_VALIDATED_PREPARE_GATED"
    )


def test_schema_v12_remains_hash_compatible_without_lineage(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_CURRENT_STATE_PATH.read_text(encoding="utf-8"))
    payload["schema_version"] = "1.2"
    payload.pop("historical_task_states")
    payload["state_hash"] = canonical_state_hash(payload)
    expected_hash = payload["state_hash"]
    path = tmp_path / "state-v1.2.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    state = load_current_development_state(path)

    assert state.schema_version == "1.2"
    assert state.historical_task_states == ()
    assert state.state_hash == expected_hash
    assert state.computed_hash() == expected_hash
    assert "historical_task_states" not in state.to_payload()


def test_duplicate_historical_task_identity_fails_closed(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_CURRENT_STATE_PATH.read_text(encoding="utf-8"))
    payload["historical_task_states"].append(payload["historical_task_states"][0].copy())
    payload["state_hash"] = canonical_state_hash(payload)
    path = tmp_path / "duplicate-lineage.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate historical Task identity"):
        load_current_development_state(path)


def test_historical_predecessor_and_successor_must_be_sealed(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_CURRENT_STATE_PATH.read_text(encoding="utf-8"))
    payload["sealed_tasks"].remove("S2-T15")
    payload["state_hash"] = canonical_state_hash(payload)
    path = tmp_path / "unsealed-predecessor.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="historical predecessor is not sealed"):
        load_current_development_state(path)


def test_historical_task_cannot_succeed_itself(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_CURRENT_STATE_PATH.read_text(encoding="utf-8"))
    lineage = payload["historical_task_states"][0]
    lineage["successor_stage_plan_version"] = lineage["stage_plan_version"]
    lineage["successor_task_id"] = lineage["task_id"]
    payload["state_hash"] = canonical_state_hash(payload)
    path = tmp_path / "self-successor.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="historical Task cannot succeed itself"):
        load_current_development_state(path)


def test_unknown_operation_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown governance operation"):
        require_operation_allowed("FORCE_RUN")
