# S2P18-T15 — AMBIGUOUS 与条件基线准备

- task_id: S2P18-T15
- version: 1.0
- status: SUPERSEDED_UNEXECUTED / successor `S2P19-T15`
- dependencies: `S2P18-T14` formal Verify PASS

## 合同

冻结 canonical-Trades-only successor First Passage 的 AMBIGUOUS、EXPIRED 与来源缺口
投影，并准备 T16 所需的 30-cell 输入。生命周期右删失和 OHLC 边界分类不进入 30-cell
H2 输入。不得删除 AMBIGUOUS、放宽失败线或改变样本。

## 验收

输入分母和分类守恒，规范化输出与 Hash 可重复；旧 T15 历史失败保持不可变，不得被新
Run 原地改写。
