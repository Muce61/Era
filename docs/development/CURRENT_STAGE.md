# Current Development State

```text
Current Stage: Stage 2
Current Plan: stage_2_plan_v1.10 — SEALED INCREMENTAL RUNTIME
Current Task: S2P110-T11 v1.1 — zero-Trade Contract Price proxy repair
Status: CR-2026-051 REPAIR VALIDATED / PREPARE PENDING / FORMAL RUN GATED
```

Plan v1.10 supersedes unexecuted Plan v1.9 with the approved S2P110-T11–T20 sealed incremental
runtime. The implementation commit may implement and fixture-test the runtime, but real `prepare`,
Authority, Run, resume and publication remain blocked until the implementation is frozen in a clean
commit. After `prepare`, Muce must grant one approval bound to the exact commit, inputs-lock Hash and adoption bundle Hash.
Historical
Plan v1.7 evidence remains immutable: BTC/ETH H2 Primary remain `PRIMARY_FAILED`, lifecycle remains
`INCONCLUSIVE_SOURCE_GAP_CENSORING`, and the research decision remains
`STAGE2_NO_GO_CURRENT_EVIDENCE`. Stage 3 remains locked.

The machine authority is `configs/governance/current_development_state.json` schema v1.3 bound to
`configs/governance/stage2_active_policy_v9.json`. The historical v1.8 source audit is
`configs/research/stage_2/s2p18_t11_source_audit_v1.json`; it binds distinct Binance Trades and
aggTrades archive families. CR-2026-051 / ADR-S2-030 permits a bound, flat zero-Trade Contract
Price second as a price proxy while continuing to forbid synthetic Trades or execution claims.

The v1.10 entrypoint is `scripts/run_stage2_v110.py` with exactly `status / prepare / run / resume`.
One inputs lock replaces source/input Catalogs; one Authority embeds the human approval; one
`events.jsonl` Hash chain replaces task receipts and task-local governance bundles. The H2 branch
remains canonical-Trades-only; lifecycle OHLC goes only to T19/T20. No real inputs lock, Authority
or Run was created by the architecture migration. The production input builder now derives all
twelve semantic Hashes from fixed formal evidence, validates T12–T18 sealed adoption and refuses
operator-supplied Hashes; this
implementation still creates no formal evidence until a clean commit runs `prepare`.

Plan v1.7 authorized only S2P17-T20. Formal Run
`stage2-s2p17-t20-20260727T154959Z-ed51e7cb220b` completed under Authority
`ed51e7cb220b22d0bbc2dff862967af635a1219523f5b0927a6fae5c58758423`. Catalog, Manifest,
reconciliation, final decision and independent Verify Hashes are respectively
`a362a2b99f471bd1acf2230b00b0136af6f5907c63bbd7854e88fd9654299e15`,
`b31e9e2f8b5f943d791381b63e2cb673c9f60d0e36a9785095b395207b92ff9f`,
`dd8f0fc90b6af67ee0baf17c7e9a0b44fdab554a15dc624cbd50b49c322cdb68`,
`f550c21b0869a17f436bff3d119b6666f6ca345e7c9d3538f90531d0499f50af` and
`86167e6ba6537d637b1e1614de182b9434286f7d6e95d9702afa0d92805ace59`.
The Run reconciled 28 gate rows, 3,420 parameter-landscape rows, 14 frequency/waiting rows and
six result-blind real event cards. Engineering, publication, reconciliation and Verify are PASS.
The research conclusion is `STAGE2_NO_GO_CURRENT_EVIDENCE`; BTC H2 Primary is
`PRIMARY_FAILED`, ETH is `PRIMARY_FAILED`, and both lifecycle projections remain
`INCONCLUSIVE_SOURCE_GAP_CENSORING`. This is not Stage 2 research PASS. T21 was not executed and
Stage 3 remains locked.

Policy v6 is now an immutable historical closure Policy and cannot authorize Plan v1.10 work or a
new formal Run.

Plan v1.2 `S2-T15` remains `STOPPED_FAILED_UNPUBLISHED` with no formal result. It is an immutable
historical Task identity, not the current Stage 2 Task and not a dependency blocker for T20.
Plan v1.3 `S2P13-T16` is its capability successor without result promotion; T20 binds that
namespaced successor rather than legacy `S2-T15`.

