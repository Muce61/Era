# S2P18-T12 — successor 路径证据

- task_id: S2P18-T12
- version: 1.0
- status: APPROVED / IMPLEMENTATION CONTRACT FROZEN / FORMAL RUN GATED
- dependencies: `S2P18-T11` formal Verify PASS

## 合同

从 T11 双轨终态与经过来源绑定的路径输入完整重建路径证据。BTC/ETH、轨道、period、
split、setup、context 与 Episode identity 不得混合。旧 T12 只作历史对照，不得复用为
新正式结果。

## 验收

producer、Catalog、Manifest、Verify、报告和全部 Hash 对账；未知缺失、orphan、
duplicate、输入漂移或未终态 Run 均 `FAILED_UNPUBLISHED`。
