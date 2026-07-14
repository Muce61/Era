# S1-T07：去重、异常、时间倒退与缺口检测

## Metadata
- task_id: S1-T07
- task_version: 1.1
- status: PASSED
- stage_id: S1
- stage_plan_version: 1.1
- created_from_spec_version: V1.3.4
- created_from_commit: 0cf9bbd
- dependencies: S1-T03 PASS; S1-T06 PASS
- supersedes: task_version 1.0
- approved_by: Muce
- approved_at: 2026-07-12

## 1. 目标
对Contract Price和NormalizedTrade执行去重、异常值、时间倒退、Trade ID连续性和时间缺口检测，输出质量标记而非静默修复。
## 2. 背景
G0要求时间单调且无未处理缺口；Stage 1不决定事件行为。
## 3. 规格来源
§3、§9.4 G0、§11、§29、附录J/L。
## 4. 前置条件
T03/T06 PASS；唯一键和允许重复语义已冻结。
## 5. 允许范围
检测、分类、报告和明确批准的确定性去重视图。
## 6. 禁止事项
不插值成交/秒、不重排后隐藏倒退、不删除原始记录、不把缺口填0。
## 7. 允许修改路径
`src/era100x/data/quality/`、`tests/data/quality/`、Task Validation/Traceability。
## 8. 禁止修改路径
raw输入、研究/策略、外部数据、`docs/spec/**`。
## 9. 输入
T03 Contract rows与T06 directed trades fixtures。
## 10. 交付物
quality issue schema、deterministic dedup view、gap segments和summary。
## 11. 实现要求
原始行数/去重行数均保留；同ID不同内容为冲突；时间单位显式；BTC/ETH分开。
## 12. 测试要求
完全重复、冲突重复、乱序、倒退、缺秒、Trade ID跳跃、负/零非法值及边界日切。
## 13. 验收标准
所有fixture异常被稳定分类；无静默修复；未处理P2数据缺口阻塞下游有效状态。
## 14. 必须运行命令
`python3.12 -m pytest tests/data/quality -q`；`python3.12 scripts/run_quality_gate.py`。
## 15. 完成报告格式
规则→问题计数→处理/未处理→命令→PASS/FAIL。
## 16. 回滚方式
撤销检测器；相关质量报告和下游数据标INVALIDATED。
## 17. 开放问题
真实缺口是否可补只能通过批准Trades源处理，不自行插值。
## 18. 变化触发器
主键、允许重复、缺口阈值或时间单位变化。
## 19. 失效条件
检测漏报、非确定或源hash变化。
## 20. 变更历史
- 2026-07-12：v1.0，将时间倒退和缺口提升为明确验收项；状态DRAFT。
- 2026-07-14：v1.1，canonical重复折叠、venue冲突事实全部保留并标记；回归PASS。
