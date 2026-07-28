# S2P18-T19 — successor 综合判定

- task_id: S2P18-T19
- version: 1.0
- status: APPROVED / IMPLEMENTATION CONTRACT FROZEN / FORMAL RUN GATED
- dependencies: `S2P18-T11`、`S2P18-T16`、`S2P18-T17`、`S2P18-T18` formal Verify PASS

## 合同

分别判定历史 H2、successor H2、PURE_TRADES 生命周期对照轨和
CONTRACT_PRICE_OHLC 生命周期主轨。生命周期可观察性提升不得自动覆盖 H2
`PRIMARY_FAILED`。旧新差异必须按来源、代码、配置和 Hash 解释。

## 验收

所有上游 Verify 绑定完整，失败线按预注册执行，工程结论、H2 研究结论和生命周期结论
分开报告；Stage 3 保持锁定。
