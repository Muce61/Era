import pandas as pd

from research_core.p4_canonical_freeze.p4_freeze_candidate_selection import evaluate_candidate_gates, selection_decision


def _row(candidate_id, pf=1.2, dd=-0.1, ret=0.2):
    return {
        "candidate_id": candidate_id,
        "base_cost_profit_factor": pf,
        "base_cost_total_return": ret,
        "base_cost_max_drawdown": dd,
        "liquidation_count": 0,
        "top1_profit_contribution": 0.1,
        "remove_top3_return": 0.1,
        "positive_valid_year_rate": 0.7,
        "positive_walk_forward_window_rate": 0.7,
        "pf_gt_1_walk_forward_window_rate": 0.7,
        "block_bootstrap_positive_probability": 0.7,
        "instrument_status": "funding_incomplete",
        "reproduction_status": "matched",
        "longest_drawdown_seconds": 10.0,
        "single_asset_worst_longest_drawdown_seconds": 20.0,
    }


def test_no_candidate_passes_freezes_zero():
    gates = evaluate_candidate_gates(pd.DataFrame([_row("C1", pf=1.0)]))
    decision = selection_decision(gates)
    assert decision["frozen_candidate_count"] == 0
    assert decision["shadow_decision"] == "B. not_eligible_for_future_shadow"


def test_passing_candidate_can_be_frozen():
    gates = evaluate_candidate_gates(pd.DataFrame([_row("C1")]))
    decision = selection_decision(gates)
    assert decision["frozen_candidate_count"] == 1
    assert decision["selected_candidate_id"] == "C1"

