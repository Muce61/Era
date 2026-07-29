# S2P110 sealed incremental runtime implementation validation

## Scope and decision

- Plan: `stage_2_plan_v1.10`
- Task bundle: `S2P110-T11`～`S2P110-T20`
- validation_status: `IMPLEMENTATION_PASS / FULL_REPOSITORY_GATES_PASS / REAL_PREPARE_PENDING`
- formal_run_executed: `false`
- authority_created: `false`
- stage3_locked: `true`

This validation covers the runtime implementation and read-only performance rehearsal. It does
not approve or execute a formal successor Run.

## Before and after

| Area | Plan v1.9 before | Plan v1.10 after |
|---|---|---|
| Trades audit | full-row price conversion and statistics over about 16.2 billion rows | sealed Stage 1 Catalog/Quality/gap inventory plus targeted T11 gap seconds |
| T12–T18 | recompute the complete chain, estimated about 19 hours | validate and reference seven immutable published results |
| T11 dependency | T11 was a non-semantic upstream of T16 | T11 and H2 first merge at T19 |
| interruption | new attempt restarted the current Task | T11 resumes verified 64-partition/Episode batches |
| Task Hash | downstream and Manifest repeatedly reread full output trees | one `task-files.json`; downstream validates only its root |
| final verification | full independent Verify | retained; every new Task file is read once at final Verify |
| incompatible adoption | implicit fallback risk | fail closed before Authority; no automatic full rerun |

```text
v1.9:
prepare(full Trades scan) -> T11 -> T12..T18 recompute -> T19 -> T20

v1.10:
prepare(sealed facts + targeted gaps)
  -> T11 EXECUTED_NEW -------------------------┐
  -> T12..T18 SEALED_ADOPTION -----------------+-> T19 -> T20
```

## Sealed adoption result

The read-only real-evidence validator closed all seven bindings:

| New Task | Adopted source | Source formal fact |
|---|---|---|
| S2P110-T12 | S2P13-T12 | PASS production receipt |
| S2P110-T13 | S2P13-T13 | PASS production receipt |
| S2P110-T14 | S2P13-T14 | PASS production receipt |
| S2P110-T15 | S2P13-T15 | PASS production receipt |
| S2P110-T16 | S2P13-T16 | PASS production receipt and Verify |
| S2P110-T17 | S2P14-T17 | published Verify PASS |
| S2P110-T18 | S2P15-T18 | published Verify PASS |

- adoption rules Hash:
  `666d5e2e0b01cbd45245c6694cf2f5cdd1a385b39d5592ca1332e14df300c683`
- observed adoption bundle Hash:
  `c61b7ee38cb657b487d1894b46bcde2da2ab955fde47ea3b6fd39f6b1ca0270f`
- adopted Task count: `7`
- historical output copied or hard-linked: `0`
- H2 labels consuming lifecycle OHLC: `false`

A matching-contract drift fixture returns
`BLOCKED_SEALED_ADOPTION_INCOMPATIBLE` before execution.

## Resume and Hash validation

The deterministic T11 fixture used 70 day/Episode partitions:

- first attempt completed one 64-partition batch and interrupted;
- the resumed attempt computed only the remaining 6 partitions;
- a clean uninterrupted run computed all 70;
- resumed and clean normalized output bytes were identical.

The ten-Task fake chain additionally verified:

- retryable interruption creates a new attempt and preserves the old attempt;
- terminal failure is not resumable;
- output drift fails final verification and is never published;
- each Task `output.json` is content-Hashed exactly twice: once at completion and once at final
  independent Verify;
- downstream and Manifest do not reread Task contents.

## Tests actually run

- lifecycle/rerun targeted suite: `78 passed`
- v1.10 adoption and resume additions: `3 passed`
- v1.10 input/runtime focused suite: `19 passed`
- governance/current-state/UI focused suite: `PASS`
- targeted Ruff: `PASS`
- targeted strict Mypy: `PASS`
- strict governance: `PASS`
- full repository pytest: `880 passed in 33.25s` in the final unified quality gate
- repository-wide Ruff format/check: `PASS`
- repository-wide strict Mypy (`src scripts`): `PASS`
- strict traceability: `PASS`

The real post-commit `prepare` remains pending and must pass before formal approval can be
requested.
