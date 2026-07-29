# S2P18-T13 — MFE/MAE/Time-to-Activation 重跑

- task_id: S2P18-T13
- version: 1.0
- status: SUPERSEDED_UNEXECUTED / successor `S2P19-T13`
- dependencies: `S2P18-T12` formal Verify PASS

## 合同

在 canonical-Trades-only successor H2 路径证据上重新计算 MFE、MAE 和
Time-to-Activation。生命周期轨道、删失与边界分类只作独立报告引用；不得加入 H2
路径或标签。粗粒度 OHLC 不得伪装成秒内成交路径。

## 验收

统计单位、分母、删失原因、轨道与输入 Manifest 可追溯；producer、Catalog、Manifest、
Verify、报告和 Hash 全部通过后才可解锁 T16。
