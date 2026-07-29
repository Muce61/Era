# S2P110-T11～T20 合并 Task 合同

## 状态

- status: `APPROVED / IMPLEMENTED_VALIDATED / PREPARE_PENDING / FORMAL RUN GATED`
- task_ids: [S2P110-T11, S2P110-T12, S2P110-T13, S2P110-T14, S2P110-T15, S2P110-T16, S2P110-T17, S2P110-T18, S2P110-T19, S2P110-T20]
- execution_limit: `S2P110-T20`
- formal_run_executed: `false`
- stage3_locked: `true`

## Task 模式

| Task | 模式 | 责任 |
|---|---|---|
| T11 | `EXECUTED_NEW` | PURE_TRADES comparator + Contract Price OHLC lifecycle |
| T12～T18 | `SEALED_ADOPTION` | 验证并引用语义未变化的正式 H2/匹配/placebo/cluster 证据 |
| T19～T20 | `EXECUTED_NEW` | 新 lifecycle 与历史 H2 分流综合、最终验收 |

`TASK_COMPLETED` 必须记录 `execution_mode`。adoption 还必须记录 source Run、source
receipt/Verify、source output tree 和 adoption binding Hash。adoption 不产生研究新结果，
不复制历史树。

## 恢复与 Hash

checkpoint schema 必须保存 `resume_cursor`、`completed_partition_ids`、
`completed_partition_hashes`、`producer_state_hash`、`deterministic_merge_order` 和
`remaining_units`。新 attempt 只能采用同 Authority、同代码、同输入、Hash 有效的最近
retryable checkpoint。

每个完成 Task 必须写 `task-files.json`。下游只验证清单自 Hash 和 output tree root；
最终 Verify 对本次新输出完整 Hash，对 adopted source 验证其正式封条和 adoption binding。

## 失败

- 输入证据不闭合：`BLOCKED_INPUT_EVIDENCE_INCOMPATIBLE`
- adoption 不兼容：`BLOCKED_SEALED_ADOPTION_INCOMPATIBLE`
- checkpoint 漂移：`BLOCKED_CHECKPOINT_STATE_DRIFT`
- 恢复结果不等价：`BLOCKED_ENGINE_SEMANTIC_DRIFT`
- 性能门失败：`BLOCKED_PERFORMANCE_GATE`

以上均不允许自动全量重跑、创建 Authority 或进入 Stage 3。
