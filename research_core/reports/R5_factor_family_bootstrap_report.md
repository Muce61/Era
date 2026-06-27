# R5 Factor Family Bootstrap Report

event_count: 1278
r4_candidate_count: 65
family_count: 8
bootstrap_runs_per_test: 5000
data_layer: discovery
data_coverage_note: current 2024-01-01 to 2026-06-24 data is not final OOS.

## Status Counts

### Factor Bootstrap
| bootstrap_status   |   count |
|:-------------------|--------:|
| robust_candidate   |      65 |

### Family Bootstrap
| family_bootstrap_status   |   count |
|:--------------------------|--------:|
| family_robust_candidate   |       4 |
| family_invalid_or_sparse  |       3 |
| family_concentrated       |       1 |

### Stress
| stress_status   |   count |
|:----------------|--------:|
| stress_survives |      65 |

### Role Classification
| allowed_next_step          |   count |
|:---------------------------|--------:|
| eligible_for_R6_validation |       2 |
| needs_more_data            |       2 |
| blocked_missing_data       |       2 |
| keep_as_risk_monitor       |       1 |
| keep_as_avoid_candidate    |       1 |

## Family Summary

| family                | role           |   factor_count |   factor_horizon_count |   horizon_count | member_factors                                            |   mean_directional_edge |   ordinary_same_direction_rate |   monthly_same_direction_rate |   quarterly_same_direction_rate |   top_factor_contribution |   top_horizon_contribution | family_bootstrap_status   |
|:----------------------|:---------------|---------------:|-----------------------:|----------------:|:----------------------------------------------------------|------------------------:|-------------------------------:|------------------------------:|--------------------------------:|--------------------------:|---------------------------:|:--------------------------|
| momentum_continuation | alpha          |              3 |                     12 |               5 | ret_12h;ret_24h;ret_4h                                    |              0.00591011 |                        0.9998  |                      0.9987   |                        0.99995  |                  0.524805 |                   0.250421 | family_robust_candidate   |
| breakout_conviction   | alpha          |              4 |                     20 |               5 | body_ratio;breakout_distance_atr;close_location;range_atr |              0.00776179 |                        0.99976 |                      0.99997  |                        0.99991  |                  0.299379 |                   0.250315 | family_robust_candidate   |
| volatility_expansion  | risk           |              3 |                     13 |               5 | atr_pct;atr_percentile_200;volatility_ratio_short_long    |              0.00746222 |                        1       |                      0.999985 |                        0.999969 |                  0.438399 |                   0.256674 | family_robust_candidate   |
| shadow_rejection      | alpha_or_avoid |              2 |                     10 |               5 | lower_shadow_ratio;upper_shadow_ratio                     |              0.00507121 |                        0.99894 |                      0.99958  |                        0.9998   |                  0.501738 |                   0.256796 | family_robust_candidate   |
| compression_expansion | alpha          |              1 |                      5 |               5 | inside_bar_compression                                    |              0.00738523 |                        0.99996 |                      1        |                        1        |                  1        |                   0.206802 | family_concentrated       |
| bad_entry_avoidance   | avoid          |              0 |                      0 |               0 |                                                           |            nan          |                      nan       |                    nan        |                      nan        |                nan        |                 nan        | family_invalid_or_sparse  |
| execution_risk        | execution      |              0 |                      0 |               0 |                                                           |            nan          |                      nan       |                    nan        |                      nan        |                nan        |                 nan        | family_invalid_or_sparse  |
| state_risk_multiplier | risk           |              0 |                      0 |               0 |                                                           |            nan          |                      nan       |                    nan        |                      nan        |                nan        |                 nan        | family_invalid_or_sparse  |

## Horizon Decay

| family                | role           | horizons_available   | direction_consistent   |   best_horizon |   best_horizon_contribution | decay_pattern          |
|:----------------------|:---------------|:---------------------|:-----------------------|---------------:|----------------------------:|:-----------------------|
| momentum_continuation | alpha          | 1;4;8;16;32          | True                   |             32 |                    0.275755 | stable_across_horizons |
| breakout_conviction   | alpha          | 1;4;8;16;32          | True                   |             32 |                    0.250315 | stable_across_horizons |
| volatility_expansion  | risk           | 1;4;8;16;32          | True                   |             32 |                    0.313598 | stable_across_horizons |
| shadow_rejection      | alpha_or_avoid | 1;4;8;16;32          | True                   |             32 |                    0.256796 | stable_across_horizons |
| compression_expansion | alpha          | 1;4;8;16;32          | True                   |              8 |                    0.206802 | stable_across_horizons |
| bad_entry_avoidance   | avoid          |                      | False                  |            nan |                  nan        | invalid_or_sparse      |
| execution_risk        | execution      |                      | False                  |            nan |                  nan        | invalid_or_sparse      |
| state_risk_multiplier | risk           |                      | False                  |            nan |                  nan        | invalid_or_sparse      |

## Role Classification

| family                | initial_role   | r5_evidence              | final_research_role   | reason                                                                                      | allowed_next_step          |
|:----------------------|:---------------|:-------------------------|:----------------------|:--------------------------------------------------------------------------------------------|:---------------------------|
| momentum_continuation | alpha          | family_robust_candidate  | alpha                 | Family survived R5 bootstrap and horizon decay is not single-horizon dependent.             | eligible_for_R6_validation |
| breakout_conviction   | alpha          | family_robust_candidate  | alpha                 | Family survived R5 bootstrap and horizon decay is not single-horizon dependent.             | eligible_for_R6_validation |
| volatility_expansion  | risk           | family_robust_candidate  | risk                  | Literature role is risk; preserve as monitor until alpha-vs-risk decomposition is stronger. | keep_as_risk_monitor       |
| shadow_rejection      | alpha_or_avoid | family_robust_candidate  | avoid                 | Evidence should be checked against MAE/tail loss before use as alpha.                       | keep_as_avoid_candidate    |
| compression_expansion | alpha          | family_concentrated      | alpha                 | Family evidence is concentrated in one factor or horizon.                                   | needs_more_data            |
| bad_entry_avoidance   | avoid          | family_invalid_or_sparse | blocked               | No usable current factor evidence or required data is unavailable.                          | needs_more_data            |
| execution_risk        | execution      | family_invalid_or_sparse | blocked               | No usable current factor evidence or required data is unavailable.                          | blocked_missing_data       |
| state_risk_multiplier | risk           | family_invalid_or_sparse | blocked               | No usable current factor evidence or required data is unavailable.                          | blocked_missing_data       |

## Required Answers

1. Family bootstrap pass/fail is reported in `family_bootstrap_summary.csv`.
2. Monthly and quarterly fragility is captured by `monthly_same_direction_rate`, `quarterly_same_direction_rate`, and `family_bootstrap_status`.
3. Best-month and best-quarter dependence is reported in `month_stress_summary.csv`.
4. Single-horizon dependence is reported in `horizon_decay_summary.csv`.
5. Direction consistency across horizons is reported in `horizon_decay_summary.csv`.
6. Alpha/avoid/risk/execution roles are reported in `role_classification.csv`.
7. Selection-on-discovery bias still exists because R2-R5 use the same discovery event table.
8. No family is allowed to become a strategy filter after R5.
9. R6 should only validate families marked `eligible_for_R6_validation`; blocked families need data before validation.
10. R5 is a pressure-test gate, not OOS evidence or simulation approval.
