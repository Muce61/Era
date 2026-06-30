# P4 Long Rule Snapshot

base_commit_sha: `e56054f0f074920e54e742a1050b1bcb29ec2543`

canonical_p4_source_files:
- `research_core/event_table.py`
- `research_core/run_rb2_low_leverage_portfolio.py`
- `research_core/strict_high_leverage_replay.py`

signal_timeframe: 15m candle close time
execution_timeframe: 1m open at signal completion time

entry_conditions:
- `close > donchian55_upper`, where Donchian uses `high.shift(1).rolling(55).max()`
- `EMA50 > EMA200`
- `ATR14` is valid

score_or_gate_conditions:
- P4 Long core does not require G1.
- RB2 compares `P4_NO_GATE` and `P4_G1_GATE` as later gate research.

exit_conditions:
- Donchian20 exit confirms when 15m `close < donchian20_lower`.
- Exit is executed at the confirmed candle close-time 1m open, not the 15m close.

stop_conditions:
- Long stop is `entry_price - 3 * ATR14`.

fee_model: project default `FEE_RATE = 0.0005`
slippage_model: project default `SLIPPAGE_RATE = 0.0002`
position_sizing: RB2 tests low leverage; P4 Short mirror first version is fixed 1x only.
leverage_mode: no high leverage in P4 Short mirror V1.

time_alignment:
- 1m timestamp is the minute open.
- 15m candle timestamp is the candle completion time.
- Signals are only tradable after 15m completion.

canonical_valid_outputs:
- RB1 realistic replay outputs.
- RB2 low leverage P4-only outputs.

invalid_legacy_outputs:
- Old left-labeled 15m long-history outputs are `time_alignment_invalid`.

oos_status: not_oos
