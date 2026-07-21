# S2-T12：MFE / MAE / Time-to-Activation

## Metadata

- task_id: S2-T12
- task_version: 1.3
- status: VALIDATED / AWAITING HUMAN ACCEPTANCE
- stage_id: S2
- stage_plan_version: 1.2
- created_from_spec_version: V1.3.4
- created_from_commit: b7d4ff3d18dcfc515feb8892659cb0b186cd68f8
- dependencies: S2-T11 PASS
- supersedes: task_version 1.1
- approved_by: Muce
- approved_at: 2026-07-21T03:02:25Z

## 1. 目标

规划并交付“MFE / MAE / Time-to-Activation”这一单一能力，使其可独立测试、审查和回滚。

## 2. 背景

该能力属于 Stage 2“事件研究”，必须保持 V1.3.4 的证据等级、状态语义和人工阶段门。

## 3. 规格来源

- 手册章节：§9、§11-16、附录D/J/L/N
- rule_id：EVENT-CONSUME-MARKET-EPISODE, STRATEGY-V1-PRICE-ONLY-HISTORICAL
- 数据契约：CanonicalKeyLevel, MarketEpisode, EntryIntent, path labels, cluster_id
- 系统不变量与 Reason Code：执行前从 `traceability/rules.yaml` 解析本 Task 的精确映射

## 4. 前置条件

Stage 2 Plan v1.2 与本 Task 均已人工批准；依赖项有真实 validation；适用 OPEN QUESTION 不阻塞；工作区和Stage 1 Baseline v1.0已核验。

## 5. 允许范围

只实现并验证“MFE / MAE / Time-to-Activation”及其直接契约、测试和追踪；允许为该单一能力增加最小审计证据。

## 6. 禁止事项

禁止越过 Stage、扩大交易风险、连接未授权 API、写入密钥、修改正式规格、把 BASELINE/RESEARCH 宣称最优或 FROZEN、自动批准或继续下一 Task。

## 7. 允许修改的路径

以第21节的v1.0精确路径为准；未列路径禁止修改。

## 8. 禁止修改的路径

`docs/spec/**`、其他未批准 Stage 的实现路径、真实密钥/账户文件、历史基线和已通过的不可覆盖验证产物。

## 9. 输入

规格基线、Stage Plan、依赖 Task 的已验证产物、适用配置/manifest/hash；执行时记录精确版本。

## 10. 交付物

该能力的最小实现或研究产物、对应测试、validation/manifest、TRACEABILITY 与 `rules.yaml` 状态更新；本 DRAFT 本身不产生实现。

## 11. 实现要求

先列出适用 rule_id、允许/禁止路径和计划；使用 Decimal/时间/证据字段等已批准契约；失败动作必须唯一且可审计；不得引入未来能力。

## 12. 测试要求

覆盖正常、边界、失败和确定性场景；涉及 FROZEN/INV 时必须运行其映射测试；历史、代理、测试网与真实证据必须分级报告。

## 13. 验收标准

目标单一完成；测试真实运行且通过；无未解释追踪缺口；回滚可执行；未完成项和未运行测试如实报告；由人工验收。

## 14. 必须运行的命令

以第21节的定向pytest命令和现有统一质量门为准；全量研究CLI必须由S2-T19预注册后通过Task新版本冻结。

## 15. 完成报告格式

规则/范围 → 修改文件 → 实际命令与结果 → 追踪更新 → 未完成/开放问题 → Go/No-Go 建议；不得自动继续。

## 16. 回滚方式

按独立提交撤销本 Task 的实现与注册引用，保留 manifest、审计和失败证据；若契约已被下游消费，先执行失效传播。

## 17. 开放问题

只记录影响本 Task 的 U/CR/ADR；需要改变风险、数据边界、执行语义或 Binance 能力判断时停止并请求人工决定。

## 18. 变化触发器

schema、标签、成本模型、事件定义、数据/配置哈希、git commit 或聚类方式变化；或发现与 V1.3.4/Binance 官方事实冲突。 触发 task_version 递增和重新审批。

