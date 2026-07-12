# S1-T08：Parquet分区、Catalog与Checksum

## Metadata
- task_id: S1-T08
- task_version: 1.0
- status: PASSED
- stage_id: S1
- stage_plan_version: 1.0
- created_from_spec_version: V1.3.4
- created_from_commit: 0cf9bbd
- dependencies: S1-T07 PASS
- supersedes: task_version 0.1
- approved_by: Muce
- approved_at: 2026-07-12

## 1. 目标
建立版本化Parquet分区、稳定catalog、文件checksum和原子run目录发布。
## 2. 背景
Stage 1要求重复构建hash一致；文件级字节hash与逻辑内容hash必须区分。
## 3. 规格来源
§23、§26、§29、附录J/L；Stage 0 manifest/hash能力。
## 4. 前置条件
S1-T07 PASS；分区键、排序键和schema version已确认。
## 5. 允许范围
Polars/Parquet写入、按instrument/date/source分区、catalog及SHA-256。
## 6. 禁止事项
不覆盖已发布run、不写外部只读根、不把大数据提交Git。
## 7. 允许修改路径
`src/era100x/data/storage/`、`tests/data/storage/`、`scripts/build_stage1_catalog.py`、Task Validation/Traceability。
## 8. 禁止修改路径
外部输入、研究/执行、`docs/spec/**`。
## 9. 输入
T07 validated rows；fixture输出到临时目录，全量输出到批准data root。
## 10. 交付物
partition writer、catalog schema、byte/logical checksum、run manifest和atomic publish。
## 11. 实现要求
稳定排序/列序/schema metadata；相同输入重复构建逻辑hash一致；库版本入manifest。
## 12. 测试要求
重复构建、分区边界、partial failure、已存在run、checksum篡改、BTC/ETH隔离。
## 13. 验收标准
fixture两次构建catalog和逻辑hash一致；失败无半发布目录。
## 14. 必须运行命令
`python3.12 -m pytest tests/data/storage -q`；`python3.12 scripts/run_quality_gate.py`。
## 15. 完成报告格式
分区→hash→原子性→命令→限制→PASS/FAIL。
## 16. 回滚方式
撤销writer；失败run保留manifest并INVALIDATED，不删除输入。
## 17. 开放问题
最终工作根/容量由OQ-S1-001决定。
## 18. 变化触发器
Parquet引擎、schema、排序或分区规则变化。
## 19. 失效条件
相同环境逻辑hash不一致或catalog遗漏文件。
## 20. 变更历史
- 2026-07-12：v1.0，补充catalog、逻辑hash和原子发布；状态DRAFT。
