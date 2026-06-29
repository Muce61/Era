# S2.8 长历史稳定性与 P4 弱期互补性补证报告

data_layer: expanded_discovery_long_history
oos_status: not_oos
strategy_backtest_generated: false

## 输入验收

| s27_exists   | s27_decision   | long_history_data_available   | symbols_available               |   available_symbol_count | input_validation_status   |
|:-------------|:---------------|:------------------------------|:--------------------------------|-------------------------:|:--------------------------|
| True         | B              | True                          | ETHUSDT,BTCUSDT,SOLUSDT,BNBUSDT |                        4 | pass                      |

## 核心指标

- overall_mean_fwd_ret_16: 0.0009599131020932379
- positive_year_rate: 0.5714285714285714
- positive_quarter_rate: 0.5769230769230769
- positive_symbol_count: 3
- random_time_percentile_mean: 0.9723425524825059
- fallback_match_rate_mean: 0.0005686125852918878
- p4_negative_month_positive_rate: 0.5956155646308448
- p4_weak_month_positive_rate: 0.5948722910216718

## 必答问题

1. 长历史是否支持 after_p4_exit_5_16：见 long_history_exit_window_summary.csv 和 decision。
2. 是否多数年份和季度为正：见 yearly/quarterly summary。
3. 是否跨 ETH/BTC/SOL/BNB 有效：见 long_history_exit_window_summary.csv。
4. long/short 是否都有效：见 long_history_symbol_side_matrix.csv。
5. high_vol 是否危险：见 long_history_regime_summary.csv。
6. 是否优于长历史 full market-state random baseline：见 s28_random_time_baseline_long_history.csv。
7. 是否与 P4 低相关：见 s28_p4_correlation.csv。
8. 是否能补 P4 亏损或弱收益月份：见 s28_p4_weak_month_overlap.csv。
9. 是否依赖少数年份、月份、事件或标的：见 s28_stress_summary.csv。
10. 是否允许进入 S3：见 s28_decision_summary.csv。

## 最终结论

B. 长历史支持但年度稳定性门槛仍不足，P4 互补性初步支持

本阶段没有生成策略回测，不能称为 OOS，也没有改变 P4 或 IDLE_MR1 定义。
