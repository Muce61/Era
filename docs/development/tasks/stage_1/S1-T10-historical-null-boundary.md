# S1-T10：历史NULL与证据能力边界

## Metadata
- task_id: S1-T10
- task_version: 1.0
- status: DRAFT
- stage_id: S1
- stage_plan_version: 1.0
- created_from_spec_version: V1.3.4
- created_from_commit: 0cf9bbd
- dependencies: S1-T03 PASS; S1-T05 PASS; S1-T06 PASS
- supersedes: former S1-T11 v0.1
- approved_by: NONE
- approved_at: NONE

## 1. 目标
以schema和回归门禁止历史数据伪造Quote、接收时间、部分成交或真实执行字段，并正确标记H1/H2能力。
## 2. 背景
NULL/0语义是FROZEN边界，应在数据进入Parquet和报告前验证。
## 3. 规格来源
§2-3、§6、§10.1、§25；`DATA-HISTORICAL-NO-FAKE-EXECUTION`；UT-DATA-013。
## 4. 前置条件
T03/T05/T06 PASS；历史证据row schema存在。
## 5. 允许范围
能力标签和历史字段guard；不生成情景成本。
## 6. 禁止事项
不得用0、Contract Price、文件mtime或估计值填充Bid/Ask/ts_recv/延迟/部分成交/滑点。
## 7. 允许修改路径
`src/era100x/data/evidence/`、`tests/data/evidence/`、Task Validation/Traceability。
## 8. 禁止修改路径
规格、前向/执行模块、raw输入。
## 9. 输入
H1 Contract与H2 Trade fixtures，包括NULL及非法0案例。
## 10. 交付物
historical evidence guard、H1/H2 capability标签和失败报告。
## 11. 实现要求
H1/H2 reference type仅Contract/Trade；F1字段存在非NULL即失败；NULL序列化保持NULL。
## 12. 测试要求
reference_ask、spread_bps、ts_recv/latency、actual fill/partial fill/slippage的NULL和非法0/伪值。
## 13. 验收标准
所有非法历史执行字段被拒绝；合法NULL round-trip；UT-DATA-013通过。
## 14. 必须运行命令
`python3.12 -m pytest tests/data/evidence -q`；`python3.12 scripts/run_quality_gate.py`。
## 15. 完成报告格式
字段→能力等级→失败样例→命令→PASS/FAIL。
## 16. 回滚方式
撤销guard使消费者INVALIDATED；不得保留无guard数据为有效。
## 17. 开放问题
无；该边界不得由OPEN问题放宽。
## 18. 变化触发器
证据字段或H1/H2定义变化。
## 19. 失效条件
非法字段可通过或NULL被改写。
## 20. 变更历史
- 2026-07-12：v1.0，从原T11前移并扩展为证据门；状态DRAFT。
