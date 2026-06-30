"""Rule and evidence audit helpers for P4 canonical freeze."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from research_core.common import current_git_commit, file_sha256, stable_hash
from research_core.leverage_research_analysis import FEE_RATE, INITIAL_BALANCE, SLIPPAGE_RATE
from research_core.run_long_history_10_symbol_review import END_UTC, START_UTC


PROTOTYPE = "P4_BREAKOUT_TOP20"
GATE = "P4_G1_GATE"
LEVERAGE_MODE = "fixed_1x"
CORE_SYMBOLS = ["BTCUSDT", "ETHUSDT"]


def canonical_config(source_commit: str | None = None) -> dict:
    return {
        "strategy_family": "time_series_trend_breakout",
        "prototype": PROTOTYPE,
        "symbols": CORE_SYMBOLS,
        "gate": GATE,
        "signal_timeframe": "15m",
        "execution_timeframe": "1m",
        "donchian_entry_window": 55,
        "donchian_exit_window": 20,
        "ema_fast": 50,
        "ema_slow": 200,
        "atr_window": 14,
        "atr_stop_multiple": 3.0,
        "entry_conditions": [
            "15m close > prior Donchian55 upper",
            "EMA50 > EMA200",
            "P4_BREAKOUT_TOP20 discovery threshold",
            "P4_G1_GATE fixed H3/H4 discovery thresholds",
        ],
        "exit_conditions": ["ATR stop", "15m close < prior Donchian20 lower"],
        "signal_timestamp_semantics": "15m candle close time; completed candle only",
        "execution_timestamp_semantics": "signal_time corresponding valid 1m open",
        "fee_model": {"entry_fee_rate": FEE_RATE, "exit_fee_rate": FEE_RATE},
        "slippage_model": {"entry_slippage_rate": SLIPPAGE_RATE, "exit_slippage_rate": SLIPPAGE_RATE},
        "funding_accounting": "audited separately; unavailable history downgrades realism",
        "position_sizing": "fixed notional 1x",
        "leverage_mode": LEVERAGE_MODE,
        "concurrent_position_policy": "one position per symbol",
        "capital_allocation": {"C1": "BTC 100%", "C2": "ETH 100%", "C3": "ETH 50%, BTC 50%"},
        "initial_balance": INITIAL_BALANCE,
        "data_start": str(START_UTC),
        "data_cutoff": str(END_UTC),
        "data_layer": "expanded_discovery",
        "oos_status": "not_oos",
        "source_commit": source_commit or current_git_commit(),
    }


def config_hash(config: dict) -> str:
    return stable_hash(config)


def candidate_registry() -> pd.DataFrame:
    rows = [
        ("C1", "BTCUSDT", PROTOTYPE, GATE, LEVERAGE_MODE, "BTC 100%", "final_candidate", "eligible_for_gate_check"),
        ("C2", "ETHUSDT", PROTOTYPE, GATE, LEVERAGE_MODE, "ETH 100%", "final_candidate", "eligible_for_gate_check"),
        ("C3", "ETHUSDT+BTCUSDT", PROTOTYPE, GATE, LEVERAGE_MODE, "ETH 50%; BTC 50%", "final_candidate", "eligible_for_gate_check"),
        ("D1", "BTCUSDT", PROTOTYPE, "P4_NO_GATE", LEVERAGE_MODE, "BTC 100%", "diagnostic_only", "not_selectable"),
        ("D2", "ETHUSDT", PROTOTYPE, "P4_NO_GATE", LEVERAGE_MODE, "ETH 100%", "diagnostic_only", "not_selectable"),
        ("D3", "ETHUSDT+BTCUSDT", PROTOTYPE, "P4_NO_GATE", LEVERAGE_MODE, "ETH 50%; BTC 50%", "diagnostic_only", "not_selectable"),
    ]
    return pd.DataFrame(rows, columns=[
        "candidate_id",
        "symbol_or_portfolio",
        "prototype",
        "gate",
        "leverage_mode",
        "capital_weight",
        "candidate_role",
        "selection_status",
    ])


def evidence_inventory(repo_root: Path) -> pd.DataFrame:
    items = [
        ("research_core/rb2_low_leverage_portfolio/rb2_backtest_summary.csv", "rb2_summary", "research_core.run_rb2_low_leverage_portfolio", "canonical_valid", ""),
        ("research_core/rb2_low_leverage_portfolio/rb2_portfolio_summary.csv", "rb2_portfolio", "research_core.run_rb2_low_leverage_portfolio", "canonical_valid", ""),
        ("research_core/realistic_replay_4_symbol/realistic_4_symbol_summary.csv", "rb1_realistic_summary", "research_core.run_realistic_replay_10_symbol", "valid_internal_discovery", "different leverage/prototype scope"),
        ("research_core/long_history_10_symbol_review/ten_symbol_long_history_summary.csv", "legacy_long_history", "research_core.run_long_history_10_symbol_review", "time_alignment_invalid", "left-labeled 15m result invalidated by RB1"),
        ("research_core/high_leverage_gate/gate_leverage_summary.csv", "h3_high_leverage", "research_core.run_high_leverage_gate", "not_applicable", "high leverage and gate research, not freeze candidate"),
        ("research_core/leverage_research_l2/leverage_l2_summary.csv", "l2_high_leverage", "research_core.run_conservative_leverage_research", "not_applicable", "leverage research superseded by low leverage RB2"),
    ]
    rows = []
    for path, kind, script, status, reason in items:
        full = repo_root / path
        rows.append({
            "artifact_path": path,
            "artifact_type": kind,
            "source_script": script,
            "source_commit_if_known": "",
            "data_start": "",
            "data_end": "",
            "symbol": "",
            "prototype": "",
            "gate": "",
            "leverage_mode": "",
            "time_alignment": "realistic_candle_close_time" if status != "time_alignment_invalid" else "left_labeled_15m_invalid",
            "data_layer": "expanded_discovery",
            "oos_status": "not_oos",
            "cost_model": "project_default" if full.exists() else "",
            "validity_status": status,
            "canonical_status": "candidate_evidence" if status == "canonical_valid" else "background",
            "exclusion_reason": reason if full.exists() else "artifact_missing",
            "exists": full.exists(),
            "sha256": file_sha256(full) if full.exists() else "",
        })
    return pd.DataFrame(rows)


def write_rule_snapshot(path: Path, config: dict) -> None:
    lines = [
        "# P4 Canonical Rule Snapshot",
        "",
        f"base_commit_sha: {config['source_commit']}",
        "data_layer: expanded_discovery",
        "oos_status: not_oos",
        "",
        "## Canonical P4 Long",
        "",
        "- Signal timeframe: 15m candle close time.",
        "- Execution: corresponding valid 1m open after signal confirmation.",
        "- Entry: 15m close above prior Donchian55 upper and EMA50 > EMA200.",
        "- Prototype: P4_BREAKOUT_TOP20 using fixed discovery metadata and thresholds.",
        "- Gate: P4_G1_GATE using fixed H3/H4 discovery thresholds.",
        "- Stop: entry_price - 3 * ATR14 known at signal time.",
        "- Exit: completed 15m close below prior Donchian20 lower, executed at valid 1m open.",
        "- Sizing: fixed_1x only for freeze candidates.",
        "",
        "## Time Alignment",
        "",
        "`1m timestamp = minute open`; `15m timestamp = completed candle close time`; Donchian windows use `shift(1)`.",
        "",
        "## Invalid Evidence",
        "",
        "Older left-labeled 15m outputs are marked `time_alignment_invalid` and cannot support freeze decisions.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
