# Stage 2 Plan v1.2 Approval Review

Status: READY_FOR_USER_DECISION

Scope: planning and governance only

Stage 2 execution authorized: NO

## OQ-S2-001

**问题原文：** Stage 2大型候选、路径、标签和研究报告的外部可写根、不可变发布布局、保留策略与空间门是什么？

**阻塞范围：** Stage 2 approval；在决定前不得写入 Stage 1 工作根、Git 仓库或未经批准的外部目录。

| 方案 | 内容 | 影响 |
| --- | --- | --- |
| A（推荐） | 独立外盘根 `/Volumes/FuckingLife/era100x_stage2`；按 `runs/<run_id>/{staging,published,manifests,reports}` 隔离；published/manifest/report append-only；失败 staging 保留到审计完成并仅人工批准清理；启动时要求可用空间不少于预估峰值的 1.20 倍。 | 与 Stage 1 物理隔离、容量最大、恢复和审计最清晰；依赖外盘在线、权限和容量探针。 |
| B | 本机独立根 `/Users/muce/1m_data/era100x_stage2`，采用同一布局和 1.20 倍空间门。 | 不依赖外盘挂载，但占用本机大容量并增加与其他研究数据争用风险。 |
| C | 用户指定其他绝对路径，并在批准时同时冻结布局、保留策略和空间系数。 | 灵活，但在路径、权限、容量和备份策略明确前仍阻塞批准。 |

**推荐：** 方案 A。它不复用 `/Volumes/FuckingLife/era100x_stage1`，只在同一卷建立独立 Stage 2 根，并保持 Stage 1 完全只读。

**必须由用户决定：** 根目录绝对路径；run/published 布局；失败 staging 保留期和清理授权；published/manifest/report 是否永久保留；空间安全系数（推荐 1.20）；外盘不可用时是 BLOCKED 还是允许批准的备用根。

## OQ-S2-002

**问题原文：** Stage 2预注册的主标的、主假设、主标签、主匹配方案，以及U-007/U-008/U-009/U-011参数域与失败线是什么？

**阻塞范围：** S2-T19 和 Stage 2 approval；Codex 不得从观察结果选择最有利设定。BTC/ETH 必须分开，非主标的只能作为预注册 secondary。

| 方案 | 内容 | 影响 |
| --- | --- | --- |
| A（推荐） | BTCUSDT 为 primary，ETHUSDT 为独立 secondary；H2 `TARGET_FIRST` 相对同标的条件随机基线的增量为主假设/主标签，AMBIGUOUS 保留并报告上下界；匹配按预注册时间段、context、波动状态和可用数据质量逐层放宽；参数仅使用手册允许域形成有限离散网格。 | 单一主检验减少研究者自由度；BTC Stage 1 无 venue-ID 冲突，主证据解释较简单；ETH 仍完整报告但不用于替换失败的 BTC 主结论。 |
| B | ETHUSDT 为 primary，BTCUSDT 为独立 secondary，其余口径同 A。 | 可直接以 ETH 为核心，但必须显式处理已审计的三组 venue-ID 冲突，且不得通过过滤冲突事实改善结果。 |
| C | BTCUSDT 与 ETHUSDT 共同 primary，分别判定并做预注册多重检验控制。 | 信息完整，但样本门、失败线和多重性更复杂；任一标的失败后的总体 Go/No-Go 解释必须预先冻结。 |

**推荐：** 方案 A，并采用“一个主标的、一个独立 secondary、有限离散参数域、固定匹配放宽序列、失败后不追加过滤器”的最小自由度设计。

**必须由用户决定：** primary instrument；主假设的精确统计表述；primary label/evidence level；匹配字段、bin 边界和放宽顺序；U-007 的来源优先级、merge tolerance、episode gap/re-arm 域；U-008 的 max target 域；U-009 的 15-35bp 止损离散值；U-011 的 5/8 与 15/25 分钟组合；主指标、cluster/CI 与多时期失败线；secondary 是否具有独立 Go/No-Go 权重。

## Approval boundary

本审查只给出选项和推荐，不将 OQ 标记为 RESOLVED。用户明确决定后，需更新 `OPEN_QUESTIONS.md`、S2-T19 预注册输入和 Plan 审批元数据；在此之前 Stage 2 不得 APPROVED 或 IN_PROGRESS。