Plan v1.6 authorized only S2P16-T19. It reads the immutable formal T11, T16, T17 and T18
evidence, projects the pre-registered H2 F1–F10 and H3 lifecycle gates, and never recomputes
Trades, outcomes, bootstrap, CI or FDR. Formal Run
`stage2-s2p16-t19-20260727T134851Z-b515924314e5` completed under Authority
`b515924314e512db1606e1cd11571c962efe10fae5209f821a17d9a3fab73f5a`.
Catalog, Manifest, reconciliation and independent Verify Hashes are respectively
`4dfbc022f1219921f23bb695c39733dc82324e41984ac11a9ad5994e223aed96`,
`f85ee05d368cc4d0d56b2e2c10c1d46561df6be90140aeb2a577c244373aa00d`,
`1374f7d846f04737194100f2eb1ad5f746954b91260fd6d8e61511b3072c3068` and
`a272924b834d7f687020ae3ec3bb30e7b639d1fb367b810de40807746dcdabef`.
The formal result is BTC Primary `PRIMARY_FAILED`, ETH `PRIMARY_FAILED`, both lifecycle
instruments `INCONCLUSIVE_SOURCE_GAP_CENSORING`, and overall `NO_GO_CURRENT_EVIDENCE`.
Engineering and Verify are PASS; this is not Stage 2 PASS. T20 is implemented only under the
new Plan v1.7 gate; T21 remains unauthorized and Stage 3 remains locked.

Plan v1.5 authorizes only S2P15-T18. The implementation binds the immutable T16 Verify
`b866905c18fd1cb1f3bbed1f74e5301c56a78e891b81ab3eea61bcff37ed2b86` and T17 Verify
`bb6f7186f068a1dcd040f369c980bdcae4bb5fef9964c2b5ee61e2d30b6c2f1c`. Formal Run
`stage2-s2p15-t18-20260727T101117Z-6be54d26a190` completed publication and reconciliation under
Authority `6be54d26a190bfc5894fa8957cb5fe7d65365db465f1f43332a607efc8dc8f5a`. Its Catalog,
Manifest, reconciliation and independent Verify Hashes are respectively
`14b2730411c23febec80cf8bda99b209a061d32716c987ab3d4eead70f166478`,
`996c3a0eb6f0898cd28caeb4e66cde72d41d2bb04ecf06fbf1ec247882682b95`,
`e2762dad9b19993d81216ea3e285873608f606d4f595a2045111d1451ca11e2d` and
`dc9ebcab3e4af3ff75e03e76ee9fa4f147e27cb2910a80b2b25874f8d5e514d1`. The Run reconciled
10,329 cluster rows, 54,720 bootstrap summaries and 96 FDR families. T18 engineering and Verify
are PASS; the research status remains `STATISTICAL_EVIDENCE_ONLY_FINAL_GATE_PENDING`. T19–T21 were
not executed and Stage 3 remains locked.

Plan v1.4 completed only the approved S2P14-T17 same-stratum non-event placebo. The final formal
Run `stage2-s2p14-t17-20260727T071439Z-0928be24425c` passed publication, reconciliation and an
independent Verify. Its Authority is
`0928be24425ccb334314d033abdbfa36d344fefafb29065ec21705a1ae144433`; Catalog/Snapshot,
Manifest, reconciliation and Verify Hashes are respectively
`2e5f00e4e375ad7e89e84a29bc6baaded7752cfa59e634f69a92e9dce1d91b00`,
`f28d75bb4146d1e77ef20f43188395c090b63df946ea2a9abde41ad8b66a0b26`,
`0cd5dd2a8b513658194d96e898205e356ed07bb94203ee0bb49149282af7b7da` and
`bb6f7186f068a1dcd040f369c980bdcae4bb5fef9964c2b5ee61e2d30b6c2f1c`.
The Run reconciled 413,827 placebo slots into 412,021 matched and 1,806 unmatched matrices,
2,060,105 assignments and 13,680 summary rows across all 456 groups, with zero orphan, within-
matrix duplicate or within-group fake-event duplicate. The engineering result is PASS; the
research result at T17 closure remained `DESCRIPTIVE_ONLY_CLUSTERING_BOOTSTRAP_PENDING`, not Stage
2 Primary PASS. T18 was subsequently executed only under Plan v1.5; T19–T21 were not executed and
Stage 3 remains locked.

