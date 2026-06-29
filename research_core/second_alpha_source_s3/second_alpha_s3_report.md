# S3 Exit-Window IDLE_MR1 最小策略原型回测报告

data_layer: expanded_discovery_long_history
oos_status: not_oos
funding_status: unavailable

## 输入验收

| s29_exists   | s29_decision   | events_available   |   event_count | symbols_available               |   symbol_count | candidate                  | p4_state_bucket         | input_validation_status   | data_layer                      | oos_status   |
|:-------------|:---------------|:-------------------|--------------:|:--------------------------------|---------------:|:---------------------------|:------------------------|:--------------------------|:--------------------------------|:-------------|
| True         | A              | True               |          5358 | ETHUSDT,BTCUSDT,SOLUSDT,BNBUSDT |              4 | IDLE_MR1_P4_IDLE_REVERSION | after_p4_exit_5_16_bars | pass                      | expanded_discovery_long_history | not_oos      |

## 核心结果

| symbol   | side_scope   | sizing_mode   |   trade_count |   total_return |   annualized_return |   max_drawdown |   profit_factor |   win_rate |   avg_win |   avg_loss |   payoff_ratio |   avg_bars_held |   median_bars_held |   fee_to_gross_profit_ratio | funding_status   |   final_equity |   top1_profit_contribution |   top3_profit_contribution |   top5_profit_contribution | longest_drawdown_duration   | sample_status   |
|:---------|:-------------|:--------------|--------------:|---------------:|--------------------:|---------------:|----------------:|-----------:|----------:|-----------:|---------------:|----------------:|-------------------:|----------------------------:|:-----------------|---------------:|---------------------------:|---------------------------:|---------------------------:|:----------------------------|:----------------|
| ALL      | both         | fixed_1x      |          2642 |      -0.650768 |           -0.149667 |      -0.653581 |        0.712142 |   0.333838 |    7.3014 |   -5.13802 |        1.42105 |         5.54219 |                3.4 |                    0.236706 | unavailable      |        349.232 |                        nan |                        nan |                        nan | 2368 days 22:44:00          | valid           |

## 必答问题

1. 事件 edge 是否转化为真实交易收益：见 `s3_backtest_summary.csv` 的 ALL fixed_1x。
2. 交易成本是否吃掉 edge：见 `fee_to_gross_profit_ratio`。
3. BTC 是否仍拖累：见 `s3_symbol_side_summary.csv`。
4. ETH 是否仍头部依赖：见 `s3_tail_dependency.csv`。
5. SOL/BNB 是否仍强：见 `s3_backtest_summary.csv` 和 symbol-side summary。
6. long/short 是否都值得保留：long_only/short_only 只作诊断，见 summary。
7. 与 P4 是否低相关：见 `s3_p4_complement_summary.csv`。
8. 是否改善 P4 弱月份：见 `s3_p4_complement_summary.csv`。
9. 组合后是否降低回撤或缩短回撤时间：见 `s3_portfolio_comparison.csv`，当前 P4 侧为月度 proxy。
10. 是否允许进入 S4：见 `s3_decision_summary.csv`。

## Event-to-Trade Conversion

| symbol   | side   |   event_count |   trade_count |   conversion_rate |   ignored_due_to_position_count |   missing_execution_count |   avg_bars_held |   median_bars_held |
|:---------|:-------|--------------:|--------------:|------------------:|--------------------------------:|--------------------------:|----------------:|-------------------:|
| BNBUSDT  | long   |          2692 |          1332 |          0.494799 |                            1360 |                         0 |         5.75305 |            3.6     |
| BNBUSDT  | short  |           174 |           120 |          0.689655 |                              54 |                         0 |         3.42889 |            2.03333 |
| BTCUSDT  | long   |          2496 |          1158 |          0.463942 |                            1338 |                         0 |         5.23984 |            3       |
| BTCUSDT  | short  |           142 |           100 |          0.704225 |                              42 |                         0 |         2.83333 |            1.86667 |
| ETHUSDT  | long   |          2478 |          1180 |          0.47619  |                            1298 |                         0 |         6.05819 |            3.8     |
| ETHUSDT  | short  |           160 |           132 |          0.825    |                              28 |                         0 |         3.47475 |            2.03333 |
| SOLUSDT  | long   |          2396 |          1140 |          0.475793 |                            1256 |                         0 |         5.95579 |            4.06667 |
| SOLUSDT  | short  |           178 |           122 |          0.685393 |                              56 |                         0 |         3.79016 |            2.13333 |

## Portfolio Comparison

| portfolio_mode                       |   trade_count |   total_return |   annualized_return |   max_drawdown |   profit_factor |   win_rate | longest_drawdown_duration   |   top1_profit_contribution |   monthly_corr_between_components |   p4_weak_month_improvement_rate | decision_note                                              |
|:-------------------------------------|--------------:|---------------:|--------------------:|---------------:|----------------:|-----------:|:----------------------------|---------------------------:|----------------------------------:|---------------------------------:|:-----------------------------------------------------------|
| A_P4_only_proxy                      |          3931 |       1.90378  |                 nan |     nan        |      nan        | nan        |                             |                        nan |                          0.201924 |                         0.179487 | P4 monthly proxy only                                      |
| B_S3_only                            |          2642 |      -0.650768 |                 nan |      -0.653581 |        0.712142 |   0.333838 | 2368 days 22:44:00          |                        nan |                          0.201924 |                         0.179487 | S3 standalone realized trades                              |
| C_P4_priority_proxy                  |          2642 |       0.614398 |                 nan |     nan        |      nan        | nan        |                             |                        nan |                          0.201924 |                         0.179487 | Proxy: P4 priority approximated by monthly component blend |
| D_P4_S3_independent_equal_risk_proxy |          2642 |       0.614398 |                 nan |     nan        |      nan        | nan        |                             |                        nan |                          0.201924 |                         0.179487 | Proxy: no position-level P4 replay generated in S3         |

## 最终结论

C. 事件 edge 被交易成本 / 持仓冲突 / 退出规则吃掉

本阶段不称为 OOS，不作为模拟盘或实盘准入依据。
