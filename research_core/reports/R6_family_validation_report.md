# R6 Family Validation Report

event_count: 1278
data_layer: discovery
data_coverage_note: current 2024-01-01 to 2026-06-24 data is not final OOS.

## Decisions
| family                |   wf_pass_rate | stress_bad   | high_corr_with_other_family   |   top20_first_breakout_rate | r6_status                              |
|:----------------------|---------------:|:-------------|:------------------------------|----------------------------:|:---------------------------------------|
| momentum_continuation |              1 | False        | False                         |                    0.101562 | eligible_for_R7_candidate_construction |
| breakout_conviction   |              1 | False        | False                         |                    0.40625  | eligible_for_R7_candidate_construction |

## Score Correlation
| score_a                     | score_b                   |   pearson_corr |   spearman_corr |   kendall_corr |   shared_top20_rate |   shared_top40_rate |
|:----------------------------|:--------------------------|---------------:|----------------:|---------------:|--------------------:|--------------------:|
| momentum_continuation_score | breakout_conviction_score |     0.0407151  |      -0.0072023 |    -0.00420587 |            0.227451 |            0.367906 |
| momentum_continuation_score | ema_gap_atr               |     0.244792   |       0.289347  |     0.197654   |            0.321569 |            0.555773 |
| momentum_continuation_score | breakout_distance_atr     |     0.132946   |       0.0844589 |     0.0570023  |            0.235294 |            0.420744 |
| momentum_continuation_score | atr_pct                   |     0.770828   |       0.74668   |     0.563268   |            0.639216 |            0.696673 |
| breakout_conviction_score   | ema_gap_atr               |    -0.015892   |      -0.0050963 |    -0.00332719 |            0.207843 |            0.403131 |
| breakout_conviction_score   | breakout_distance_atr     |     0.818192   |       0.770693  |     0.586171   |            0.807843 |            0.774951 |
| breakout_conviction_score   | atr_pct                   |    -0.0478974  |      -0.0847058 |    -0.0562976  |            0.188235 |            0.365949 |
| ema_gap_atr                 | breakout_distance_atr     |    -0.0544866  |      -0.0458449 |    -0.030506   |            0.196078 |            0.389432 |
| ema_gap_atr                 | atr_pct                   |    -0.0202546  |       0.0255983 |     0.017685   |            0.176471 |            0.410959 |
| breakout_distance_atr       | atr_pct                   |    -0.00894138 |      -0.0460884 |    -0.0309668  |            0.203922 |            0.377691 |

## Walk-forward Summary
| family                |   horizon |   window_count |   valid_window_count |   positive_window_rate |   median_top20_minus_bottom20 |   worst_top20_minus_bottom20 |   best_top20_minus_bottom20 | walk_forward_status   |
|:----------------------|----------:|---------------:|---------------------:|-----------------------:|------------------------------:|-----------------------------:|----------------------------:|:----------------------|
| breakout_conviction   |         1 |              5 |                    5 |                    1   |                    0.00959038 |                  0.00666169  |                  0.0108539  | wf_pass               |
| breakout_conviction   |         4 |              5 |                    5 |                    1   |                    0.0120911  |                  0.00779726  |                  0.0134292  | wf_pass               |
| breakout_conviction   |         8 |              5 |                    5 |                    1   |                    0.0119075  |                  0.00828206  |                  0.0130089  | wf_pass               |
| breakout_conviction   |        16 |              5 |                    5 |                    1   |                    0.0105036  |                  0.00297171  |                  0.012754   | wf_pass               |
| breakout_conviction   |        32 |              5 |                    5 |                    1   |                    0.0110582  |                  0.00278928  |                  0.0193365  | wf_pass               |
| momentum_continuation |         1 |              5 |                    5 |                    1   |                    0.00576031 |                  0.00424962  |                  0.00699895 | wf_pass               |
| momentum_continuation |         4 |              5 |                    5 |                    1   |                    0.00829368 |                  0.00358905  |                  0.0102034  | wf_pass               |
| momentum_continuation |         8 |              5 |                    5 |                    0.8 |                    0.00629032 |                 -0.000678673 |                  0.00944186 | wf_pass               |
| momentum_continuation |        16 |              5 |                    5 |                    1   |                    0.00377201 |                  0.00256687  |                  0.00989816 | wf_pass               |
| momentum_continuation |        32 |              5 |                    5 |                    0.6 |                    0.00470774 |                 -0.00259976  |                  0.019031   | wf_pass               |

