# S1-T05：Trades标准化

## Metadata
- task_id: S1-T05
- task_version: 1.0
- status: DRAFT
- stage_id: S1
- stage_plan_version: 1.0
- created_from_spec_version: V1.3.4
- created_from_commit: 0cf9bbd
- dependencies: S1-T04 PASS
- supersedes: task_version 0.1
- approved_by: NONE
- approved_at: NONE

## 1. 目标
将不可变RawTrade映射为版本化NormalizedTrade，冻结主键、Decimal、时间和来源lineage。
## 2. 背景
方向解析和质量检查必须消费同一规范化契约，不能各自解释源字段。
## 3. 规格来源
§2-3、§11、§23-25、§29、附录C/J。
## 4. 前置条件
S1-T04离线导入PASS；源字段含义已由schema记录。
## 5. 允许范围
字段重命名、类型转换、单位/UTC归一化、source hash与row identity。
## 6. 禁止事项
不去重、不补缺失成交、不推断Quote/recv/slippage、不解析策略事件。
## 7. 允许修改路径
`src/era100x/data/normalize/`、`tests/data/normalize/`、Task Validation/Traceability。
## 8. 禁止修改路径
raw输入、`docs/spec/**`、研究/执行路径。
## 9. 输入
T04 raw fixtures/manifest；输出仅写批准的normalized run目录。
## 10. 交付物
NormalizedTrade转换器、schema version、lineage和行数/失败统计。
## 11. 实现要求
Trade ID与instrument组成稳定身份；价格/数量禁float；时间不使用本地时区。
## 12. 测试要求
round-trip、边界Decimal、坏时间/负数量/未知列、BTC/ETH隔离和确定性输出。
## 13. 验收标准
相同raw+config得到逐行一致输出hash；错误行策略明确且不静默丢弃。
## 14. 必须运行命令
`python3.12 -m pytest tests/data/normalize -q`；`python3.12 scripts/run_quality_gate.py`。
## 15. 完成报告格式
映射→lineage→失败行→命令→PASS/FAIL。
## 16. 回滚方式
撤销转换器；旧normalized run标INVALIDATED，不覆盖。
## 17. 开放问题
真实源列歧义需OQ/CR，不按经验猜测。
## 18. 变化触发器
raw schema、单位、主键或错误策略变化。
## 19. 失效条件
转换hash不稳定或lineage断裂。
## 20. 变更历史
- 2026-07-12：v1.0，冻结标准化与质量职责分离；状态DRAFT。
