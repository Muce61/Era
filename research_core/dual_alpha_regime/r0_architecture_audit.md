# R0 Architecture Audit: Dual Alpha Market Regime Research

branch: `codex/dual-alpha-market-regime-research`
status: R0 complete, no trading strategy implemented
audit_date: 2026-07-02

## Scope

This audit covers the existing repository structure relevant to:

- event table generation
- factor extraction and family scoring
- prototype attribution
- minimal backtest and accounting
- OOS / walk-forward validation
- leverage and path-safety research
- prior second-alpha or residual-entry research

R0 intentionally does not add a mean-reversion strategy, route trades, optimize trend parameters, or change the frozen Donchian/EMA/ATR trend rules.

## Existing Code That Can Be Reused

| Area | Reusable files | Reuse policy |
| --- | --- | --- |
| 1m OHLCV loading | `strategy/eth_trend_signals.py`, `strategy/trend_following.py` | Reuse parsing, UTC normalization, OHLCV validation patterns. Generalize symbol handling instead of hard-coding ETH. |
| 15m aggregation | `strategy/eth_trend_signals.py::build_base_frame` | Reuse aggregation style, but R1 must preserve completed-bar availability explicitly. |
| Trend baseline config | `configs/stage2_b1_frozen.json`, `configs/stage2_b2_frozen.json`, `configs/stage2_b3_frozen.json`, `configs/stage4_c1_frozen.json` | Use as historical references. Do not modify Donchian 55/20, EMA 50/200, ATR 14, 3 ATR stop for the trend benchmark. |
| Frozen-config discipline | `backtest/stage2_config.py`, `backtest/stage4_config.py`, `tests/test_stage2_frozen_config.py` | Reuse hashing, no-override checks, metadata style. Extend with dual-alpha freeze files if needed. |
| Accounting primitives | `backtest/accounting.py`, `backtest/position_sizing.py`, `backtest/metrics.py` | Reuse for entry/exit fills, fee/slippage accounting, PF, drawdown, concentration metrics. |
| Trend engine reference | `backtest/eth_trend_engine.py` | Use as execution timing reference, not as the regime/MR engine. |
| Data audit patterns | `backtest/run_stage2_existing_data_pipeline.py` | Reuse duplicate, missing-minute, invalid OHLC, outlier, and 15m completeness audit patterns. |
| Random baseline patterns | `backtest/run_stage2_existing_data_pipeline.py`, `backtest/run_stage3_trend_context_attribution.py`, `backtest/run_stage4_c1_validation.py` | Reuse matched sampling and non-overlap discipline, but rebuild matching dimensions for MR events. |
| Walk-forward / bootstrap / stress | Stage2-4 runners and `docs/anti_overfit_policy.md` | Reuse reporting concepts. R1-R6 must not calculate test thresholds on full sample. |
| Prior conclusion files | `backtest_results/stage2/stage2_conclusion.md`, `backtest_results/stage3/stage3_conclusion.md`, `backtest_results/stage4/stage4_conclusion.md` | Use as negative-control history and implementation-risk evidence. |

## Code That Must Not Be Reused Directly

| Existing logic | Reason |
| --- | --- |
| `research/trend_research_pipeline.py::generate_events` | Produces only breakout signal events. R1 requires one row for every complete 15m bar for every symbol. |
| `research/trend_research_pipeline.py::regime_labels` | Uses event-only data and full-sample quantiles in places. Not acceptable as realtime market-state table. |
| Stage2 `build_regime_labels` | 4h descriptive labels only, not the required 15m TREND/RANGE/TRANSITION/EXTREME classifier. |
| Stage2/3 random candidate pools | Candidate pools are trend-context candidate events, not all-market RANGE deviation events. |
| Stage3 C1 event simulation as strategy proof | Stage4 showed the event simulation did not survive engine validation. Use as warning, not as proof. |
| Any historical `IDLE_MR1` / residual-after-trend idea if found later | The new MR alpha must be built from all-market RANGE states and independent events, not after P4/P6 exits. |
| Live trading risk code in `main.py`, `risk/manager.py`, `backtest/real_engine.py` | Contains high-leverage/live assumptions. This research starts with event studies, fixed 1x and fixed risk 0.5%, no high leverage. |