The first commit-bound formal attempt at `272e22644864ab07738846350d5815ec306454d3` sealed Authority
`b447069df72a951a9d0685ca74d833802f066d27607c380d450ffe0cb55a0bfc`, then stopped before Run ID
creation because the strict Python reader rejected JSON arrays for two frozen tuple fields. The
Authority remains append-only; no Run, selection, outcome, summary or publication exists. The
reader now uses Pydantic's strict JSON path, which preserves tuple validation while accepting
canonical JSON arrays. The recovery gate accepts only an approval that names this exact failed
Authority, proves it has no Run, and authorizes one successor Authority/Run. A new clean commit and
explicit unique-successor approval are required before any further formal write.

The approved successor at `ab38ccb13e2aea962e7e87d6b9235b1aba6b6db1` sealed Authority
`75fdc5abc76e587b50aa9c9ada9a690ab7dea7e7f4bd01f5ac60e942517181ca` and reserved Run
`stage2-s2p14-t17-20260727T061156Z-75fdc5abc76e`, then stopped while hashing its first checkpoint:
the progress percentage used a forbidden binary float. The Run contains only its validated
UNPUBLISHED run contract; it has no checkpoint, blind selection, outcome, summary, publication or
Verify. Progress percentages are now fixed Decimal-derived strings, and the recovery gate accepts
only an approval naming this exact Authority and empty Run. Another clean commit and explicit
successor approval are required before continuation.

The next approved successor at `90ac911048a5dbf67d56894de0d579f6a109b950` sealed Authority
`2cc5d55da5d95e4086ce29a562762dceae8bdbb2844bd7f51e363e2046d06610` and reserved Run
`stage2-s2p14-t17-20260727T065616Z-2cc5d55da5d9`. Its source Audit checkpoint passed, but blind
selection stopped before writing its first group because the prepared-Episode index treated two
different H2 classification paths under one MarketEpisode as duplicates. The Run contains only
its validated run contract and Hash-valid Audit checkpoint; it has no blind-selection file,
outcome read, summary, publication or Verify. A read-only scan confirmed all 413,837 eligible
prepared paths and all 413,837 real-match matrices are unique when identity includes
`classification_row_hash` / `source_h2_path_hash`. The correction carries that path identity
through selection, real-matrix lookup and final output. The UI now reports a stopped checkpoint
with a free process lock as `PRE_BLIND_PREFIX_FAILED`, not `IN_PROGRESS`. Continuation remains
forbidden until the correction passes the complete quality gate and receives a new commit-bound
approval naming this exact `AUDIT_ONLY` prefix.

The final formal successor `fa92072063be8455fab814c1e9f302f2b06392a999820a53bd430e7282f57579`
completed T11–T16 at commit `555c2a543a9cb3fdf1cb8c79c644792933de2260`. Every Task handoff,
Catalog, Manifest, reconciliation and independent Verify passed. T16 published 532,708 H2 paths,
413,837 eligible Episodes, 413,827 matched and 10 unmatched Episodes, 1,278,527 control matrices
and 13,680 summaries. Its Verify Hash is
`b866905c18fd1cb1f3bbed1f74e5301c56a78e891b81ab3eea61bcff37ed2b86`.
The shared window-local contract reports 96,922 / 413,837 gap-affected event matrices and
307,603 / 1,278,527 gap-affected control matrices. The engineering result is PASS; the research
result remains `DESCRIPTIVE_ONLY_PRIMARY_PENDING_T18`, not Stage 2 Primary PASS.

Muce accepted the performance and Reason Code projection change at
`007b3147abc013ea0a41f214cbff52650b2b20a2` without another data Run. That change passed the
complete repository quality gate, but no claim is made that it produced or accelerated the
immutable formal successor above. Plan v1.3 is now closed at its approved T16 execution ceiling.
S2P13-T17～T21 remain unexecuted, and any continuation requires a new approved plan/version. The
append-only governance decision is recorded in
[`stage_2_plan_v1.3_closure.md`](validations/stage_2/stage_2_plan_v1.3_closure.md).

The earlier formal predecessor remains append-only engineering evidence. Acceptance found that it
used daily aggregate quality as if it were window-local coverage, so CR-2026-045/ADR-S2-021
rejected that predecessor's research interpretation. The final successor above applies
`H2_WINDOW_INTERNAL_GAP_BEFORE_DECISION_V1` symmetrically and does not rewrite the predecessor.

