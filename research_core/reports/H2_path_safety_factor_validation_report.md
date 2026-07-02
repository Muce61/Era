# H2 Path Safety Factor Validation Report

branch: codex/adaptive-leverage-10x-20x
data_layer: high_leverage_research
oos_status: not_oos
simulation_approval: not_allowed

This stage validates path-safety evidence only. No alpha rule or trading filter is changed.

## Role Counts

| factor_role        |   count |
|:-------------------|--------:|
| alpha_only         |      82 |
| dual_use_candidate |      79 |
| path_safety_only   |      11 |
| invalid_or_sparse  |       6 |
| risk_monitor       |       2 |

## Bootstrap Counts

| bootstrap_status             |   count |
|:-----------------------------|--------:|
| event_sample_fragile         |     115 |
| robust_path_safety_candidate |      65 |

## Stress Counts

| stress_status        |   count |
|:---------------------|--------:|
| month_dependent      |     103 |
| stress_pass          |      69 |
| symbol_dependent     |       7 |
| tail_event_dependent |       1 |

## H3 Candidate Check

| factor                      | prototype                     | bootstrap_ok   | stress_ok   | horizon_ok   | failure_explainability   | decision_status            | allowed_next_step         |
|:----------------------------|:------------------------------|:---------------|:------------|:-------------|:-------------------------|:---------------------------|:--------------------------|
| volatility_ratio_short_long | P4_BREAKOUT_TOP20             | True           | True        | True         | weak_explanation         | candidate_for_H3_prototype | H3_minimal_gate_prototype |
| atr_pct                     | P6_MOMENTUM_OR_BREAKOUT_TOP20 | True           | True        | True         | explains_failures        | candidate_for_H3_prototype | H3_minimal_gate_prototype |
| volatility_ratio_short_long | P6_MOMENTUM_OR_BREAKOUT_TOP20 | True           | True        | True         | weak_explanation         | candidate_for_H3_prototype | H3_minimal_gate_prototype |
| breakout_score_quantile     | P6_MOMENTUM_OR_BREAKOUT_TOP20 | True           | True        | True         | explains_failures        | candidate_for_H3_prototype | H3_minimal_gate_prototype |
| atr_pct                     | P4_BREAKOUT_TOP20             | True           | True        | True         | no_explanation           | needs_more_validation      | research_only             |
| atr_percentile_200          | P4_BREAKOUT_TOP20             | True           | True        | True         | no_explanation           | needs_more_validation      | research_only             |
| prior_5m_lower_wick_ratio   | P4_BREAKOUT_TOP20             | True           | True        | True         | no_explanation           | needs_more_validation      | research_only             |
| prior_15m_lower_wick_ratio  | P4_BREAKOUT_TOP20             | True           | True        | True         | no_explanation           | needs_more_validation      | research_only             |
| momentum_score_quantile     | P4_BREAKOUT_TOP20             | True           | True        | True         | no_explanation           | needs_more_validation      | research_only             |
| breakout_score_quantile     | P4_BREAKOUT_TOP20             | True           | True        | True         | no_explanation           | needs_more_validation      | research_only             |
| atr_percentile_200          | P6_MOMENTUM_OR_BREAKOUT_TOP20 | True           | True        | True         | no_explanation           | needs_more_validation      | research_only             |
| prior_5m_lower_wick_ratio   | P6_MOMENTUM_OR_BREAKOUT_TOP20 | True           | True        | True         | no_explanation           | needs_more_validation      | research_only             |
| prior_15m_lower_wick_ratio  | P6_MOMENTUM_OR_BREAKOUT_TOP20 | True           | True        | True         | no_explanation           | needs_more_validation      | research_only             |
| momentum_score_quantile     | P6_MOMENTUM_OR_BREAKOUT_TOP20 | True           | True        | True         | no_explanation           | needs_more_validation      | research_only             |
| atr_pct_rank                | P4_BREAKOUT_TOP20             | False          | False       | True         | explains_failures        | needs_more_validation      | research_only             |
| prior_15m_return            | P4_BREAKOUT_TOP20             | False          | False       | True         | weak_explanation         | needs_more_validation      | research_only             |
| prior_30m_return            | P4_BREAKOUT_TOP20             | False          | False       | True         | explains_failures        | needs_more_validation      | research_only             |
| range_atr                   | P6_MOMENTUM_OR_BREAKOUT_TOP20 | False          | False       | True         | no_explanation           | needs_more_validation      | research_only             |
| prior_15m_return            | P6_MOMENTUM_OR_BREAKOUT_TOP20 | False          | False       | True         | explains_failures        | needs_more_validation      | research_only             |
| prior_30m_return            | P6_MOMENTUM_OR_BREAKOUT_TOP20 | False          | False       | True         | weak_explanation         | needs_more_validation      | research_only             |

