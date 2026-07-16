# Specification Traceability

Model: formal rule → Stage → Task → implementation → tests → validation → current validity. The machine-readable complete catalogue is [`traceability/rules.yaml`](traceability/rules.yaml); every implementation/test path is explicitly PLANNED, not implemented.

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

Stage 2 is `APPROVED / NOT_EXECUTED`. Muce approved Plan v1.2 and Group 1 Task v1.3 (S2-T19, S2-T01～S2-T10). ADR-S2-004 governs later research definitions; CR-2026-002/ADR-S2-005 govern exact Group-1 key-level, event, gate, OFAT and CLI definitions. Groups 2～4 remain DRAFT. All implementation/test paths remain PLANNED; no Stage 2 business code or research has executed and no execution BLOCKER remains.

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
| MarketEpisode identity, consume and re-arm | S2-T09 | fixture-only `episodes/identity`; FI-14, UT-EVT-011 | APPROVED_NOT_EXECUTED |
| Registry-driven full candidate generation; BTC/ETH, setup/context and variants separate | S2-T10 | only full-candidate owner, bound to locked Group-1 Manifest and published hashes | APPROVED_NOT_EXECUTED |
| Historical path metrics and labels | S2-T11, S2-T12, S2-T13, S2-T14 | v2 ordering, MFE/MAE/time, first passage, AMBIGUOUS bounds | DRAFT_NOT_APPROVED |
| Conditional baseline and placebo | S2-T15, S2-T16 | matched baseline/placebo with frozen relaxation and seeds | DRAFT_NOT_APPROVED |
| Cluster ownership and cluster bootstrap CI | S2-T17, S2-T18 | BTC/ETH-separated clustering and cluster-level resampling | DRAFT_NOT_APPROVED |
| Stage 2 research gate and deterministic evidence-card reporting | S2-T20 | Stage validation and human Go/No-Go; no automatic Stage 3 | DRAFT_NOT_APPROVED |

Trade Identity v2 propagation is explicit: `(instrument, canonical_trade_id)` is the historical fact identity; `venue_trade_id` is only a venue attribute; ordering is `(ts_event_ns, venue_trade_id, canonical_trade_id)`; confirmed conflicting venue IDs remain separate facts and enter sensitivity/quality reporting. No Stage 2 task may deduplicate by venue ID or filter conflict-labelled facts without an approved L3 change.

Research extensibility is bounded: only the V1.3.4 key-low sweep/reclaim/hold family is approved for Group 1; preregistered G1 context models may be added through the registry without altering MarketEpisode consumption. New strategy families remain outside this Plan. The former S2-T21 draft is folded into draft S2-T20 reporting acceptance and is not an additional business dependency. Approval never promotes a PLANNED implementation path to IMPLEMENTED.
