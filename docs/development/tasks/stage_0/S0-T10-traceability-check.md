# S0-T10：Traceability 自动检查

## Metadata

- task_id: S0-T10
- task_version: 1.0
- status: DRAFT
- stage_id: S0
- stage_plan_version: 1.0
- created_from_spec_version: V1.3.4
- created_from_commit: cfd19ed3c9c76e8ef7fdada776bfb47cbcd50c9a
- dependencies: S0-T04, S0-T08, S0-T09
- supersedes: task_version 0.1
- approved_by: NONE
- approved_at: NONE

## 1. 目标

交付并验证“Traceability 自动检查”这一单一能力，使其可独立提交、审查和回滚。

## 2. 背景

Stage 0只建立可审计工程地基、契约和能力验证前置边界。延后Stage的行为在本Task只能登记或建立schema，不得提前实现。

## 3. 规格来源

- 手册章节：规则元数据要求、§27、附录A/C-E/G-H/I/K/L
- rule_id：全部32条rule_id、INV-001～INV-041、测试ID和阶段门
- 数据契约：traceability/rules.yaml及生成的人类可读覆盖报告
- 精确INV、Reason和测试映射以 `traceability/rules.yaml` 的本Task条目为准。

## 4. 前置条件

Stage 0 Plan v1.0和本Task均获人工批准；依赖Task有真实validation；规格基线有效；开始前复核适用OPEN问题。

## 5. 允许范围

建立机器检查器：规则、INV、契约、Reason、测试和Stage/Task引用的存在性、唯一性及状态一致性；不实现被追踪的业务规则。

## 6. 禁止事项

禁止修改 `docs/spec/**`；禁止数据下载、事件研究、回测、完整状态机/交易事务、Binance连接、API Key、测试网、真实资金、自动复利和自动进入下一Task。

## 7. 允许修改的路径

`scripts/check_traceability.py`、`tests/governance/`、`docs/development/TRACEABILITY.md`、`docs/development/traceability/rules.yaml`

## 8. 禁止修改的路径

除第7节列出的路径和本Task validation/traceability更新外，其他路径均禁止；尤其禁止 Stage 1～9 Plan/Task、正式规格、密钥和基线历史。

## 9. 输入

`spec-v1.3.4-final`、Stage 0 Plan v1.0、依赖Task产物与validation、适用的附录表和OPEN问题。

## 10. 交付物

第5节能力的最小产物、对应测试、`docs/development/validations/stage_0/S0-T10.md`和精确追踪更新；不得捆绑下一Task。

## 11. 实现要求

保持FROZEN原义；BASELINE只作起始配置；RESEARCH和BLOCKED项不得启用；失败必须返回非0并产生可审计说明；实现不得跨越本Task路径边界。

## 12. 测试要求

32规则、41 INV、附录契约、Reason和阶段门无缺失；INV唯一；引用文件/Task存在；PLANNED不得伪装IMPLEMENTED/PASSED。

## 13. 验收标准

严格检查退出码为0；T-INV-ID-001～004全部通过；生成覆盖报告明确行为性测试仍为PLANNED。

## 14. 必须运行的命令

```bash
python3.12 scripts/check_traceability.py --strict
```
```bash
python3.12 -m pytest tests/governance -q
```
```bash
python3.12 scripts/run_quality_gate.py
```

命令必须在仓库根目录运行并在validation中记录真实退出码；若命令尚不存在，本Task不得宣称完成。

## 15. 完成报告格式

适用规则与范围；实际修改文件；逐条命令/退出码；测试结果；追踪更新；未完成与OPEN问题；本Task Go/No-Go。不得自动继续。

## 16. 回滚方式

使用本Task独立提交反向提交；保留validation和失败证据。若共享契约已被消费，先标记消费者INVALIDATED再回滚。

## 17. 开放问题

需要改变风险、数据边界、执行语义或Binance能力判断时停止并登记。现有相关问题不得在本Task内自行关闭。

## 18. 变化触发器

规格、schema、枚举、公式、依赖锁、命令、输入hash或官方Binance事实变化时递增task_version并重新审批。

## 19. 失效条件

依赖Task重开、输入hash变化、测试被推翻、命令不可复现、追踪映射变化或越界实现时标记INVALIDATED。

## 20. 变更历史

- 2026-07-12：v0.1，初始泛化草案。
- 2026-07-12：v1.0，精确规格、依赖、路径、命令和验收边界；状态仍为DRAFT。
