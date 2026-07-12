# S1-T06：主动买卖方向解析

## Metadata
- task_id: S1-T06
- task_version: 1.0
- status: PASSED
- stage_id: S1
- stage_plan_version: 1.0
- created_from_spec_version: V1.3.4
- created_from_commit: 0cf9bbd
- dependencies: S1-T05 PASS
- supersedes: task_version 0.1
- approved_by: Muce
- approved_at: 2026-07-12

## 1. 目标
依据已确认的Binance Trade maker字段语义生成aggressor side及可审计映射版本。
## 2. 背景
H2 Flow只能使用逐笔成交方向；不得从价格变化或Quote伪造方向。
## 3. 规格来源
§2、§9.4、§11、§29；H2证据边界。
## 4. 前置条件
S1-T05 PASS；maker字段语义在T02 registry中有来源记录。
## 5. 允许范围
BUY/SELL aggressor纯映射与unknown拒绝。
## 6. 禁止事项
不计算Flow阈值、信号、事件或策略变体结论。
## 7. 允许修改路径
`src/era100x/data/trades/aggressor.py`、`tests/data/trades/`、Task Validation/Traceability。
## 8. 禁止修改路径
raw/normalized输入、研究/策略、`docs/spec/**`。
## 9. 输入
NormalizedTrade fixture的maker flag；无该字段时失败而非推断。
## 10. 交付物
纯函数、映射版本和方向计数审计字段。
## 11. 实现要求
映射无状态、确定性；不使用float或相邻价格。
## 12. 测试要求
maker两值、缺失/非布尔、BTC/ETH、稳定序列和属性测试。
## 13. 验收标准
fixture预期方向100%一致；非法输入失败；未生成Flow规则。
## 14. 必须运行命令
`python3.12 -m pytest tests/data/trades -q`；`python3.12 scripts/run_quality_gate.py`。
## 15. 完成报告格式
语义来源→映射→测试→限制→PASS/FAIL。
## 16. 回滚方式
撤销映射；消费者失效后重建。
## 17. 开放问题
源字段语义冲突需停止并登记。
## 18. 变化触发器
Binance字段语义或registry版本变化。
## 19. 失效条件
方向映射被官方事实否定。
## 20. 变更历史
- 2026-07-12：v1.0，限定为方向解析而非Flow研究；状态DRAFT。
