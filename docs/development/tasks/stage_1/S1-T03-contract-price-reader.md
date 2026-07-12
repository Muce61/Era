# S1-T03：1秒Contract Price读取与校验

## Metadata
- task_id: S1-T03
- task_version: 1.0
- status: DRAFT
- stage_id: S1
- stage_plan_version: 1.0
- created_from_spec_version: V1.3.4
- created_from_commit: 0cf9bbd
- dependencies: S1-T02 PASS
- supersedes: task_version 0.1
- approved_by: NONE
- approved_at: NONE

## 1. 目标
实现对批准格式的1秒Contract Price OHLCV只读、惰性、流式友好读取和校验。
## 2. 背景
H1依赖Contract Price；不得将其误称Mark或可执行Quote。
## 3. 规格来源
§2-3、§9.2、§12.3、§29；`STRATEGY-V1-PRICE-ONLY-HISTORICAL`。
## 4. 前置条件
S1-T02 schema/fixtures PASS；真实格式只支持S1-T01已审计项。
## 5. 允许范围
格式映射、列投影、时间/单位/OHLC约束与批次迭代。
## 6. 禁止事项
不重采样、不填缺秒、不下载、不生成事件或Mark/Quote。
## 7. 允许修改路径
`src/era100x/data/readers/contract_price.py`、`tests/data/readers/`、Task Validation/Traceability。
## 8. 禁止修改路径
外部输入、`docs/spec/**`、聚合/研究/执行模块。
## 9. 输入
T02 ContractPrice fixtures；全量路径仅在T14使用。
## 10. 交付物
reader API、格式错误/单位/时区校验和读取统计。
## 11. 实现要求
BTC/ETH显式instrument；时间UTC；价格/数量Decimal兼容；源行不被改写。
## 12. 测试要求
正常、空文件、缺列、OHLC非法、重复秒、倒退、边界时间和确定性批次。
## 13. 验收标准
小样本读取结果与fixture逐字段一致；错误输入非0失败且无输出。
## 14. 必须运行命令
`python3.12 -m pytest tests/data/readers -q`；`python3.12 scripts/run_quality_gate.py`。
## 15. 完成报告格式
格式→映射→测试→限制→PASS/FAIL。
## 16. 回滚方式
撤销reader/test；无数据写入需回滚。
## 17. 开放问题
未识别真实格式阻塞对应格式适配，不阻塞fixture能力。
## 18. 变化触发器
Contract Price格式、时区或单位变化。
## 19. 失效条件
reader输出schema/hash变化。
## 20. 变更历史
- 2026-07-12：v1.0，按`era100x.data`真实结构重写；状态DRAFT。
