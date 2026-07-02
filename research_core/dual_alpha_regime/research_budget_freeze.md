# Dual Alpha Regime Research Budget Freeze

status: initial freeze before R1
date: 2026-07-02

## Symbols

Primary:

- ETHUSDT
- BTCUSDT

Secondary cross-market checks:

- SOLUSDT
- BNBUSDT

## Data Splits

Default split for long-history data:

- Discovery: 2020-01-01 through 2023-12-31
- Validation: 2024-01-01 through 2024-12-31
- OOS: 2025-01-01 through latest audited complete date

If a symbol starts later, use the same calendar cutoffs and mark missing early coverage. Walk-forward tests may additionally use training 24 months and test 6 months, rolling every 6 months.

## Fixed Forward Horizons

- 15 minutes
- 30 minutes
- 60 minutes
- 120 minutes
- 240 minutes
- 480 minutes

No new forward horizons may be added in this research round without logging a change.

## Market State Prototypes

- Regime-0: no state classification
- Regime-1: TREND / NON_TREND
- Regime-2: TREND / RANGE / UNCERTAIN
- Regime-3: TREND / RANGE / TRANSITION / EXTREME

No additional classifier families may be added before these are reported.

## Trend Structure Factors

- ema_gap_atr
- ema200_slope_4h
- adx_14
- efficiency_ratio_20
- efficiency_ratio_40
- higher_high_lower_low_score
- donchian_position_55
- breakout_duration_55
- return_autocorr_20
- trend_direction_consistency_20

## Range Structure Factors

- efficiency_ratio_20
- efficiency_ratio_40
- return_autocorr_20
- mean_cross_count_ema20_96
- range_width_atr_96
- range_round_trip_count_96
- breakout_failure_rate_96
- zscore_ema20
- zscore_ema50
- variance_ratio_20_80
- range_persistence_96

## Volatility Structure Factors

- atr_pct
- atr_percentile_200
- volatility_ratio_short_long
- realized_volatility_20
- realized_volatility_80
- bollinger_bandwidth_20
- volatility_compression_duration
- volatility_change_rate_20
- downside_volatility_80
- jump_score_80

## Liquidity Proxies

- volume
- quote_volume_proxy
- volume_zscore_96
- dollar_volume_percentile_200
- high_low_spread_pct
- missing_1m_count_in_15m

## Mean Definitions For R4

- EMA20
- EMA50
- rolling VWAP
- Bollinger middle
- rolling median
- Donchian midpoint

## Deviation Definitions For R4

- `(close - mean) / ATR`
- rolling z-score
- `(close - VWAP) / realized_volatility`
- range position
- short-return oversold percentile

## MR Prototypes For R4

- MR-P0: all RANGE deviation events
- MR-P1: deviation severity top 20%
- MR-P2: deviation top 20% plus range quality top 40%
- MR-P3: MR-P2 plus one path-safety factor

Only one MR-P3 path-safety factor may be selected in this research round.

## R6 Exit Rules If R4/R5 Pass

- return to EMA20
- return to EMA50
- return to rolling VWAP
- fixed maximum holding time
- range structure invalidation

## R6 Stop Rules If R4/R5 Pass

- fixed ATR stop
- range lower-bound invalidation stop

## Cost And Execution Assumptions

- Fee: use current frozen trend baseline fee unless a phase explicitly stress-tests it.
- Slippage: use current frozen trend baseline slippage unless a phase explicitly stress-tests it.
- Entry execution: next tradable 1m open after the completed 15m signal/state bar is available.
- Same-bar stop/target ambiguity: worst-case path assumption in executable backtests.
- First sizing modes: `fixed_1x`, then `fixed_risk_0_5pct`.
- High leverage research is explicitly out of scope before independent MR validation.

## Robustness Tests

- fee 2x
- slippage 2x
- entry delay 1 minute
- entry delay 3 minutes
- exit delay 1 minute
- exit delay 3 minutes
- threshold perturbation
- remove best month
- remove best quarter
- remove best 1% trades
- year splits
- symbol splits
- volatility-state splits

## Multiple-Testing Log Requirements

Each phase must report:

- factor count tested
- prototype count tested
- horizon count tested
- exit rule count tested
- stop rule count tested
- failed configurations, not just winners

