# S1-T12：数据质量报告与小样本验收

## Metadata
- task_id: S1-T12
- task_version: 1.1
- status: PASSED
- stage_id: S1
- stage_plan_version: 1.1
- created_from_spec_version: V1.3.4
- created_from_commit: 0cf9bbd
- dependencies: S1-T07, S1-T09, S1-T10, S1-T11 PASS
- supersedes: task_version 1.0
- approved_by: Muce
- approved_at: 2026-07-12

## 1. 目标
汇总fixture级schema、完整性、聚合、能力标签和split证据，证明Stage 1能力可在小样本确定性验收。
## 2. 背景
小样本PASS只证明能力，不证明BTC/ETH全量覆盖。
## 3. 规格来源
§29、附录J/L；Stage 0 deterministic manifest。
## 4. 前置条件
T07/T09/T10/T11 PASS且各自validation存在。
## 5. 允许范围
报告生成、门槛判断和fixture manifest汇总。
## 6. 禁止事项
不下载/处理全量数据，不输出事件或收益，不把样本PASS写成Stage PASS。
## 7. 允许修改路径
`src/era100x/data/reporting/`、`tests/data/reporting/`、`scripts/report_stage1_quality.py`、Task Validation/Traceability。
## 8. 禁止修改路径
外部输入、研究/执行、正式规格。
## 9. 输入
T02-T11 fixture产物、checksums和validations。
## 10. 交付物
机器可读quality summary、Markdown样本报告和能力/限制矩阵。
## 11. 实现要求
BTC/ETH、H1/H2和source分别统计；未运行全量字段明确`NOT_RUN_FULL_DATA`。
## 12. 测试要求
缺报告、失败门、错误能力升级、排序/序列化确定性和报告hash。
## 13. 验收标准
小样本所有门PASS且报告明确不代表全量完整性或研究收益。
## 14. 必须运行命令
`python3.12 -m pytest tests/data/reporting -q`；`python3.12 scripts/run_quality_gate.py`。
## 15. 完成报告格式
fixture门→结果→未运行全量→命令→PASS/FAIL。
## 16. 回滚方式
撤销报告器；样本报告标INVALIDATED。
## 17. 开放问题
OQ-S1-001/002继续阻塞全量，不阻塞本Task。
## 18. 变化触发器
任何上游schema/质量/聚合/split变化。
## 19. 失效条件
上游Task重开或报告遗漏失败证据。
## 20. 变更历史
- 2026-07-12：v1.0，将样本能力验收与全量运行分离；状态DRAFT。
- 2026-07-14：v1.1，增加Trade Identity v2及官方月/日冲突集合质量门；回归PASS。