## Horizon Roles

| factor                      | prototype                     |   windows_available |   safe20_positive_window_count |   mae_positive_window_count |   mfe_positive_window_count | direction_consistency   | best_window   | window_role                 |
|:----------------------------|:------------------------------|--------------------:|-------------------------------:|----------------------------:|----------------------------:|:------------------------|:--------------|:----------------------------|
| range_atr                   | P4_BREAKOUT_TOP20             |                   6 |                              0 |                           0 |                           6 | consistent_nonpositive  | 5m            | alpha_mfe_only              |
| atr_pct                     | P4_BREAKOUT_TOP20             |                   6 |                              6 |                           0 |                           6 | consistent_positive     | 15m           | path_safety_multi_window    |
| atr_pct_rank                | P4_BREAKOUT_TOP20             |                   6 |                              1 |                           0 |                           6 | mixed                   | 15m           | window_reversal             |
| volatility_ratio_short_long | P4_BREAKOUT_TOP20             |                   6 |                              5 |                           0 |                           6 | mixed                   | 15m           | path_safety_multi_window    |
| atr_percentile_200          | P4_BREAKOUT_TOP20             |                   6 |                              6 |                           0 |                           6 | consistent_positive     | 15m           | path_safety_multi_window    |
| prior_5m_range_pct          | P4_BREAKOUT_TOP20             |                   6 |                              0 |                           0 |                           6 | consistent_nonpositive  | 1m            | alpha_mfe_only              |
| prior_15m_range_pct         | P4_BREAKOUT_TOP20             |                   6 |                              0 |                           0 |                           6 | consistent_nonpositive  | 1m            | alpha_mfe_only              |
| prior_30m_range_pct         | P4_BREAKOUT_TOP20             |                   6 |                              0 |                           0 |                           6 | consistent_nonpositive  | 1m            | alpha_mfe_only              |
| prior_5m_return             | P4_BREAKOUT_TOP20             |                   5 |                              0 |                           0 |                           5 | consistent_nonpositive  | 1m            | alpha_mfe_only              |
| prior_15m_return            | P4_BREAKOUT_TOP20             |                   6 |                              0 |                           0 |                           6 | consistent_nonpositive  | 1m            | alpha_mfe_only              |
| prior_30m_return            | P4_BREAKOUT_TOP20             |                   6 |                              0 |                           0 |                           6 | consistent_nonpositive  | 1m            | alpha_mfe_only              |
| prior_5m_lower_wick_ratio   | P4_BREAKOUT_TOP20             |                   6 |                              6 |                           4 |                           4 | consistent_positive     | 15m           | path_safety_multi_window    |
| prior_15m_lower_wick_ratio  | P4_BREAKOUT_TOP20             |                   6 |                              6 |                           4 |                           3 | consistent_positive     | 15m           | path_safety_multi_window    |
| breakout_score_quantile     | P4_BREAKOUT_TOP20             |                   6 |                              5 |                           0 |                           6 | mixed                   | 15m           | path_safety_multi_window    |
| momentum_score_quantile     | P4_BREAKOUT_TOP20             |                   6 |                              6 |                           0 |                           6 | consistent_positive     | 15m           | path_safety_multi_window    |
| range_atr                   | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   6 |                              0 |                           6 |                           6 | consistent_nonpositive  | 60m           | alpha_mfe_only              |
| atr_pct                     | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   6 |                              1 |                           0 |                           6 | mixed                   | 1m            | execution_risk_short_window |
| atr_pct_rank                | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   6 |                              0 |                           0 |                           6 | consistent_nonpositive  | 15m           | alpha_mfe_only              |
| volatility_ratio_short_long | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   6 |                              6 |                           4 |                           6 | consistent_positive     | 15m           | path_safety_multi_window    |
| atr_percentile_200          | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   6 |                              6 |                           0 |                           6 | consistent_positive     | 15m           | path_safety_multi_window    |
| prior_5m_range_pct          | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   6 |                              0 |                           0 |                           6 | consistent_nonpositive  | 1m            | alpha_mfe_only              |
| prior_15m_range_pct         | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   6 |                              0 |                           0 |                           6 | consistent_nonpositive  | 1m            | alpha_mfe_only              |
| prior_30m_range_pct         | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   6 |                              0 |                           0 |                           6 | consistent_nonpositive  | 1m            | alpha_mfe_only              |
| prior_5m_return             | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   3 |                              0 |                           0 |                           3 | consistent_nonpositive  | 1m            | alpha_mfe_only              |
| prior_15m_return            | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   5 |                              0 |                           0 |                           4 | consistent_nonpositive  | 1m            | alpha_mfe_only              |
| prior_30m_return            | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   5 |                              0 |                           0 |                           4 | consistent_nonpositive  | 1m            | alpha_mfe_only              |
| prior_5m_lower_wick_ratio   | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   6 |                              6 |                           0 |                           3 | consistent_positive     | 60m           | path_safety_multi_window    |
| prior_15m_lower_wick_ratio  | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   6 |                              6 |                           4 |                           3 | consistent_positive     | 15m           | path_safety_multi_window    |
| breakout_score_quantile     | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   6 |                              5 |                           6 |                           5 | mixed                   | 60m           | path_safety_multi_window    |
| momentum_score_quantile     | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   6 |                              6 |                           0 |                           6 | consistent_positive     | 3m            | path_safety_multi_window    |

