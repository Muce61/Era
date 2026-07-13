# S1-T14：全量数据构建与可重复性验证

## Metadata
- task_id: S1-T14
- task_version: 1.1
- status: IN_PROGRESS
- stage_id: S1
- stage_plan_version: 1.0
- created_from_spec_version: V1.3.4
- created_from_commit: 0cf9bbd
- dependencies: S1-T13 PASS and explicit full-data execution approval
- supersedes: task_version 1.0
- approved_by: Muce
- approved_at: 2026-07-13

## 1. 目标
按冻结命令执行BTC/ETH全量Trades获取/导入、标准化、质量检查、Parquet/K线构建，并验证重复构建逻辑hash。
## 2. 背景
此Task是Stage 1唯一全量数据运行门；前序PASS不能替代它。
## 3. 规格来源
§2-3、§29、附录J/L；T13批准运行计划。
## 4. 前置条件
T13 PASS；用户明确批准网络/路径/区间；磁盘充足；输入只读；run_id全新。
## 5. 允许范围
仅批准来源和区间的全量Stage 1流水线及抽样重复构建。
## 6. 禁止事项
账户API/API Key、Quote/Mark/L2、事件研究、覆盖旧run、删除源数据或自动扩展区间。
## 7. 允许修改路径
批准的外置工作根、`src/era100x/data/full_build/`、`tests/data/full_build/`、`scripts/run_stage1_full_build.py`、轻量Manifest/Catalog摘要、Task Validation/Traceability。
## 8. 禁止修改路径
除第7节明确扩围路径外的`src/**`、`tests/**`、`docs/spec/**`；不得修改S1-T01～T13既有契约语义。
## 9. 输入
T13冻结的source inventory/config/commit/lock/path/coverage/run_id。
## 10. 交付物
BTC/ETH完整catalog、quality report、coverage/gap表、checksums、manifest和重复构建证据。
## 11. 实现要求
可恢复、append-only run；BTC/ETH分开；失败区间明确；第二次独立输出或批准抽样证明逻辑hash一致。
## 12. 测试要求
先重跑全量质量门，再运行冻结命令；验证行数、时间范围、duplicate/gap、NULL能力、聚合差异、checksum和manifest。
## 13. 验收标准
目标覆盖或批准的明确缺口；所有硬门PASS；重复构建hash一致；未把历史证据升级为F1。
## 14. 必须运行命令
`python3.12 scripts/run_quality_gate.py`；T13冻结的全量命令；`python3.12 scripts/check_traceability.py --strict`。
## 15. 完成报告格式
来源/区间→运行统计→质量/差异→hash→限制→PASS/FAIL。
## 16. 回滚方式
保留失败run/manifest并INVALIDATED；不删除源；新run恢复。
## 17. 开放问题
任何未批准缺口或来源变化立即停止。
## 18. 变化触发器
输入hash、覆盖、实现、依赖或配置变化。
## 19. 失效条件
源/代码/config/hash变化或重复构建不一致。
## 20. 变更历史
- 2026-07-12：v1.0，新增全量数据执行与重现门；状态DRAFT。
- 2026-07-13：v1.1，人工批准全量编排、流式解析、checkpoint/manifest及测试扩围；状态IN_PROGRESS。
