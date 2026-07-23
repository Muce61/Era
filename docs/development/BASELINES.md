# Baseline Registry

Record a baseline only after the required validation and human approval. Never overwrite an approved record; invalidate or supersede it explicitly.

| Baseline Type | Stage | Version | Commit | Tag | Status | Validation | Validated At | Invalidated By |
| ------------- | ----- | ------- | ------ | --- | ------ | ---------- | ------------ | -------------- |
| specification baseline | N/A | V1.3.4-final | `spec-v1.3.4-final^{commit}` | `spec-v1.3.4-final` | ESTABLISHED | `docs/development/validations/spec_import_validation.md` | 2026-07-12 | |
| planning baseline | N/A | planning-v0.1 | `planning-v0.1^{commit}` | `planning-v0.1` | DRAFT | `docs/development/validations/stage_and_task_planning_validation.md` | 2026-07-12 | |
| stage baseline | Stage 0 | 1.0 | `692dd29` | `stage-0-v1.0-passed` | PASSED | `docs/development/validations/stage_0_validation.md` | 2026-07-12 | |
| stage baseline | Stage 1 | 1.0 | `b106000` | `stage-1-v1.0-passed` | PASSED / VALID | `docs/development/validations/stage_1_validation.md` | 2026-07-16 | |
| data baseline | | | | | RESERVED | | | |
| experiment baseline | | | | | RESERVED | | | |
| execution capability baseline | | | | | RESERVED | | | |

## Stage 1 Data Baseline Detail

- Stage: Stage 1
- Baseline version: 1.0
- Approved execution Plan: `stage_1_plan_v1.1` (supersedes v1.0; includes CR-2026-001 Trade Identity v2)
- Validation commit: `b106000`
- Validation file: `docs/development/validations/stage_1_validation.md`
- Tag: `stage-1-v1.0-passed` (points to the final governance closure commit)
- Status / validity: PASSED / VALID
- Approved by: USER
- Approval reason: Stage 1 final approval after complete data build and scheduler regression closure
- Data run ID: `stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682`
- Manifest SHA-256: `436ffbe36e310dd015a962a29593360729d06db25ff96eddf12644c62d76e94f`
- Official archives: 162 planned / 162 processed / 0 nonterminal / 0 UNKNOWN / 0 recovery pending / 0 errors
- Quality Report: PASS
- Determinism: 6/6
- Published partitions: 4,752 total

| Instrument | Interval (UTC, end date inclusive) | Partitions | Rows | Logical Data Hash | Publication |
| --- | --- | ---: | ---: | --- | --- |
| BTCUSDT | 2020-01-01 through 2026-07-03 | 2,376 | 7,831,606,031 | `03d437ed9a6c19d92162e5c9dd115df4988e8accce3c8180b749f15cfdcc36a8` | PUBLISHED |
| ETHUSDT | 2020-01-01 through 2026-07-03 | 2,376 | 8,395,334,648 | `6db4d5e411edae3838b352944b83c38ba68915841a1f9c9de8f16ef44c3b8332` | PUBLISHED |

The pre-publication Catalog snapshots retain `READY_TO_PUBLISH`; final publication status is evidenced by the immutable Manifest, COMPLETE checkpoint and existing published directories. This known status-layer distinction does not alter rows, partition metadata or logical hashes.
