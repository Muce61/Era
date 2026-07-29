# ADR-S2-029：密封证据采用与可恢复 Solo Runtime

## 状态

`APPROVED / IMPLEMENTED_VALIDATED / PREPARE_PENDING / FORMAL RUN NOT AUTHORIZED`

## 决定

Plan v1.9 保留为 `SUPERSEDED_UNEXECUTED`。Plan v1.10 使用新的
`S2P110-T11`～`S2P110-T20` 身份，采用 Stage 1、T10 和已发布 T12～T18 的不可变正式
证据，只重新执行改变了证据问题的 T11 lifecycle，以及综合 T19/T20。

adoption 是新 Run 的显式完成模式，不是伪造新计算。每个 adoption descriptor 必须绑定
源 Task、Run、receipt/Verify、Manifest/Catalog、输出 Hash、数据范围和当前冻结研究合同。
任何源为 FAILED、unpublished、predecessor、探索性或 Hash 不闭合均失败关闭。

`prepare` 不再逐行重扫 canonical Trades。它从 Stage 1 receipt/Catalog/Quality 采用 gap
和 Logical Hash 事实，只对无法由唯一封条确定或发生元数据漂移的文件定向重验。

checkpoint 必须保存恢复 cursor、完成分片身份/Hash、producer state Hash、确定性合并顺序
和剩余单元。新 attempt 验证旧 checkpoint 后只执行剩余分片。Task 完成时密封
`task-files.json`；下游验证文件清单和根 Hash，最终 Verify 对新输出执行一次独立全量 Hash。

## 不变项

- `RESEARCH-S2-CONDITIONAL-LIFECYCLE`
- `DATA-HISTORICAL-NO-FAKE-EXECUTION`
- `STRATEGY-V1-PRICE-ONLY-HISTORICAL`
- `RESEARCH-H3-CONDITIONAL-ROUND-PROB`
- `RESEARCH-LOCKED-REPLAY-ONCE`
- Authority-before-Run、唯一锁、append-only event ledger、附录 J、原子发布和 Stage 3 锁。
