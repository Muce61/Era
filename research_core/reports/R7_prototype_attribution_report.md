# R7 Prototype Attribution Report

data_layer: discovery
data_coverage: 2024-01-01 00:00 UTC to 2026-06-24 12:05 UTC
oos_status: not_oos
simulation_approval: not_allowed

R7 only compares event-level forward labels. It does not run trade accounting and does not create deployable strategy rules.

## H16 Prototype Snapshot

- `P0_ALL_TREND_CONTEXT`: events=1278, h16_mean=0.006426, month_positive=90.00%, tail=not_tail_dependent, decision=explanatory_only
- `P1_C1_FIRST_BREAKOUT`: events=371, h16_mean=0.007935, month_positive=96.67%, tail=not_tail_dependent, decision=explanatory_only
- `P2_STRONG_BREAKOUT`: events=777, h16_mean=0.007630, month_positive=96.67%, tail=not_tail_dependent, decision=explanatory_only
- `P3_MOMENTUM_TOP20`: events=256, h16_mean=0.011591, month_positive=90.00%, tail=not_tail_dependent, decision=candidate_for_R8_backtest
- `P4_BREAKOUT_TOP20`: events=256, h16_mean=0.013303, month_positive=96.15%, tail=not_tail_dependent, decision=candidate_for_R8_backtest
- `P5_MOMENTUM_AND_BREAKOUT_TOP40`: events=188, h16_mean=0.013358, month_positive=88.24%, tail=not_tail_dependent, decision=candidate_for_R8_backtest
- `P6_MOMENTUM_OR_BREAKOUT_TOP20`: events=454, h16_mean=0.011073, month_positive=93.10%, tail=not_tail_dependent, decision=candidate_for_R8_backtest
- `P7_C1_PLUS_MOMENTUM_TOP40`: events=52, h16_mean=0.012286, month_positive=50.00%, tail=not_tail_dependent, decision=explanatory_only
- `P8_C1_PLUS_BREAKOUT_TOP40`: events=197, h16_mean=0.010823, month_positive=92.31%, tail=not_tail_dependent, decision=explanatory_only

## H16 Incremental Attribution

- `P3_vs_P0`: incremental_mean=0.005165, plus_1atr_delta=-0.003747, mae_delta=-0.000031, interpretation=weak_incremental
- `P4_vs_P0`: incremental_mean=0.006877, plus_1atr_delta=0.093909, mae_delta=0.004965, interpretation=clear_incremental
- `P5_vs_P0`: incremental_mean=0.006932, plus_1atr_delta=0.096402, mae_delta=0.003067, interpretation=clear_incremental
- `P6_vs_P0`: incremental_mean=0.004647, plus_1atr_delta=0.037845, mae_delta=0.001724, interpretation=clear_incremental
- `P7_vs_P1`: incremental_mean=0.004351, plus_1atr_delta=-0.028768, mae_delta=0.002202, interpretation=weak_incremental
- `P8_vs_P1`: incremental_mean=0.002888, plus_1atr_delta=0.057233, mae_delta=0.002421, interpretation=clear_incremental
- `P4_vs_P2`: incremental_mean=0.005673, plus_1atr_delta=0.051390, mae_delta=0.004226, interpretation=clear_incremental
- `P8_vs_P2`: incremental_mean=0.003193, plus_1atr_delta=0.049050, mae_delta=0.003131, interpretation=clear_incremental

## Required Answers

