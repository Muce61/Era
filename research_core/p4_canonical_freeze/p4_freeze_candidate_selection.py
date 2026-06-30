"""Deterministic candidate gate rules for P4 canonical freeze."""

from __future__ import annotations

import math

import pandas as pd


SINGLE_ASSET_GATES = {
    "base_cost_profit_factor": lambda r: r.get("base_cost_profit_factor", math.nan) >= 1.15,
    "base_cost_total_return": lambda r: r.get("base_cost_total_return", math.nan) > 0,
    "max_drawdown": lambda r: r.get("base_cost_max_drawdown", math.nan) >= -0.25,
    "liquidation_count": lambda r: r.get("liquidation_count", math.nan) == 0,
    "top1_profit_contribution": lambda r: r.get("top1_profit_contribution", math.nan) <= 0.30,
    "remove_top3_return": lambda r: r.get("remove_top3_return", math.nan) > 0,
    "positive_valid_year_rate": lambda r: r.get("positive_valid_year_rate", math.nan) >= 0.60,
    "positive_walk_forward_window_rate": lambda r: r.get("positive_walk_forward_window_rate", math.nan) >= 0.60,
    "pf_gt_1_walk_forward_window_rate": lambda r: r.get("pf_gt_1_walk_forward_window_rate", math.nan) >= 0.60,
    "block_bootstrap_positive_probability": lambda r: r.get("block_bootstrap_positive_probability", math.nan) >= 0.60,
    "instrument_status": lambda r: r.get("instrument_status") != "unknown",
    "reproduction_status": lambda r: r.get("reproduction_status") in {"matched", "no_rb2_reference"},
}

PORTFOLIO_GATES = {
    "base_cost_total_return": lambda r: r.get("base_cost_total_return", math.nan) > 0,
    "portfolio_max_drawdown": lambda r: r.get("base_cost_max_drawdown", math.nan) >= -0.20,
    "portfolio_profit_factor": lambda r: r.get("base_cost_profit_factor", math.nan) >= 1.15,
    "longest_drawdown_duration": lambda r: r.get("longest_drawdown_seconds", math.inf) < r.get("single_asset_worst_longest_drawdown_seconds", math.inf),
    "positive_walk_forward_window_rate": lambda r: r.get("positive_walk_forward_window_rate", math.nan) >= 0.60,
    "remove_top3_return": lambda r: r.get("remove_top3_return", math.nan) > 0,
    "liquidation_count": lambda r: r.get("liquidation_count", math.nan) == 0,
    "reproduction_status": lambda r: r.get("reproduction_status") in {"matched", "no_rb2_reference"},
}


def evaluate_candidate_gates(metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in metrics.iterrows():
        data = row.to_dict()
        gates = PORTFOLIO_GATES if data.get("candidate_id") == "C3" else SINGLE_ASSET_GATES
        gate_results = {name: bool(check(data)) for name, check in gates.items()}
        hard_pass = all(gate_results.values())
        failed = [name for name, ok in gate_results.items() if not ok]
        rows.append({
            "candidate_id": data.get("candidate_id"),
            **{f"gate_{k}": v for k, v in gate_results.items()},
            "hard_gate_pass": hard_pass,
            "selection_rank": None,
            "freeze_decision": "eligible" if hard_pass else "rejected",
            "rejection_reason": "" if hard_pass else ";".join(failed),
        })
    out = pd.DataFrame(rows)
    passed = out[out["hard_gate_pass"]].copy()
    if passed.empty:
        out["selection_rank"] = ""
        out.loc[:, "freeze_decision"] = "freeze_0_candidates"
        return out
    rank_order = {"C3": 0, "C1": 1, "C2": 2}
    passed["rank_key"] = passed["candidate_id"].map(rank_order).fillna(99)
    selected = passed.sort_values(["rank_key", "candidate_id"]).iloc[0]["candidate_id"]
    out["selection_rank"] = out["candidate_id"].map(lambda x: 1 if x == selected else "")
    out["freeze_decision"] = out.apply(
        lambda r: "frozen_candidate" if r["candidate_id"] == selected else ("eligible_not_selected" if r["hard_gate_pass"] else "rejected"),
        axis=1,
    )
    return out


def selection_decision(gates: pd.DataFrame) -> dict:
    frozen = gates[gates["freeze_decision"] == "frozen_candidate"]
    if len(frozen) == 1:
        return {
            "freeze_decision": "A. one_candidate_frozen_for_future_shadow",
            "selected_candidate_id": frozen.iloc[0]["candidate_id"],
            "frozen_candidate_count": 1,
            "shadow_decision": "A. eligible_for_future_shadow",
        }
    return {
        "freeze_decision": "D. no_candidate_passed_freeze_gates",
        "selected_candidate_id": "",
        "frozen_candidate_count": 0,
        "shadow_decision": "B. not_eligible_for_future_shadow",
    }

