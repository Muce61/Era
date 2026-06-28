"""Minimal-backtest gate for second-alpha candidates.

This module intentionally does not implement a strategy yet. The project
requires candidate event evidence before any deployable-style backtest is
allowed.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class MinimalBacktestGate:
    status: str = "blocked_event_research_first"
    data_layer: str = "expanded_discovery"
    oos_status: str = "not_oos"
    deployable_strategy_generated: bool = False
    reason: str = "minimal strategy backtest is only allowed after event study shows robust edge"


def minimal_backtest_blocked_reason() -> dict:
    gate = MinimalBacktestGate()
    return {
        "status": gate.status,
        "data_layer": gate.data_layer,
        "oos_status": gate.oos_status,
        "deployable_strategy_generated": gate.deployable_strategy_generated,
        "reason": gate.reason,
    }


def write_blocked_summary(path: str) -> None:
    pd.DataFrame([minimal_backtest_blocked_reason()]).to_csv(path, index=False)
