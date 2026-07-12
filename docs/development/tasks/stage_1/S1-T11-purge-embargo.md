# S1-T11：时间切分、Purge与Embargo

## Metadata
- task_id: S1-T11
- task_version: 1.0
- status: DRAFT
- stage_id: S1
- stage_plan_version: 1.0
- created_from_spec_version: V1.3.4
- created_from_commit: 0cf9bbd
- dependencies: S1-T02 PASS
- supersedes: former S1-T12 v0.1
- approved_by: NONE
- approved_at: NONE

## 1. 目标
定义并验证按时间的train/validation/locked区间、purge与embargo纯契约，防止未来泄漏。
## 2. 背景
时间切分属于数据基础；具体研究窗口由后续预注册配置提供。
## 3. 规格来源
§11、§13.3、§29；`purge >= 最大特征回看 + 最大episode/持仓窗口`。
## 4. 前置条件
T02时间schema PASS；窗口参数只作为显式输入，不宣称最优。
## 5. 允许范围
区间数学、边界校验、manifest表达和重叠检查。
## 6. 禁止事项
不选择研究最优窗口、不读取事件结果、不打开LOCKED区间。
## 7. 允许修改路径
`src/era100x/data/splits/`、`tests/data/splits/`、Task Validation/Traceability。
## 8. 禁止修改路径
研究/回放、正式规格、数据输入。
## 9. 输入
UTC区间与显式lookback/episode/holding/embargo参数fixtures。
## 10. 交付物
split contract、无重叠证明、manifest字段和失败原因。
## 11. 实现要求
左闭右开；purge下界公式强制；locked interval不可被训练/调参消费。
## 12. 测试要求
相邻/重叠/空区间、DST无关UTC、边界纳秒、purge不足和确定性序列化。
## 13. 验收标准
所有泄漏fixture失败；合法split稳定；未冻结任何研究参数。
## 14. 必须运行命令
`python3.12 -m pytest tests/data/splits -q`；`python3.12 scripts/run_quality_gate.py`。
## 15. 完成报告格式
区间→公式→失败例→命令→PASS/FAIL。
## 16. 回滚方式
撤销split契约并使相关实验manifest失效。
## 17. 开放问题
具体窗口属于Stage 2/3预注册，不在本Task决定。
## 18. 变化触发器
lookback/episode/holding定义或区间策略变化。
## 19. 失效条件
出现区间重叠、purge不足或locked泄漏。
## 20. 变更历史
- 2026-07-12：v1.0，从原T12前移并限定为无泄漏契约；状态DRAFT。
