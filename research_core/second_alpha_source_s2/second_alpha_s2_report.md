# Canonical S2 第二类 Alpha 事件研究报告

data_layer: expanded_discovery / internal_validation
oos_status: not_oos
strategy_backtest_generated: false

## Canonical Checks

- event_count_total: 64501
- idle_mr1_event_count: 24067
- idle_mr1_p4_held_count: 0
- after_p4_exit_5_16_count: 1562

## Decisions

| candidate                          |   event_count |   mean_fwd_16 |   positive_symbol_count |   percentile_vs_random |   bootstrap_positive_rate |   positive_year_rate |   top1_positive_contribution |   remove_top3_mean_fwd_ret | decision            |
|:-----------------------------------|--------------:|--------------:|------------------------:|-----------------------:|--------------------------:|---------------------:|-----------------------------:|---------------------------:|:--------------------|
| FB2_FAILED_BREAKOUT_FAST_REVERSION |          3718 |  -0.000178353 |                       1 |             0.520958   |                     0.226 |             0.666667 |                   0.0230555  |               -0.000447915 | event_research_only |
| MR2_DEVIATION_CONFIRMED_REVERSION  |         32976 |  -0.000111313 |                       2 |             0.00199601 |                     0.068 |             0.333333 |                   0.00351399 |               -0.000160848 | event_research_only |
| IDLE_MR1_P4_IDLE_REVERSION         |         24067 |  -1.53834e-05 |                       1 |             1          |                     0.446 |             0.333333 |                   0.00458088 |               -8.45813e-05 | event_research_only |
| RV1_LITE_ETHBTC_RELATIVE           |          3740 |  -0.000729595 |                       0 |             0.473054   |                     0     |             0.666667 |                   0.00652398 |               -0.00077859  | event_research_only |

本阶段只提供 canonical S2 事件研究输入，不允许直接策略化。
