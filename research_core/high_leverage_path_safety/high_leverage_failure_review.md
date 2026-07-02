# High Leverage Failure Review

failure_case_count: 120

## Concentration

| failure_source        | symbol   | prototype                     |   count |
|:----------------------|:---------|:------------------------------|--------:|
| L1_liquidation        | BNBUSDT  | P4_BREAKOUT_TOP20             |       2 |
| L1_liquidation        | BNBUSDT  | P6_MOMENTUM_OR_BREAKOUT_TOP20 |       2 |
| L1_liquidation        | SOLUSDT  | P4_BREAKOUT_TOP20             |       1 |
| L1_liquidation        | SOLUSDT  | P6_MOMENTUM_OR_BREAKOUT_TOP20 |       4 |
| L2_extreme_trade_loss | BNBUSDT  | P4_BREAKOUT_TOP20             |       9 |
| L2_extreme_trade_loss | BNBUSDT  | P6_MOMENTUM_OR_BREAKOUT_TOP20 |      16 |
| L2_extreme_trade_loss | BTCUSDT  | P4_BREAKOUT_TOP20             |       3 |
| L2_extreme_trade_loss | BTCUSDT  | P6_MOMENTUM_OR_BREAKOUT_TOP20 |       4 |
| L2_extreme_trade_loss | ETHUSDT  | P4_BREAKOUT_TOP20             |       7 |
| L2_extreme_trade_loss | ETHUSDT  | P6_MOMENTUM_OR_BREAKOUT_TOP20 |      10 |
| L2_extreme_trade_loss | SOLUSDT  | P4_BREAKOUT_TOP20             |      19 |
| L2_extreme_trade_loss | SOLUSDT  | P6_MOMENTUM_OR_BREAKOUT_TOP20 |      43 |

## Common Traits

- median_atr_pct_rank: 0.8282
- median_breakout_score_quantile: 0.8568
- median_momentum_score_quantile: 0.7725
- median_bars_after_breakout: nan
- 60m safe_for_20x rate: 0.8833

## Plain Answers

1. 爆仓交易在入场前有哪些共同特征：见 Common Traits。
2. 是否集中在某个 symbol：见 Concentration。
3. 是否集中在 P4 或 P6：见 Concentration。
4. 是否发生在高 ATR 环境：以 median_atr_pct_rank 判断。
5. 是否发生在连续亏损之后：L1/L2 交易文件保留权益路径和 trade_return，可进一步逐笔追踪。
6. 是否发生在趋势后半段：以 bars_after_breakout 判断。
7. P4/P6 原因子是否能提前识别这些风险：需要结合 path_safety_factor_summary。
8. 需要的是新 alpha，还是 risk/execution filter：H1 定位为 risk/execution filter 研究，不生成策略规则。
