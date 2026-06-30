# P4 Short Trend Direction Coverage Research Report

base_branch: codex/adaptive-leverage-10x-20x
base_commit_sha: e56054f0f074920e54e742a1050b1bcb29ec2543
research_branch: codex/p4-short-trend-direction-coverage
research_head_commit_sha: 1631385a3e6654fb405da0cccdb4874f72e1d12f
data_layer: expanded_discovery
oos_status: not_oos
paper_trading_status: not_allowed

## Decisions

short_decision: F. no_validated_short_trend_edge
combination_decision: F. no_validated_directional_coverage
archive_status: P4_SHORT_EVENT_EDGE_NOT_FOUND;P4_SHORT_MIRROR_V1_ARCHIVED

## Interpretation

- P4 Short was evaluated as a mechanical trend-direction mirror, not as an independent second alpha.
- P4 Long rules were not modified.
- Old left-labeled 15m results remain time_alignment_invalid and were not used as valid evidence.
- Funding was downloaded from Binance USDT-M where available and separately attributed; missing coverage downgrades realism.

## Required Answers

1. Current P4 Long uses Donchian55 upper breakout, EMA50 > EMA200, ATR stop, and Donchian20 lower exit under repaired candle-close time alignment.
2. Legacy left-labeled outputs are invalid.
3. Short mirror uses Donchian55 lower breakout, EMA50 < EMA200, ATR stop above entry, and Donchian20 upper exit.
4. Short events did not outperform matched random bear-regime events: observed h16 mean `-0.001465`, random mean `+0.000512`, percentile `0.0`.
5. The clearest decision horizon h16 was negative; all-symbol h16 mean was `-0.001465`, h32 mean was `-0.001251`.
6. At h16, favorable +1ATR first-touch rate was `0.481689`, while adverse -1ATR first-touch rate was `0.482667`; no favorable first-touch edge.
7. Squeeze/tail risk is summarized in `short_tail_risk_summary.csv`; event MAE did not justify replay.
8. The mirror short was not only a 2022-style bear-market edge: positive year rate was `0.428571`.
9. BTC and ETH were both negative at h16: BTC `-0.001151`, ETH `-0.001223`.
10. SOL was also negative at h16 `-0.002473`; BNB was less negative but still below zero at `-0.000893`.
11. Cost-before event expectancy was negative, so strategy replay was blocked before cost-after testing.
12. Base-cost replay was not run because the event gate failed.
13. High/stress cost replay was not run because the event gate failed.
14. Funding history was downloaded/audited for ETH, BTC, SOL, and BNB; rows are listed in `short_instrument_audit.csv`.
15. Short PnL accounting is quantity-based and covered by `tests/test_p4_short_accounting.py`.
16. No future-function issue was found in the added tests; Donchian uses shifted bands and execution uses completed 15m candle time.
17. Prefix invariance is covered by `tests/test_p4_short_prefix_invariance.py`.
18. Walk-forward replay was blocked because event evidence failed first.
19. Deleting best trades was not applicable to replay; event top1 positive contribution was only `0.003515`, so failure was not due to one missing winner.
20. Short standalone did not meet admission standards.
21. Long/Short monthly correlation was not computed because Short did not qualify for replay.
22. P4 Long loss-month Short positive rate was not computed because Short did not qualify for replay.
23. Combination max drawdown was not evaluated because Short standalone expectancy was not validated.
24. Combination longest drawdown was not evaluated because Short standalone expectancy was not validated.
25. Combination cost impact was not evaluated because Short standalone expectancy was not validated.
26. The mirror short did not validate as a reliable direction-coverage module.
27. It is not eligible for strict OOS.
28. Simulation and live trading remain forbidden.
29. Research branch: `codex/p4-short-trend-direction-coverage`; final pushed SHA is recorded in Git and final task output.
30. Remote push status is recorded in final task output after `git push`.

Final statement:

`No validated P4 short trend edge found`

Archive status:

`P4_SHORT_MIRROR_V1_ARCHIVED`