## 19. 失效条件

依赖 Task/Stage 重开、输入哈希变化、映射规则变化、验收测试被推翻或产物不可复现时标记 INVALIDATED，不得继续作为有效证据。

## 20. 变更历史

- 2026-07-12：v0.1，依据 Stage 2 Plan v0.1 创建，状态 DRAFT，未执行。
- 2026-07-14：v1.0，按Stage 1 Trade Identity v2与Stage 2 Plan v1.0重规划；状态DRAFT，未执行。
- 2026-07-14：v1.1，加入可扩展研究setup架构与事件说明图规划；状态DRAFT，未执行。
- 2026-07-16：v1.2，按Plan v1.2收口分组、前置S2-T19并修订DAG；状态DRAFT，未执行。
- 2026-07-21：Muce批准v1.3最小路径指标合同，从已收口并推送的
  `9c3aadd5166ea2a2f6ab59b365ed1aee9b46aab6`独立执行；状态
  `APPROVED / IN_PROGRESS`。本版本冻结第22节合同，不批准S2-T13或Stage 3。
- 2026-07-21：全量Run `stage2-s2t12-metrics-20260721T040435Z-de9aaea56f2a`与独立Verify
  PASS，共发布1,065,416条BTC/ETH分离的H1/H2历史路径指标；状态更新为
  `VALIDATED / AWAITING HUMAN ACCEPTANCE`。Web UI自动识别仍由待批准CR-2026-022阻塞，
  不批准S2-T13或Stage 3。

## 21. Stage 2 Plan v1.2执行覆盖（优先于旧版通用占位）