CR-2026-041 producer wiring found OQ-S2-012. Muce approved CR-2026-042/ADR-S2-019: protection and
structure are explicitly not modeled in Stage 2, Contract Price owns scenario valuation and
funding notional, Trades own target/stop, and the two policies replay independent single-position
timelines. OQ-S2-012 is resolved. Final rehearsal implementation may continue; every formal write
remains blocked.

Plan v1.2 and every old S2-T10～T15 artifact remain immutable historical evidence. Plan v1.3 uses
the `(stage_plan_version, task_id)` identity and the namespaced public IDs `S2P13-T11` through
`S2P13-T21`. The completed execution ceiling is `S2P13-T16`; S2P13-T17～T21 were not executed and
Stage 3 remains locked.

The repository contains the fail-closed SRP framework, namespaced task identity, deterministic
S2P13-T11 lifecycle core, typed availability audit, recoverable orchestration and evidence-driven
Web UI. The completed formal evidence remains immutable. No S2P13-T17+ work or Stage 3 unlock is
authorized.

A read-only source inventory on 2026-07-23 confirmed that the fixed T10 snapshot exposes
`contract_price_1s`, `causal_price_bars`, `trade_second_primitives`, Trades indexes and Group-1
event datasets, but no bound historical funding-rate dataset or leverage-bracket schedule.
CR-2026-036/ADR-S2-016 approve Contract Price/canonical Trades as the Stage 2 H3 price proxy, so
historical Mark is no longer a Stage 2 input gate. CR-2026-037/ADR-S2-017 define theoretical
liquidation as Contract-Price net margin depletion at -8U, so a historical bracket is also no
longer required. Zero funding remains forbidden. CR-2026-038 authorizes read-only acceptance of
the existing local BTC/ETH funding
candidates, a Binance official seven-day archive comparison and isolated append-only funding
evidence. Muce waived the full month-by-month reconciliation and separate preflight-binding gate
after the rehearsal exposed the known millisecond rounding issue. The structurally complete,
Hash-bound local history is now human accepted and `HISTORICAL_FUNDING` is satisfied.

The CR-2026-038 funding rehearsal over `[2020-01-01, 2020-01-08)` passed serialization,
strict read-back, reconciliation and independent Verify for 42 accepted rows. It found three
legacy timestamps per instrument rounded down by 1-2 milliseconds; the set comparison therefore
records six differences per instrument. The append-only accepted copy preserves the official
timestamps and the legacy files remain unchanged. This is a successful official-override scenario,
and is the official sample supporting the accepted local history. The limitation remains explicit:
not every calendar month was reconciled row-by-row to the Binance archive.

CR-2026-036/ADR-S2-016 also resolve the target conflict: T2 20bp is auxiliary First Passage only.
The continuation policy exits at net ticket doubling; under the zero-funding 11bp main-cost example
the threshold is approximately 136bp and must move upward with accumulated funding.
Primary uses signed historical funding. Stress separately reports adverse 1.5x/2x payments and a
no-credit case; Stress cannot replace a missing Primary funding row.

The required clean seven-day audit has now run over `[2020-01-01, 2020-01-08)`. Feature
availability and raw-path non-pollution pass: 20,160 anchors reconcile to 20,038 available plus
122 typed boundary-warmup exclusions; 1,211 raw paths remain byte-identical after 2,422 T12 and
2,422 T13 derived rows. Strict audit Verify passes with report Hash `a47b6488…b344`.

The earlier seven-day audit remains useful only as historical pre-contract evidence. It proved the
old 600-second path chain did not mutate its inputs, but it is not the required final-code Plan
v1.3 rehearsal and cannot authorize a long run. CR-2026-039/ADR-S2-018 remove the duplicate
whole-history pre-audit requirement. CR-2026-040 resolves OQ-S2-009 because the answer is now a
fixed execution specification, not an unknown question. The independent
`FINAL_CODE_7_DAY_REHEARSAL` gate remains pending until final code runs seven complete UTC days
through producer, serialization, next-consumer read-back, reconciliation, Verify and UI. The later
formal full-data Run must still validate and reconcile the complete range and fail closed.

