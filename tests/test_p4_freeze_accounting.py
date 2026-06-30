from research_core.p4_canonical_freeze.p4_freeze_accounting import BASE_COST, long_net_pnl


def test_long_accounting_identity():
    row = long_net_pnl(1000.0, 100.0, 110.0, 1.0, BASE_COST, funding_paid=1.0, funding_received=0.5)
    expected = (
        row["gross_pnl"]
        + row["funding_received"]
        - row["funding_paid"]
        - row["entry_fee"]
        - row["exit_fee"]
        - row["liquidation_fee"]
    )
    assert abs(row["net_pnl"] - expected) < 1e-9
    assert abs(row["accounting_error"]) < 1e-9


def test_long_profit_positive_when_exit_above_entry_after_costs():
    row = long_net_pnl(1000.0, 100.0, 120.0, 1.0, BASE_COST)
    assert row["net_pnl"] > 0