- 数据与能力边界：计算MFE/MAE/Time-to-Activation/Time-since-MFE等纯路径指标；不计成本、不称PnL。
- 允许修改路径：`src/era100x/research/stage_2/metrics/path/`、`tests/research/stage_2/metrics/path/`，以及本Task validation/TRACEABILITY。禁止修改Stage 1实现/数据、\`docs/spec/**\`和Stage 3+。
- 验证命令：\`uv run python -m pytest tests/research/stage_2/metrics/path -q\`；\`uv run python scripts/run_quality_gate.py\`。全量研究CLI须由S2-T19冻结后再写入Task新版本，不得当前虚构。
- 验收标准：Decimal/符号、零/未激活、边界、单调性、路径截断和确定性测试通过；BTC/ETH分别汇总。
- 证据模式：\`FIXTURE_CAPABILITY + FULL STATISTICS\`。无论fixture能力是否可验收，Stage 1最终PASSED与VALID data baseline之前均不得执行本Task。

## 22. v1.3最小路径指标合同

### 22.1 冻结输入与参考价

- 唯一上游路径证据为已人工接收的S2-T11 v1.3 Run
  `stage2-s2t11-paths-20260721T023117Z-029707f3c111`，Snapshot
  `d4d6a2f5c72a9fb8c964585a009d2c11048b1baa34432d3d16fb68ee9ff3979c`。
- 每个指标记录必须绑定`instrument`、`market_episode_id`、
  `canonical_candidate_id`、`candidate_version_id`、`canonical_payload_hash`、
  S2-T11 manifest/catalog/hash和来源证据等级。
- 参考价必须从固定S2-T10 Snapshot中由MarketEpisode的`trigger_id`连接到
  `PriceTriggerFact.reference_price`；不得用路径第一条价格、未来价格或可执行报价替代。
- BTCUSDT和ETHUSDT分别计算、分别汇总，不产生跨标的合并统计。

### 22.2 指标公式与时间语义

仅处理LONG历史价格路径。对参考价`r > 0`和路径价格`p`：

```text
signed_move_bps = (p / r - 1) * 10000
MFE_bps = max(0, max(signed_move_bps))
MAE_bps = min(0, min(signed_move_bps))
```

- H1用每个1秒Contract Price bar的`high`计算MFE、`low`计算MAE；时间精度标记为
  `COARSE_SECOND`，不得推断秒内先后。
- H2按`(ts_event_ns, venue_trade_id, canonical_trade_id)`处理Trade price；历史事实身份仍为
  `(instrument, canonical_trade_id)`，冲突事实全部保留。
- 相同极值多次出现时，使用稳定顺序中第一次达到该最终极值的事件时间。
- 极值、阈值比较和首次时间均使用未量化Decimal；写入`MFE_bps/MAE_bps`证据字段时统一
  量化到小数点后18位，舍入模式为`ROUND_HALF_EVEN`，不得隐式截断或使用binary float。
- `time_since_mfe_ns = last_observation_ts_event_ns - mfe_first_ts_event_ns`；无观测时指标为
  `NO_OBSERVATIONS`且数值为空，不得以零伪装缺失。
- 路径继续使用UTC event time和左闭右开窗口；截断、缺口、歧义与S2-T11质量状态原样传播。

### 22.3 Time-to-Activation代理边界

- `activation_threshold_bps`只是有利价格位移阈值代理，不是§21.2真实保护激活、净ROE、
  成交保证或live规则，不解决U-010/U-011。
- 预注册敏感度域为既有OQ-S2-002 target/stop域的并集：
  `15, 20, 25, 30, 35, 40, 50, 70, 100 bp`；不得看结果后追加阈值。
- `time_to_activation_ns`为窗口内第一次满足`signed_move_bps >= threshold`的事件时间减
  `window_start_ns`；未达到时为`null`且`activated=false`。
- H1只能报告首次触及所在秒，H2报告稳定Trade事件时间；本Task不比较target/stop先后，
  不产生first-passage或AMBIGUOUS bounds。

### 22.4 允许输出、路径与CLI

- 允许输出：逐Episode的H1/H2 MFE、MAE、极值时间、Time-since-MFE、各预注册阈值的
  Time-to-Activation、质量/截断/lineage，以及BTC/ETH分离的描述性汇总。
- 明确禁止：PnL、return/real return、成本、first-passage、TARGET_FIRST/STOP_FIRST、
  AMBIGUOUS bounds、条件基线、placebo、cluster、bootstrap、CI及任何交易连接。
- 允许修改：`src/era100x/research/stage_2/metrics/path/**`、
  `tests/research/stage_2/metrics/path/**`、`scripts/run_stage2_path_metrics.py`、
  `configs/research/stage_2/s2_t12_path_metrics_v1.3.json`、
  `artifacts/manifests/stage_2/s2_t12_path_metrics_summary.json`、本Task、对应validation、
  `CURRENT_STAGE.md`、`TRACEABILITY.md`和`traceability/rules.yaml`中仅与S2-T12直接相关内容。
- 全量CLI冻结为：
  `uv run python scripts/run_stage2_path_metrics.py {preflight,run,resume,verify}`。
- 全量结果写入`/Volumes/FuckingLife/era100x_stage2/runs/<run_id>/`既有不可变布局；
  `published/manifests/reports` append-only，任何失败不覆盖S2-T11或S2-T10产物。
- 若冻结的H2源文件发生物理字节损坏，只允许在Stage 2 `tmp`中从同一Binance官方Trades
  归档确定性重建只读overlay；overlay必须同时命中T11记录的`source_byte_sha256`、Stage 1
  `logical_sha256`、行数和官方归档SHA-256。不得写回、移动或替换Stage 1文件；不完全匹配则
  fail-closed。当前唯一overlay为BTCUSDT 2022-03-01，影响249个Episode/310个slice，
  重建后byte hash `fc0f50e0…c296`与logical hash `eee2263f…d84`精确匹配。

### 22.5 验收与停止边界

- 必测Decimal与符号、零、无观测、未激活、边界、稳定排序、冲突事实、缺口、截断、
  input shuffle确定性、BTC/ETH隔离和lineage。
- 必跑定向pytest和统一质量门；全量统计必须有独立verify与不可覆盖证据。
- Web UI只能从Task/validation/receipt真实证据自动投影，不得在HTML硬编码PASSED。
- 完成后最多建议S2-T12 Go/No-Go；不得自动批准或开始S2-T13。
