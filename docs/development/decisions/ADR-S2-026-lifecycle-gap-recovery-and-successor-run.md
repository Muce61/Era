# ADR-S2-026 — 生命周期缺口粗边界恢复与 successor Run

## 状态

APPROVED — 2026-07-28

## 决定

Stage 2 Plan v1.8 采用两条并行生命周期轨道：

- `PURE_TRADES_COMPARATOR` 保持 canonical Trades 缺口与删失，用于证明历史数据没有被
  暗中补造；
- `CONTRACT_PRICE_OHLC_PRIMARY` 仅在终态前 Trade 缺口秒中使用 Binance USD-M
  aggTrades 派生的 1s OHLC 判断 target/stop 边界是否被触及。

OHLC 完整 high/low 只有在 `available_at_ns` 后才可用。若同秒同时触及 target 和 stop，
结果为 `AMBIGUOUS`；若问题涉及秒内次序、移动状态或多个动态切换，则为
`INCONCLUSIVE_INTRASECOND_ORDER`。零成交量的前向填充秒不能恢复 Trade 缺口。

这条生命周期主轨不是新的 H2 Primary，也不是成交、滑点或真实收益证据。T16 性能重构
必须保持现有 H2 结果逐项等价；任何结果漂移先按实现偏差处理。历史
`PRIMARY_FAILED` 与 `STAGE2_NO_GO_CURRENT_EVIDENCE` 不被覆盖。
