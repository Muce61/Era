# Stage 2 lightweight operations

This document preserves the historical operator contract for Stage 2 Plan v1.3.
`configs/governance/stage2_active_policy_v2.json` is the immutable Plan v1.3 policy; v3 through v6
are the separately approved Plan v1.4 through v1.7 policies. The current repository-wide operation
authority is `configs/governance/current_development_state.json`, which points to Policy v9 /
Plan v1.10. It permits read-only work and `prepare` after the implementation is frozen. Authority,
formal Run, resume and publication remain blocked until a clean commit, a real inputs/adoption lock
and separate exact-Hash human approval. Runtime history comes from
append-only Authorities, events, checkpoints, the final Manifest and final Verify. Historical
governance files remain readable evidence but cannot authorize a new run.

Plan v1.10 uses `scripts/run_stage2_v110.py` with four commands:
`status / prepare / run / resume`. `prepare` creates the single full-period inputs lock and prints
the exact commit, Policy, preregistration, contract-bundle, input-lock and adoption-bundle Hashes. After one human
approval, `run` fsyncs Authority before creating a Run and automatically executes the DAG, final
Manifest, candidate Verify and atomic publication. `resume` accepts only `TASK_INTERRUPTED`;
terminal failure and published Run cannot resume.

T12–T18 use `SEALED_ADOPTION` only when their published Verify, Authority, contracts and output
roots close against the current inputs lock. T11 is newly executed with deterministic resumable
batches; T19/T20 are newly executed. Adoption incompatibility stops before Authority and never
falls back to a silent full-history recomputation.

进度 UI 只从 inputs lock、Authority、events、checkpoint 和 final Verify 投影状态；对象缺失
时必须显示 `NOT_FROZEN` 或 `PENDING`，不能从代码存在性推断正式门已通过。

Legacy `S2-T15` is the immutable Plan v1.2 `STOPPED_FAILED_UNPUBLISHED` predecessor. Its Plan v1.3
capability successor is `S2P13-T16`; this mapping grants no result promotion or execution
authority. Operators must not resume the old failed unpublished chain or treat it as a direct T20
dependency.

The single operator entrypoint is `scripts/run_stage2.py` with `status`, `rehearse`,
`record-approval`, `run`, `resume` and `verify`. A formal approval is stored outside Git and binds
the exact clean commit and Policy Hash. It binds a final-code rehearsal receipt by default.
Only an explicit human request for one unattended non-research-hours background runtime may replace
that receipt with a commit-bound waiver inside the append-only approval. The waiver never bypasses
Authority ordering, input Hash checks, the unique lock, reconciliation, full Verify or the Stage 3
lock. Recording approval does not change the repository.

The default approval command requires `--rehearsal`. The only no-rehearsal form is explicit:

```bash
uv run python scripts/run_stage2.py record-approval \
  --approval-source "<human approval source>" \
  --waive-rehearsal-for-background-runtime \
  --waiver-reason "<why this unattended run may skip rehearsal>"
```

CR or ADR is required only for research semantics, frozen rules, data/source authority, risk
behavior, Stage boundaries or real-execution scope. Code fixes, UI fixes, adapter wiring,
performance work, receipt formatting and ordinary tests use normal commits and regression tests.

Every formal chain freezes a ChainAuthority before any Task Run ID. S2P13-T16 later freezes its
dynamic upstream Authority and TRAIN-only bins before its own Run ID. Within the Plan v1.3
namespace, S2P13-T17 through S2P13-T21 were not executed. Later Plans v1.4 through v1.7 separately
authorized and completed T17 through T20. Their final research decision is
`STAGE2_NO_GO_CURRENT_EVIDENCE`; T21 was not executed and Stage 3 remains locked.
