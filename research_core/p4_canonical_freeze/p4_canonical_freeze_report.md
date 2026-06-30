# P4 Canonical Freeze Readiness Report

data_layer: expanded_discovery
oos_status: not_oos
paper_trading_status: prohibited
live_trading_status: prohibited

## Final Decision

freeze_decision: A. one_candidate_frozen_for_future_shadow
oos_decision: B. no_proven_untouched_historical_interval
shadow_decision: A. eligible_for_future_shadow
selected_candidate_id: C1

## Candidate Gate Results

| candidate_id   |   gate_base_cost_profit_factor | gate_base_cost_total_return   |   gate_max_drawdown | gate_liquidation_count   |   gate_top1_profit_contribution | gate_remove_top3_return   |   gate_positive_valid_year_rate | gate_positive_walk_forward_window_rate   |   gate_pf_gt_1_walk_forward_window_rate |   gate_block_bootstrap_positive_probability |   gate_instrument_status | gate_reproduction_status   | hard_gate_pass   | selection_rank   | freeze_decision   | rejection_reason                                                                                                                  |   gate_portfolio_max_drawdown |   gate_portfolio_profit_factor |   gate_longest_drawdown_duration |
|:---------------|-------------------------------:|:------------------------------|--------------------:|:-------------------------|--------------------------------:|:--------------------------|--------------------------------:|:-----------------------------------------|----------------------------------------:|--------------------------------------------:|-------------------------:|:---------------------------|:-----------------|:-----------------|:------------------|:----------------------------------------------------------------------------------------------------------------------------------|------------------------------:|-------------------------------:|---------------------------------:|
| C1             |                              1 | True                          |                   1 | True                     |                               1 | True                      |                               1 | True                                     |                                       1 |                                           1 |                        1 | True                       | True             | 1                | frozen_candidate  |                                                                                                                                   |                           nan |                            nan |                              nan |
| C2             |                              1 | True                          |                   0 | True                     |                               0 | True                      |                               0 | False                                    |                                       0 |                                           1 |                        1 | True                       | False            |                  | rejected          | max_drawdown;top1_profit_contribution;positive_valid_year_rate;positive_walk_forward_window_rate;pf_gt_1_walk_forward_window_rate |                           nan |                            nan |                              nan |
| C3             |                            nan | True                          |                 nan | True                     |                             nan | True                      |                             nan | False                                    |                                     nan |                                         nan |                      nan | True                       | False            |                  | rejected          | positive_walk_forward_window_rate                                                                                                 |                             1 |                              1 |                                1 |

## Candidate Metrics

| candidate_id   |   trade_count |   base_cost_total_return |   base_cost_profit_factor |   base_cost_max_drawdown |   positive_valid_year_rate |   positive_walk_forward_window_rate |   pf_gt_1_walk_forward_window_rate |   top1_profit_contribution |   remove_top3_return |   block_bootstrap_positive_probability |
|:---------------|--------------:|-------------------------:|--------------------------:|-------------------------:|---------------------------:|------------------------------------:|-----------------------------------:|---------------------------:|---------------------:|---------------------------------------:|
| C1             |           349 |                  1.33643 |                   1.38965 |                -0.182517 |                   0.714286 |                            0.666667 |                           0.666667 |                   0.180514 |             0.799247 |                                  0.994 |
| C2             |           341 |                  2.729   |                   1.35345 |                -0.261918 |                   0.571429 |                            0.555556 |                           0.555556 |                   0.312841 |             1.30473  |                                  0.99  |
| C3             |           690 |                  2.03272 |                   1.36458 |                -0.168527 |                   0.714286 |                            0.555556 |                           0.555556 |                   0.210001 |             1.32058  |                                  1     |

## Instrument Audit

| symbol   | ohlcv_source                                           | market_type                                                     | price_type   | leverage_supported   | funding_required   | funding_data_available   | funding_coverage_start   | funding_coverage_end   | fee_source                         | slippage_assumption                | execution_completeness           | instrument_status   |
|:---------|:-------------------------------------------------------|:----------------------------------------------------------------|:-------------|:---------------------|:-------------------|:-------------------------|:-------------------------|:-----------------------|:-----------------------------------|:-----------------------------------|:---------------------------------|:--------------------|
| BTCUSDT  | /Users/muce/1m_data/long_history_1m/merged/BTCUSDT.csv | USDT perpetual assumed from Binance futures long-history source | 1m OHLCV     | True                 | True               | False                    |                          |                        | project default frozen assumptions | project default frozen assumptions | 1m open/high/low/close available | funding_incomplete  |
| ETHUSDT  | /Users/muce/1m_data/long_history_1m/merged/ETHUSDT.csv | USDT perpetual assumed from Binance futures long-history source | 1m OHLCV     | True                 | True               | False                    |                          |                        | project default frozen assumptions | project default frozen assumptions | 1m open/high/low/close available | funding_incomplete  |

## Integrity

prefix_invariance_status: pass
future_mutation_status: pass
lookahead_violation_count: 0

## Answers

P4 Long唯一规范固定为 P4_BREAKOUT_TOP20 + P4_G1_GATE + fixed_1x，15m完成时间信号，1m open执行。
旧左标签15m结果全部标记为 time_alignment_invalid。本轮没有证明任何历史严格OOS区间，因此只能等待未来Shadow。
