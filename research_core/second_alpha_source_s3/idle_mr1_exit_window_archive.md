# IDLE_MR1 Exit-Window Candidate Archive

## Final Status

Candidate:

- `IDLE_MR1_P4_IDLE_REVERSION`
- `p4_state_bucket = after_p4_exit_5_16_bars`

Archive decision:

**Stop this candidate. Do not continue optimization around IDLE_MR1 exit-window.**

Reason:

The candidate showed a weak event-level signal, but the signal did not survive realistic trade execution. It should be archived as:

> Event research showed weak evidence, but the candidate failed to become a tradable strategy.

Data layer:

- `expanded_discovery_long_history`
- Not OOS
- Not simulation approval
- Not live-trading approval

## Research Path

S2.6 and S2.7 found a local event-level edge after P4 exits:

- Event bucket: `after_p4_exit_5_16_bars`
- Event count in 1-year validation: `1562`
- `mean_fwd_ret_16` around `+0.001915`
- Random time baseline percentile: `1.0`
- Random direction baseline percentile: `1.0`

S2.8 extended the check to long history:

- Long-history events: `5358`
- Overall `mean_fwd_ret_16`: about `+0.00096`
- Random time percentile mean: about `97.23%`
- P4 weak/negative month positive rate: about `59.5%`
- Positive symbol count: `3`

S2.9 attributed the edge:

- BTC: `negative_mean`
- ETH: `positive_but_top_trade_dependent`
- SOL/BNB: `positive_and_stable`
- Main diagnosis: `mixed_state`

Interpretation:

The signal was not a clean mean-reversion alpha. It looked more like a post-P4-exit state effect with mixed reversion and continuation behavior.

## S3 Realistic Backtest Result

S3 was the first stage that allowed a minimal strategy prototype.

Rules used:

- 15m candle close-time signal alignment
- Entry at next executable 1m open
- One position per symbol
- No adding
- No martingale
- Long and short both retained
- Fixed `after_p4_exit_5_16_bars` window
- Fixed `IDLE_MR1` definition
- Fixed 1x and fixed-risk 0.5% sizing
- ATR stop
- Mean exit to EMA20 or range midpoint
- Time stop at 16 15m bars
- P4 trend-restart exit
- Fees and slippage included
- Funding marked `unavailable`

Key S3 result, ALL symbols, both directions, `fixed_1x`:

| Metric | Value |
|---|---:|
| Trade count | 2642 |
| Total return | -65.08% |
| Max drawdown | -65.36% |
| Profit factor | 0.71 |
| Win rate | 33.38% |
| Final equity | 349.23 |
| Longest drawdown | 2368 days 22:44:00 |
| Fee to gross profit ratio | 23.67% |

Per-symbol `fixed_1x`, both directions:

| Symbol | Trade count | Total return | Max drawdown | PF |
|---|---:|---:|---:|---:|
| ETHUSDT | 656 | -65.95% | -66.11% | 0.66 |
| BTCUSDT | 629 | -71.02% | -71.31% | 0.55 |
| SOLUSDT | 631 | -53.80% | -64.31% | 0.85 |
| BNBUSDT | 726 | -69.53% | -70.15% | 0.65 |

No symbol survived realistic execution with PF > 1.

## P4 Complement Check

Event research suggested possible P4 complement value, but S3 trade-level results did not confirm it.

ALL symbols:

- Monthly correlation with P4 proxy: about `0.20`
- S3 positive rate during P4 negative months: `18.75%`
- S3 positive rate during P4 weak months: `18.46%`
- Complement status: `not_complementary`

Interpretation:

Low correlation alone is not useful if the second strategy loses money during P4 weak months. The candidate did not improve P4 weak-month behavior in trade-level testing.

## Why The Candidate Failed

The event-level edge was consumed by:

1. Realistic entry and exit timing.
2. Position conflict, which reduced event-to-trade conversion.
3. ATR stop and mean-exit path dependency.
4. Fees and slippage.
5. Mixed state behavior after P4 exits.
6. BTC negative expectancy and ETH top-trade dependence.

The main lesson:

> Positive forward-return statistics are not enough. A candidate must survive execution, costs, exits, and position conflict.

## Final Decision

Final decision:

**C. Event edge was consumed by execution, costs, position conflict, and exits.**

Action:

- Stop this candidate.
- Do not optimize `IDLE_MR1`.
- Do not tune `after_p4_exit_5_16_bars`.
- Do not remove BTC/ETH to make results look better.
- Do not continue to S4 for this candidate.
- Do not use it for simulation or live trading.

## Allowed Future Use

This research may still be used as background evidence for:

- Understanding post-P4-exit market states.
- Designing future event studies with stricter path-safety checks before strategy backtest.
- Avoiding candidates whose forward edge is too small relative to fees and exit path risk.

It must not be used as:

- A tradable strategy.
- A P4 filter.
- A simulation candidate.
- A reason to optimize the same window.

## Next Research Direction

The next second-alpha attempt should not continue IDLE_MR1 exit-window optimization.

Recommended next directions:

1. Funding / basis carry.
2. Cross-asset relative value with explicit spread stability checks.
3. Volatility compression followed by short-horizon expansion.
4. Higher-frequency mean reversion only if path and cost tests are built before strategy backtest.

