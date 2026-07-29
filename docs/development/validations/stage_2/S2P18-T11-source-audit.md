# S2P18-T11 Contract Price 来源审计

- date: 2026-07-28
- status: HISTORICAL_PASS_FOR_IMPLEMENTATION_AND_REHEARSAL / SUPERSEDED_UNEXECUTED
- audit_hash: `48d7f421d16172322a0628a927865bc69599a35b212b9e0d4ac7085bc9e03319`
- scope: `[2020-01-01, 2020-01-08)`

## 来源关系

canonical Trades 来自 Binance USD-M `trades` archives。候选 Contract Price 1s OHLC 来自
Binance USD-M `aggTrades` daily archives，经已绑定脚本按秒聚合；它不是交易所原生 1s
Kline。两者是不同官方归档族，但仍来自同一市场事实，因此 OHLC 只能作为同秒价格边界
证据，不能作为独立成交或秒内顺序证据。

| Instrument | Trade ID gaps | Gap seconds | OHLC covered | zero-volume | duplicate seconds | extrema beyond visible Trades |
|---|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 122 | 34 | 34 | 0 | 0 | 0 |
| ETHUSDT | 14 | 13 | 13 | 0 | 0 | 0 |

测试范围内，每个缺口秒都有 OHLC，且没有用前向填充的零成交量秒恢复缺口。OHLC 没有
发现超出当前可见 Trades 的新极值；因此它提供的是第二归档族对同秒边界的额外确认，
不是证明缺失 Trade 的精确轨迹已经恢复。

## 约束

正式 Run 必须逐分区绑定 Contract Price Hash。缺失、时间语义不明、零成交量、重复秒或
Hash 漂移均失败关闭。完整 high/low 只在该秒 `available_at_ns` 后可用。
