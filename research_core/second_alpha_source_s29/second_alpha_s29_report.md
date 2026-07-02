# S2.9 Exit-Window Edge 失效来源拆解报告

data_layer: expanded_discovery_long_history
oos_status: not_oos
strategy_backtest_generated: false

## 输入验收

| s28_exists   | events_available   | s28_decision   |   event_count | symbols_available               |   symbol_count | input_validation_status   | data_layer                      | oos_status   |
|:-------------|:-------------------|:---------------|--------------:|:--------------------------------|---------------:|:--------------------------|:--------------------------------|:-------------|
| True         | True               | B              |          5358 | BNBUSDT,BTCUSDT,ETHUSDT,SOLUSDT |              4 | pass                      | expanded_discovery_long_history | not_oos      |

## 归因摘要

- BTC failure_reason: negative_mean
- ETH failure_reason: positive_but_top_trade_dependent
- SOL failure_reason: positive_and_stable
- BNB failure_reason: positive_and_stable
- dominant reversion/continuation diagnosis: mixed_state
- decision: A. edge 可解释且弱点可控，可进入 S3 最小策略原型

## 必答问题

1. BTC 为什么拖累：见 `symbol_failure_attribution.csv`，当前分类为 `negative_mean`。
2. ETH 为什么不稳：见 `symbol_failure_attribution.csv`，当前分类为 `positive_but_top_trade_dependent`。
3. SOL/BNB 为什么更强：见 `symbol_failure_attribution.csv`，SOL=`positive_and_stable`，BNB=`positive_and_stable`。
4. 失败年份/季度共同特征：见 `year_failure_attribution.csv` 与 `quarter_failure_attribution.csv`。
5. 这是均值回归还是状态效应：主诊断 `mixed_state`，见 `reversion_vs_continuation_diagnostics.csv`。
6. continuation breakout 风险：见 `reversion_vs_continuation_diagnostics.csv` 和失败案例样本。
7. 与 P4 的互补性：沿用 S2.8 `s28_p4_weak_month_overlap.csv`，并在 explainability 中汇总。
8. 是否进入 S3/S2.10/停止：见 `s29_decision_summary.csv`。
9. 当前仍然不是 OOS：是，长历史只标记 expanded_discovery_long_history。
10. 下一阶段：若结论为 B，进入 S2.10 做 P4 exit 后状态分类验证；若 A 才能进入 S3。

## Explainability

| question         | answer                                                                    | evidence_file                             | evidence_metric                                 | interpretation                                             |
|:-----------------|:--------------------------------------------------------------------------|:------------------------------------------|:------------------------------------------------|:-----------------------------------------------------------|
| BTC 为什么弱     | BTC mean 为负，优先归因为 negative_mean；不是随机基线缺失问题时仍需降级。 | symbol_failure_attribution.csv            | negative_mean                                   | BTC 是当前候选不能直接进 S3 的核心拖累之一。               |
| ETH 为什么不稳   | ETH 若 remove_top3 后接近 0 或为负，说明稳定性不足。                      | symbol_failure_attribution.csv            | positive_but_top_trade_dependent                | ETH 可保留观察，但不能单独证明 edge。                      |
| SOL/BNB 为什么强 | SOL/BNB 的均值、随机基线和 P4 弱月互补性更好。                            | symbol_failure_attribution.csv            | SOL=positive_and_stable;BNB=positive_and_stable | 优势有标的集中风险，不能直接删掉 ETH/BTC 后策略化。        |
| 失败年份原因     | 失败年份若不是全标的同时失败，则更像状态/标的混合问题。                   | year_failure_attribution.csv              | broad_symbol_failure_years=0                    | 需要先做状态分类，而不是直接回测。                         |
| 是否真回归       | 由 mean_reversion_rate 与 continuation_breakout_rate 判断。               | reversion_vs_continuation_diagnostics.csv | mixed_state                                     | 如果 mixed_state 为主，下一阶段应转向 P4 exit 后状态分类。 |
| 是否与 P4 互补   | P4 弱/亏损月份中 S2.8 正收益比例接近或高于门槛。                          | s28_p4_weak_month_overlap.csv             | neg=0.596;weak=0.595                            | 互补性初步成立，但还不是策略准入证据。                     |
| 是否值得进入 S3  | explainable_edge_candidate_for_S3                                         | s29_decision_summary.csv                  | explainable_edge_candidate_for_S3               | S2.9 不生成策略回测。                                      |

## 最终结论

A. edge 可解释且弱点可控，可进入 S3 最小策略原型

本阶段没有生成策略回测，没有修改 P4 或 IDLE_MR1，也没有把长历史称为 OOS。