1. P3 momentum 是否优于 P0：`weak_incremental`，h16 增量均值 0.005165。
2. P4 breakout 是否优于 P0：`clear_incremental`，h16 增量均值 0.006877。
3. P5 交集是否优于单因子：P5 决策 `candidate_for_R8_backtest`；需要同时对照 P3/P4，不视为独立策略结论。
4. P6 并集是否更稳健：P6 月度正收益率 93.10%，尾部状态 `not_tail_dependent`。
5. P7 是否改善 C1：`weak_incremental`。
6. P8 是否改善 C1：`clear_incremental`；若 C1 重合高，只能作为 C1 强度解释。
7. 极端事件依赖：[{'prototype': 'P0_ALL_TREND_CONTEXT', 'tail_dependence_status': 'not_tail_dependent'}, {'prototype': 'P1_C1_FIRST_BREAKOUT', 'tail_dependence_status': 'not_tail_dependent'}, {'prototype': 'P2_STRONG_BREAKOUT', 'tail_dependence_status': 'not_tail_dependent'}, {'prototype': 'P3_MOMENTUM_TOP20', 'tail_dependence_status': 'not_tail_dependent'}, {'prototype': 'P4_BREAKOUT_TOP20', 'tail_dependence_status': 'not_tail_dependent'}, {'prototype': 'P5_MOMENTUM_AND_BREAKOUT_TOP40', 'tail_dependence_status': 'not_tail_dependent'}, {'prototype': 'P6_MOMENTUM_OR_BREAKOUT_TOP20', 'tail_dependence_status': 'not_tail_dependent'}, {'prototype': 'P7_C1_PLUS_MOMENTUM_TOP40', 'tail_dependence_status': 'not_tail_dependent'}, {'prototype': 'P8_C1_PLUS_BREAKOUT_TOP40', 'tail_dependence_status': 'not_tail_dependent'}]。
8. 月度/季度稳定：[{'prototype': 'P0_ALL_TREND_CONTEXT', 'stability_status': 'stable'}, {'prototype': 'P1_C1_FIRST_BREAKOUT', 'stability_status': 'stable'}, {'prototype': 'P2_STRONG_BREAKOUT', 'stability_status': 'stable'}, {'prototype': 'P3_MOMENTUM_TOP20', 'stability_status': 'stable'}, {'prototype': 'P4_BREAKOUT_TOP20', 'stability_status': 'stable'}, {'prototype': 'P5_MOMENTUM_AND_BREAKOUT_TOP40', 'stability_status': 'stable'}, {'prototype': 'P6_MOMENTUM_OR_BREAKOUT_TOP20', 'stability_status': 'stable'}, {'prototype': 'P7_C1_PLUS_MOMENTUM_TOP40', 'stability_status': 'insufficient_sample'}, {'prototype': 'P8_C1_PLUS_BREAKOUT_TOP40', 'stability_status': 'stable'}]。
9. 可进入 R8 最小回测：['P3_MOMENTUM_TOP20', 'P4_BREAKOUT_TOP20', 'P5_MOMENTUM_AND_BREAKOUT_TOP40', 'P6_MOMENTUM_OR_BREAKOUT_TOP20']。
10. 仍然禁止称为 OOS / 模拟盘：是。当前数据仍是 discovery，R7 不允许模拟盘准入。

## R7 Decision Summary

| prototype                      |   event_count_h16 |   mean_ret_h16 |   incremental_vs_base_h16 |   positive_month_rate_h16 | tail_dependence_status_h16   |   c1_overlap_rate | decision_status           | allowed_next_step   |
|:-------------------------------|------------------:|---------------:|--------------------------:|--------------------------:|:-----------------------------|------------------:|:--------------------------|:--------------------|
| P0_ALL_TREND_CONTEXT           |              1278 |     0.0064257  |                0          |                  0.9      | not_tail_dependent           |          0.290297 | explanatory_only          | keep_as_explanation |
| P1_C1_FIRST_BREAKOUT           |               371 |     0.00793489 |                0          |                  0.966667 | not_tail_dependent           |          1        | explanatory_only          | keep_as_explanation |
| P2_STRONG_BREAKOUT             |               777 |     0.00762957 |                0          |                  0.966667 | not_tail_dependent           |          0.314028 | explanatory_only          | keep_as_explanation |
| P3_MOMENTUM_TOP20              |               256 |     0.0115907  |                0.00516497 |                  0.9      | not_tail_dependent           |          0.101562 | candidate_for_R8_backtest | R8_minimal_backtest |
| P4_BREAKOUT_TOP20              |               256 |     0.0133027  |                0.00567316 |                  0.961538 | not_tail_dependent           |          0.40625  | candidate_for_R8_backtest | R8_minimal_backtest |
| P5_MOMENTUM_AND_BREAKOUT_TOP40 |               188 |     0.0133581  |                0.00693236 |                  0.882353 | not_tail_dependent           |          0.175532 | candidate_for_R8_backtest | R8_minimal_backtest |
| P6_MOMENTUM_OR_BREAKOUT_TOP20  |               454 |     0.011073   |                0.00464734 |                  0.931034 | not_tail_dependent           |          0.259912 | candidate_for_R8_backtest | R8_minimal_backtest |
| P7_C1_PLUS_MOMENTUM_TOP40      |                52 |     0.0122859  |                0.00435101 |                  0.5      | not_tail_dependent           |          1        | explanatory_only          | keep_as_explanation |
| P8_C1_PLUS_BREAKOUT_TOP40      |               197 |     0.0108226  |                0.003193   |                  0.923077 | not_tail_dependent           |          1        | explanatory_only          | keep_as_explanation |
