"""Canonical P4 Long rule snapshot for short mirror research."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def write_p4_long_rule_snapshot(path: Path, base_commit_sha: str) -> None:
    lines = [
        "# P4 Long Rule Snapshot",
        "",
        f"base_commit_sha: `{base_commit_sha}`",
        "",
        "canonical_p4_source_files:",
        "- `research_core/event_table.py`",
        "- `research_core/run_rb2_low_leverage_portfolio.py`",
        "- `research_core/strict_high_leverage_replay.py`",
        "",
        "signal_timeframe: 15m candle close time",
        "execution_timeframe: 1m open at signal completion time",
        "",
        "entry_conditions:",
        "- `close > donchian55_upper`, where Donchian uses `high.shift(1).rolling(55).max()`",
        "- `EMA50 > EMA200`",
        "- `ATR14` is valid",
        "",
        "score_or_gate_conditions:",
        "- P4 Long core does not require G1.",
        "- RB2 compares `P4_NO_GATE` and `P4_G1_GATE` as later gate research.",
        "",
        "exit_conditions:",
        "- Donchian20 exit confirms when 15m `close < donchian20_lower`.",
        "- Exit is executed at the confirmed candle close-time 1m open, not the 15m close.",
        "",
        "stop_conditions:",
        "- Long stop is `entry_price - 3 * ATR14`.",
        "",
        "fee_model: project default `FEE_RATE = 0.0005`",
        "slippage_model: project default `SLIPPAGE_RATE = 0.0002`",
        "position_sizing: RB2 tests low leverage; P4 Short mirror first version is fixed 1x only.",
        "leverage_mode: no high leverage in P4 Short mirror V1.",
        "",
        "time_alignment:",
        "- 1m timestamp is the minute open.",
        "- 15m candle timestamp is the candle completion time.",
        "- Signals are only tradable after 15m completion.",
        "",
        "canonical_valid_outputs:",
        "- RB1 realistic replay outputs.",
        "- RB2 low leverage P4-only outputs.",
        "",
        "invalid_legacy_outputs:",
        "- Old left-labeled 15m long-history outputs are `time_alignment_invalid`.",
        "",
        "oos_status: not_oos",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_mirror_mapping(path: Path) -> None:
    rows = [
        {"long_rule": "close > previous Donchian55 upper", "short_rule": "close < previous Donchian55 lower", "mirror_type": "comparison_and_band", "parameter_changed": False, "reason": "mechanical downside breakout mirror"},
        {"long_rule": "EMA50 > EMA200", "short_rule": "EMA50 < EMA200", "mirror_type": "comparison", "parameter_changed": False, "reason": "mechanical bearish trend mirror"},
        {"long_rule": "Donchian20 exit: close < previous lower", "short_rule": "Donchian20 exit: close > previous upper", "mirror_type": "comparison_and_band", "parameter_changed": False, "reason": "mechanical trend invalidation mirror"},
        {"long_rule": "ATR stop: entry - 3*ATR", "short_rule": "ATR stop: entry + 3*ATR", "mirror_type": "direction", "parameter_changed": False, "reason": "same stop distance opposite direction"},
        {"long_rule": "next valid 1m open after 15m signal completion", "short_rule": "next valid 1m open after 15m signal completion", "mirror_type": "execution", "parameter_changed": False, "reason": "same realistic execution timing"},
    ]
    pd.DataFrame(rows).to_csv(path, index=False)