## Failure Explainability

| factor                      | prototype                     |   failure_case_count | risk_direction   |   failure_in_risk_quintile_rate |   all_events_in_risk_quintile_rate |     lift | explainability_status   |
|:----------------------------|:------------------------------|---------------------:|:-----------------|--------------------------------:|-----------------------------------:|---------:|:------------------------|
| atr_pct                     | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   45 | high_factor_risk |                       0.666667  |                           0.200704 | 3.32164  | explains_failures       |
| prior_30m_range_pct         | P4_BREAKOUT_TOP20             |                   23 | high_factor_risk |                       0.652174  |                           0.200542 | 3.25206  | explains_failures       |
| breakout_score_quantile     | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   45 | low_factor_risk  |                       0.622222  |                           0.199531 | 3.11843  | explains_failures       |
| prior_15m_range_pct         | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   45 | high_factor_risk |                       0.555556  |                           0.200704 | 2.76803  | explains_failures       |
| atr_pct_rank                | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   45 | high_factor_risk |                       0.533333  |                           0.200704 | 2.65731  | explains_failures       |
| prior_5m_range_pct          | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   45 | high_factor_risk |                       0.511111  |                           0.200704 | 2.54659  | explains_failures       |
| prior_30m_range_pct         | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   45 | high_factor_risk |                       0.488889  |                           0.200704 | 2.43587  | explains_failures       |
| atr_pct_rank                | P4_BREAKOUT_TOP20             |                   23 | high_factor_risk |                       0.478261  |                           0.200542 | 2.38484  | explains_failures       |
| prior_5m_range_pct          | P4_BREAKOUT_TOP20             |                   23 | high_factor_risk |                       0.478261  |                           0.200542 | 2.38484  | explains_failures       |
| prior_15m_range_pct         | P4_BREAKOUT_TOP20             |                   23 | high_factor_risk |                       0.478261  |                           0.200542 | 2.38484  | explains_failures       |
| prior_30m_return            | P4_BREAKOUT_TOP20             |                   23 | high_factor_risk |                       0.478261  |                           0.200542 | 2.38484  | explains_failures       |
| prior_15m_return            | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   45 | high_factor_risk |                       0.466667  |                           0.200704 | 2.32515  | explains_failures       |
| prior_5m_return             | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   45 | high_factor_risk |                       0.377778  |                           0.200704 | 1.88226  | explains_failures       |
| prior_30m_return            | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   45 | high_factor_risk |                       0.333333  |                           0.200704 | 1.66082  | weak_explanation        |
| volatility_ratio_short_long | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   45 | low_factor_risk  |                       0.311111  |                           0.198357 | 1.56844  | weak_explanation        |
| prior_5m_return             | P4_BREAKOUT_TOP20             |                   23 | high_factor_risk |                       0.304348  |                           0.200542 | 1.51763  | weak_explanation        |
| volatility_ratio_short_long | P4_BREAKOUT_TOP20             |                   23 | low_factor_risk  |                       0.26087   |                           0.199187 | 1.30967  | weak_explanation        |
| prior_15m_return            | P4_BREAKOUT_TOP20             |                   23 | high_factor_risk |                       0.26087   |                           0.200542 | 1.30082  | weak_explanation        |
| breakout_score_quantile     | P4_BREAKOUT_TOP20             |                   23 | low_factor_risk  |                       0.173913  |                           0.199187 | 0.873114 | no_explanation          |
| range_atr                   | P4_BREAKOUT_TOP20             |                   23 | high_factor_risk |                       0.173913  |                           0.200542 | 0.867215 | no_explanation          |
| prior_5m_lower_wick_ratio   | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   45 | low_factor_risk  |                       0.155556  |                           0.199531 | 0.779608 | no_explanation          |
| prior_15m_lower_wick_ratio  | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   45 | low_factor_risk  |                       0.155556  |                           0.199531 | 0.779608 | no_explanation          |
| atr_percentile_200          | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   45 | low_factor_risk  |                       0.133333  |                           0.199531 | 0.668235 | no_explanation          |
| atr_percentile_200          | P4_BREAKOUT_TOP20             |                   23 | low_factor_risk  |                       0.130435  |                           0.199187 | 0.654836 | no_explanation          |
| range_atr                   | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   45 | high_factor_risk |                       0.111111  |                           0.200704 | 0.553606 | no_explanation          |
| prior_15m_lower_wick_ratio  | P4_BREAKOUT_TOP20             |                   23 | low_factor_risk  |                       0.0434783 |                           0.199187 | 0.218279 | no_explanation          |
| prior_5m_lower_wick_ratio   | P4_BREAKOUT_TOP20             |                   23 | low_factor_risk  |                       0.0434783 |                           0.199187 | 0.218279 | no_explanation          |
| atr_pct                     | P4_BREAKOUT_TOP20             |                   23 | low_factor_risk  |                       0         |                           0.199187 | 0        | no_explanation          |
| momentum_score_quantile     | P4_BREAKOUT_TOP20             |                   23 | low_factor_risk  |                       0         |                           0.199187 | 0        | no_explanation          |
| momentum_score_quantile     | P6_MOMENTUM_OR_BREAKOUT_TOP20 |                   45 | low_factor_risk  |                       0         |                           0.199531 | 0        | no_explanation          |

