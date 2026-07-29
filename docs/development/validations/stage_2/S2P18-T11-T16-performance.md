# S2P18-T11/T16 等价性与性能验证

- date: 2026-07-28
- status: HISTORICAL_IMPLEMENTATION_GATE_PASS / SUPERSEDED_UNEXECUTED
- machine: current local macOS host
- workers: single process for fixed benchmark
- memory_gate: `3,221,225,472` bytes

## 固定结果

| Task | Corpus | Baseline | Optimized | Speedup | Equality |
|---|---|---:|---:|---:|---|
| T11 | 250,000 points × 200 range queries | 0.006278 s | 0.001233 s | 5.090× | exact |
| T11 | 20 real overlapping BTC Episodes, same 600 s COMPLETE semantics | 6.902750 s | 3.172270 s | 2.176× | exact |
| T16 | 20,000 synthetic canonical Trades, frozen 30-cell semantics | 0.023187 s | 0.011008 s | 2.106× | exact |

真实七日 T11 rehearsal 的第一条 BTC Episode 在冷索引路径上用时 12.102 s；相邻 Episode
复用日分区和索引后为 0.022916 s。进程观测到的最大 RSS 为 `2,875,785,216` bytes，
低于 `3 GiB` 门。该 rehearsal 仅验证 producer-to-consumer 和缓存复用，不是正式研究
Run，也没有创建 Authority、Manifest 或研究结论。

## 语义检查

- T11 索引查询与标量参考在 COMPLETE 窗口逐项一致；
- T16 matching 身份、30-cell 标签和规范化结果一致；
- 固定测试覆盖无缺口、终态后缺口、非决定性缺口、target-only、stop-only、同秒双边、
  多秒缺口、Contract Price 缺失、funding、右删失、重复时间戳与来源审计失败关闭；
- 结果漂移仍定义为 `BLOCKED_ENGINE_SEMANTIC_DRIFT`，不能解释为策略改善。

## 未完成

正式冷/热缓存证据包、正式 worker 变化确定性、全量 T11/T16 Run、Catalog、Manifest、
Verify 和 T12–T20 均未执行。它们继续受干净 commit 和单独 commit-bound 人工批准约束。
