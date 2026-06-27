# Quant Literature Ingestion - 2026-06-27

Source: `/Users/muce/Downloads/量化文献拆解总笔记.md`

Scope: 473 documented quant literature notes, with repeated section-level summaries and personal-system implications.

Data layer: literature only. This document does not create strategy rules, live filters, or OOS claims.

## Core Lessons

1. Separate layers before judging alpha.
   Feature representation, model structure, factor generation, portfolio construction, execution, and risk control are different layers. A novelty in any one layer is not automatically alpha.

2. Research process beats model complexity.
   The most transferable knowledge is not a specific Transformer, GNN, GP, DeepLOB, or reinforcement learning model. The transferable part is the validation system: point-in-time data, frozen hypotheses, candidate accounting, rolling validation, bootstrap, random baseline, cost model, and risk attribution.

3. Candidate count is the hidden denominator.
   Large factor searches, model zoos, multiple windows, multiple neutralization choices, and post-hoc event definitions all expand the real number of trials. Every candidate family must record its search space, rejected variants, and selection path.

4. Discovery evidence is not OOS evidence.
   Reusing the same sample for R2/R3/R4 can identify useful structure, but cannot produce final validation. Current ETH 2024-2026 data remains discovery/internal validation only.

5. High-frequency information is more realistic as low-frequency context.
   For the current system, Level-2/order-book style information is more useful as lower-frequency liquidity, pressure, volatility, toxicity, or execution-risk features than as direct low-latency trading.

6. Many attractive signals are short-side or avoid signals.
   A factor may have good long-short statistics while the long side is weak. For a long-only or constrained system, classify signals as `alpha`, `avoid`, `risk`, or `execution`, instead of forcing every signal into a positive entry filter.

7. Timing/state signals should usually scale risk, not hard switch.
   Factor timing, macro timing, crowding, and regime signals have low independent sample counts. Their robust use is often risk-budget scaling, concentration control, or de-risking, not binary all-in/all-out strategy switching.

8. Risk model and attribution are infrastructure, not optional reporting.
   Every strategy or factor study should separate expected return from industry/style/liquidity/volatility exposure, turnover, cost, and concentration. Net equity alone is not enough.

## Research Core Implications

### R0-R4 Alignment

The existing Research Core already matches several literature requirements:

- R0 freezes data layer and hashes.
- R1 creates a unified event table.
- R2 performs descriptive factor grouping.
- R3 checks time stability.
- R4 compares against random baselines using `(1+count)/(N+1)` and FDR.

The literature reinforces that these are necessary but not sufficient. R4 passing still cannot be called OOS because factor candidates were selected on the same discovery sample.

### Required Additions

1. Candidate ledger.
   Record every proposed factor, its source, whether it is alpha/avoid/risk/execution, its formula family, and whether it came from literature, manual reasoning, or automated search.

2. Factor family accounting.
   Factors with shared logic, such as momentum variants or volatility variants, must share a family-level multiple-testing denominator.

3. Signal role taxonomy.
   Add explicit role labels:
   - `alpha`: improves expected forward return.
   - `avoid`: identifies bad entries or toxic states.
   - `risk`: changes position size or risk budget.
   - `execution`: affects fill quality, slippage, or cost.

4. Horizon decay curves.
   Many high-frequency and price-pressure features reverse sign across horizons. Each factor should report horizon decay rather than one selected horizon.

5. Concentration and tail dependence.
   R5 should test whether R4 evidence depends on specific months, large events, or extreme forward-return bars.

6. Risk attribution layer.
   For ETH, replace equity-style industry exposure with crypto-relevant exposures:
   - trend age
   - volatility regime
   - breakout extension
   - liquidity proxy if available
   - intraday time bucket
   - event clustering

## Candidate Research Queue

These are research hypotheses only. They must enter R1/R2/R3/R4/R5 before any strategy use.

1. Momentum continuation family.
   Existing R2/R4 evidence suggests `ret_4h`, `ret_12h`, and `ret_24h` have strong directional separation. Treat these as one family, not independent discoveries.

2. Breakout extension family.
   `breakout_distance_atr`, `range_atr`, `body_ratio`, and `close_location` appear to measure the strength and location of the breakout bar. Test whether this is one underlying pressure/conviction factor.

3. Volatility expansion family.
   `atr_pct`, `atr_percentile_200`, and `volatility_ratio_short_long` should be grouped as volatility regime factors. Literature suggests they may be risk/execution features as much as alpha features.

4. Shadow/rejection family.
   `upper_shadow_ratio` and `lower_shadow_ratio` likely behave as rejection/absorption proxies. Test horizon-specific sign stability before assigning an economic story.

5. Compression family.
   `inside_bar_compression` should be treated as volatility contraction before expansion, not as the B3 Hikkake pattern itself.

6. Avoid/risk signals.
   Add a future research path for signals that reduce bad entries rather than increase average forward return. This should be evaluated with drawdown, MAE, and tail-loss reduction, not only mean forward return.

## Guardrails

- Do not convert literature ideas directly into strategy filters.
- Do not count repeated papers or variants as independent evidence.
- Do not treat high model accuracy as tradability.
- Do not optimize factor thresholds on the current discovery data.
- Do not call current results OOS or simulation-ready.
- Do not add complex ML models before simple baselines, random baselines, bootstrap, and attribution are complete.

## Recommended Next Stage

Continue with R5:

1. Bootstrap R4-passed factor evidence.
2. Block bootstrap by month and quarter.
3. Remove best months/events.
4. Repeat worst months/events.
5. Report survival by factor family, not only individual factor-horizon rows.
6. Classify surviving evidence into `alpha`, `avoid`, `risk`, or `execution`.
