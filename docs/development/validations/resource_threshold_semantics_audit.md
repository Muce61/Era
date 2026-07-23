# Repository Resource-Threshold Semantics Audit

## Scope and decision

- audit_date: 2026-07-20
- approved_by: Muce
- scope: Stage 0 through Stage 9 registry, all current `src/` production modules and `scripts/`
- governing correction: CR-2026-013 and CR-2026-017
- result: PASS_AFTER_ONE_STAGE_2_CORRECTION

Resource, capacity and performance thresholds may produce append-only anomalies or a recoverable
pre-execution/runtime pause. They must not independently change research semantics, quality PASS,
Catalog validity or publication eligibility. Authority, Hash, Schema, checksum, identity,
ownership, exact coverage, append-only and exact-comparison failures remain hard integrity gates.

## Stage-by-stage result

| Stage | Implemented scope inspected | Result |
| --- | --- | --- |
| Stage 0 | passed foundation/contracts and governance implementation | PASS — no object/resource-count publication gate found; risk/data-contract gates are semantic safety rules |
| Stage 1 | data ingest, full build, catalogs and validation scripts | PASS — disk free-space check is a write-safety gate before/while building, not research quality or publication semantics |
| Stage 2 | manifests, candidate runner, Runtime V2, Catalog, recovery, release and operational scripts | CORRECTED — removed stale Catalog 200-object terminal gate and all misleading hard-budget APIs/names |
| Stage 3～Stage 9 | registry and DRAFT plans | NOT IMPLEMENTED — no production source exists to hide a resource publication gate; future source is covered by the repository guard test |

The source audit covered 124 production Python modules under `src/era100x` plus operational Python
scripts. Exact-count checks such as 80,784 total partitions, 61,776 Group-1 partitions, source
coverage and one-to-one Seal ownership were reviewed as integrity contracts and intentionally kept.

## Corrections made

1. `CatalogPublisherV2` accepts Catalogs with more than 200 distinct objects and Seals.
2. Removed `require_catalog_object_budget`, whose no-op existence could be reconnected as a hard
   gate later.
3. Replaced `MAX_*`/`budget` object-count naming with explicit `*_observation_threshold` naming in
   Foundation, Group 1 and the production backend.
4. Removed tests that asserted production output must remain `<= 200`; tests now assert exact
   fixture semantics and successful 201-object publication.
5. Added a repository-wide source guard that fails if deprecated hard-gate symbols or the terminal
   error message reappear anywhere under `src/` or `scripts/`.
6. Added an all-category test proving MEMORY_RSS, ARROW_INFLIGHT, SHARD_SIZE, OBJECT_COUNT,
   DISK_CAPACITY, STORAGE_AVAILABILITY, PERFORMANCE and MONITOR_STALL crossings only append anomaly
   evidence.

## Deliberately retained safety gates

| Gate | Why it remains hard |
| --- | --- |
| Stage 1 disk safety gate | Prevents unsafe writes when the approved work volume lacks capacity; it does not turn existing research evidence into semantic failure |
| Stage 2 legacy preflight/runner space gate | Stops execution before a large build starts; it does not reject an already valid Catalog |
| Runtime V2 external-volume capacity gate | Emits recoverable `ResourcePause` / storage pause evidence, not `FAILED_INTEGRITY` |
| Hash, Schema, uniqueness, exact coverage and comparison checks | These establish data identity and correctness, not resource preference |

## Permanent regressions

- `tests/test_resource_threshold_semantics.py`
- `tests/research/stage_2/runtime_v2/test_resource_anomalies.py`
- `tests/research/stage_2/runtime_v2/test_catalog_hashing.py`

Validation completed with Runtime V2 212/212 and the unified repository gate 425/425; Ruff,
strict mypy and strict Traceability all passed.

This audit does not authorize a new Authority, successor Run B, S2-T11 through S2-T20, or Stage 3.
