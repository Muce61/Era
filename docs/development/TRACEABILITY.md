# Specification Traceability

> Stage 2 Plan v1.3 operations use
> `configs/governance/stage2_active_policy_v2.json` plus append-only runtime receipts as the
> machine gate. Historical prose records below remain traceability evidence and are not runtime
> authorization inputs. See `docs/development/STAGE2_OPERATIONS.md`.

Model: formal rule → Stage → Task → implementation → tests → validation → current validity. The machine-readable complete catalogue is [`traceability/rules.yaml`](traceability/rules.yaml); every implementation/test path is explicitly PLANNED, not implemented.

## Stage 2 Plan v1.3 lifecycle successor status

CR-2026-035 and ADR-S2-014/015 establish V1.3.5 and Plan v1.3 without mutating Plan v1.2 evidence.
The final executed identity is `stage_2_plan_v1.3/S2P13-T16`; Plan v1.3 closed at that approved
execution ceiling on 2026-07-27. The repository implements the SRP fail-closed framework, task namespace,
price-only lifecycle core, typed availability audit, recoverable orchestrator contract and
evidence-driven UI projection with directed tests. The production adapter layer now requires an
approved, commit-bound six-task argv plan, complete versioned upstream handoffs, self-hashed
producer receipts, consumer read-back, reconciliation and Verify PASS before translating any task
result into the successor checkpoint. CR-2026-041 froze the successor source-binding scope and
corrects the DAG so T13 and T14 both consume T12 while T12 binds T11 only as a PASS gate. The
adapter distinguishes retryable process interruption from terminal producer failure and never
invokes commands through a shell.

CR-2026-042/ADR-S2-019 resolve OQ-S2-012 with a minimum price-only producer: protection/structure
are explicitly not modeled, Contract Price owns scenario valuation and funding notional, canonical
Trades own target/stop, and immediate/continue use independent single-position timelines.
The shared extraction/metric/First-Passage cores now accept explicit successor roots and scope;
the Plan v1.3 producer CLI seals full upstream handoffs, preregistration, scope, Manifest, Catalog,
output and receipt hashes. A real pre-commit seven-day component chain passed T12 through T15 and
the lifecycle component correctly fail-closed all 42 Primary Episodes as declared-gap censored.
The first clean-commit attempt at `0c27e41` failed closed on external-volume AppleDouble
`._*.parquet` sidecars during T12 inventory. The unpublished failed root is retained; the scoped
inventory ignores only those metadata sidecars and has a dedicated regression test.

The final formal successor
`fa92072063be8455fab814c1e9f302f2b06392a999820a53bd430e7282f57579` completed T11–T16 at
`555c2a543a9cb3fdf1cb8c79c644792933de2260`. The replacement uses
`H2_WINDOW_INTERNAL_GAP_BEFORE_DECISION_V1` on both sides, reports both gap distributions and
passed Catalog, Manifest, reconciliation and independent Verify. T16 Verify Hash is
`b866905c18fd1cb1f3bbed1f74e5301c56a78e891b81ab3eea61bcff37ed2b86`; its engineering result is
PASS and its research result remains `DESCRIPTIVE_ONLY_PRIMARY_PENDING_T18`. The append-only
predecessor remains engineering PASS but research-rejected under CR-2026-045/ADR-S2-021.
The performance and Reason Code projection change at
`007b3147abc013ea0a41f214cbff52650b2b20a2` later passed the complete repository quality gate and
was accepted without another data Run. It is code evidence only and is not attributed to the
immutable formal successor. Plan v1.3 is closed at T16; S2P13-T17～T21 remain unexecuted. The
closure decision is recorded in
[`stage_2_plan_v1.3_closure.md`](validations/stage_2/stage_2_plan_v1.3_closure.md).
CR-2026-038 resolves
OQ-S2-010 by binding the accepted BTC/ETH historical funding source. CR-2026-039 resolves
OQ-S2-011 after the SRP framework passed repository-wide quality and traceability; the framework
and all historical SRP/CR/ADR records remain. CR-2026-040 resolves OQ-S2-009 and moves the already
defined seven-day requirement to the independent `FINAL_CODE_7_DAY_REHEARSAL` execution gate.
CR-2026-044 keeps that gate as the default and permits only a commit-bound, explicitly approved
unattended-background waiver. A clean commit and commit-bound human run receipt remain mandatory
before a unique successor chain. The completed formal Run validated and reconciled the complete
range and failed closed on unknown missingness or drift. Stage 3 remains locked.

## Stage 0 v1.0 Foundation Coverage

Stage 0 uses S0-T04 to catalogue all 32 formal rules and S0-T10 to enforce uniqueness/status/test ownership. S0-T07 owns the PnL foundation; S0-T08 owns Appendix C-E schema completeness; S0-T09 owns states and Reason Codes. Execution behavior remains assigned to later Stages and is not marked implemented by Stage 0. INV-001～INV-041 all include S0-T10 for registry/test-reference validation while retaining their behavioral Stage owner.

Stage 0 v1.0 is a valid PASSED baseline at validated implementation commit `692dd29`, with acceptance evidence in [`validations/stage_0_validation.md`](validations/stage_0_validation.md). The Stage 0 delivery rows below are effective. Entries assigned to Stage 1～9 remain PLANNED and are not promoted by this baseline. U-001～U-003 remain OPEN for their downstream scopes and do not invalidate the offline Stage 0 foundation baseline.

## Formal Rule Registry Coverage

