# S1-T02：Schema Registry与样本数据契约

## Metadata
- task_id: S1-T02
- task_version: 1.1
- status: PASSED
- stage_id: S1
- stage_plan_version: 1.1
- created_from_spec_version: V1.3.4
- created_from_commit: 0cf9bbd
- dependencies: S1-T01 PASS
- supersedes: task_version 1.0
- approved_by: Muce
- approved_at: 2026-07-12

## 1. 目标
冻结ContractPrice1s、RawTrade、NormalizedTrade、HistoricalEvidenceRow、ContractBar、DataQuality与DataManifest的Stage 1 schema及最小fixture规范。
## 2. 背景
Stage 0仅有通用契约骨架；当前没有`era100x.data`包或数据fixture。
## 3. 规格来源
§2-3、§23-25、附录C/D/J；Decimal与时间源使用Stage 0类型。
## 4. 前置条件
S1-T01报告存在；未知源字段可标记待映射，不得猜语义。
## 5. 允许范围
schema、字段能力标签、fixture schema及顶层`data`包显式允许清单。
## 6. 禁止事项
不实现读取/下载/聚合；不修改Stage 0已冻结契约语义。
## 7. 允许修改路径
`src/era100x/data/schema/`、`tests/data/schema/`、`tests/fixtures/stage_1/`、`tests/test_package_import.py`、`configs/data/`、Task Validation/Traceability。
## 8. 禁止修改路径
`docs/spec/**`、`src/era100x/foundation/**`、`src/era100x/contracts/**`、Stage 2+。
## 9. 输入
V1.3.4字段表、S1-T01格式发现；fixture必须小、无敏感信息、可明确许可提交。
## 10. 交付物
版本化registry、字段类型/nullable/单位/时区/主键定义及正常/边界/损坏fixtures。
## 11. 实现要求
未知字段拒绝；Decimal禁float；UTC纳秒语义明确；历史不可得执行字段nullable且无默认0。
## 12. 测试要求
schema round-trip、unknown字段、单位、nullable、坏fixture和未知顶层包拒绝。
## 13. 验收标准
registry覆盖计划全部对象；fixture可供T03-T12离线验收；`data`之外未知顶层包仍失败。
## 14. 必须运行命令
`python3.12 -m pytest tests/data/schema tests/test_package_import.py -q`；`python3.12 scripts/run_quality_gate.py`。
## 15. 完成报告格式
对象/字段→fixture→兼容性→命令→限制→PASS/FAIL。
## 16. 回滚方式
撤销新data包/fixture并恢复允许清单；保留validation。
## 17. 开放问题
源文件未知列写入S1-T01报告，不自行映射。
## 18. 变化触发器
源schema、单位、主键或nullable变化。
## 19. 失效条件
下游已消费schema后schema hash变化。
## 20. 变更历史
- 2026-07-12：v1.0，合并schema registry与可复用样本契约；状态DRAFT。
- 2026-07-14：v1.1，CR-2026-001重开并PASS；Trade Identity v2新增canonical身份和冲突标签。
