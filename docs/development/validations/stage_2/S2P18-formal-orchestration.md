# S2P18 正式编排实现验证

- status: IMPLEMENTED / FORMAL RUN NOT AUTHORIZED
- approved_scope: infrastructure implementation and clean commit only
- formal_run_executed: false
- stage3_locked: true

## 已实现

- commit-bound approval receipt；
- adapter plan 全十 Task、argv、执行文件 Hash 与超时验证；
- Authority-before-Run 和十二类固定输入绝对路径、文件 SHA-256、语义 binding Hash；
- 覆盖完整周期的 Contract Price 逐分区 Catalog 生成与消费前 Hash 重验工具；
- 十个真实 S2P18 producer handlers；旧实现只作为数学引擎，不继承旧 receipt/Run；
- T12–T18 canonical-Trades-only H2 与 T11→T19/T20 生命周期分支隔离；
- 每个 Authority 只允许一个 Run，每个 approval 只允许一个 Authority；
- 唯一 Run lock；
- T11–T20 冻结 DAG 和上游 receipt Hash 门；
- 版本化、前向 Hash 链式 checkpoint；
- producer stdout/stderr append-only 日志；
- retryable interruption 保留同一非终态 Run，并以 append-only 新 attempt 恢复当前 Task；
- 非恢复型失败 Run 终态 FAILED、保留前缀、禁止 resume、保持 unpublished；
- 总 Catalog、Manifest、reconcile；
- 同卷 hard-link 候选发布、完整发布文件 Hash Verify、Verify 后 publication receipt；
- Stage 3 永久锁定字段。

## 执行边界

本验证使用隔离 fake producer、最小 production handler fixture 和输入 Catalog 漂移
fixture 检查编排，不产生研究数据。完整周期来源审计工具在本提交中只做静态/单元验证，
未写正式来源证据。生产 adapter plan 必须在下一干净 commit 上另行冻结；缺任一 Task、
可执行文件 Hash 漂移、输入文件漂移、receipt 身份不一致或输出 Hash 漂移时，Run ID
创建前或对应 Task 处失败关闭。

正式运行顺序为：

`record-approval → freeze-authority → run/resume → task checkpoints → reconcile →`
`candidate publication → full Verify → publication receipt`。

## 已执行验证

- OQ-S2-013 定向合同、input Catalog、完整周期 Catalog fixture、十 adapters 与同 Run
  retryable Task 恢复：37 passed；
- lifecycle/governance/UI 相关回归：122 passed；
- 全仓 870 项测试按内存隔离分片全部 PASS（75 + 126 + 253 + 118 + 67 + 223 + 8）；
- 单进程全仓命令在 91% 后被本机终止且未输出 pytest 终态，因此不将其伪报为 PASS；
- `.venv/bin/ruff check .`：PASS；
- `.venv/bin/mypy src scripts`：PASS，283 source files；
- `scripts/check_governance_state.py --strict`：PASS；
- `scripts/check_traceability.py --strict`：PASS；
- jCodeMunch 提交前重建索引：459 files / 8,603 symbols。

以上测试只覆盖代码、隔离 fake producer、最小真实 handler fixture 和既有只读证据。
未执行完整周期审计，未创建正式 source/input Catalog、adapter plan、approval、Authority、
Run、Manifest、Verify 或 publication。
