# Stage 2：事件研究 Plan v1.2

## Metadata

- stage_id: S2
- plan_version: 1.2
- status: READY_FOR_APPROVAL
- created_from_spec_version: V1.3.4
- created_from_stage_1_baseline: v1.0
- created_from_commit: b7d4ff3d18dcfc515feb8892659cb0b186cd68f8
- dependencies: Stage 0 PASSED; Stage 1 PASSED / VALID
- supersedes: stage_2_plan_v1.1
- approved_by: NONE
- approved_at: NONE

## 1. 目标与边界

建立 BTCUSDT 与 ETHUSDT 严格分离、确定性、可审计且无未来泄漏的事件研究流程。Stage 2 从冻结的 Stage 1 published baseline 构造关键位、事件、路径、标签和统计证据，是进入 Stage 3 前的研究 Go/No-Go 门。

本 Plan 不执行交易、H3 成本/PnL、F1、参数优化、测试网、实盘、10 USDT 单轮或复利；不创建 EntryIntent 或订单；不修改 Stage 1 数据、Manifest、Catalog、Logical Hash、标签或 V1.3.4 正式规格。

## 2. 规格与规则

- 权威：V1.3.4 §3、§9、§11-16、§25、§27、§30、附录 C/D/J/L/N。
- FROZEN：`EVENT-CONSUME-MARKET-EPISODE`、`STRATEGY-V1-PRICE-ONLY-HISTORICAL`、`INV-005`、`INV-011`、`INV-013`、`GATE-STAGE-2`。
- RESEARCH：关键位优先级、合并容差、episode gap/re-arm、Sweep/Reclaim/Hold/Trigger/Flow 参数、路径标签、匹配、聚类和统计阈值；不得声明最优或 FROZEN。
- L2 输入决定：CR-2026-001、ADR-2026-001 Trade Identity v2。

## 3. 冻结输入基线

- Stage 1 Baseline：v1.0；tag `stage-1-v1.0-passed`；commit `b7d4ff3d18dcfc515feb8892659cb0b186cd68f8`。
- Data Run ID：`stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682`。
- Manifest SHA-256：`436ffbe36e310dd015a962a29593360729d06db25ff96eddf12644c62d76e94f`。
- BTCUSDT Logical Hash：`03d437ed9a6c19d92162e5c9dd115df4988e8accce3c8180b749f15cfdcc36a8`。
- ETHUSDT Logical Hash：`6db4d5e411edae3838b352944b83c38ba68915841a1f9c9de8f16ef44c3b8332`。
- 只读 published baseline；禁止消费 raw、staging、checkpoint 或未发布分区。Trades 使用 `(instrument, canonical_trade_id)` 事实身份和 `(ts_event_ns, venue_trade_id, canonical_trade_id)` 稳定顺序；同 venue ID 的不同 canonical 事实不得丢弃。

## 4. 批准前置条件

Stage 2 只有在以下条件全部成立后才能从 `READY_FOR_APPROVAL` 转为 `APPROVED`：

1. OQ-S2-001 与 OQ-S2-002 获得用户书面决定并在治理文件中记录。
2. Stage 2 外部工作根、append-only 发布布局、保留策略和空间门确定。
3. 主标的、主假设、主标签、匹配方案、参数域与失败线确定。
4. Plan v1.2 和对应 Task v1.2 获得用户批准。
5. Stage 1 baseline、Manifest、Catalog、schema 和 Logical Hash 只读复核通过。
6. 当前分支为经批准的 Stage 2 业务实现分支；规划分支不得直接承载业务实现。
7. 无 BLOCKER、阻塞中 Change Request、测试网、实盘或交易执行进程。

## 5. 分组与执行顺序

### 第一组：事件构造

`S2-T19 → S2-T01 → S2-T02 → S2-T03 → S2-T04 → S2-T05 → S2-T06 → S2-T07`；`S2-T08` 在 T19 后独立实现 H2 Flow fixture；`S2-T09` 在 T06/T07/T08 后统一事件身份与消费；最后 `S2-T10` 在 T01～T09 全部 PASS 且第一组 Manifest 锁定后运行全量候选事件构建。

- S2-T19：预注册 Manifest 能力。
- S2-T01～S2-T09：只完成契约、实现与小样本确定性验证，不承担全量构建。
- S2-T10：唯一负责 BTC/ETH 分离、可恢复、可重入、append-only 的全量候选事件生成。

### 第二组：路径和标签

`S2-T11 → S2-T12`；`S2-T11 → S2-T13 → S2-T14`。包含路径提取、MFE/MAE/Time-to-Activation、First Passage 和 AMBIGUOUS；不得计算 PnL 或把路径标签称为 ROUND_SUCCESS。

### 第三组：统计证据

`S2-T15`、`S2-T16`、`S2-T17` 在第二组完成后按依赖执行，最后 `S2-T18`。包含条件随机基线、安慰剂、事件聚类和 cluster bootstrap；不得通过观察结果追加过滤器或选择最佳参数。

