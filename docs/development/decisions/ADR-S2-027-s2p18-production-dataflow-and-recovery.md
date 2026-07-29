# ADR-S2-027 — S2P18 production 数据流、输入目录与恢复边界

## 状态

SUPERSEDED_UNEXECUTED — 2026-07-29；由 ADR-S2-028 / Plan v1.9 替代

## 决定

OQ-S2-013 按最小合同修复：

1. 正式 adapter 冻结前，必须用完整周期
   `[2020-01-01, 2026-07-04)` 来源审计工具生成并验证 Contract Price 分区 Catalog；
2. Authority 必须绑定一个不可变 input Catalog。该 Catalog 同时记录十二类输入的绝对
   路径、文件 SHA-256 与语义 binding Hash；任一文件、路径或 Hash 漂移均失败关闭；
3. `S2P18-T12`–`S2P18-T18` 的 H2 估计对象只使用 canonical Trades，不能把 T11 的
   Contract Price OHLC 粗边界分类当成 H2 标签。双轨生命周期仅沿
   `T11 → T19 → T20` 分支汇总；
4. 十个 S2P18 production adapter 可以复用旧实现中的数学引擎，但必须产生新的
   S2P18 receipt、Catalog、Manifest 与 Verify。旧 Authority、Run、receipt、固定计数
   和任务身份均不得继承；
5. 可恢复中断写成同一 Run、同一 Task 的 `INTERRUPTED` checkpoint。重试创建新的
   append-only attempt，保留旧 attempt 和日志；终态 producer 失败仍将 Run 冻结为
   `FAILED_UNPUBLISHED`，不得恢复为 PASS。

## 不改变的结论

本 ADR 不改 BTC H2 Primary、matching、AMBIGUOUS、cluster、固定 seed 或失败线，不把
生命周期变成 H2 Primary，不批准正式 Run，也不解锁 Stage 3。历史
`PRIMARY_FAILED` 与 `STAGE2_NO_GO_CURRENT_EVIDENCE` 保持不可变。
