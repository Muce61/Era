# S2P18-T11 — 生命周期双轨修复与性能门

- task_id: S2P18-T11
- version: 1.0
- status: APPROVED / IMPLEMENTATION AUTHORIZED / FORMAL RUN GATED
- dependencies: Stage 1 VALID；T10 历史密封证据；来源审计 PASS

## 合同

为每个 Episode 同时产生 `PURE_TRADES_COMPARATOR` 与
`CONTRACT_PRICE_OHLC_PRIMARY`。后者只在终态前 Trade 缺口秒读取同秒 OHLC，并记录
gap ID、来源 Hash、边界分类、`decision_available_at_ns`、
`intrasecond_order_known=false` 和 `synthetic_execution=false`。

同秒双边触及为 `AMBIGUOUS`；动态状态需要秒内次序时为
`INCONCLUSIVE_INTRASECOND_ORDER`；七日无终态为右删失。零成交量前向填充秒禁止用于
恢复。BTC/ETH 独立，最多各一个 worker，按冻结顺序流式合并。

## 验收

固定语料覆盖无缺口、终态后缺口、非决定性缺口、单边/双边、多秒缺口、同步缺失、
funding、右删失、稳定排序、checkpoint 与 worker 确定性。相对标量参考至少 `2×`，
完整无缺口窗口与旧语义完全一致，峰值 RSS `≤3 GiB`。

正式输出必须新 Authority/Run/Manifest/Catalog/Verify；未获 commit-bound 人工批准不得运行。
