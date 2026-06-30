# P4 Short Trend Direction Coverage Research Report

base_branch: codex/adaptive-leverage-10x-20x
base_commit_sha: e56054f0f074920e54e742a1050b1bcb29ec2543
research_branch: codex/p4-short-trend-direction-coverage
research_head_commit_sha: e56054f0f074920e54e742a1050b1bcb29ec2543
data_layer: expanded_discovery
oos_status: not_oos
paper_trading_status: not_allowed

## Decisions

short_decision: F. no_validated_short_trend_edge
combination_decision: F. no_validated_directional_coverage
archive_status: P4_SHORT_EVENT_EDGE_NOT_FOUND

## Interpretation

- P4 Short was evaluated as a mechanical trend-direction mirror, not as an independent second alpha.
- P4 Long rules were not modified.
- Old left-labeled 15m results remain time_alignment_invalid and were not used as valid evidence.
- Funding was downloaded from Binance USDT-M where available and separately attributed; missing coverage downgrades realism.

## Required Answers

1. Current P4 Long uses Donchian55 upper breakout, EMA50 > EMA200, ATR stop, and Donchian20 lower exit under repaired candle-close time alignment.
2. Legacy left-labeled outputs are invalid.
3. Short mirror uses Donchian55 lower breakout, EMA50 < EMA200, ATR stop above entry, and Donchian20 upper exit.
4. Random baseline and event deltas are in `short_random_baseline_summary.csv` and `short_event_vs_random_delta.csv`.
5. Forward horizon evidence is in `short_event_summary.csv`.
6. First-touch evidence is in `short_event_summary.csv`.
7. Squeeze/tail risk is in `short_tail_risk_summary.csv`.
8. Year/quarter stability is in `short_yearly_summary.csv` and `short_quarterly_summary.csv`.
9. BTC/ETH evidence is separated in all symbol-level outputs.
10. SOL/BNB are supporting cross-asset references, not primary go/no-go assets.
11. Gross and cost-after results are in backtest outputs if event gate passed.
12. Cost scenarios materially change fee/slippage assumptions.
13. Funding completeness is in `short_instrument_audit.csv`.
14. Accounting identity is tested in `tests/test_p4_short_accounting.py`.
15. No OOS, paper, or live approval is granted.
