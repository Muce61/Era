# S2.6 P4 Exit 后 5-16 根回归窗口验证报告

data_layer: expanded_discovery / internal_validation
oos_status: not_oos
strategy_backtest_generated: false

## Canonical S2 验收

| s2_source_path                                                                | source_status   |   event_count_total |   idle_mr1_event_count |   p4_held_event_count |   idle_mr1_p4_held_count |   after_exit_5_16_count | canonical_validation_status   |
|:------------------------------------------------------------------------------|:----------------|--------------------:|-----------------------:|----------------------:|-------------------------:|------------------------:|:------------------------------|
| /Users/muce/PycharmProjects/20260625/Era/research_core/second_alpha_source_s2 | canonical       |               64501 |                  24067 |                  6856 |                        0 |                    1562 | pass                          |

## 核心结果

- 事件数: 1562
- mean_fwd_ret_16: 0.0019145152258236917
- percentile_vs_random: 1.0
- ordinary_bootstrap_positive_rate: 1.0
- monthly_block_positive_rate: 0.958
- top1_positive_contribution: 0.025729888460722546

## 必答问题

1. canonical S2 是否合格：见 canonical_s2_validation.csv。
2. IDLE_MR1 是否还混入 p4_held：canonical 验收要求 idle_mr1_p4_held_count = 0。
3. after_p4_exit_5_16 是否仍为正：见 exit_window_event_summary.csv。
4. 是否优于 full market-state random baseline：见 exit_window_random_baseline_summary.csv。
5. 是否跨至少 2 个标的有效：见 exit_window_symbol_breakdown.csv。
6. 是否依赖少数月份：见 monthly/quarterly breakdown。
7. 是否依赖少数事件：见 exit_window_top_trade_dependency.csv。
8. high_vol 是否危险：见 exit_window_volatility_breakdown.csv。
9. 是否值得进入 S2.7：见 exit_window_decision_summary.csv。
10. 当前仍然不是 OOS：是，不能称为 OOS 或策略结论。

## 最终结论

A. after_p4_exit_5_16 存在明确局部 edge，可进入 S2.7

本阶段没有生成策略回测，也没有改变 P4 或 IDLE_MR1 规则。