### 第四组：Stage 验收

`S2-T20` 依赖 S2-T01～S2-T19 全部 PASS，汇总 Stage 2 证据并形成最多 `READY_FOR_FINAL_APPROVAL` 的人工入口。事件说明图与真实事件证据卡作为验收报告要求折入 S2-T20，不构成独立业务 Task。

## 6. Task DAG

```text
Stage 1 PASSED / VALID + Plan APPROVED + OQ cleared
  → S2-T19
  → S2-T01 → T02 → T03 → T04 → T05 → T06 → T07
       └──────────────────────────────────────────┐
S2-T19 + Stage 1 H2 Trades → S2-T08              │
S2-T06 + T07 + T08 → S2-T09                      │
S2-T01～T09 PASS + locked Group-1 Manifest → T10 ┘
  → T11 → T12
       └→ T13 → T14
  → T15, T16, T17 → T18
S2-T01～T19 PASS → T20
```

精确依赖以 Task v1.2 Metadata 为准；任何变化必须通过新 Plan/Task 版本复核并重新做循环检测。

## 7. S2-T19 预注册契约

S2-T19 必须先提供并验证：研究运行 Manifest Schema、parameter_set_id/version、Stage 1 数据基线与 hash、代码版本、UTC 时间切分和 purge/embargo、instrument、evidence level、允许指标、禁止指标、输出根与 run 布局、原子发布/不可覆盖规则、失效条件，以及第一组全量运行的预注册配置。

S2-T19 只建立 schema、配置快照、验证器和 append-only 台账；不读取研究结果选择参数，不运行收益研究，不生成候选事件或研究结论。

## 8. 产物与发布

- Git：代码、测试、schema、配置、轻量 fixture、Manifest 摘要、Validation、Traceability 和报告摘要。
- 外部工作根：大型候选、路径、标签、统计和图片产物；具体根与布局等待 OQ-S2-001 人工决定。
- 每次运行必须有 run_id、instrument、setup/context/variant、parameter_set_id、config hash、code commit、data run/hash、evidence level 和状态；失败运行不得发布；有效运行不得覆盖。

## 9. 质量门

规划审批前必须实际运行：

- Task ID/版本/status 唯一与一致性检查。
- Task 依赖引用闭合及 DAG 无环检查。
- Markdown 本地链接检查。
- `PATH="$PWD/.venv/bin:$PATH" python scripts/check_traceability.py --strict`。
- `git diff --check`。
- 相对 Stage 1 baseline 的禁止路径扫描：不得修改 `src/`、`tests/`、`docs/spec/`、Stage 1 Task/Validation/Baseline。

业务执行阶段每个 Task 必须运行其定向 pytest 和 `PATH="$PWD/.venv/bin:$PATH" python scripts/run_quality_gate.py`；本次规划收口不运行 Stage 2 pytest、研究 CLI 或全量任务。

## 10. Stage 验收与停止规则

S2-T20 必须检查 BTC/ETH 与 V1_PRICE/V1_FLOW 隔离、无泄漏、Manifest 先于结果、事件消费稳定、路径/标签/AMBIGUOUS 完整、条件基线/安慰剂/聚类/CI 完整和所有失败实验入账。事件无稳定增量、cluster/CI 门失败、多时期方向不一致、安慰剂同样有效、结果依赖单一最佳参数、数据/hash 失效或证据混用时 NO-GO；不得进入 Stage 3。

## 11. 开放问题

- OQ-S2-001：Stage 2 外部工作根、发布布局、保留策略、空间门。
- OQ-S2-002：主标的、主假设、主标签、匹配方案、U-007/U-008/U-009/U-011 参数域与失败线。

两项均保持 OPEN；本 Plan 的推荐方案不等于人工决定。

## 12. 失效、恢复与变更

Stage 1 schema/dataset/Manifest/Logical Hash、Trade Identity、事件/标签/匹配/聚类、purge/embargo、参数域、主指标、代码或配置 hash 任一变化，使受影响证据 `INVALIDATED`。旧运行和失败实验保留；恢复只允许从同一有效 baseline 与锁定 Manifest 重入，不得覆盖。

研究方法、标签或指标变化按 L3 Change Request 处理；FROZEN 风险/执行规则变化按 L4 处理，均须人工批准。

## 13. 变更历史

- 2026-07-12：v0.1，初始草案。
- 2026-07-14：v1.0，适配 Trade Identity v2。
- 2026-07-14：v1.1，增加 setup/context 注册表及事件说明规划；保持 DRAFT。
- 2026-07-16：v1.2，基于 Stage 1 Baseline v1.0 收口四组边界，前置 S2-T19，消除 T02/T08/T19 依赖冲突，统一全量职责至 T10；状态 READY_FOR_APPROVAL，未执行 Stage 2。
