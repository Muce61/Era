# P4 Canonical Rule Snapshot

base_commit_sha: e56054f0f074920e54e742a1050b1bcb29ec2543
data_layer: expanded_discovery
oos_status: not_oos

## Canonical P4 Long

- Signal timeframe: 15m candle close time.
- Execution: corresponding valid 1m open after signal confirmation.
- Entry: 15m close above prior Donchian55 upper and EMA50 > EMA200.
- Prototype: P4_BREAKOUT_TOP20 using fixed discovery metadata and thresholds.
- Gate: P4_G1_GATE using fixed H3/H4 discovery thresholds.
- Stop: entry_price - 3 * ATR14 known at signal time.
- Exit: completed 15m close below prior Donchian20 lower, executed at valid 1m open.
- Sizing: fixed_1x only for freeze candidates.

## Time Alignment

`1m timestamp = minute open`; `15m timestamp = completed candle close time`; Donchian windows use `shift(1)`.

## Invalid Evidence

Older left-labeled 15m outputs are marked `time_alignment_invalid` and cannot support freeze decisions.
