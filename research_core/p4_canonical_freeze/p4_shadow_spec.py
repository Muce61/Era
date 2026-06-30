"""Future shadow validation specification writer."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from research_core.common import stable_hash


def shadow_start_time(data_cutoff: str, freeze_timestamp: str | None = None) -> str:
    freeze = pd.Timestamp(freeze_timestamp or datetime.now(timezone.utc).isoformat()).tz_convert("UTC")
    cutoff = pd.Timestamp(data_cutoff).tz_convert("UTC")
    start = max(freeze, cutoff).ceil("D")
    return start.isoformat()


def build_shadow_spec(config: dict, selected_candidate_id: str, eligible: bool, data_cutoff: str) -> dict:
    if not eligible:
        return {
            "shadow_status": "not_eligible",
            "candidate_id": "",
            "reason": "no_candidate_passed_freeze_gates",
            "deployable_strategy_generated": False,
            "oos_status": "not_oos",
        }
    freeze_ts = datetime.now(timezone.utc).isoformat()
    candidate_symbols = {
        "C1": ["BTCUSDT"],
        "C2": ["ETHUSDT"],
        "C3": ["ETHUSDT", "BTCUSDT"],
    }.get(selected_candidate_id, config.get("symbols"))
    candidate_allocation = {
        "C1": {"BTCUSDT": "100%"},
        "C2": {"ETHUSDT": "100%"},
        "C3": {"ETHUSDT": "50%", "BTCUSDT": "50%"},
    }.get(selected_candidate_id, config.get("capital_allocation"))
    return {
        "shadow_status": "eligible_for_future_shadow",
        "candidate_id": selected_candidate_id,
        "strategy_rules": config,
        "symbols": candidate_symbols,
        "gate": config.get("gate"),
        "leverage": config.get("leverage_mode"),
        "capital_allocation": candidate_allocation,
        "fee_model": config.get("fee_model"),
        "slippage_model": config.get("slippage_model"),
        "funding_model": config.get("funding_accounting"),
        "data_cutoff": data_cutoff,
        "freeze_timestamp": freeze_ts,
        "freeze_source_commit": config.get("source_commit"),
        "shadow_start_time": shadow_start_time(data_cutoff, freeze_ts),
        "minimum_shadow_duration": "6 months",
        "minimum_completed_trades": 30,
        "no_change_policy": "no parameter, symbol, gate, cost, or allocation changes during shadow",
        "invalidating_conditions": [
            "rule change after freeze",
            "accounting identity failure",
            "execution completeness failure",
            "data rewrite without audit",
        ],
        "promotion_criteria": [
            "net_return > 0",
            "profit_factor > 1",
            "no_liquidation",
            "accounting_identity_pass",
            "execution_completeness_pass",
            "cost_model_not_underestimated",
            "no_rule_changes_since_freeze",
        ],
        "deployable_strategy_generated": False,
        "oos_status": "not_oos",
    }


def shadow_hash(spec: dict) -> str:
    return stable_hash(spec)
