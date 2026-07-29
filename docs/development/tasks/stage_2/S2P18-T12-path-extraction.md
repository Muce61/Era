# S2P18-T12 — successor 路径证据

- task_id: S2P18-T12
- version: 1.0
- status: SUPERSEDED_UNEXECUTED / successor `S2P19-T12`
- dependencies: `S2P18-T11` formal Verify PASS

## 合同

从经过来源绑定的 canonical Trades 路径输入完整重建 H2 路径证据。T11 是治理依赖，
但其 Contract Price OHLC 生命周期分类不得作为 H2 标签。双轨生命周期只保留独立引用，
沿 T11→T19/T20 报告。BTC/ETH、period、split、setup、context 与 Episode identity
不得混合。旧 T12 只作数学引擎/历史对照，不得复用为新正式结果。

## 验收

producer、Catalog、Manifest、Verify、报告和全部 Hash 对账；未知缺失、orphan、
duplicate、输入漂移或未终态 Run 均 `FAILED_UNPUBLISHED`。
