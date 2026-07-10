from decimal import Decimal
from pathlib import Path

import pytest

from era100x.domain.enums import PositionState, StateEvent
from era100x.domain.models import ProtectionStep, load_app_config
from era100x.domain.state_machine import InvalidStateTransition, transition
from era100x.research.labels import BarrierOutcome, label_competing_barriers
from era100x.risk.sizing import calculate_contract_quantity, estimate_round_trip_cost_roe_pct
from era100x.risk.trailing_stop import next_protection_lock


def test_research_config_is_valid() -> None:
    root = Path(__file__).resolve().parents[2]
    config = load_app_config(root / "configs/research.yaml")
    assert config.risk.isolated_margin_only is True
    assert config.risk.max_concurrent_positions == 1
    assert config.risk.leverage == 100


def test_contract_quantity_and_cost() -> None:
    result = calculate_contract_quantity(available_margin_usdt=Decimal("10"), max_margin_usdt=Decimal("8"), leverage=100, price_usdt=Decimal("4000"), contract_multiplier_base=Decimal("0.001"), quantity_step=Decimal("1"), minimum_quantity=Decimal("1"))
    assert result.quantity_contracts == Decimal("200")
    cost = estimate_round_trip_cost_roe_pct(leverage=100, entry_fee_rate=Decimal("0.0005"), exit_fee_rate=Decimal("0.0005"), entry_slippage_bps=Decimal("1"), exit_slippage_bps=Decimal("1.5"))
    assert cost == Decimal("12.50000")


def test_protection_never_moves_backward() -> None:
    ladder = (
        ProtectionStep(mfe_net_roe_pct=Decimal("20"), lock_net_roe_pct=Decimal("0")),
        ProtectionStep(mfe_net_roe_pct=Decimal("50"), lock_net_roe_pct=Decimal("35")),
        ProtectionStep(mfe_net_roe_pct=Decimal("70"), lock_net_roe_pct=Decimal("50")),
    )
    raised = next_protection_lock(mfe_net_roe_pct=Decimal("72"), previous_lock_net_roe_pct=Decimal("35"), ladder=ladder)
    pullback = next_protection_lock(mfe_net_roe_pct=Decimal("30"), previous_lock_net_roe_pct=raised.new_lock_net_roe_pct, ladder=ladder)
    assert pullback.new_lock_net_roe_pct == Decimal("50")


def test_barrier_tie_is_ambiguous() -> None:
    label = label_competing_barriers(high_net_roe_pct=[Decimal("55")], low_net_roe_pct=[Decimal("-25")], target_net_roe_pct=Decimal("50"), stop_net_roe_pct=Decimal("-20"))
    assert label.outcome is BarrierOutcome.AMBIGUOUS


def test_state_machine_enforces_order_and_safety() -> None:
    state = transition(PositionState.IDLE, StateEvent.CONTEXT_ALLOWED)
    assert state is PositionState.CONTEXT_OK
    assert transition(PositionState.ENTRY_PENDING, StateEvent.SAFETY_FAILURE) is PositionState.EMERGENCY_EXIT
    with pytest.raises(InvalidStateTransition):
        transition(PositionState.IDLE, StateEvent.ENTRY_FILLED)