CR-2026-033 and ADR-S2-012 are approved. The implemented SRP framework defaults to all rules,
rejects unknown IDs, wildcards and registry Hash drift, preserves a non-waivable safety set and
forces `EXPLORATORY_NONCOMPLIANT` evidence out of formal consumers. Repository-wide Ruff, strict
mypy, strict Traceability, strict governance and 678 tests passed. CR-2026-039 therefore resolves
OQ-S2-011 and removes it from the formal lifecycle gate. The framework remains available for
future genuinely exploratory research.

Muce has now classified CR-2026-031/032 and ADR-S2-010/011 as the first point,
`SRP-S2-001`. The availability/missingness layer declares no exemptions. The lifecycle layer
declared three temporary exemptions during contract formation. V1.3.5 now supplies the formal
lifecycle contract, so EX-001/002/003 are expired for new runs and cannot authorize a V1.3
successor. CR-2026-031/032, ADR-S2-010/011 and the exploratory record remain append-only history.

The unique CR-2026-028 successor
`stage2-s2t15-conditional-20260722T120658Z-023f47cffef2` passed the corrected sealed Episode
Context boundary and completed all `456 / 456` outcome-blind matching groups. It then stopped
before the first selected-control H2 outcome because the post-selection receiver passed the
canonical JSON string form of `control_entry_price` to strict Decimal validation. The checkpoint
is `FAILED_UNPUBLISHED`, `published=false`, `resume_allowed=false`; no outcome matrix, summary,
reconciliation, Catalog, Manifest, Verify or research delta exists. Muce approved CR-2026-029 and
resolved OQ-S2-008 at `2026-07-22T14:12:52Z`, authorizing only the strict Decimal receiver fix,
invalidation of the failed successor chain and exactly one final replacement chain. Quality,
fresh-audit, Authority/bin and preflight gates remain. S2-T16+ remain unauthorized and Stage 3
remains locked.

At Muce's instruction on `2026-07-22T14:41:45Z`, the running final TRAIN-bin freeze was stopped
before a Binning Set or Run ID existed, and the repository root now requires a real seven-day
producer-to-consumer rehearsal before every long-running/full-data task. The stopped Authority is
`e3d9814f…c365`; two prepared BTC/P1 blocks and one incomplete temporary block remain preserved,
unpublished and non-reusable. The first isolated rehearsal correctly failed because its simulated
packaging placed BTC and ETH groups in one selection file. A fresh complete rerun then passed
20,160 feature rows, 42 boundary JSON round-trips, 10 strict Decimal candidate receptions, 10 H2
matrices, 300 outcome cells, 10 assignments and 60 summary rows. This is simulation-only evidence,
not a research result. Because `AGENTS.md` changes the Authority-bound repository commit and
CR-2026-029's final Authority has already been created, a new formal chain is blocked pending
explicit approval of CR-2026-030. Muce approved it at `2026-07-22T14:47:04Z`, authorizing exactly
one replacement Authority/bin/Run chain after a final-clean-code seven-day rehearsal, full quality
gate and fresh audit pass. No long task is active yet.

