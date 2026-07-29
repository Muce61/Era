# ADR-S2-028：Plan v1.9 个人开发轻量正式运行架构

## 状态

`APPROVED / IMPLEMENTED / FORMAL RUN NOT AUTHORIZED`

## 决定

Plan v1.8 的研究合同保留，但其未执行的正式运行包装由 Plan v1.9 替代。v1.8 标记为
`SUPERSEDED_UNEXECUTED`，不得被描述为失败 Run 或已产生正式 successor 结果。

Plan v1.9 采用四个入口：`status / prepare / run / resume`。`prepare` 把来源审计、十二类
输入 binding 和完整 Contract Price 日分区合并为一个 `inputs.lock.json`。人工只批准一次
精确代码 commit 和 inputs-lock Hash；`run` 必须先 fsync `run-authority.json`，然后才可
创建 Run ID。

十个 Task 不再重复产生 Catalog、Manifest、Verify 和 Receipt。每次 attempt 只保留输出、
checkpoint 和日志；完成事实写入一个 fsync 的 `events.jsonl` Hash 链。全链完成后只生成
一次附录 J `final-manifest.json` 和一次 `final-verify.json`。Run 目录依次从 `runs/` 原子
移动到 `candidates/`，Verify PASS 后原子移动到 `published/`；失败进入 `failed/`。

## 不变项

- BTC / ETH 隔离；
- BTC/T2/20bp/25bp H2 Primary、matching、AMBIGUOUS、cluster、seed 不变；
- T12–T18 只消费 canonical Trades，Contract Price OHLC 只服务生命周期 T19/T20；
- 历史 Plan v1.7 Primary FAIL 和生命周期 INCONCLUSIVE 不变；
- clean commit、完整输入 Hash、唯一锁、Authority-before-Run、checkpoint、任务 DAG、
  最终完整 Verify 和 Stage 3 锁全部保留；
- Contract Price 是粗粒度价格边界证据，不是历史成交。

## 后果

v1.8 的 11 个操作命令压缩为 4 个；Run 前正式对象从 5 类压缩为 2 类；约 40 个每 Task
治理对象归零；不再 hard-link 复制候选输出树。复杂度下降只改变证据包装，不改变研究
问题、统计标准或正式批准门。