| Rule ID | Rule Status | Source | Stage | Task | Implementation | Tests | State |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EXEC-NATIVE-STOP-IMMUTABLE | FROZEN | Appendix A; Binance B01-B05 + ADR-V13-001 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| EXEC-EXIT-COORDINATOR-ONLY | FROZEN | Appendix A; 审计A002/A030 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| EXEC-UNKNOWN-NO-BLIND-RETRY | FROZEN | Appendix A; Binance B06 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| RISK-PROTECTION-SUFFICIENT | FROZEN | Appendix A; Binance B05 + ADR-V13-002 | S7 | S7-T01 | PLANNED | PLANNED | PLANNED |
| RISK-LIQUIDATION-BUFFER | FROZEN | Appendix A; Binance B09 + 审计A010 | S7 | S7-T01 | PLANNED | PLANNED | PLANNED |
| ACCOUNT-DEDICATED-SUBACCOUNT | FROZEN | Appendix A; 审计A027/A028 | S7 | S7-T01 | PLANNED | PLANNED | PLANNED |
| ROUND-ONE-NONZERO-FILL | FROZEN | Appendix A; 审计A006 | S8 | S8-T01 | PLANNED | PLANNED | PLANNED |
| ROUND-SUCCESS-FLAT-EQUITY | FROZEN | Appendix A; 审计A020 | S9 | S9-T01 | PLANNED | PLANNED | PLANNED |
| EVENT-CONSUME-MARKET-EPISODE | FROZEN | Appendix A; 审计A014 | S2 | S2-T01 | PLANNED | PLANNED | PLANNED |
| FILL-FIRST-NONZERO-PROTECT | FROZEN | Appendix A; 审计A015 | S7 | S7-T01 | PLANNED | PLANNED | PLANNED |
| FILL-CONTINUE-BY-REACHABILITY | FROZEN | Appendix A; 审计A007 | S3 | S3-T01 | PLANNED | PLANNED | PLANNED |
| PNL-NO-DOUBLE-SLIPPAGE | FROZEN | Appendix A; 审计A004 | S3 | S3-T01 | PLANNED | PLANNED | PLANNED |
| DATA-HISTORICAL-NO-FAKE-EXECUTION | FROZEN | Appendix A; 数据能力边界 | S5 | S5-T01 | PLANNED | PLANNED | PLANNED |
| RESEARCH-LOCKED-REPLAY-ONCE | FROZEN | Appendix A; 审计A008 | S4 | S4-T01 | PLANNED | PLANNED | PLANNED |
| STATE-BREAKER-PERSIST | FROZEN | Appendix A; 审计A005/A046 | S8 | S8-T01 | PLANNED | PLANNED | PLANNED |
| STRATEGY-V1-PRICE-ONLY-HISTORICAL | FROZEN | Appendix A; 数据能力边界 | S2 | S2-T01 | PLANNED | PLANNED | PLANNED |
| RESEARCH-H3-CONDITIONAL-ROUND-PROB | FROZEN | Appendix A; V1.3.1验收修复F1 | S9 | S9-T01 | PLANNED | PLANNED | PLANNED |
| STATE-POSITION-INSTANCE-REVISION | FROZEN | Appendix A; V1.3.1验收修复F2 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| STATE-FLAT-CONFIRMATION-PROTOCOL | FROZEN | Appendix A; V1.3.1验收修复F3 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| EXEC-EXIT-RACE-OWNERSHIP | FROZEN | Appendix A; V1.3.1验收修复F4 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| RISK-RESIZING-FULL-REVALIDATION | FROZEN | Appendix A; V1.3.1验收修复F5 | S7 | S7-T01 | PLANNED | PLANNED | PLANNED |
| CLOSE-THREE-STAGE | FROZEN | Appendix A; V1.3.2补丁P1 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| EXIT-EPOCH-ATOMIC-CREATE | FROZEN | Appendix A; V1.3.2补丁P2 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| EXIT-LEG-SINGLE-ACTIVE-LOCAL | FROZEN | Appendix A; V1.3.2补丁P3 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| CLOSE-FINAL-FLAT-BEFORE-ROUND | FROZEN | Appendix A; V1.3.3冻结F1/F2 | S8 | S8-T01 | PLANNED | PLANNED | PLANNED |
| EXIT-EPOCH-BOOTSTRAP-ATOMIC | FROZEN | Appendix A; V1.3.3冻结F3 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| EXIT-LEG-CREATION-ATOMIC | FROZEN | Appendix A; V1.3.3冻结F4 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| EXIT-LEG-DB-UNIQUE-GUARD | FROZEN | Appendix A; V1.3.3冻结F4 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| EXIT-BOOTSTRAP-MODE | FROZEN | Appendix A; V1.3.4定稿F1 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| EXIT-TRANSACTION-FIELD-COMPLETE | FROZEN | Appendix A; V1.3.4定稿F2 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| INVARIANT-ID-GLOBAL-UNIQUE | FROZEN | Appendix A; V1.3.4定稿F3 | S0 | S0-T04, S0-T10 | PLANNED | PLANNED | PLANNED |
| CLOSURE-STAGE-SINGLE-RESPONSIBILITY | FROZEN | Appendix A; V1.3.4定稿F4 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |

Additional machine entries cover INV-001～INV-041, Appendix C/D/E/J contracts, Appendix I Reason Codes and all ten Appendix L Stage gates. DEPRECATED behavior is represented only by prevention/regression coverage and must not be implemented. BASELINE, RESEARCH and BLOCKED_BY_FORWARD_VALIDATION statuses remain unchanged.

## Stage 0 Task Delivery Status

