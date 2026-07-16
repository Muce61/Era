# S2-T21：事件说明图与真实事件证据卡

## Metadata

- task_id: S2-T21
- task_version: 1.0
- status: DRAFT
- stage_id: S2
- stage_plan_version: 1.1
- created_from_spec_version: V1.3.4
- created_from_commit: c984fb4
- dependencies: S2-T10 PASS; S2-T11 PASS; S2-T12 PASS; S2-T13 PASS; S2-T14 PASS; S2-T19 PASS
- supersedes: NONE
- approved_by: NONE
- approved_at: NONE

## 1. 目标

建立确定性事件可视化能力，生成类似参考深色信息图的事件说明图，以及由真实历史事件记录驱动、可追溯和可复现的证据卡。

## 2. 背景

Stage 2需要让Sweep、Reclaim、Hold、Activation、Flow、G0～G6和路径标签可被人类审查。图片是研究说明与审计入口，不是新的信号、标签、执行事实或收益证据。

## 3. 规格来源

- 手册章节：§3.3、§4、§9、§11-13、§30、附录A/H/J/L。
- rule_id：`DATA-HISTORICAL-NO-FAKE-EXECUTION`、`STRATEGY-V1-PRICE-ONLY-HISTORICAL`、`EVENT-CONSUME-MARKET-EPISODE`。
- 系统不变量：`INV-005`、`INV-011`、`INV-013`。
- 数据契约：ResearchSetup、ContextModel、CanonicalKeyLevel、MarketEpisode、event path、path labels、experiment manifest。

## 4. 前置条件

Stage 2 Plan v1.1与本Task均已人工批准；依赖Task均为PASS；Stage 1 published baseline有效；S2-T19已冻结图片模式、模板版本和输出范围；适用OPEN QUESTION不阻塞。

## 5. 允许范围

实现纯报告层的确定性布局、注释和导出；允许输出两类互斥产物：`EVENT_EXPLAINER`教育示意图与`EVENT_EVIDENCE_CARD`真实历史事件证据卡。

## 6. 禁止事项

禁止生成式模型补画或修改正式证据；禁止平滑、插值、删除不利路径或选择性隐藏AMBIGUOUS；禁止伪造Bid、Ask、Spread、执行、延迟、部分成交、滑点或真实PnL；禁止把目标/止损示例称为真实成交；禁止改变事件、门、标签或统计结果；禁止自动进入Stage 3。

## 7. 允许修改的路径

- `src/era100x/research/stage_2/reporting/event_explainer/`
- `tests/research/stage_2/reporting/event_explainer/`
- `configs/research/stage_2/visualization/`
- `artifacts/reports/stage_2/event_explainers/`中的轻量fixture样例、索引和checksum
- 本Task Validation、TRACEABILITY与必要的Task治理状态

如实现PNG导出必须引入新依赖，先提交ADR并提升本Task版本重新审批；当前Plan不预先批准修改`pyproject.toml`或`uv.lock`。

## 8. 禁止修改的路径

`docs/spec/**`、Stage 1实现/工作根/raw/staging/checkpoint/published、其他Stage实现、事件检测和标签实现、真实账户/密钥文件、已通过的不可覆盖验证产物。

## 9. 输入

已验证的ResearchSetup/ContextModel注册信息、实验Manifest、CanonicalKeyLevel、MarketEpisode、事件窗口OHLC/Trades路径、G0～G6结果、MFE/MAE/Time-to-Activation、First Passage/AMBIGUOUS标签，以及run/data/config/code/schema/template hash。

## 10. 交付物

- 版本化`EventVisualizationSpec`与模板。
- `EVENT_EXPLAINER`确定性SVG和PNG样例。
- `EVENT_EVIDENCE_CARD`确定性SVG和PNG及机器可读sidecar manifest。
- 图片索引、checksum、fixture、测试、Validation和Traceability更新。

## 11. 实现要求

- 参考布局至少包含：一句话说明、K线/成交量路径、关键位、Sweep/Reclaim/Hold/Activation注释、G0～G6状态、V1_PRICE/V1_FLOW或setup/context信息、路径观察项和研究口径声明。
- `EVENT_EXPLAINER`使用示意或fixture数据时，图面必须显著显示`ILLUSTRATIVE_FIXTURE / 非真实市场证据`。
- `EVENT_EVIDENCE_CARD`只能使用对应事件的不可变输入切片；必须显示instrument、event/episode ID、UTC窗口、setup/context/variant版本、run ID和数据/config/code/template hash短码。
- 真实证据卡不得出现输入中不存在的字段。不可得字段显示`UNAVAILABLE`，不得显示0、空字符串或推测值。
- 相同规范输入、模板和字体环境必须产生相同语义SVG、注释坐标、sidecar和逻辑图片hash；PNG物理字节差异必须被解释并不得替代逻辑hash。
- BTC与ETH、不同setup/context/variant必须独立生成和索引。
- 正式证据卡采用全量事件产物；仓库只保存小型fixture样例和索引，大型图片写经批准的Stage 2外部工作根。

## 12. 测试要求

覆盖正常事件、缺失Flow、AMBIGUOUS、窗口截断、冲突Trade事实、UTC边界、中文文本、极端价格范围、空成交量、未知setup、示意图水印缺失、真实图审计字段缺失、不可得字段被0替代、输入打乱、重复渲染和跨标的/setup混合失败路径。

## 13. 验收标准

- fixture说明图视觉结构与参考需求等价，且明确为示意。
- 真实证据卡的每个数值和注释可回查到事件记录或Manifest。
- 相同输入重复渲染的逻辑图片hash、sidecar、注释位置和文本一致。
- 未批准setup、缺失审计字段、伪造历史能力、跨标的/setup混合或水印缺失时硬失败。
- SVG和PNG均可打开，无遮挡关键字段；自动结构检查和人工视觉审查均有记录。
- 未执行全量正式证据卡生成时，本Task不得PASS。

## 14. 必须运行的命令

- `uv run python -m pytest tests/research/stage_2/reporting/event_explainer -q`
- `uv run python scripts/run_quality_gate.py`
- `uv run python scripts/check_traceability.py --strict`
- `git diff --check`

全量渲染CLI必须由S2-T19预注册后在本Task后续批准版本中冻结，不得当前虚构。

## 15. 完成报告格式

规则与范围 → 修改文件 → 图片模式/模板版本 → 样例与正式输出数量 → 审计字段与hash → 实际命令/结果 → 人工视觉审查 → 已知限制/开放问题 → PASS/CONDITIONAL PASS/FAIL。

## 16. 回滚方式

撤销本Task独立实现与注册引用；保留已发布图片、sidecar和索引并标记`INVALIDATED`，不得覆盖或删除被报告引用的证据卡。

## 17. 开放问题

精确字体、配色和排版属于BASELINE，可在Task审批前冻结；若PNG需要新依赖，必须先通过ADR和新Task版本批准。不得因美观调整事件事实或研究口径。

## 18. 变化触发器

事件/标签/schema、setup/context/variant、输入data/config/code hash、模板版本、字体版本、布局语义、审计字段或渲染依赖变化。

## 19. 失效条件

上游Task/Stage重开、输入/模板/hash变化、图片无法回查事实、示意与真实模式混淆、确定性失败或验收测试被推翻时，相关图片全部标记`INVALIDATED`并重新生成。

## 20. 变更历史

- 2026-07-14：v1.0，依据用户提供的Stage 2事件说明图参考新增；状态DRAFT，未执行。