## Current Research History Summary

- Stage2 found B3 profitable in the local ETH sample but not better than a matched random baseline. Final verdict: D for that specific B3 hypothesis.
- Stage3 suggested broader trend context explained more than B3 timing, but the best event-simulated simple timing was not a deployable result.
- Stage4 re-tested C1 in the engine and found PF < 1 with poor bootstrap behavior. This is a strong warning that event-level alpha must be separated from executable strategy performance.
- Existing research has not answered whether an independent all-market RANGE mean-reversion source exists across ETH/BTC and other symbols.

## Data Inventory Observed Locally

Preferred R1 input candidate:

| Directory | ETH | BTC | SOL | BNB | Coverage observed |
| --- | ---: | ---: | ---: | ---: | --- |
| `/Users/muce/1m_data/long_history_1m/merged` | yes | yes | yes | yes | ETH/BTC from 2020-01-01 to 2026-06-28; SOL from 2020-09-14; BNB from 2020-02-10 |
| `/Users/muce/1m_data/new_backtest_data_1year_1m` | yes | yes | yes | yes | 2024-12-01 to 2026-07-01 |
| `/Users/muce/1m_data/2024_validation_1m` | yes | yes | yes | yes | 2024 calendar year |

R1 should start from `/Users/muce/1m_data/long_history_1m/merged`, then generate a fresh data quality report before any factor study.

## Leakage Risks

| Risk | Repository evidence | Required control |
| --- | --- | --- |
| Full-sample quantiles | Some existing regime/event studies use `qcut` or rank over available event data. | In R2/R3/R4, thresholds must be fit on training windows only and applied forward. |
| Incomplete 15m bar use | Existing 15m bars are indexed by period open, while execution happens after the 1m bar ending the period. | R1 must store both `bar_open_time` and `available_time`; tests must assert 00:00-00:14 is only usable at 00:15. |
| Event labels entering features | Existing event tables append future returns and path labels next to features. | R1 registry must include `factor_role`, `uses_future_data`, `realtime_available`, `fit_scope`, `transform_scope`; labels must never feed classifiers. |
| Rolling percentiles | Rolling rank can accidentally include current or future bars if not shifted intentionally. | Every realtime rolling statistic must document whether current completed bar is included and must not include future bars. |
| VWAP / range boundary leakage | Future windows are tempting for range definitions. | R1 range boundaries and VWAP must use only completed historical bars up to `bar_open_time`; forward labels are separate. |
| Matched random baseline leakage | Existing matched baseline depends on previously simulated exits. | R5 must build random events with the same holding horizon/frequency and matching buckets without using outcome fields for selection. |

## Timing Alignment Risks

- 1m timestamps are treated as bar open times.
- A 15m bar indexed `00:00` covers 00:00 through 00:14.
- That completed 15m bar is only available for decision at `00:15`.
- An order generated from that bar must execute at the next tradable 1m open, not the 00:00 or 00:14 open.
- R1 must include `bar_open_time`, `bar_close_time`, `available_time`, and `next_exec_time`.
- R1 timing tests must fail if any realtime feature uses the unfinished current 15m bar or any future 1m bar.

## Accounting Risks

- Stage3 vs Stage4 showed that event simulation and executable engine output can diverge materially.
- Existing accounting does include entry fee, exit fee, and slippage; funding is usually zero.
- Existing fixed leverage outputs must not be confused with alpha quality.
- MR strategy testing is forbidden before R4/R5 event evidence exists.
- When R6 is reached, first tests are limited to `fixed_1x` and `fixed_risk_0_5pct`.

## Duplicate Research Risks