| Task | Capability | Specification | Implementation | Tests | Validation | State |
| --- | --- | --- | --- | --- | --- | --- |
| S0-T01 | Python 3.12 project skeleton and import boundary | §23, §24, §28 | `pyproject.toml`, `src/era100x/__init__.py`, README development entry | `tests/test_package_import.py` | `validations/stage_0/S0-T01.md` | PASSED |
| S0-T02 | Locked Python toolchain and deterministic quality gate | §23, §27, §28 | `pyproject.toml`, `uv.lock`, `scripts/run_quality_gate.py` | collection, Ruff, mypy, pytest | `validations/stage_0/S0-T02.md` | PASSED |
| S0-T05 | Decimal, timestamp-source and stable-ID primitives | §6, §19.1, §25, Appendix C-E | `src/era100x/foundation/types/` | `tests/foundation/types/` | `validations/stage_0/S0-T05.md` | PASSED |
| S0-T03 | Effective configuration resolution and deterministic snapshot | §5, Appendix B | `src/era100x/foundation/config/`, `configs/` | `tests/foundation/config/` | `validations/stage_0/S0-T03.md` | PASSED |
| S0-T04 | 32-rule metadata registry and status guard | Appendix A | `src/era100x/foundation/rules/`, `configs/rules/` | `tests/foundation/rules/` | `validations/stage_0/S0-T04.md` | PASSED |
| S0-T09 | Frozen state, closure-phase, decision and Reason Code vocabularies | §20-22, §41, Appendix G/I | `src/era100x/foundation/state/` | `tests/foundation/state/` | `validations/stage_0/S0-T09.md` | PASSED |
| S0-T06 | Deterministic manifests and append-only audit records | §16, §26, §45, Appendix J | `src/era100x/foundation/audit/` | `tests/foundation/audit/` | `validations/stage_0/S0-T06.md` | PASSED |
| S0-T07 | Decimal-only Appendix F PnL contracts | §6, §10.4, §14.1, Appendix F | `src/era100x/foundation/accounting/` | `tests/foundation/accounting/` | `validations/stage_0/S0-T07.md` | PASSED |
| S0-T08 | Appendix C-E strict schema skeletons | §18-20, §25-26, Appendix C-E | `src/era100x/contracts/` | `tests/contracts/`, `tests/test_package_import.py` | `validations/stage_0/S0-T08.md` | PASSED |
| S0-T10 | Strict traceability integrity checker | §27, Appendix A/C-E/G-H/I/K/L | `scripts/check_traceability.py` | `tests/governance/` | `validations/stage_0/S0-T10.md` | PASSED |
| S0-T11 | Read-only locked CI quality gate | §23, §27, §28 | `.github/workflows/quality.yml`, `scripts/run_quality_gate.py` | local gate and static workflow audit | `validations/stage_0/S0-T11.md` | PASSED |
| S0-T12 | Offline execution capability port and hard network denial | §17-18, §22-28, Appendix E/K/N | `src/era100x/spike/ports/`, `configs/spike/example.yaml` | `tests/spike/offline/` | `validations/stage_0/S0-T12.md` | PASSED |
| S0-T13 | Stage 0 evidence integration and final-approval gate | §27-28, §38, §46, Appendix A/L/N | governance validations only | full quality, scope and prerequisite audits | `validations/stage_0/S0-T13.md`, `validations/stage_0_validation.md` | PASSED |

S0-T01 carries no business `rule_id` and does not mark any FROZEN rule or INV as implemented. It provides only the package boundary required by later individually approved Stage 0 Tasks.

Stage 0 baseline validity: **VALID / PASSED**. Any later change to its code, configuration contracts, dependency lock, traceability catalogue, or validation evidence requires explicit invalidation or reopening under `CHANGE_POLICY.md`.

## Stage 1 v1.1 Execution Coverage

Stage 1 is `PASSED / VALID` under baseline version 1.0, approved Plan v1.1 and CR-2026-001. S1-T01～S1-T15 are PASSED and [`validations/stage_1_validation.md`](validations/stage_1_validation.md) concludes PASS. `venue_trade_id` is a venue property, `canonical_trade_id` is the fact identity, and official conflicting venue IDs are retained only after monthly/daily canonical-set confirmation. S1-T14 v1.5 uses the immutable 162/162 published run and read-only post-run verification; its scheduler-only repair changes no dataset semantics or recorded logical hash. The prior 134/162 run remains INVALIDATED and unpublished. The valid baseline tag is `stage-1-v1.0-passed`.