## Required Answers

1. 哪些因子是真正的 path safety 因子：见 factor_role_decomposition 中 path_safety_only / dual_use_candidate。
2. 哪些因子只是 alpha / MFE 因子：见 factor_role_decomposition 中 alpha_only。
3. 哪些因子只适合做 risk monitor：见 factor_role_decomposition 中 risk_monitor。
4. 哪些因子只适合 execution 层：见 horizon_consistency_summary 中 execution_risk_short_window。
5. 哪些因子跨 symbol 稳定：见 path_safety_bootstrap_summary 的 symbol_positive_rate 与 bootstrap_status。
6. 哪些因子依赖某个月份或某个 symbol：见 path_safety_stress_summary。
7. 哪些因子能解释 L1/L2 失败案例：见 failure_case_explainability.csv。
8. 是否可以进入 H3 做最小高杠杆准入原型：True。
9. 是否仍禁止形成策略规则：是。H2 不是策略化阶段。
10. 是否需要 1s 或盘口数据：若继续研究 10x-20x 强平边界，需要 1s/盘口数据验证执行风险。

## Final Decision

A. 存在稳定 path-safety 因子，可进入 H3 最小准入原型

## Guardrails

- no alpha rule changed
- factor validation only
- not OOS
- no deployable strategy rule generated