- Do not rerun a trend parameter search.
- Do not reinterpret B3/P4/P6 findings as the new second alpha.
- Do not rebuild IDLE_MR1 or "after trend exit residual reversion."
- Do not call a risk filter a second alpha.
- Do not treat a profitable routed portfolio as proof of MR alpha unless MR standalone and matched-baseline tests pass.

## Required New Modules

| Module | First allowed phase | Purpose |
| --- | --- | --- |
| `research_core/dual_alpha_regime/market_regime_event_table.py` | R1 | Build all-market, every-complete-15m regime event rows and labels. |
| `research_core/dual_alpha_regime/regime_factor_registry.py` | R2 | Emit and validate factor registry metadata. |
| `research_core/dual_alpha_regime/regime_factor_research.py` | R2 | Stability, distribution, redundancy, and explanatory-power reports. |
| `research_core/dual_alpha_regime/regime_classifiers.py` | R3 | Fixed Regime-0/1/2/3 prototypes. |
| `research_core/dual_alpha_regime/mean_reversion_event_study.py` | R4 | RANGE-only MR events, factor grouping, forward labels. |
| `research_core/dual_alpha_regime/random_baseline.py` | R5 | Matched random and counterfactual baselines. |
| `research_core/dual_alpha_regime/mean_reversion_backtest.py` | R6 only after R4/R5 pass | Minimal executable MR prototype. |
| `research_core/dual_alpha_regime/portfolio_routing.py` | After independent trend/MR validation | Route trend/MR by regime. |
| `research_core/dual_alpha_regime/common_risk_layer.py` | After routing comparison | Portfolio risk budget, exposure caps, audit table. |

## R0 Findings

1. The existing trend research infrastructure is useful for data loading, execution discipline, accounting, frozen configs, random baselines, and stress testing.
2. The current event-table infrastructure is not sufficient for regime research because it is signal-event based.
3. The existing regime labels are descriptive and too coarse for the requested realtime TREND/RANGE/TRANSITION/EXTREME state system.
4. The strongest known implementation risk is event-simulation optimism; executable backtests must be separate and delayed until event evidence passes.
5. Local cross-asset data appears sufficient for R1/R2 exploration, but a fresh multi-symbol data quality audit is required.
6. There is no evidence in the current code that an independent all-market RANGE mean-reversion alpha has already been tested.

## Failure Points / Blockers

- No current module creates every-complete-15m all-market state rows.
- No formal factor registry exists for regime factors with leakage metadata.
- No timing-alignment tests currently enforce 15m completed-bar availability at 1m execution granularity.
- No current matched random baseline matches symbol, calendar period, hour, volatility regime, liquidity regime, holding horizon, and frequency for MR events.

## Data Problems

- Stage2/3/4 outputs were based on an ETH-focused merged file and marked data coverage as below original minimum.
- The longer multi-symbol data directory extends back to 2020, but it has not yet been audited inside this research branch.
- SOL and BNB start later than ETH/BTC, so cross-asset summaries must handle unequal histories and report asset-specific coverage.

## Decision: Allow R1?

Allowed, with restrictions.

R1 may build the unified market regime event table and timing tests. R1 must not:

- create MR entries or exits
- optimize thresholds on full sample
- alter frozen trend rules
- call any state a profitable strategy
- use future returns to define current regime features

## Frozen Items For R1

- Symbols: `ETHUSDT`, `BTCUSDT`, `SOLUSDT`, `BNBUSDT`; primary conclusions require at least ETH and BTC.
- Primary data directory: `/Users/muce/1m_data/long_history_1m/merged`.
- Signal/state timeframe: 15 minutes.
- Execution timeframe: 1 minute.
- 1m timestamp semantics: bar open time.
- Completed 15m bar availability: next 1m open after bar completion.
- Forward label horizons: 15m, 30m, 60m, 120m, 240m, 480m.
- Trend baseline rules stay frozen: Donchian 55 entry, EMA50 > EMA200, Donchian 20 exit, ATR14, 3 ATR stop, long only.