| Requirement | Planned Tasks | Planned Evidence | State |
| --- | --- | --- | --- |
| Existing local asset/path audit | S1-T01 | read-only asset report, path/permission/capacity record | PLANNED |
| S1-T01 delivered evidence | S1-T01 | `scripts/audit_stage1_assets.py`, `reviews/stage_1_asset_audit.md`, `tests/data/audit/` | PASSED |
| Schema Registry and sample fixtures | S1-T02 | schema/nullable/unit tests and committed minimal fixtures | PLANNED |
| S1-T02 v1.1 delivered evidence | S1-T02 | `src/era100x/data/schema/`, `tests/data/schema/`, `tests/fixtures/stage_1/`, ADR-2026-001 | PASSED_V2 |
| 1s Contract Price H1 input | S1-T03, S1-T07, S1-T09 | reader, integrity/gap and deterministic aggregation tests | PLANNED |
| S1-T03 delivered evidence | S1-T03 | `src/era100x/data/readers/`, `tests/data/readers/` | PASSED |
| S1-T09 delivered evidence | S1-T09 | `src/era100x/data/aggregate/`, `tests/data/aggregate/` | PASSED |
| Binance Trades raw lineage | S1-T04 | immutable raw manifest, source/coverage/hash and idempotency tests | PLANNED |
| S1-T04 delivered evidence | S1-T04 | `src/era100x/data/ingest/`, `scripts/import_stage1_trades.py`, `tests/data/ingest/` | PASSED |
| Trade normalization and aggressor side | S1-T05, S1-T06 | Decimal/time/ID mapping and maker-side tests | PLANNED |
| S1-T05 v1.1 delivered evidence | S1-T05 | `src/era100x/data/normalize/`, `tests/data/normalize/` | PASSED_V2 |
| S1-T06 delivered evidence | S1-T06 | `src/era100x/data/trades/`, `tests/data/trades/` | PASSED |
| Duplicates, anomalies, rollback and gaps | S1-T07 | issue classification, deterministic dedup and gap segments | PLANNED |
| S1-T07 v1.1 delivered evidence | S1-T07 | canonical dedup + venue conflict retention in `src/era100x/data/quality/`, `tests/data/quality/` | PASSED_V2 |
| Parquet catalog and checksum | S1-T08 | partition/catalog/logical-hash/atomic-publish tests | PLANNED |
| S1-T08 v1.1 delivered evidence | S1-T08 | v2 Parquet/Catalog in `src/era100x/data/storage/`, `tests/data/storage/`, full-build schema | PASSED_V2 |
| Historical execution fields remain NULL | S1-T02, S1-T10 | UT-DATA-013 and illegal-zero/false-evidence regression | PLANNED |
| S1-T10 delivered evidence | S1-T10 | `src/era100x/data/evidence/`, `tests/data/evidence/` | PASSED |
| Purge and embargo/no leakage | S1-T11 | interval/property tests and manifest fields | PLANNED |
| S1-T11 delivered evidence | S1-T11 | `src/era100x/data/splits/`, `tests/data/splits/` | PASSED |
| Small-sample capability acceptance | S1-T12 | fixture quality report marked NOT_RUN_FULL_DATA | PLANNED |
| S1-T12 v1.1 delivered evidence | S1-T12 | v2 identity/conflict gates plus existing report/null/split regression | PASSED_V2 |
| Full-data preflight and build | S1-T13, S1-T14 | approved paths/source/coverage, resumable builder, full catalog, repeat-build hash | PASSED |
| S1-T14 v1.5 builder implementation and scheduler recovery | S1-T14 | `stage1-trades-v2`, official conflict cross-validation, explicit multi-symbol terminal-state scheduler, resumable `.part`, `src/era100x/data/full_build/`, `tests/data/full_build/` | PASSED_162_OF_162_READ_ONLY_REVERIFIED |
| S1-T13 actual preflight | S1-T13 | 162/162 official archives; write probe; 20% disk safety calculation | PASSED |
| Stage 1 gate | S1-T15 | `validations/stage_1_validation.md`; BTC/ETH separate PASS conclusions | PASSED_VALIDATED |

Stage 1 delivery state: **IMPLEMENTED / TESTED / VALIDATED / PASSED**. S1-T01～S1-T15 are PASSED. Historical data contracts resolve to `src/era100x/data/`, `tests/data/`, the immutable run Manifest/Catalogs and the Stage 1 Task/Stage Validations. Later-stage behavior remains PLANNED and is not promoted by this baseline.

`DATA-HISTORICAL-NO-FAKE-EXECUTION` is enforced at the Stage 1 historical boundary by S1-T02/T10/T12/T14 and remains planned for Stage 5 forward-field separation. `STRATEGY-V1-PRICE-ONLY-HISTORICAL` is enforced at the Stage 1 input/source boundary by S1-T03/T09/T10; event behavior remains Stage 2. This does not promote either later behavioral implementation to PASSED.

## Stage 2 Plan v1.2 APPROVED Coverage