## C1 Overlap
| family                | score_group   |   event_count |   first_breakout_rate |   strong_breakout_rate |   avg_bars_after_breakout |   avg_breakout_distance_atr |   avg_range_atr |   avg_body_ratio |   avg_close_location |
|:----------------------|:--------------|--------------:|----------------------:|-----------------------:|--------------------------:|----------------------------:|----------------:|-----------------:|---------------------:|
| momentum_continuation | top20         |           256 |              0.101562 |              0.609375  |                       nan |                    0.787839 |         1.93363 |         0.635522 |             0.764239 |
| momentum_continuation | top40         |           256 |              0.101562 |              0.585938  |                       nan |                    0.704143 |         1.8994  |         0.623947 |             0.748984 |
| momentum_continuation | middle20      |           255 |              0.247059 |              0.631373  |                       nan |                    0.764655 |         2.05863 |         0.659763 |             0.771616 |
| momentum_continuation | bottom40      |           256 |              0.40625  |              0.644531  |                       nan |                    0.653594 |         2.13094 |         0.640823 |             0.760849 |
| momentum_continuation | bottom20      |           255 |              0.596078 |              0.568627  |                       nan |                    0.551472 |         2.19156 |         0.626827 |             0.740452 |
| breakout_conviction   | top20         |           256 |              0.40625  |              0.917969  |                       nan |                    1.69518  |         3.10329 |         0.832746 |             0.87864  |
| breakout_conviction   | top40         |           256 |              0.363281 |              0.886719  |                       nan |                    0.7464   |         2.23383 |         0.756265 |             0.841735 |
| breakout_conviction   | middle20      |           255 |              0.247059 |              0.745098  |                       nan |                    0.491601 |         1.78437 |         0.669786 |             0.796104 |
| breakout_conviction   | bottom40      |           256 |              0.25     |              0.4375    |                       nan |                    0.343696 |         1.64384 |         0.545793 |             0.711416 |
| breakout_conviction   | bottom20      |           255 |              0.184314 |              0.0509804 |                       nan |                    0.182316 |         1.44483 |         0.381371 |             0.557628 |

## Stress Summary
| family                |   horizon |   original_top20_minus_bottom20 |   remove_best_1_month |   remove_best_2_month |   remove_best_quarter |   remove_top1pct_events |   remove_top5pct_events | stress_status   |
|:----------------------|----------:|--------------------------------:|----------------------:|----------------------:|----------------------:|------------------------:|------------------------:|:----------------|
| momentum_continuation |         1 |                      0.00500273 |            0.0047351  |            0.00462882 |            0.00473273 |              0.00357425 |              0.00218214 | stress_pass     |
| momentum_continuation |         4 |                      0.00554756 |            0.00528809 |            0.00515506 |            0.00499884 |              0.00381258 |              0.00185167 | stress_pass     |
| momentum_continuation |         8 |                      0.00518818 |            0.0049348  |            0.00413164 |            0.00429043 |              0.00293506 |              0.00119319 | stress_pass     |
| momentum_continuation |        16 |                      0.00735512 |            0.00716178 |            0.0060107  |            0.00609848 |              0.00474666 |              0.00223168 | stress_pass     |
| momentum_continuation |        32 |                      0.00811394 |            0.00788533 |            0.00730227 |            0.00735509 |              0.00472259 |              0.00245102 | stress_pass     |
| breakout_conviction   |         1 |                      0.00948798 |            0.00922756 |            0.00917286 |            0.00905326 |              0.00813927 |              0.00649476 | stress_pass     |
| breakout_conviction   |         4 |                      0.010086   |            0.00964611 |            0.00957062 |            0.00983912 |              0.00810577 |              0.00622485 | stress_pass     |
| breakout_conviction   |         8 |                      0.0106376  |            0.0103614  |            0.0101806  |            0.0102678  |              0.00870627 |              0.00635741 | stress_pass     |
| breakout_conviction   |        16 |                      0.0109909  |            0.010699   |            0.0104203  |            0.0103684  |              0.0095274  |              0.00699938 | stress_pass     |
| breakout_conviction   |        32 |                      0.0131269  |            0.0126333  |            0.0121272  |            0.0121751  |              0.0123253  |              0.00918357 | stress_pass     |

## Required Answers

1. Momentum and breakout decisions are in `r6_decision_summary.csv`.
2. Correlation and redundancy are in `family_score_correlation.csv`.
3. C1/FIRST_BREAKOUT overlap is in `c1_overlap_audit.csv`.
4. R6 still has selection-on-discovery bias because it uses the same event table as R2-R5.
5. R6 does not permit live strategy filters or simulation approval.
6. New unseen data is still required before any OOS claim.
