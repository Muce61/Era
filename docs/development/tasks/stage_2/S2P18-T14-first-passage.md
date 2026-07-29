# S2P18-T14 — First Passage / AMBIGUOUS 重跑

- task_id: S2P18-T14
- version: 1.0
- status: APPROVED / IMPLEMENTATION CONTRACT FROZEN / FORMAL RUN GATED
- dependencies: `S2P18-T12` formal Verify PASS

## 合同

按原冻结 target/stop、T1–T4 和 `AMBIGUOUS=FAILURE` 合同重算 First Passage。
H2 标签只使用 canonical Trades。Contract Price 同秒边界分类属于独立生命周期轨，
不得改变 H2 First Passage；该轨同秒双边触及不得推断先后，涉及动态状态切换则保持
不可判定。

## 验收

每个 Episode 唯一分类，计数守恒，BTC/ETH 和轨道隔离，Manifest/Catalog/Verify/报告/
Hash 对账后解锁 T15。