Stage 2 is `IN_PROGRESS / S2_T15_STOPPED_SRP_S2_001_EXEMPTIONS_APPROVED_NOT_EXECUTABLE`. S2-T19 and S2-T01～S2-T14 are PASSED;
the fixed Runtime V2 Run is published with Quality/Verify PASS and the exact Run-A comparison
matches 61,776/61,776 Group-1 partitions with zero differences. S2-T11 v1.3 and CR-2026-021 are
human-approved. Full-output Run `stage2-s2t11-paths-20260721T023117Z-029707f3c111` published
220,201 BTC and 312,507 ETH episode path indexes; read-only verify, repository quality gates and
automatic UI projection pass. S2-T12 v1.3 is human-approved for historical price-only MFE/MAE/
timing evidence. Full Run `stage2-s2t12-metrics-20260721T040435Z-de9aaea56f2a` and read-only
Verify PASS over 220,201 BTC and 312,507 ETH Episodes, producing 1,065,416 separate H1/H2 metric
rows. CR-2026-022 is approved, implemented and validated; the read-only UI derives the fixed Run,
separate BTC/ETH H1/H2 counts and 16/16 checks from immutable evidence. Muce accepted S2-T12 at
2026-07-21T06:39:21Z and approved S2-T13 v1.2 at 2026-07-21T07:45:12Z.
[CR-2026-023](changes/CR-2026-023.md) was approved by Muce at 2026-07-21T10:41:50Z and freezes the
S2-T13 v1.3 full-output and automatic read-only UI scope. Authority `ab76072c…bbbe` and formal Run
`stage2-s2t13-first-passage-20260721T110224Z-d3f0c0331395` published 1,065,416 H1/H2 path rows and
31,962,480 classifications; full Verify and the automatic real-evidence UI projection pass. Muce
accepted and closed S2-T13 at 2026-07-21T12:52:58Z. Muce subsequently approved the S2-T14 v1.2
fixture capability at 2026-07-21T13:07:08Z. The v1.2 deterministic fixture and repository quality
gate pass. Muce approved CR-2026-024 and S2-T14 v1.3 at 2026-07-21T13:37:13Z for the minimum
full-distribution and read-only automatic UI scope. Authority `3a563bd2…f7a` and Run
`stage2-s2t14-ambiguity-bounds-20260721T140507Z-8b4cf765602d` passed full execution and read-only
Verify over 1,065,416 H1/H2 rows, 31,962,480 classifications and 2,280 compact distributions; the
automatic real-evidence UI also passed. Muce's explicit close instruction became effective after
evidence passed at 2026-07-21T14:15:01Z. Muce approved S2-T15 v1.2 method-fixture work at
2026-07-21T14:35:06Z. The exact L0-L5 conditional matcher, 16 directed tests and 553-test quality
gate pass within the fixture boundary. Muce approved CR-2026-025 and v1.3 at
2026-07-21T14:41:46Z, but the pre-Run audit found the executable volatility/Trades-activity
formulas, split/fold boundaries, exact purge/embargo duration and non-event control-anchor rule
absent from the repository and complete Git history. OQ-S2-005 blocked Authority/Run creation at
that time. Muce approved CR-2026-026, ADR-S2-009, S2-T15 v1.4 and the T19 append-only addendum at
2026-07-22T02:25:41Z, closing OQ-S2-005 with executable definitions. The v1.4 upstream audit then
found 14,256 fixed T10 Group-1 receipts missing required field-distribution digests. Muce approved
CR-2026-027; its final supplement verified 14,256/14,256 with no T10 mutation and audit binding
`b1140c4b…380d` passed. The first formal T15 Run
`stage2-s2t15-conditional-20260722T071250Z-871c404c5f43` stopped `FAILED_UNPUBLISHED` during
Episode preparation with 0/456 matching groups and no published result: T15 reconstructed Context
at final Episode availability rather than binding the sealed price-trigger Context. Exact read-only
reconciliation proves BTC 220,201/220,201 and ETH 312,507/312,507 conflict-free
`(trigger_id,event_parameter_set_id)` bindings, all `UP/PASS`. The correction and automatic FAILED
UI projection are implemented, but direct `price_triggers` reception exposes 4,752 additional
legacy distribution omissions. Muce approved CR-2026-028 and resolved OQ-S2-007 at
2026-07-22T08:53:43Z, authorizing the independent read-only supplement, invalidation of the first
unpublished chain and exactly one successor chain. Supplement/audit/quality/preflight gates remain;
the successor then passed the corrected Episode Context boundary and completed 456/456
outcome-blind groups, but stopped `FAILED_UNPUBLISHED` before the first control H2 outcome because
the post-selection strict Decimal receiver rejected the canonical JSON string representation of
`control_entry_price`. Muce approved CR-2026-029 and resolved OQ-S2-008 at
`2026-07-22T14:12:52Z`, authorizing only the strict Decimal receiver correction, invalidation of
that failed chain and exactly one final replacement chain; implementation gates remain.
Muce then required a seven-day real-input rehearsal before every long-running task and stopped the
CR-2026-029 TRAIN-bin freeze before any Binning Set or Run ID was created. The first isolated T15
rehearsal exposed an invalid two-groups-in-one-file simulation package; the complete fresh rerun
passed 20,160 feature rows, 42 boundary JSON round-trips, 10 real Decimal candidate receptions,
10 H2 matrices, 300 outcome cells and exact 2-group/60-summary reconciliation. CR-2026-030
records the stopped `e3d9814f…c365` Authority. Muce approved CR-2026-030 at
`2026-07-22T14:47:04Z`, authorizing exactly one replacement Authority/bin/Run chain only after the
final-clean-code seven-day rehearsal, full quality gate and fresh audit pass. The rehearsal is
simulation-only and does not change the formal research result.
The replacement Authority `5a1a3faa…e7b56` then began TRAIN feature preparation, but Muce stopped
it before a Binning Set or Run ID after the read-only view exposed 61 unavailable BTC/P1 boundary
anchors. At that time, CR-2026-031/ADR-S2-010 and OQ-S2-009 required a typed whole-range BTC/ETH
availability audit; the prepared files remain unpublished and non-reusable.
CR-2026-032/ADR-S2-011 and OQ-S2-010 separately proposed immutable exit-rule-free event paths plus
an H3 theoretical
full-lifecycle study with landmark risk-set comparison. Muce approved both governance pairs at
`2026-07-22T16:27:27Z`: the availability audit and two-layer direction are authorized, while both
OQs remain OPEN. No code, Authority, Run, S2-T16+ or Stage 3 is authorized.
The clean CR-2026-031/032 seven-day audit then passed 20,160 feature-anchor reconciliation,
strict receipt read-back and byte-identical T1-T4 raw-path consumption over 1,211 Episode paths.
Its report/receipt Hashes are `a47b6488…b344` / `fed27311…a905`. The lifecycle consumer remains
BLOCKED: T11 stops at 600 seconds and 19/52 H2 T4 rows remain Primary EXPIRED. The first audit
attempt also exposed and fixed an audit-only daily-offset checker bug; a fresh full rerun passed.
CR-2026-033 and ADR-S2-012 then proposed an S2-T19 v1.4 `SPECIAL_RESEARCH_POINT` extension: all
rules apply by default, only explicitly named research-rule exemptions may be considered, and
truth, safety and governance rules remain non-waivable. At that point OQ-S2-011 was OPEN and there
was no framework implementation, Authority, Run or formal result. Point-specific exemption
approval is recorded separately below.
Muce subsequently classified CR-2026-031/032 and ADR-S2-010/011 as `SRP-S2-001`. Its A-layer
availability and raw-path evidence has an empty exemption set. Muce approved its B-layer
EX-001/002/003 at `2026-07-23T01:04:16Z`: `RESEARCH-LOCKED-REPLAY-ONCE`, the T1-T4/600-second
source boundary and the U-011 universal time-exit baselines. All undeclared rules remain effective.
At that time OQ-S2-009/010 and framework/Task implementation still blocked execution.
CR-2026-031/ADR-S2-010 are
retained as an active safety contract; CR-2026-032/ADR-S2-011 are retained as source authority with
no standalone Authority/Run entry.
CR-2026-038 later resolved OQ-S2-010. CR-2026-039 resolved OQ-S2-011 after full repository quality
and changed OQ-S2-009's release gate from a duplicate whole-range pre-audit to the final-code
seven-day end-to-end rehearsal. Complete-range validation remains mandatory inside the formal
full-data Run.
S2-T16 through S2-T18 and S2-T20 remain `DRAFT_NOT_APPROVED`, and Stage 3 remains locked.
[CR-2026-007](changes/CR-2026-007.md) and [CR-2026-008](changes/CR-2026-008.md)
approve a bounded hybrid transition without changing Stage 1, preregistration, config, parameters,
candidate semantics or the Plan v1.2 DAG. Formal Run A is now PUBLISHED with Quality PASS,
9508/9508 completed work items, zero failed/UNKNOWN work items, 61,776 logical partitions,
published logical hash `8583f220dc880bf5b7e7ace1435ca2285e59b80dd48aa7d15bd2f8cacac60870` and published physical
hash `9fe33a4e7fde1ace3281a208c46f7474f66bc5c5a0e538871b273b2f20131578`.
[CR-2026-009](changes/CR-2026-009.md) is RESOLVED / IMPLEMENTED / VALIDATED. Its bounded
release/operator corrections remain authoritative for formal Run A. The first V2
authority freeze failed because the resolved-entry contract rejected the legitimate
Catalog-authorized exact-day archive tail `archive=2026-07-01`; the failed run remains immutable.
A write-once replacement Bundle resolved all 4,752 instrument-days, including six exact-day tails,
but its conditionally authorized preflight exposed a separate frozen-parser drift: V2 accepted only
release supplement v1.0/CR-2026-006 while formal Run A protection binds v1.1/CR-2026-009. The
preflight consumed no Run B ID. [CR-2026-010](changes/CR-2026-010.md) approves the bounded read
compatibility correction, exact match-count diagnostics, Authority refreeze and successor Run B
only after all gates pass. The replacement Bundle froze twice identically and preflight passed,
but the first `FOUNDATION:BTCUSDT` task failed unpublished when process RSS `1,704,640,512`
exceeded the frozen `943,718,400` byte limit. No task, staging artifact, publication, Group-1 work
or comparison completed. [CR-2026-011](changes/CR-2026-011.md) implements profiled row-group
streaming, explicit source release and separate 1 GiB Arrow, 3 GiB current-RSS and 1 GiB
baseline-relative peak-delta gates. Real-data failure/cross-month/high-volume profiles,
deterministic replays and all quality gates PASS. The failed run remains terminal; one final-code
Authority and unique replacement Run B are conditionally authorized. Groups 2～4 remain DRAFT and
were not executed.

