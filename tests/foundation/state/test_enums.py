import pytest

from era100x.foundation.state import CoreState, ExitDecision, ReasonCode, ReconcilePhase


def test_core_state_set_is_exact() -> None:
    assert len(CoreState) == 15
    assert "CLOSED" not in CoreState.__members__
    assert "EXPANDING" not in CoreState.__members__
    assert "EXIT_REVIEW" not in CoreState.__members__


def test_three_closure_phases_are_distinct() -> None:
    assert ReconcilePhase.RESIDUAL_ORDER_CLEANUP != ReconcilePhase.FINAL_FLAT_CONFIRMATION


def test_exit_decision_is_pure_output_vocabulary() -> None:
    assert {item.value for item in ExitDecision} == {
        "HOLD", "EXIT_TARGET", "EXIT_PROTECTION", "EXIT_TIME", "EXIT_STRUCTURE", "EXIT_EMERGENCY"
    }


def test_reason_codes_are_unique_and_complete() -> None:
    assert len(ReasonCode) == len({item.value for item in ReasonCode})
    assert len(ReasonCode) >= 50
    assert ReasonCode.DATA_CONTRACT_INCOMPLETE.value == "DATA_CONTRACT_INCOMPLETE"


@pytest.mark.parametrize("deprecated", ["CLOSED", "EXPANDING", "EXIT_REVIEW"])
def test_deprecated_states_cannot_be_constructed(deprecated: str) -> None:
    with pytest.raises(ValueError):
        CoreState(deprecated)
