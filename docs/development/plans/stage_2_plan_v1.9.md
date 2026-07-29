# Stage 2 Plan v1.9：个人开发轻量正式运行架构

## Metadata

- plan_id: `stage_2_plan_v1.9`
- stage_id: `S2`
- plan_version: `1.9`
- status: `APPROVED / IMPLEMENTED / PREPARE AND FORMAL RUN NOT EXECUTED`
- approved_by: `Muce`
- approved_at: `2026-07-29`
- migration_adr: `ADR-S2-028`
- implementation_authority: `docs/spec/system_manual_v1.3.5_final.md`
- preregistration: `configs/research/stage_2/s2p19_t11_t20_solo_runtime_v1.json`

## 目标

在不改变研究语义的前提下，把 Plan v1.8 未执行正式链的重复治理包装压缩成个人可维护的
正式运行架构。Plan v1.8 保留为历史合同并标记 `SUPERSEDED_UNEXECUTED`；Plan v1.7 及
更早正式证据保持不可变。

## 操作链

```text
status
prepare → inputs-<hash>.lock.json
        → 人工批准 exact commit + inputs_lock_hash
run     → run-authority.json (先 fsync)
        → Run ID
        → events.jsonl + Task output/checkpoint
        → final-manifest.json
        → candidates/<run_id>
        → final-verify.json
        → published/<run_id> 或 failed/<run_id>
resume  → 仅恢复 TASK_INTERRUPTED，创建新 attempt
```

## Task DAG

任务身份为 `S2P19-T11`～`S2P19-T20`。依赖关系与 v1.8 相同：

```text
T11 → T12 → T13 ┐
  └────→ T16 ───┼→ T17 → T18 ┐
T12 → T14 → T15 ┘              ├→ T19 → T20
T11 ────────────────────────────┘
```

## 硬门

1. `prepare` 必须在干净 commit 上审计 `[2020-01-01, 2026-07-04)` 的 BTC/ETH 来源及逐日
   分区，任何缺失、symlink、Hash 漂移、范围不足或品种混合均失败关闭。
2. 人工批准必须精确绑定 commit、Policy Hash、预注册 Hash、contract bundle Hash 和
   inputs-lock Hash。
3. Authority 必须先写入并 fsync；一个 Authority 最多一个 Run。
4. 任务严格按 DAG；下游启动前重验上游完成事件与输出树 Hash。
5. retryable interruption 只创建新 attempt；FAILED、已完成或已发布 Run 不可 resume。
6. 最终 Verify 必须重验输入、Authority、事件链、十 Task、附录 J Manifest、全部输出、
   计数和 Stage 3 锁。

Policy v8 只声明这些操作在满足上述门后具有能力；当前 machine state 在真实 inputs lock
和精确人工批准出现前仍阻止 Authority、Run、resume 和 publication。

## 研究边界

BTC/T2/20bp/25bp、matching、AMBIGUOUS、cluster、seed、H2/生命周期分流全部不变。本
Plan 不执行 Stage 3，不研究移动止损，不把 Contract Price 当成交，不让生命周期结果
自动覆盖历史 H2 Primary FAIL。

## 当前执行状态

本迁移提交只实现代码、合同和 fixture 验证。不得在同一提交内执行真实 `prepare`、
创建真实 Authority 或正式 Run。必须先冻结干净实现 commit，再执行 `prepare`，然后等待
用户针对精确 commit 与 inputs-lock Hash 的新批准。
