# S1-T13：全量数据运行计划与预检

## Metadata
- task_id: S1-T13
- task_version: 1.0
- status: BLOCKED
- stage_id: S1
- stage_plan_version: 1.0
- created_from_spec_version: V1.3.4
- created_from_commit: 0cf9bbd
- dependencies: S1-T01, S1-T12 PASS; OQ-S1-001/002 RESOLVED
- supersedes: NONE
- approved_by: Muce
- approved_at: 2026-07-12

## 1. 目标
冻结全量BTC/ETH数据源、绝对路径、覆盖区间、容量、run_id、恢复策略和预期资源，不执行下载或转换。
## 2. 背景
全量运行成本高且有外部依赖，必须先形成可审查预检。
## 3. 规格来源
§3、§16、§29、§45；OQ-S1-001/002决定。
## 4. 前置条件
T01/T12 PASS；两项OQ由人工确认；路径权限和空间可读验证。
## 5. 允许范围
只读preflight、文件计数/抽样、容量估算、命令计划和恢复检查点设计。
## 6. 禁止事项
不下载、不转换、不写全量分区、不删除/覆盖数据。
## 7. 允许修改路径
`scripts/preflight_stage1_full_data.py`、`tests/data/preflight/`、`docs/development/reviews/stage_1_full_data_run_v1.0.md`、Task Validation/Traceability。
## 8. 禁止修改路径
`src/**`、外部输入、正式规格、Stage 2+。
## 9. 输入
人工批准绝对路径/来源/区间、T01资产报告、T12样本报告。
## 10. 交付物
可复制全量命令、磁盘/时间估算、checkpoint、失败恢复、预期文件/manifest清单。
## 11. 实现要求
命令必须显式`--input-root/--output-root/--run-id`；禁止默认扫描home；输入只读断言。
## 12. 测试要求
fixture验证空间不足、同根输入输出、未授权路径、已有run_id和缺失源文件失败。
## 13. 验收标准
预检在真实批准路径上PASS；没有写入/下载；用户可审查T14命令和成本。
## 14. 必须运行命令
`python3.12 -m pytest tests/data/preflight -q`；`python3.12 scripts/run_quality_gate.py`；真实preflight命令由已确认路径填入Validation。
## 15. 完成报告格式
路径/授权→覆盖/容量→命令→恢复→PASS/FAIL。
## 16. 回滚方式
撤销preflight代码/计划；无数据产物。
## 17. 开放问题
OQ未解决则本Task BLOCKED，不得条件通过。

- OQ-S1-003：当前磁盘未满足预计峰值×1.20安全余量；等待人工扩容或批准新的存储/保留设计。
## 18. 变化触发器
路径、来源、区间、空间或run命令变化。
## 19. 失效条件
预检后输入hash/目录清单或容量显著变化。
## 20. 变更历史
- 2026-07-12：v1.0，新增全量运行前人工门；状态DRAFT。
- 2026-07-12：真实预检发现约348.67GiB安全空间缺口；状态BLOCKED，未创建工作根。