Stage 0 and Stage 1 remain PASSED with VALID baselines. Stage 2 Plan v1.2 remains APPROVED;
S2-T19 and S2-T01～S2-T12 are PASSED. Muce approved S2-T12 v1.3 at
2026-07-21T03:02:25Z. Its full historical H1/H2 path-metric Run
`stage2-s2t12-metrics-20260721T040435Z-de9aaea56f2a` published 1,065,416 BTC/ETH-separated metric
rows and passed read-only Verify. CR-2026-022 is approved, implemented and validated: the
read-only Web UI now derives PASS, 1,065,416 rows and 16/16 evidence checks from the real immutable
evidence without hard-coding acceptance. Muce accepted and closed S2-T12 at
2026-07-21T06:39:21Z. Muce approved S2-T13 v1.2 at 2026-07-21T07:45:12Z, then approved
CR-2026-023 and v1.3 at 2026-07-21T10:41:50Z. The strict historical first-passage fixture,
full-output runner, read-only Verify and automatic Web-UI projection are implemented. Authority
`ab76072c…bbbe` and Run `stage2-s2t13-first-passage-20260721T110224Z-d3f0c0331395` published
1,065,416 H1/H2 path rows and 31,962,480 classifications; full Verify and the real-evidence UI
projection pass. Muce accepted and closed S2-T13 at 2026-07-21T12:52:58Z, then approved S2-T14
v1.2 fixture capability with `开始t14` at 2026-07-21T13:07:08Z. S2-T14 is isolated to historical
AMBIGUOUS bounds. Its deterministic fixture implementation and repository quality gate pass.
Muce approved CR-2026-024 and S2-T14 v1.3 at 2026-07-21T13:37:13Z for the minimum formal
full-distribution and read-only automatic UI scope. Authority `3a563bd2…f7a` and Run
`stage2-s2t14-ambiguity-bounds-20260721T140507Z-8b4cf765602d` produced 31,962,480 classifications,
2,280 compact distributions and 2,862,231 AMBIGUOUS cases from 1,065,416 immutable H1/H2 path
rows. Full Verify, quality gate and live automatic UI projection pass; Muce's explicit close
instruction became effective after evidence passed at 2026-07-21T14:15:01Z. Muce then approved
S2-T15 v1.2 method-fixture work with `进入t15` at 2026-07-21T14:35:06Z. The implementation is
isolated to preregistered conditional matching. Its 16 directed tests and 553-test repository gate
pass. Muce approved CR-2026-025 and the minimum v1.3 full research/read-only UI scope at
2026-07-21T14:41:46Z. The mandatory pre-Run audit then proved that the repository and complete Git
history do not contain executable volatility/Trades-activity formulas, split/fold boundaries,
exact purge/embargo duration or a deterministic non-event control-anchor rule. OQ-S2-005 therefore
blocked Authority/Run creation at that time. On 2026-07-22T02:25:41Z Muce approved CR-2026-026,
ADR-S2-009, S2-T15 v1.4 and the T19 append-only addendum. OQ-S2-005 is now RESOLVED; v1.4
implementation upstream binding Hash `a1f73a8…9f92` then found 14,256 fixed T10 Group-1 receipts without the
field-distribution digests required by their DatasetSpecs. Muce approved CR-2026-027; the first
append-only supplement verified 14,256/14,256 with zero T10 changes and audit Hash
`b1140c4b…380d` passed. The first formal Run
`stage2-s2t15-conditional-20260722T071250Z-871c404c5f43` then stopped `FAILED_UNPUBLISHED`
during Episode preparation because T15 reconstructed Context at the final Episode timestamp rather
than binding the sealed T10 price-trigger Context. It published no result and completed 0/456
matching groups. Exact read-only reconciliation proves complete, conflict-free composite trigger
bindings for BTC 220,201/220,201 and ETH 312,507/312,507, all `UP/PASS`. The implementation and
automatic UI failure projection are corrected, but directly receiving `price_triggers` exposes
4,752 additional legacy receipt-distribution omissions. Muce approved CR-2026-028 and resolved
OQ-S2-007 at 2026-07-22T08:53:43Z, authorizing the independent read-only supplement, invalidation
of the first unpublished chain and exactly one successor chain. Implementation quality, supplement
and fresh audit remain mandatory before replacement Authority/bins; preflight remains mandatory
before the single successor Run.
No formal T15 research result exists. S2-T16 through
S2-T18 and S2-T20 remain `DRAFT_NOT_APPROVED`, and Stage 3 remains locked.

S2-T11 v1.3 full-output Run `stage2-s2t11-paths-20260721T023117Z-029707f3c111` published
220,201 BTC and 312,507 ETH historical path indexes. Read-only Verify, repository quality gates
and automatic UI projection passed; Muce accepted and closed S2-T11 at 2026-07-21T02:47:07Z.
This is the direct S2-T13 dependency; it does not approve S2-T14 or unlock Stage 3.

## Historical S2-T10 progression

S2-T10 v1.12 was REOPENED_FOR_PERFORMANCE_CORRECTION under
CR-2026-007 and CR-2026-008. Formal Run A
`stage2-g1-full-a-20260716T144233Z-366a541b7956` is PUBLISHED with Quality PASS, 9508/9508
completed work items, zero failed/UNKNOWN work items and 61,776 logical partitions. Its published
logical hash is `8583f220dc880bf5b7e7ace1435ca2285e59b80dd48aa7d15bd2f8cacac60870`; its published physical
hash is `9fe33a4e7fde1ace3281a208c46f7474f66bc5c5a0e538871b273b2f20131578`.

