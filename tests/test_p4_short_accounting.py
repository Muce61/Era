from research_core.p4_short_research.p4_short_accounting import short_gross_pnl, short_net_pnl, short_quantity


def test_short_pnl_positive_when_exit_below_entry():
    qty = short_quantity(1000, 100)
    assert qty == 10
    assert short_gross_pnl(qty, 100, 90) == 100
    assert short_gross_pnl(qty, 100, 110) == -100


def test_short_accounting_identity():
    out = short_net_pnl(
        quantity=10,
        entry_price=100,
        exit_price=90,
        fee_rate=0.001,
        slippage_cost=2,
        funding_paid=3,
        funding_received=4,
        liquidation_fee=5,
    )
    expected = 100 + 4 - 3 - 1 - 0.9 - 2 - 5
    assert abs(out["net_pnl"] - expected) < 1e-9
    assert abs(out["accounting_error"]) < 1e-12

