# ADR-S2-007 — Deterministic Group-1 PRICE/FLOW Execution Optimization

- Status: ACCEPTED
- Date: 2026-07-19
- Decision owner: Muce
- Change request: `CR-2026-014`
- Applies to: S2-T10 v1.12
- Rule status: execution-only L2 correction; no research or FROZEN-rule change

## Context

Runtime V2 produced correct Group-1 facts but recomputed adjacent processing days, reread overlapping
Foundation fragments, serialized work through an immediately awaited thread future and amplified
legacy compatibility hashing through many small files and a daily Parquet reread.

## Decision

Processing-day calculation becomes a content-bound write-once cache, while owner-day finalization
remains the formal ownership boundary. Instrument-month work executes in three spawn-safe isolated
processes; workers never share a formal writer and the parent publishes results in manifest order.
Foundation data is reused only after its first full receipt/Seal/Hash validation in a bounded
in-memory sliding window. Canonical compatibility bytes remain exact but are encoded and externally
sorted in larger batches and streamed directly to the monthly writer.

User stops are recoverable interruptions, not integrity failures. Progress is exposed through a
read-only localhost service and atomic evidence file. Resource and performance observations remain
outside all research identities and semantic hashes.

## Determinism and rollback

Worker completion order, retry, resume, cache hit/miss and physical layout cannot change row order,
identity, payload, ownership or any logical hash. Every cache and month result binds code tree,
Authority, config, snapshot and upstream hashes. Unknown or conflicting evidence fails closed.

The old executor remains available through Git history and old runs remain append-only. Reverting
this decision cannot delete or rewrite any Authority, run, checkpoint or publication.

## Consequences

The performance gate must pass before a new Authority is frozen. A performance miss blocks full
reexecution but does not classify correct data as failed integrity. No later Stage 2 Task is
authorized.