`CR-2026-009` is RESOLVED / IMPLEMENTED / VALIDATED by Muce approval. Its bounded
release/operator corrections remain valid for formal Run A. `CR-2026-010` is APPROVED / IMPLEMENTED /
VALIDATED. Its replacement Authority Bundle froze twice identically and its unique successor Run B
passed preflight.
The failed Authority run
`stage2-g1-v2-authority-20260717T155227Z-b739106b8dca` rejected a legitimate Catalog-authorized
exact-day `archive=YYYY-MM-DD` tail because the V2 resolved-entry contract allowed only monthly
`archive=YYYY-MM`; it remains immutable failed evidence. The replacement Bundle resolves all
4,752 instrument-days, including BTC/ETH exact-day tails for 2026-07-01 through 2026-07-03, and
repeated freeze produced identical receipts without creating its reserved Run B directory. That
Authority and reserved ID are superseded after preflight proved the frozen V2 parser could not
read formal Run A release supplement v1.1. The successor Run B
`stage2-g1-v2-b-20260718T092459Z-85a6a71ab953` is `FAILED_UNPUBLISHED`: its first BTC Foundation
task observed RSS `1,704,640,512` bytes above the frozen `943,718,400` byte process limit. It
completed no task and wrote no staging or published data. `CR-2026-011` row-group streaming,
explicit release and separate Arrow/current-RSS/baseline-relative gates are IMPLEMENTED and
VALIDATED. The approved real-data profiles and all quality gates PASS. The failed Run B remains
terminal; the next permitted actions are its append-only invalidation, a final-code Authority
refreeze and exactly one replacement Run B. Groups 2～4 remain DRAFT and unexecuted.

That replacement Run B `stage2-g1-v2-b-20260718T105814Z-cb5c25abd485` completed all 316 BTC
monthly and 82 BTC packed Foundation checkpoints but failed before Task evidence sealing because
process-lifetime `ru_maxrss` was enforced as a phase-local delta. It remains terminal
`FAILED_UNPUBLISHED` with zero published files. Muce approved
[CR-2026-012](changes/CR-2026-012.md) keeps lifetime peak audit-only and enforces continuously
sampled phase-current RSS instead. Its real 9,504-row-group packing/seal profile and all code
quality gates PASS. The only permitted continuation is append-only invalidation of that terminal
run, a final-code Authority freeze repeated identically and one unique replacement Run B.

The next replacement Run B
`stage2-g1-v2-b-20260718T141137Z-f0c150bfa1c9` completed all 316 BTC month-level Foundation
objects, then failed unpublished before packing because the phase-current RSS observation exceeded
the former 1 GiB delta threshold. Current RSS remained below 3 GiB and no semantic or integrity
violation was reported. Muce approved [CR-2026-013](changes/CR-2026-013.md): resource and
performance thresholds become append-only anomaly evidence, unsafe continuation becomes a
recoverable pause, and integrity failures remain fail-closed. The failed run is immutable; a new
run may adopt its 316 sealed month objects only through complete per-object verification.

The CR-2026-013 implementation gate is PASS: Runtime V2 191/191 and the unified repository gate
397/397 passed with Ruff, strict mypy and strict Traceability. S2-T10 remains IN_PROGRESS; the next
authorized actions are final-code Authority freeze, audited adoption, the unique replacement Run B
and the unchanged exact comparison.

Muce approved [CR-2026-014](changes/CR-2026-014.md) after the next replacement Run B completed
both Foundation Tasks but proved Group-1 PRICE too slow. Run
`stage2-g1-v2-b-20260719T045142Z-0eeb27e0be21` is retained at `INTERRUPTED_RECOVERABLE`, revision 6,
with eight completed BTC PRICE months, no publication and no active process. It may not resume under
changed code or provide Group-1 artifacts to the successor. S2-T10 is blocked pending exact
correctness, performance, recovery and progress-dashboard validation; Groups 2～4 remain DRAFT.

CR-2026-014's accepted r8 implementation reproduces all 9,314,723 rows and 806 receipts exactly and
improves the fixed BTC/ETH July benchmark from 996.78 to 329.69 seconds (3.02x). Muce accepted this
as the practical external-disk ceiling on 2026-07-19. The original 4x and 2.5-core goals remain
recorded as unmet performance objectives, not integrity failures. The next permitted actions are
the final repository quality gate, final-code Authority freeze and one unique replacement Run B.
The successor Run B `stage2-g1-v2-b-20260719T141315Z-bf8c6a186f66` completed and sealed all
80,784 V2 logical partitions, then failed unpublished during final component construction because
the producer and consumer used different artifact sort keys. CR-2026-015 is approved: the 19 packed
objects are proven physically unique, the ordering contract is being corrected, and a new Run B may
adopt only verified monthly evidence before repeating packing, release, verify and comparison.
Groups 2～4 remain DRAFT and unexecuted.

