# ADR-S2-008 — Group 1 Packing Recovery Without Event Recalculation

- Status: ACCEPTED
- Date: 2026-07-20
- Decision owner: Muce
- Change Request: CR-2026-015

## Decision

The authoritative component artifact order is ascending `object_sha256`, matching the existing
consumer validator. A repeated physical Hash is an integrity error and is never silently removed.

A successor Run B may adopt complete immutable Foundation and Group-1 monthly evidence only after
per-file authority verification. Final Group-1 packed objects and all execution caches are excluded.
The successor therefore repeats packing, release, verification and the exact Run A comparison, but
does not repeat the already sealed 61,776 logical Group-1 partition calculations.

The recovery pipeline exposes seven read-only Web subflows: failed-run protection, duplicate audit,
monthly adoption, final packing, release, verify and Run A/Run B compare. Progress evidence is
execution metadata and does not enter research identity, payload or semantic Hashes.
