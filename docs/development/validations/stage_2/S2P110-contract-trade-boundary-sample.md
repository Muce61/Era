# S2P110 Contract Price / Trades 边界小样本验证

- date: `2026-07-30`
- status: `PASS_FOR_CR-2026-051`
- scope: `2020-01-01`
- method: `EVENLY_SPACED_SECONDS`
- evidence_hash:
  `b1ff97f2261af63ff161a123902593fcb9a0a8a3e372e9a082ca99f734dc199c`

## 结果

| Instrument | 有Trade样本 | low/high精确一致 | CP包围Trade边界 | 零-Trade样本 | 平坦OHLC | 无可见Trade |
|---|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 100 | 100 | 100 | 20 | 20 | 20 |
| ETHUSDT | 100 | 100 | 100 | 20 | 20 | 20 |

BTC Trade partition Hash：
`25e528e2d3d0873b15578a655f4c8d5964bb6940bd1bfb10a8129025a3846475`

BTC Contract Price receipt Hash：
`ba473dd622a1ccaaa5f922d9d3a64ce49b1530ce3b48dc88252683546a4b3f38`

ETH Trade partition Hash：
`435a18bc591fd46b4fd2f767c0d200c933cc6a741aa23977c610da5484a0a42a`

ETH Contract Price receipt Hash：
`0b575c28dad99668aac3c608f4e9f4e0ba63dc9c9879db9774042a73cb16d75d`

## 解释边界

结果支持在 canonical Trades 不可用时把已绑定 Contract Price 当作价格代理。它不证明
真实成交、滑点或秒内顺序。零-Trade秒只有在 OHLC 平坦、分区与 receipt Hash 闭合时才
可使用；不满足则失败关闭。

## 真实 producer rehearsal

- scope: `2020-01-03`
- instruments: `BTCUSDT / ETHUSDT`
- source audit schema: `1.3`
- source audit Hash:
  `59ea48e56f0290d373567892f7f6bc8c4a16ed31a71063019a30c7a8eef71539`
- lifecycle rows: `80`
- resume batches: `1`
- result: `PASS`

该 rehearsal 使用真实只读输入和隔离 unpublished 临时目录，走过
`produce_scoped_lifecycle_v110` 的 producer-to-gap-recovery 路径。它不是正式研究 Run，
不改变任何历史结果。
