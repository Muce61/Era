# S2P18-T16 — 条件匹配基线等价加速与重跑

- task_id: S2P18-T16
- version: 1.0
- status: SUPERSEDED_UNEXECUTED / successor `S2P19-T16`
- dependencies: `S2P18-T11`、`S2P18-T13`、`S2P18-T15` formal Verify PASS

## 合同

保持既有 matching、30-cell matrix、固定 seed、缺口、cluster 和 TRAIN-only quintile
合同不变。按分区/row group/anchor 批量处理；同一物理 control anchor 只分类一次；
一次计算最大 horizon 并派生 T1–T4；输出边界才进行规范化与 Hash。

## 验收

新旧 matching、标签、统计摘要与规范化 Hash 完全一致；相对 main 同语义基线至少
`2×`，峰值 RSS `≤3 GiB`。任何 H2 差异先判为
`BLOCKED_ENGINE_SEMANTIC_DRIFT`，不能解释为策略改善。
