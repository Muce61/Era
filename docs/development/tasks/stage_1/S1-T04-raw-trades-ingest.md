# S1-T04：Binance Trades不可变原始获取与导入

## Metadata
- task_id: S1-T04
- task_version: 1.0
- status: DRAFT
- stage_id: S1
- stage_plan_version: 1.0
- created_from_spec_version: V1.3.4
- created_from_commit: 0cf9bbd
- dependencies: S1-T02 PASS; OQ-S1-002 resolved before any network/full acquisition
- supersedes: task_version 0.1
- approved_by: NONE
- approved_at: NONE

## 1. 目标
建立Binance USDⓈ-M BTCUSDT/ETHUSDT Trades归档的不可变原始获取/导入能力与来源manifest。
## 2. 背景
Trades是唯一允许补齐的历史微观结构；网络获取授权尚未确定。
## 3. 规格来源
§2-3、§11、§29；`DATA-HISTORICAL-NO-FAKE-EXECUTION`。
## 4. 前置条件
离线导入只需T02；任何网络访问还需OQ-S1-002明确授权、来源和覆盖。
## 5. 允许范围
离线fixture/本地归档导入、内容hash、来源URL字符串、状态码/重试计划；获批后才可下载公开Trades。
## 6. 禁止事项
无授权网络、API Key、账户API、aggTrades冒充Trades、覆盖或删除原始文件、补Quote/Mark/L2。
## 7. 允许修改路径
`src/era100x/data/ingest/raw_trades.py`、`tests/data/ingest/`、`configs/data/`、`scripts/import_stage1_trades.py`、Task Validation/Traceability。
## 8. 禁止修改路径
外部归档、`docs/spec/**`、执行/研究模块。
## 9. 输入
T02 RawTrade fixture；全量来源/区间由OQ-S1-002确认，原始落盘到批准的ignored data root。
## 10. 交付物
不可变raw文件、per-file SHA-256、source/coverage/size manifest及可恢复导入日志。
## 11. 实现要求
存在且hash一致则幂等跳过；冲突失败；临时文件原子完成；重试不改变对象身份。
## 12. 测试要求
fixture导入、重复运行、hash冲突、截断文件、失败恢复、BTC/ETH隔离；网络测试默认不运行。
## 13. 验收标准
小样本离线导入可重复；未授权网络调用被拒绝；全量获取只在T14验收。
## 14. 必须运行命令
`python3.12 -m pytest tests/data/ingest -q`；`python3.12 scripts/run_quality_gate.py`。
## 15. 完成报告格式
来源/授权→文件/hash→重试证据→未运行网络项→PASS/FAIL。
## 16. 回滚方式
撤销代码；生成raw按run manifest隔离，不删除用户原始数据。
## 17. 开放问题
OQ-S1-002阻塞网络和全量覆盖，不阻塞离线fixture。
## 18. 变化触发器
官方归档格式、URL、Trade ID或覆盖变化。
## 19. 失效条件
源hash变化、非Binance Trades混入或不可重现。
## 20. 变更历史
- 2026-07-12：v1.0，分离离线导入与需授权的全量获取；状态DRAFT。
