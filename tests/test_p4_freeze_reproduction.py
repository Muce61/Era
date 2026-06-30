import pandas as pd

from research_core.p4_canonical_freeze.p4_freeze_replay import compare_trades_to_rb2


def test_reproduction_missing_reference_is_explicit():
    trades = pd.DataFrame({"entry_time": [], "exit_time": []})
    row = compare_trades_to_rb2(trades, None)
    assert row["reproduction_status"] == "no_rb2_reference"