The CR-2026-015 successor `stage2-g1-v2-b-20260720T084846Z-3885667a` passed preflight at commit
`388566742b2bcc32eb478d376fbff25a637415fc` but its adoption stopped before writing staging data:
the implementation incorrectly treated 632 monthly Foundation checkpoints as the complete
Foundation coverage, while the source has 632 monthly plus 164 packed checkpoints. Candidate
commit `b8a1c79` corrects the exact 796-checkpoint contract and streams checkpoint decoding; Runtime
V2 208/208 and the repository gate 419/419 pass. Muce approved
[CR-2026-016](changes/CR-2026-016.md) on 2026-07-20. The preflight-only Run B must remain
immutable and receive append-only disablement evidence. The authorized continuation is the final
code gate, two identical Authority freezes and exactly one successor Run B; S2-T10 remains
IN_PROGRESS and Groups 2～4 remain DRAFT.

At final code commit `9c4b7c423a0479e3d1eb8b6f6423c2d09f2f2813`, complete quality evidence
passed Runtime V2 210/210, Stage 2 302/302 and the unified repository gate 421/421 with strict
Traceability and all safety scans PASS. The preflight-only Run B
`stage2-g1-v2-b-20260720T084846Z-3885667a` received append-only CR-2026-016 disablement with
`resume_allowed=false`, `reuse_allowed=false` and `delete_allowed=false`. Authority
`stage2-g1-v2-authority-20260720T111704Z-9c4b7c423a04` froze twice byte-identically as Bundle
`stage2-v2-authority-bundle-f8e44c9f04b7fd218e88667d`; its unique successor
`stage2-g1-v2-b-20260720T111704Z-9c4b7c423a04` passed preflight at revision 0 with zero completed
tasks, staging files or published files. Audited adoption, recovery, packing, release, verification
and exact comparison have not run; S2-T10 and Group 1 remain incomplete and Groups 2～4 remain DRAFT.

That successor subsequently adopted 8,708 authorized files, completed all 80,784 logical
partitions and recreated 44 Group-1 packed objects, but release failed unpublished because
`CatalogPublisherV2` retained a stale hard limit of 200 object/Seal summaries while the real
Catalog contains 208 (164 Foundation + 44 Group 1). This is an implementation contradiction of
approved CR-2026-013 resource-observation semantics, not a semantic or data-integrity mismatch.
[CR-2026-017](changes/CR-2026-017.md) code correction and cross-Stage resource-threshold audit are
approved. The stale hard gate and misleading object-budget APIs are removed and protected by a
repository-wide regression. Muce separately approved append-only disablement, the final-code gate,
two byte-identical Authority freezes and exactly one successor on 2026-07-20. No successor has yet
been created under that approval. S2-T10 and Group 1 remain IN_PROGRESS; S2-T11～S2-T20 and Stage 3
remain locked.

Muce subsequently approved the CR-2026-018 fixed-Run release-only path and CR-2026-019
comparison-only correction. Fixed Run
`stage2-g1-v2-b-20260720T111704Z-9c4b7c423a04` is
`PUBLISHED_WITH_RESOURCE_ANOMALIES` with Quality PASS and independent Verify PASS over 6 Tasks,
80,784 partitions, 77,265 fragments, 208 objects and 208 Seals. The 27 resource observations are
non-terminal; UNKNOWN, error and identity-conflict counts are zero.

CR-2026-019 then executed only Exact Compare and matched Run A and Run B across all 61,776 Group-1
partitions: 61,776 daily row Hash matches, zero missing, zero extra, zero differences and equal
global distributions. Comparison report SHA-256 is
`69298e5d05161223b354e1b60a65ef032e9370e4017da487e35657264af8e9f0`. S2-T10 v1.14 and Group 1
are PASSED. No later Task was started: S2-T11 through S2-T20 remain `DRAFT_NOT_APPROVED`, and
Stage 3 remains locked.
