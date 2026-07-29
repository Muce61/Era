# S2P18 正式编排实现验证

- status: IMPLEMENTED / FORMAL RUN NOT AUTHORIZED
- approved_scope: infrastructure implementation and clean commit only
- formal_run_executed: false
- stage3_locked: true

## 已实现

- commit-bound approval receipt；
- adapter plan 全十 Task、argv、执行文件 Hash 与超时验证；
- Authority-before-Run 和十二类固定输入 Hash；
- 每个 Authority 只允许一个 Run，每个 approval 只允许一个 Authority；
- 唯一 Run lock；
- T11–T20 冻结 DAG 和上游 receipt Hash 门；
- 版本化、前向 Hash 链式 checkpoint；
- producer stdout/stderr append-only 日志；
- 失败 Run 终态 FAILED、保留前缀、禁止 resume、保持 unpublished；
- 总 Catalog、Manifest、reconcile；
- 同卷 hard-link 候选发布、完整发布文件 Hash Verify、Verify 后 publication receipt；
- Stage 3 永久锁定字段。

## 执行边界

本验证使用隔离 fake producer 检查编排，不产生研究数据。生产 adapter plan 必须在正式
批准时绑定实际 T11–T20 producer 可执行文件；缺任一 Task、可执行文件 Hash 漂移、
receipt 身份不一致或输出 Hash 漂移时，Run ID 创建前或对应 Task 处失败关闭。

正式运行顺序为：

`record-approval → freeze-authority → run/resume → task checkpoints → reconcile →`
`candidate publication → full Verify → publication receipt`。

## 已执行验证

- `PYTHONPATH=. .venv/bin/pytest -q`：865 passed；
- `.venv/bin/ruff check .`：PASS；
- `.venv/bin/mypy src scripts`：PASS，280 source files；
- `scripts/check_governance_state.py --strict`：PASS；
- `scripts/check_traceability.py --strict`：PASS；
- jCodeMunch 增量索引：454 files / 8,548 symbols。

以上测试只覆盖代码、隔离 fake producer 和既有只读证据。未创建正式 approval、
Authority、Run、Catalog、Manifest、Verify 或 publication。
