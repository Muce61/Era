# ADR-S2-030 — 零-Trade 秒 Contract Price 代理边界

## 状态

`APPROVED — 2026-07-30`

## 决定

S2P110-T11 的生命周期保持双轨：

- `PURE_TRADES_COMPARATOR` 不补造任何 canonical Trade；
- `CONTRACT_PRICE_OHLC_PRIMARY` 在 Trade 缺口秒使用已绑定 Contract Price OHLC。

对于 `volume=0` 的 Contract Price 秒：

1. OHLC 必须为平坦值，否则来源合同失败；
2. 平坦 OHLC 作为 Contract Price 状态进入原 target/stop 边界分类；
3. 未触及边界则 `GAP_NON_DECISIVE` 并继续；
4. 触及单侧边界则记录对应 coarse boundary；
5. 不产生真实 Trade 或成交声明，`synthetic_execution=false`；
6. Contract Price 文件、Hash、范围或时间语义不可信时仍失败关闭。

该决定由 CR-2026-051 批准，并仅取代 ADR-S2-026 的零成交量拒绝条款。历史 H2
Primary FAIL、旧生命周期 INCONCLUSIVE 和两个 S2P110 FAILED Run 均保持不可变。
