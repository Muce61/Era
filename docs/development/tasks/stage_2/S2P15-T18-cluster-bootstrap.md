# S2P15-T18 v1.0 — Cluster Bootstrap

## Metadata

- task_id: S2P15-T18
- task_version: 1.0
- stage_plan_version: 1.5
- status: APPROVED / IMPLEMENTATION AUTHORIZED / FORMAL RUN GATED
- approved_by: Muce
- approved_at: 2026-07-27
- dependencies: verified formal S2P13-T16 and S2P14-T17
- evidence_level: H2 historical statistical evidence

## Objective

Calculate deterministic cluster-bootstrap confidence intervals, null-centered raw p-values and
Benjamini-Hochberg FDR for the verified real-event, placebo and paired real-minus-placebo evidence.

## Frozen contract

- Cluster identity is instrument plus the UTC Monday `week_start_ns` of the source real Episode.
- Resampling uses 5,000 equal-probability cluster draws with replacement, rooted at seed
  `20260716`.
- Metrics are `REAL_EVENT_DELTA`, `PLACEBO_DELTA` and `PAIRED_REAL_MINUS_PLACEBO`.
- Outputs cover all 19 registered parameter/timing pairs and all 30 target/stop combinations at
  FOLD, PERIOD and OVERALL levels while keeping BTC and ETH separate.
- The 413,827 T16 matched events, 412,021 T17 matched placebos and 1,806 unmatched placebos must
  reconcile exactly.
- Primary `G1-PRIMARY-V1 / T2 / target=20|stop=25` receives a raw p-value but is excluded from BH.
- Exploratory families use BH `q <= 0.10`.
- The Task publishes statistical evidence only and cannot issue Stage 2 Primary PASS.

## Allowed paths

- `src/era100x/research/stage_2/statistics/bootstrap/**`
- `tests/research/stage_2/statistics/bootstrap/**`
- `scripts/run_stage2_cluster_bootstrap.py`
- the approved Plan/Task/CR/ADR/policy/preregistration/validation and Traceability records
- the read-only Stage 2 progress API/UI and its tests
- a new append-only external `stage2-plan-v1.5` evidence root

## Forbidden paths and actions

- `docs/spec/**`, Stage 1 implementation/data, T16/T17 evidence and trading/execution code
- T19–T21 and Stage 3 implementation or execution
- rereading Trades or recomputing T16/T17 outcomes
- PnL, real-return, ROUND_SUCCESS, live-probability or final Primary claims
- Authority or Run creation before a clean final commit receives commit-bound approval

## Required validation

- `uv run python -m pytest tests/research/stage_2/statistics/bootstrap -q`
- `uv run python scripts/run_quality_gate.py`
- strict source/hash audit, real format smoke, performance-equivalence test and browser UI check

Implementation completion must stop at the formal-run approval gate.
