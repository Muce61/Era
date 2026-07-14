# ADR-2026-001 — Trade Identity v2

- Status: ACCEPTED
- Date: 2026-07-14
- Decision owner: Muce
- Change Request: `CR-2026-001`

## Context

Binance官方Trades归档已证明`venue_trade_id`并非历史事实的唯一主键。丢弃任一不同官方事实会改变历史证据；把归档路径写入身份又会使月包/日包同一事实产生不同ID。

## Decision

- Dataset/schema version为`stage1-trades-v2`。
- `venue_trade_id`仅保存交易所原值。
- `canonical_trade_id`是以下规范JSON的SHA-256：schema版本、instrument、venue_trade_id、UTC纳秒、规范Decimal price/quantity/quote_quantity、is_buyer_maker。JSON键排序且无多余空白；不含归档路径或source hash。
- 唯一键为`(instrument, canonical_trade_id)`。
- 同canonical ID确定性折叠并计数；同venue ID而canonical ID不同则全部保留，状态为`CONFLICTING_VENUE_ID`，冲突组为`<instrument>:<venue_trade_id>`。
- 排序键为`(ts_event_ns, venue_trade_id, canonical_trade_id)`。
- 冲突月包与对应官方日包canonical事实集合完全一致才标记`CONFIRMED_OFFICIAL_CONFLICT`并允许发布；否则`SOURCE_DISAGREEMENT`阻止发布。
- 官方checksum变化使受影响run、分区与下游证据失效。

## Consequences

Parquet、Catalog、Manifest、逻辑hash和K线均消费v2身份。历史事实保留lineage与冲突标签。执行订单fill的`venue_trade_id`语义不受本ADR修改。
