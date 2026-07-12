# S1-T01：现有资产与路径审计

## Metadata
- task_id: S1-T01
- task_version: 1.0
- status: DRAFT
- stage_id: S1
- stage_plan_version: 1.0
- created_from_spec_version: V1.3.4
- created_from_commit: 0cf9bbd
- dependencies: Stage 0 v1.0 PASSED; Stage 1 Plan v1.0 APPROVED
- supersedes: task_version 0.1
- approved_by: NONE
- approved_at: NONE

## 1. 目标
只读盘点现有BTC/ETH秒级、分钟级及Trades资产，形成路径、格式、时间范围、大小、权限、重复候选和容量报告。
## 2. 背景
当前仓库没有数据模块或已批准绝对数据路径；不得从旧项目猜路径。
## 3. 规格来源
§2-3、§29；Stage 0 manifest/audit；规则`DATA-HISTORICAL-NO-FAKE-EXECUTION`。
## 4. 前置条件
用户批准本Task并至少提供候选只读根；OQ-S1-001可在审计后细化。
## 5. 允许范围
文件元数据、扩展名、schema抽样、hash抽样和空间检查；不下载、不转换、不删除。
## 6. 禁止事项
禁止写输入根、遍历未授权根、复制全量文件、推断缺失Quote或执行字段。
## 7. 允许修改路径
`scripts/audit_stage1_assets.py`、`tests/data/audit/`、`docs/development/reviews/stage_1_asset_audit.md`、Task Validation/Traceability。
## 8. 禁止修改路径
`docs/spec/**`、`src/**`、输入数据根、Stage 0基线文件、Stage 2+。
## 9. 输入
人工批准的候选绝对路径；默认只读。不得把绝对路径提交到仓库。
## 10. 交付物
资产清单、不可读/格式未知项、建议逻辑映射和OQ-S1-001更新。
## 11. 实现要求
审计输出按路径稳定排序；BTC/ETH分列；不读取整个大文件；记录命令、HEAD和权限。
## 12. 测试要求
合成目录验证只读、符号链接、重复文件、不可读文件和稳定输出。
## 13. 验收标准
fixture审计确定性；真实路径仅完成获授权的只读元数据审计；没有输入修改。
## 14. 必须运行命令
`python3.12 -m pytest tests/data/audit -q`；`python3.12 scripts/run_quality_gate.py`。
## 15. 完成报告格式
路径边界→资产汇总→未知格式/覆盖→命令→OQ→PASS/FAIL。
## 16. 回滚方式
撤销脚本、测试和报告；不触碰任何外部数据。
## 17. 开放问题
OQ-S1-001、OQ-S1-002。
## 18. 变化触发器
候选根、权限、格式或覆盖区间变化。
## 19. 失效条件
资产移动、hash变化或审计越界。
## 20. 变更历史
- 2026-07-12：v1.0，替代泛化v0.1；状态DRAFT。
