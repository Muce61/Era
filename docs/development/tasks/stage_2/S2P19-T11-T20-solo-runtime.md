# S2P19-T11～T20 合并 Task 合同

## 状态与范围

- task_ids: [S2P19-T11, S2P19-T12, S2P19-T13, S2P19-T14, S2P19-T15, S2P19-T16, S2P19-T17, S2P19-T18, S2P19-T19, S2P19-T20]
- status: `APPROVED / IMPLEMENTED / FORMAL RUN GATED`
- execution_limit: `S2P19-T20`
- formal_run_executed: `false`
- stage3_locked: `true`

本合同一次性覆盖十个真实 handler 的运行边界。研究算法继续使用 v1.8 已验证的实现，
仅移除外层 adapter plan、独立 approval 和每 Task Catalog/Manifest/Verify/Receipt。

## 统一输入与返回

每个 handler 接收 `TaskExecutionContext`：Task ID、attempt、Authority、inputs lock、
声明的上游完成 Hash、输出根和 checkpoint 回调。固定 registry 必须恰好按顺序绑定
`S2P19-T11`～`S2P19-T20`。

每个 handler 返回研究 payload；runner 将其封装为 `TaskResult`：

- task ID 与 attempt；
- output root / output tree Hash；
- row count；
- metrics；
- checkpoint tip Hash；
- research status。

正式 inputs lock 之前必须由固定 production builder 从历史密封证据和当前预注册配置
自动推导十二类 binding。禁止外部 input-spec、手填 semantic Hash 或仅做 HEX64 格式
检查。每个 entry 同时保存源文件 SHA-256、semantic binding Hash 和固定 rule ID；在
Authority 创建前必须重新推导并逐项相等。Contract Price Catalog binding 必须覆盖
`[2020-01-01, 2026-07-04)` 的 BTC/ETH 全部逐日分区；四处固定 seed 必须一致。

## Task 语义

| Task | 研究责任 | 数据边界 |
|---|---|---|
| S2P19-T11 | 双轨生命周期与来源缺口恢复 | Trades comparator + Contract Price OHLC lifecycle |
| S2P19-T12 | 路径证据 | canonical Trades only |
| S2P19-T13 | MFE/MAE/Time-to-Activation | canonical Trades only |
| S2P19-T14 | First Passage | canonical Trades only |
| S2P19-T15 | AMBIGUOUS | canonical Trades only |
| S2P19-T16 | 条件匹配基线 | 冻结 matching/seed/30-cell |
| S2P19-T17 | Placebo | T16 frozen output |
| S2P19-T18 | Cluster/bootstrap | 冻结 cluster unit |
| S2P19-T19 | 综合证据门 | H2 与生命周期分开报告 |
| S2P19-T20 | 最终验收 | 历史结果、successor、性能、Stage 3 锁 |

## 完成与失败

`TASK_COMPLETED` 是唯一 Task 完成事实，必须绑定上游 Hash、输出树 Hash、行数和研究状态。
缺失上游、重复完成、输出漂移、未知缺失或 Hash 漂移立即停止。可恢复中断写
`TASK_INTERRUPTED`；非恢复错误写 `RUN_FAILED` 并永久 unpublished。任何 fixture PASS
都不构成真实正式研究结果。