The CR-2026-011 replacement then built all 316 BTC monthly and 82 BTC packed Foundation
checkpoints, but failed before Task sealing because process-lifetime `ru_maxrss` was interpreted
as a phase-local delta. [CR-2026-012](changes/CR-2026-012.md) approves the bounded v1.10
correction: lifetime peak remains audit evidence, while Arrow inflight, absolute current RSS and
continuously sampled phase-current delta remain fail-closed. No research semantics or comparison
rule changes. The full 82-object/9,504-row-group packing/seal profile and repository quality gates
PASS; the terminal failed run now awaits its append-only invalidation receipt and a final-code
Authority refreeze.

The subsequent replacement Run B `stage2-g1-v2-b-20260718T141137Z-f0c150bfa1c9` completed all
316 BTC month-level Foundation objects and failed unpublished before packing when a 1 GiB
phase-current RSS observation threshold was treated as a terminal research failure. Current RSS
was below 3 GiB and no semantic defect existed. [CR-2026-013](changes/CR-2026-013.md) changes all
resource/performance thresholds to deterministic anomaly evidence, adds recoverable resource and
storage pauses, and preserves hard failures for integrity and exact comparison defects. The failed
run is immutable; its sealed objects require a new-run adoption Manifest and full verification.

| Requirement | Plan v1.2 Tasks | Planned implementation/tests | State |
| --- | --- | --- | --- |
| Pre-registration before any Stage 2 implementation/result | S2-T19 | manifest schema, parameter/data/code/time/evidence/metric/output/invalidation contracts; ADR-S2-004 | APPROVED_NOT_EXECUTED_READY |
| S2-T19 v1.3 delivered evidence | S2-T19 | `src/era100x/research/stage_2/manifests/`, config/summary, immutable external Manifest and `validations/stage_2/S2-T19.md` | PASSED |
| Stage 1 v2 baseline, ResearchSetup/ContextModel registry and CanonicalKeyLevel contract | S2-T01 | `contracts/`, `registry/` and fixture conformance tests | APPROVED_NOT_EXECUTED_AFTER_T19 |
| S2-T01 v1.3 delivered evidence | S2-T01 | `src/era100x/research/stage_2/contracts/`, `registry/`, tests and `validations/stage_2/S2-T01.md` | PASSED |
| Three causal key-level sources and arbitration | S2-T02, S2-T03 | fixture-only `key_levels/sources`, `key_levels/arbitration` | APPROVED_NOT_EXECUTED |
| S2-T02 v1.3 delivered evidence | S2-T02 | independent sources, tests and `validations/stage_2/S2-T02.md` | PASSED |
| S2-T03 v1.3 delivered evidence | S2-T03 | deterministic arbitration, source retention tests and `validations/stage_2/S2-T03.md` | PASSED |
| Sweep → Reclaim → Hold and invalidation | S2-T04, S2-T05, S2-T06 | fixture-only `episodes/sweep`, `reclaim`, `hold` | APPROVED_NOT_EXECUTED |
| S2-T04 v1.3 delivered evidence | S2-T04 | causal Sweep detector/tests and `validations/stage_2/S2-T04.md` | PASSED |
| S2-T05 v1.3 delivered evidence | S2-T05 | causal Reclaim detector/tests and `validations/stage_2/S2-T05.md` | PASSED |
| S2-T06 v1.3 delivered evidence | S2-T06 | causal Hold detector/tests and `validations/stage_2/S2-T06.md` | PASSED |
| V1_PRICE G0-G3 and separate V1_FLOW G4 | S2-T07, S2-T08 | fixture-only `gates/price`, `gates/flow`; no G5/G6 | APPROVED_NOT_EXECUTED |
| S2-T07 v1.3 delivered evidence | S2-T07 | causal G1/G3 facts/tests and `validations/stage_2/S2-T07.md` | PASSED |
| S2-T08 v1.3 delivered evidence | S2-T08 | Trades-only G4 facts/tests and `validations/stage_2/S2-T08.md` | PASSED |
| MarketEpisode identity, consume and re-arm | S2-T09 | fixture-only `episodes/identity`; FI-14, UT-EVT-011 | APPROVED_NOT_EXECUTED |
| S2-T09 v1.4 identity correction | S2-T09 | CR-2026-004 canonical candidate identity/payload hash while preserving FROZEN MarketEpisode identity; `validations/stage_2/CR-2026-004.md` | PASSED |
| Registry-driven full candidate generation; BTC/ETH, variant and Primary/Exploratory separate | S2-T10 v1.14 | CR-2026-006 through CR-2026-019; fixed Run B Quality/Verify PASS; exact comparison report `69298e5d05161223b354e1b60a65ef032e9370e4017da487e35657264af8e9f0` | S2-T10 PASS / GROUP 1 PASS |
| Deterministic Group-1 PRICE/FLOW execution optimization | S2-T10 v1.12 | CR-2026-014; ADR-S2-007; processing-day/Foundation caches, spawn month workers, streaming compatibility Hash, read-only progress and performance history | IMPLEMENTED / SEMANTIC PASS / 3.02X HUMAN-ACCEPTED / READY_FOR_FINAL_QUALITY_GATE |
| Group-1 final packing sorting and audited monthly-result recovery | S2-T10 v1.13 | CR-2026-015; ADR-S2-008; packed-artifact audit; monthly adoption Manifest; read-only recovery subflows | COMPLETED / 44 PACKED OBJECTS / 208 COMBINED SEALS |
| CR-015 Foundation recovery coverage and successor authorization | S2-T10 v1.13 | CR-2026-016; exact 632 monthly + 164 packed Foundation checkpoint coverage; preflight-only Run B protection; validation `docs/development/validations/stage_2/CR-2026-016.md` | SUCCESSOR BUILT 80,784 / RELEASE FAILED UNPUBLISHED ON STALE 200-OBJECT GATE |
| Catalog object-count observation correction | S2-T10 v1.13 | CR-2026-017/018; stale 200-object hard gate removed; fixed 208-object Run atomically published and independently verified | IMPLEMENTED / PUBLISHED / QUALITY PASS / VERIFY PASS |
| Shared causal Feature Foundation, content DAG, receipts and layout-independent Catalog | S2-T10 v1.8 | `CR-2026-007`; `ADR-S2-006`; current approved setup/context/variants only | PASSED — 19,008 FOUNDATION PARTITIONS |
| Cross-implementation determinism and future Feature Snapshot Tier F/E/D protocol | S2-T10 v1.14; future separately approved Tasks | CR-2026-008/019; exact full Run-A/Run-B comparison plus future approval boundary | VALIDATED — 61,776/61,776 MATCH; 0 DIFFERENCES |
| Compare algorithm-authority production wiring | S2-T10 v1.14 | CR-2026-019; one-line production correction; compare-only Authority `e3688ca21a987849388cb9e694929033aac51ed245d1f0eb5337c43f554eb740` | IMPLEMENTED / 431 TESTS PASS / EXACT COMPARE PASS |
| Group-1 small-sample integration | S2-T01～S2-T09 | fixture chain plus six controlled real windows; locked execution Manifest | PASSED |
| Historical price-only path metrics | S2-T12 v1.3 | H1/H2 MFE/MAE, Time-to-Activation proxy and Time-since-MFE; 1,065,416 rows; Run/Verify/UI PASS; no PnL/return/first-passage | PASSED / HUMAN ACCEPTED; CR-2026-022 UI PASS |
| Historical first-passage labels | S2-T13 v1.3 | strict H1/H2 TARGET_FIRST/STOP_FIRST/EXPIRED/AMBIGUOUS; 1,065,416 path rows; 31,962,480 classifications; full Verify/UI PASS; no PnL/ROUND_SUCCESS/bounds | PASSED / HUMAN ACCEPTED |
| Historical AMBIGUOUS bounds | S2-T14 v1.3 | immutable raw labels; Primary failure treatment; conditional exclusion; theoretical upper; H1 adverse/optimistic bounds; 31,962,480 classifications; 2,280 compact distributions; full Verify/UI PASS; no PnL/ROUND_SUCCESS | PASSED / HUMAN ACCEPTED; CR-2026-024 |
| Historical H1/H2 path extraction | S2-T11 v1.3 | `paths/extraction`; approved lossless source-slice CLI; BTC 220,201 + ETH 312,507 episodes; Manifest `d4d6a2f5…`; verify/UI/quality PASS; Muce accepted 2026-07-21; `validations/stage_2/S2-T11.md` | PASSED / HUMAN ACCEPTED |
| Conditional random baseline | S2P13-T16 v1.1 | causal RMS/activity/distance; rolling F0-F3; outcome-blind 5 controls shared by 30 H2 cells; shared window-local H2 gap-before-decision contract; no PnL/return | FINAL SUCCESSOR ENGINEERING/VERIFY PASS / DESCRIPTIVE ONLY / PRIMARY PENDING T18 |
| Seven-day theoretical lifecycle | Plan v1.3 S2P13-T11 | `stage_2/lifecycle`; Contract Price H3 proxy; 20bp auxiliary; dynamic net ticket-doubling; historical Primary and adverse Stress funding; -8U margin depletion | IMPLEMENTED CORE / DIRECTED TESTS PASS / CR-2026-038 FUNDING ACCEPTANCE REHEARSAL AUTHORIZED |
| Historical funding acceptance | Plan v1.3 S2P13-T11 | `stage_2/funding`; complete local BTC/ETH history plus seven-day official sample; checksum, append-only acceptance, Manifest/Catalog/Verify, strict read-back | HUMAN ACCEPTED / 7,128+7,128 LOCAL ROWS HASH-BOUND / MONTHLY RECONCILIATION WAIVED / NO LIFECYCLE RUN |
| Plan v1.3 successor orchestration | S2P13-T11～T16 | CR-2026-041/042/045; `stage_2/rerun`; static/input preflight, exclusive lock, complete source bindings, checkpoint/readback/reconciliation/Verify; T16 SQLite uses local scratch; H2 coverage parity is independently reported | PLAN V1.3 CLOSED AT T16 / FINAL FORMAL CHAIN COMPLETE / T11-T16 VERIFY PASS / PRIMARY PENDING / STAGE 3 LOCKED |
| Append-only Trade partition recovery | S2P13-T11 | CR-2026-043; ADR-S2-020; exact-key supplement overlay for truncated `BTCUSDT/2022-03-01`; official archive checksum plus original receipt byte/logical/count equality; Policy/approval/Authority binding | IMPLEMENTATION AUTHORIZED / FIRST FORMAL CHAIN TERMINAL_FAILED / SUCCESSOR GATED |
| Special research point explicit exemptions | Plan v1.3 governance; SRP-S2-001 | default all-rules inheritance; explicit exact exemptions; non-waivable truth/safety/governance; unknown/wildcard/hash drift rejection; formal consumer rejection | FRAMEWORK IMPLEMENTED / FULL QUALITY PASS / OQ-S2-011 RESOLVED; SRP-S2-001 EXEMPTIONS EXPIRED |
| Placebo | S2-T16 | preregistered placebo; separate future Task | DRAFT_NOT_APPROVED |
| Cluster ownership and cluster bootstrap CI | S2-T17, S2-T18 | BTC/ETH-separated clustering and cluster-level resampling | DRAFT_NOT_APPROVED |
| Stage 2 research gate and deterministic evidence-card reporting | S2-T20 | Stage validation and human Go/No-Go; no automatic Stage 3 | DRAFT_NOT_APPROVED |

Trade Identity v2 propagation is explicit: `(instrument, canonical_trade_id)` is the historical fact identity; `venue_trade_id` is only a venue attribute; ordering is `(ts_event_ns, venue_trade_id, canonical_trade_id)`; confirmed conflicting venue IDs remain separate facts and enter sensitivity/quality reporting. No Stage 2 task may deduplicate by venue ID or filter conflict-labelled facts without an approved L3 change.

Research extensibility is bounded: only the V1.3.4 key-low sweep/reclaim/hold family is approved for Group 1; preregistered G1 context models may be added through the registry without altering MarketEpisode consumption. New strategy families remain outside this Plan. The former S2-T21 draft is folded into draft S2-T20 reporting acceptance and is not an additional business dependency. Approval never promotes a PLANNED implementation path to IMPLEMENTED.

The Feature Foundation and Tier F/E/D protocol are internal S2-T10 v1.8 engineering and
validation contracts, not new Task nodes. They add no edge to the Plan v1.2 DAG, do not create
S2-T21/S2-T22/S2-T23 and do not authorize S2-T11 through S2-T20. Future event definitions require
their own approved Task and preregistration even when they reuse an already frozen Feature
Snapshot.
