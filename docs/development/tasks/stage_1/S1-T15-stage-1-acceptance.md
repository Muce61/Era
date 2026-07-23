# S1-T15：Stage 1集成验收

## Metadata
- task_id: S1-T15
- task_version: 1.0
- status: PASSED
- stage_id: S1
- stage_plan_version: 1.1
- created_from_spec_version: V1.3.4
- created_from_commit: 0cf9bbd
- dependencies: S1-T01～S1-T14 PASS
- supersedes: former S1-T13 v0.1
- approved_by: Muce
- approved_at: 2026-07-16

## 1. 目标
汇总Stage 1真实代码、fixture和全量数据证据，形成不自动晋级的人工验收入口。
## 2. 背景
Stage 1门槛要求Trades完整性、聚合一致性和能力标签全部通过。
## 3. 规格来源
§29、§38、§46、附录L；GATE-STAGE-1。
## 4. 前置条件
T01-T14均PASS且validation存在；无BLOCKER；全量manifest有效。
## 5. 允许范围
只执行门禁、核对证据、生成Stage validation和Go/No-Go建议。
## 6. 禁止事项
不修业务缺陷、不运行Stage 2、不批准Stage、不创建最终tag/baseline。
## 7. 允许修改路径
`docs/development/validations/stage_1/`、`docs/development/validations/stage_1_validation.md`、Traceability及必要治理状态。
## 8. 禁止修改路径
`src/**`、`tests/**`、数据输入、正式规格、Stage 2+。
## 9. 输入
全部Task validation、全量catalog/manifest/quality report、commit/config/lock hash。
## 10. 交付物
Stage 1 validation、规则/契约覆盖和人工最终批准入口。
## 11. 实现要求
区分小样本与全量结果；未运行项不得PASS；BTC/ETH分别结论。
## 12. 测试要求
全量质量门、strict traceability、Task/validation完整性、hash重现、NULL/能力标签和禁止Stage 2扫描。
## 13. 验收标准
第29节和附录L门槛全部有真实PASS证据；否则FAIL或CONDITIONAL PASS并停止。
## 14. 必须运行命令
`python3.12 scripts/run_quality_gate.py`；`python3.12 scripts/check_traceability.py --strict`；`python3.12 -m pytest -q`；T14冻结的数据验收命令。
## 15. 完成报告格式
Task统计→数据覆盖→门槛→命令→OPEN/限制→Go/No-Go。
## 16. 回滚方式
保留验收历史；错误报告失效后新版本替代。
## 17. 开放问题
未解决且影响数据门槛的问题阻止PASS。
## 18. 变化触发器
任一输入、代码、schema、config、manifest或quality证据变化。
## 19. 失效条件
上游重开、数据baseline失效或验收声明不实。
## 20. 变更历史
- 2026-07-12：v1.0，从原T13改为依赖小样本与全量双门；状态DRAFT。
- 2026-07-16：用户明确批准在S1-T14 PASS后执行Stage 1集成验收；状态IN_PROGRESS。
- 2026-07-16：全量质量门、数据只读一致性、NULL能力边界、可恢复调度回归和Traceability全部通过；Stage Validation结论PASS，Task状态PASSED。
