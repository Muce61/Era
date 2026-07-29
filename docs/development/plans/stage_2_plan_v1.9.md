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

### 十二类 production binding 的唯一推导

`prepare` 不接受操作者提供的 input-spec 或手填 Hash。唯一生产规则由
`s2p19_production_input_bindings_v1.json` 固定，并由代码重新计算：

| role | 唯一 Hash 来源 |
|---|---|
| BTC / ETH Stage 1 Logical Hash | 对应已发布 instrument Catalog 的 `logical_data_hash` |
| canonical Trades Catalog | Stage 1 Manifest 排除自 Hash 字段后的规范 Hash |
| canonical Trades Verify | PASS Quality Report 的完整规范 Hash |
| Contract Price Catalog | `prepare` 实际枚举的完整周期逐日分区清单规范 Hash |
| funding acceptance | CR-2026-038 acceptance 排除自 Hash 字段后的规范 Hash |
| T10 Manifest | 密封 T10 Manifest 排除自 Hash 字段后的规范 Hash |
| Primary config | Group 1 预注册配置声明的 `config_hash` |
| matching contract | 最终 T16 matching Authority 的自 Hash |
| cluster contract | 最终 T18 cluster Authority 的自 Hash |
| fixed seed | matching/placebo/bootstrap/event-card 四个 consumer seed 的联合规范 Hash |
| historical T20 Verify | Plan v1.7 最终 PASS Verify 的自 Hash |

所有自 Hash 都必须重新计算；所有源文件还要单独记录 SHA-256。输入锁记录每项
`binding_rule` 和 production rules Hash。创建 Authority 前必须根据输入锁内的分区和当前
冻结合同重新推导十二项；仅满足“64位字符串格式”不构成有效绑定。

`BTCUSDT/2022-03-01` 必须通过 CR-2026-043 / ADR-S2-020 的唯一 exact-key supplement
读取。`prepare` 必须重新验证官方 ZIP checksum、supplement Acceptance/Manifest/Catalog、
原 sealed receipt 的 byte/logical/count 相等性，并把 Acceptance 路径、文件 SHA、
Acceptance Hash 和 exact key 写入自哈希 source audit；不得增加第十三类 role、覆盖损坏
的 Stage 1 文件或把 overlay 放宽到其他日期。`run/resume` 只能从已批准 inputs lock
恢复同一绑定。

Policy v8 只声明这些操作在满足上述门后具有能力；当前 machine state 在真实 inputs lock
和精确人工批准出现前仍阻止 Authority、Run、resume 和 publication。

## 研究边界

BTC/T2/20bp/25bp、matching、AMBIGUOUS、cluster、seed、H2/生命周期分流全部不变。本
Plan 不执行 Stage 3，不研究移动止损，不把 Contract Price 当成交，不让生命周期结果
自动覆盖历史 H2 Primary FAIL。

## 当前执行状态

solo runtime 迁移提交只实现了代码、合同和 fixture 验证；后续最小修复补齐 production
input-spec builder 和十二类唯一推导规则。真实 `prepare` 仍必须在该修复的干净 commit
上执行。生成 inputs lock 后必须停止，等待用户针对精确 commit 与 inputs-lock Hash 的
新批准；此时仍不得创建 Authority 或正式 Run。
