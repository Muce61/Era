# Stage 1 Integration Validation

## Conclusion

**PASS**

- Validated at: 2026-07-16
- Plan: `stage_1_plan_v1.1`
- Tasks: S1-T01～S1-T15 PASSED
- Stage status after validation: `READY_FOR_FINAL_APPROVAL`
- Final Stage baseline/tag: NOT CREATED

## Scope and rules

This acceptance covers V1.3.4 §29 and Appendix L Stage 1 gates, `DATA-HISTORICAL-NO-FAKE-EXECUTION`, `STRATEGY-V1-PRICE-ONLY-HISTORICAL`, `INV-013`, the Stage 1 data contracts, and CR-2026-001 / ADR-2026-001 Trade Identity v2. BTCUSDT and ETHUSDT remain separate datasets.

No Stage 2 code, event research, H1/H2/H3/F1, account API, testnet, live execution, or compounding work was performed.

## Task and capability acceptance

- S1-T01～S1-T13: PASSED with existing Task Validations.
- S1-T14 v1.5: PASSED; final evidence is [`stage_1/S1-T14-v1.5.md`](stage_1/S1-T14-v1.5.md).
- S1-T15: PASSED; all integration gates below have actual evidence.
- Historical execution-only fields remain NULL/unavailable; the Manifest lists nine unavailable capabilities and no zero or inferred value substitutes them.
- Purge/embargo, deterministic aggregation, immutable raw/published handling, Catalog/Manifest generation, recovery and idempotency retain passing regression coverage.

## Full published dataset

- Run ID: `stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682`
- Dataset version: `stage1-trades-v2`
- Target/actual interval: `[2020-01-01T00:00:00Z, 2026-07-04T00:00:00Z)`
- Official archives: 162 planned, 162 prefetched, 162 processed, 0 nonterminal, 0 UNKNOWN, 0 recovery pending, 0 errors.
- Quality Report: PASS.
- Determinism: six preregistered partition rebuilds passed; post-run physical checksum samples passed 6/6.
- Manifest SHA-256: `436ffbe36e310dd015a962a29593360729d06db25ff96eddf12644c62d76e94f`.

| Symbol | Status | Partitions | Published rows | Exact duplicates audited | Venue-ID conflicts | Logical dataset hash |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| BTCUSDT | PUBLISHED | 2,376 | 7,831,606,031 | 2,707,003 | 0 | `03d437ed9a6c19d92162e5c9dd115df4988e8accce3c8180b749f15cfdcc36a8` |
| ETHUSDT | PUBLISHED | 2,376 | 8,395,334,648 | 1,814,996 | 3 | `6db4d5e411edae3838b352944b83c38ba68915841a1f9c9de8f16ef44c3b8332` |

The three ETH venue-ID conflict groups were retained as separate canonical facts after official monthly/daily canonical-set confirmation. No source disagreement remains.

## Scheduler correction and recovery evidence

The premature-completion defect was reproduced before repair. Its cause was an active-future loop condition that could terminate between scheduling rounds while an asymmetric symbol tail remained. The repair introduces explicit scheduler states and exact planned-set completion. Regression covers both symbol directions, temporary idle, out-of-order completions, interruption/resume, failed-item recovery, idempotent completed-run scans, no duplicate publication, and exact global completion.

The published run was completed by the audited recovery driver before this repair. Post-repair acceptance performed only read-only reconciliation; it did not regenerate or overwrite published data. The Manifest records data-producing commit `9676d50ae686`; scheduler repair commit `fcbf188` changes orchestration only. User instructions explicitly required preserving the existing publication. Schema, canonical identity, sort order, rows, partition keys, Catalog and logical hashes are unchanged.

## Actual validation commands

- `PATH="$PWD/.venv/bin:$PATH" python -m pytest -q tests/data/full_build/test_full_build.py` — PASS, 20 passed.
- `PATH="$PWD/.venv/bin:$PATH" python -m pytest -q tests/data` — PASS, 59 passed.
- `PATH="$PWD/.venv/bin:$PATH" python scripts/run_quality_gate.py` — PASS: Ruff format, Ruff lint, mypy strict, strict Traceability and 119 full pytest tests.
- `PATH="$PWD/.venv/bin:$PATH" python scripts/check_contract_coverage.py` — PASS, Appendix C-E 15/15.
- `PATH="$PWD/.venv/bin:$PATH" python scripts/check_traceability.py --strict` — PASS: 32 rules, 41 INV, 18 contracts, 52 Reason Codes and 10 gates.
- Read-only checkpoint/Manifest/Catalog/partition reconciliation — PASS; 4,752 partition metadata and byte sizes agree, six physical SHA-256 samples agree, watched evidence mtimes unchanged.
- Historical unavailable-field and dataset-version assertion — PASS.
- Stage 2 source-path scan — PASS, no Stage 2 implementation exists.
- Build/recovery process scan — PASS, no process running.
- `git diff --check` — PASS.

An initial quality-gate attempt used the wrong system PATH and failed mypy due to missing locked-environment typing dependencies. It is retained as a failed attempt, not a pass. The approved `.venv` gate subsequently passed without weakening dependencies or checks.

## Open matters and decision

- No Stage 1 BLOCKER or blocking Change Request remains.
- Quality count-outlier review annotations remain visible in the immutable report and did not trigger a hard data error.
- U-001～U-013 and Stage 2 OQ-S2-001/OQ-S2-002 belong to later research/execution gates and do not invalidate Stage 1.
- BASELINES.md still has no Stage 1/data baseline. Final Stage PASSED status, baseline commit and tag require explicit user approval.

**Go recommendation:** approve and freeze the Stage 1 baseline. Do not enter Stage 2 until that separate final approval and Stage 2 approval gates are complete.
