from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from era100x.foundation.accounting import (
    final_realized_ticket_equity,
    proxy_long_pnl,
    realized_long_pnl,
    required_target_bps,
    target_exit_price,
)


D = Decimal


def test_appendix_f_proxy_fixed_example_deducts_scenario_once() -> None:
    entry, exit_, net = proxy_long_pnl(
        reference_entry=D("100"),
        reference_exit=D("110"),
        quantity=D("2"),
        entry_scenario_bps=D("10"),
        exit_scenario_bps=D("20"),
        entry_fee=D("0.20"),
        exit_fee=D("0.21"),
        funding=D("0.05"),
    )
    assert entry == D("100.100")
    assert exit_ == D("109.780")
    assert net == D("18.900")


def test_ut_pnl_015_realized_fill_prices_have_no_slippage_input_or_double_charge() -> None:
    result = realized_long_pnl(
        entry_fills=[(D("101"), D("2"))],
        exit_fills=[(D("109"), D("2"))],
        actual_commission=D("0.50"),
        actual_funding=D("0.25"),
    )
    assert result == D("15.25")


@given(st.integers(min_value=1, max_value=999), st.integers(min_value=1, max_value=999))
def test_required_target_is_non_decreasing_as_notional_decreases(a: int, b: int) -> None:
    larger, smaller = D(max(a, b)), D(min(a, b))
    common = dict(remaining_net_profit_target=D("1"), estimated_remaining_cost=D("0.1"))
    assert required_target_bps(actual_position_notional=smaller, **common) >= required_target_bps(
        actual_position_notional=larger, **common
    )


def test_target_exit_price_formula_and_failure_boundaries() -> None:
    assert target_exit_price(
        remaining_net_profit=D("10"),
        quantity=D("2"),
        entry_price=D("100"),
        entry_fee_rate=D("0.001"),
        exit_fee_rate=D("0.001"),
        funding=D("1"),
    ) == D("211.2") / D("1.998")
    with pytest.raises(TypeError):
        required_target_bps(
            remaining_net_profit_target=1.0,  # type: ignore[arg-type]
            estimated_remaining_cost=D("0"),
            actual_position_notional=D("1"),
        )
    with pytest.raises(ValueError):
        target_exit_price(
            remaining_net_profit=D("1"),
            quantity=D("1"),
            entry_price=D("1"),
            entry_fee_rate=D("0"),
            exit_fee_rate=D("1"),
            funding=D("0"),
        )


def test_final_equity_requires_final_flat_and_cleanup() -> None:
    with pytest.raises(ValueError):
        final_realized_ticket_equity(
            starting_ticket_equity=D("10"),
            cumulative_realized_net_pnl=D("10"),
            position_flat=True,
            cleanup_complete=False,
            external_cash_flow_since_round_start=D("0"),
        )
    assert final_realized_ticket_equity(
        starting_ticket_equity=D("10"),
        cumulative_realized_net_pnl=D("10"),
        position_flat=True,
        cleanup_complete=True,
        external_cash_flow_since_round_start=D("0"),
    ) == D("20")
