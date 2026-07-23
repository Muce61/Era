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


def test_repository_current_state_is_stopped_and_hash_valid() -> None:
    state = load_current_development_state()

    assert state.current_stage == "S2"
    assert state.current_task == "S2-T15"
    assert state.current_task_version == "1.4"
    assert state.task_status == "STOPPED"
    assert state.formal_t15_result_exists is False
    assert state.stage3_locked is True
    assert state.srp_execution_status == "NOT_EXECUTABLE"
    assert state.state_hash == state.computed_hash()


@pytest.mark.parametrize(
    "operation",
    ["READ_ONLY_AUDIT", "VERIFY_EXISTING_EVIDENCE", "READ_ONLY_UI"],
)
def test_current_state_allows_only_read_only_operations(operation: str) -> None:
    state = require_operation_allowed(operation)
    assert operation in state.allowed_operations


@pytest.mark.parametrize(
    "operation",
    [
        "BUILD_AUDIT_SUPPLEMENT",
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

    assert error.value.reason_code == "GOVERNANCE_CURRENT_TASK_STOPPED"
    assert error.value.operation == operation
    assert error.value.blocking_questions == ("OQ-S2-009", "OQ-S2-010", "OQ-S2-011")


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
    assert load_current_development_state().task_status == "STOPPED"


def test_unknown_operation_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown governance operation"):
        require_operation_allowed("FORCE_RUN")
