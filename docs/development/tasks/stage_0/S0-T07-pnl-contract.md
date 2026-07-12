# S0-T07：PnL 口径基础契约

## Metadata

- task_id: S0-T07
- task_version: 1.0
- status: PASSED
- stage_id: S0
- stage_plan_version: 1.0
- created_from_spec_version: V1.3.4
- created_from_commit: cfd19ed3c9c76e8ef7fdada776bfb47cbcd50c9a
- dependencies: S0-T05, S0-T06
- supersedes: task_version 0.1
- approved_by: Muce
- approved_at: 2026-07-12

## 1. 目标

交付并验证“PnL 口径基础契约”这一单一能力，使其可独立提交、审查和回滚。

## 2. 背景

Stage 0只建立可审计工程地基、契约和能力验证前置边界。延后Stage的行为在本Task只能登记或建立schema，不得提前实现。

## 3. 规格来源

- 手册章节：§6、§10.4、§14.1、附录F
- rule_id：PNL-NO-DOUBLE-SLIPPAGE；RESEARCH-H3-CONDITIONAL-ROUND-PROB（仅输出字段边界）
- 数据契约：proxy_entry_price、proxy_exit_price、proxy_net_pnl、estimated_exit_net_pnl、realized_net_pnl、final_realized_ticket_equity
- 精确INV、Reason和测试映射以 `traceability/rules.yaml` 的本Task条目为准。

## 4. 前置条件

Stage 0 Plan v1.0和本Task均获人工批准；依赖Task有真实validation；规格基线有效；开始前复核适用OPEN问题。

## 5. 允许范围

实现纯函数公式与字段模式测试；不实现回放、订单、Round状态机、成本参数选择或收益研究。

## 6. 禁止事项

禁止修改 `docs/spec/**`；禁止数据下载、事件研究、回测、完整状态机/交易事务、Binance连接、API Key、测试网、真实资金、自动复利和自动进入下一Task。

## 7. 允许修改的路径

`src/<root_package>/foundation/accounting/`、`tests/foundation/accounting/`

## 8. 禁止修改的路径

除第7节列出的路径和本Task validation/traceability更新外，其他路径均禁止；尤其禁止 Stage 1～9 Plan/Task、正式规格、密钥和基线历史。

## 9. 输入

`spec-v1.3.4-final`、Stage 0 Plan v1.0、依赖Task产物与validation、适用的附录表和OPEN问题。

## 10. 交付物

第5节能力的最小产物、对应测试、`docs/development/validations/stage_0/S0-T07.md`和精确追踪更新；不得捆绑下一Task。

## 11. 实现要求

保持FROZEN原义；BASELINE只作起始配置；RESEARCH和BLOCKED项不得启用；失败必须返回非0并产生可审计说明；实现不得跨越本Task路径边界。

## 12. 测试要求

真实PnL不二次扣滑点；代理价只扣一次情景；手续费/资金费口径正确；数量减小时required_target_bps不下降；final equity写入前置条件以契约断言表达。

## 13. 验收标准

附录F固定算例、Decimal属性测试、UT-PNL-015和边界失败测试通过；报告字段不能把proxy/estimated标为realized。

## 14. 必须运行的命令

```bash
python3.12 -m pytest tests/foundation/accounting -q
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
- 2026-07-12：纯 Decimal 公式、失败边界及 UT-PNL-015 验证通过；状态 PASSED。
