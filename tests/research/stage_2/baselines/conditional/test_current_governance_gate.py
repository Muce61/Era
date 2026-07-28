from __future__ import annotations

from pathlib import Path

import pytest

from era100x.foundation.governance import (
    GovernanceBlockedError,
    require_operation_allowed,
)
from era100x.research.stage_2.baselines.conditional.binning_run import (
    freeze_binning_snapshots,
)
from era100x.research.stage_2.baselines.conditional.full_run import freeze_authority, preflight
from era100x.research.stage_2.baselines.conditional.successor_policy import (
    require_final_successor_creation_state,
    require_final_successor_resume_state,
)


def _assert_blocked(error: pytest.ExceptionInfo[GovernanceBlockedError], operation: str) -> None:
    assert error.value.reason_code == "GOVERNANCE_OPERATION_NOT_AUTHORIZED"
    assert error.value.operation == operation
    assert error.value.blocking_questions == (
        "FORMAL_RUN_REQUIRES_CLEAN_COMMIT_AND_SEPARATE_COMMIT_BOUND_HUMAN_APPROVAL",
    )


def test_direct_authority_freeze_is_blocked_before_reading_an_audit() -> None:
    with pytest.raises(GovernanceBlockedError) as error:
        freeze_authority(audit_path=Path("does-not-exist.json"))
    _assert_blocked(error, "FREEZE_AUTHORITY")


def test_direct_preflight_is_blocked_before_reading_inputs() -> None:
    with pytest.raises(GovernanceBlockedError) as error:
        preflight(
            authority_path=Path("does-not-exist-authority.json"),
            binning_set_path=Path("does-not-exist-bins.json"),
        )
    _assert_blocked(error, "PREFLIGHT")


def test_direct_bin_freeze_is_blocked_before_reading_inputs() -> None:
    with pytest.raises(GovernanceBlockedError) as error:
        freeze_binning_snapshots(
            authority_path=Path("does-not-exist-authority.json"),
            bin_root=Path("does-not-exist-bin-root"),
            t10_snapshot=Path("does-not-exist-t10"),
            t10_snapshot_id="missing",
            current_commit="0" * 40,
            repository_clean=True,
        )
    _assert_blocked(error, "FREEZE_BINS")


def test_direct_receiver_supplement_build_is_now_authorized() -> None:
    state = require_operation_allowed("BUILD_AUDIT_SUPPLEMENT")
    assert "BUILD_AUDIT_SUPPLEMENT" in state.allowed_operations


def test_direct_context_supplement_build_is_now_authorized() -> None:
    state = require_operation_allowed("BUILD_AUDIT_SUPPLEMENT")
    assert "BUILD_AUDIT_SUPPLEMENT" in state.allowed_operations


def test_direct_new_run_is_blocked_before_inspecting_run_directories(tmp_path: Path) -> None:
    with pytest.raises(GovernanceBlockedError) as error:
        require_final_successor_creation_state(tmp_path)
    _assert_blocked(error, "RUN")


def test_direct_resume_is_blocked_before_inspecting_run_directories(tmp_path: Path) -> None:
    with pytest.raises(GovernanceBlockedError) as error:
        require_final_successor_resume_state(tmp_path, "stage2-s2t15-conditional-fake")
    _assert_blocked(error, "RESUME")
