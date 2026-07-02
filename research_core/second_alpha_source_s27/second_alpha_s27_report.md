# S2.7 严格 Exit Window 事件验证报告

data_layer: expanded_discovery / internal_validation
oos_status: not_oos
strategy_backtest_generated: false

## 输入验收

| canonical_s2_exists   | s26_exists   | s26_decision   |   idle_mr1_p4_held_count |   s26_event_count |   s26_mean_fwd_ret_16 | input_validation_status   |
|:----------------------|:-------------|:---------------|-------------------------:|------------------:|----------------------:|:--------------------------|
| True                  | True         | A              |                        0 |              1562 |            0.00191452 | pass                      |

## 核心对照

- after_p4_exit_5_16 mean_fwd_ret_16: 0.0019145152258236917
- after_p4_exit_0_4 mean_fwd_ret_16: 0.0003175101813482271
- deep_idle mean_fwd_ret_16: -0.00032591939827413165
- random_direction_percentile: 1.0
- random_time_percentile: 1.0
- positive_month_rate: 0.6842105263157895
- positive_quarter_rate: 0.5714285714285714
- top1_positive_contribution: 0.025729888460722546

## 必答问题

1. S2.7 输入是否合格：见 s27_input_validation.csv。
2. 5-16 窗口是否优于相邻窗口：见 exit_window_neighbor_comparison.csv。
3. edge 是否来自方向判断：见 exit_window_random_direction_baseline.csv。
4. edge 是否优于更严格随机时间基线：见 exit_window_random_time_baseline.csv。
5. 是否跨 symbol 和 side 稳定：见 exit_window_direction_symbol_matrix.csv。
6. 是否多数月份/季度为正：见 monthly/quarterly stability。
7. 是否依赖少数事件、月份或季度：见 stress summary 和 top dependency。
8. 与 P4 是否低相关：见 exit_window_p4_correlation.csv。
9. 是否能改善 P4 弱月份：见 exit_window_drawdown_overlap_proxy.csv。
10. 是否允许进入 S3：见 exit_window_decision_summary.csv。

## 最终结论

B. 有弱 edge，但仍需更长历史或更严格随机基线

本阶段没有生成策略回测，不是 OOS，也没有改变 P4 或 IDLE_MR1 规则。
