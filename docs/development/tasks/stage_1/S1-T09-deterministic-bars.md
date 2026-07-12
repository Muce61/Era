# S1-T09：确定性K线聚合

## Metadata
- task_id: S1-T09
- task_version: 1.0
- status: PASSED
- stage_id: S1
- stage_plan_version: 1.0
- created_from_spec_version: V1.3.4
- created_from_commit: 0cf9bbd
- dependencies: S1-T08 PASS
- supersedes: task_version 0.1
- approved_by: Muce
- approved_at: 2026-07-12

## 1. 目标
从规范化Trade或已验证Contract Price按明确UTC边界生成确定性OHLCV，并与可比较的既有bar做一致性报告。
## 2. 背景
重聚合一致性是Stage 1门槛；不同价格源不得混成同一bar。
## 3. 规格来源
§2-3、§11、§29、附录C/J/L；`STRATEGY-V1-PRICE-ONLY-HISTORICAL`。
## 4. 前置条件
S1-T08 PASS；source type、interval和边界规则进入config/hash。
## 5. 允许范围
1s/批准分钟间隔OHLCV聚合和对比统计。
## 6. 禁止事项
不前向填充、不混Contract/Trade、不生成事件/标签/收益。
## 7. 允许修改路径
`src/era100x/data/aggregate/`、`tests/data/aggregate/`、Task Validation/Traceability。
## 8. 禁止修改路径
raw输入、研究/回测、`docs/spec/**`。
## 9. 输入
T08 curated partitions；小样本含跨秒/分钟/日边界。
## 10. 交付物
bar聚合器、source标签、对比结果及确定性hash。
## 11. 实现要求
UTC左闭右开；open/close由时间+稳定tie-breaker；volume定义和空桶政策显式。
## 12. 测试要求
边界、同时间多Trade、空桶、乱序输入、Decimal OHLC、重复运行和源隔离。
## 13. 验收标准
打乱输入不改变输出；固定fixture精确相等；差异报告不静默容忍。
## 14. 必须运行命令
`python3.12 -m pytest tests/data/aggregate -q`；`python3.12 scripts/run_quality_gate.py`。
## 15. 完成报告格式
边界/源→结果hash→差异→命令→PASS/FAIL。
## 16. 回滚方式
撤销聚合器；聚合产物INVALIDATED。
## 17. 开放问题
真实源volume含义不明时停止对应对比。
## 18. 变化触发器
interval、边界、tie-break、volume或source变化。
## 19. 失效条件
聚合非确定或跨源混用。
## 20. 变更历史
- 2026-07-12：v1.0，补充价格源和UTC边界；状态DRAFT。
