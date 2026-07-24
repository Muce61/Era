# ADR-S2-020 — Explicit append-only Trade partition supplement overlay

## Status

APPROVED — 2026-07-24 by Muce

## Context

S2P13-T11 correctly failed closed on a physically truncated Stage 1 Trade Parquet. Replacing the
file in place would make old manifests lie, while treating the day as a declared market-data gap
would also be false because the accepted official monthly archive remains intact.

## Decision

Use one exact-key overlay for `(instrument, UTC date)`. Normal partitions continue to resolve from
the immutable Stage 1 root. Only a key explicitly listed in a self-hashed supplement acceptance may
resolve to the append-only rebuilt partition.

The acceptance binds the official archive and checksum, original receipt Hash, rebuilt byte and
logical Hash, row count, Manifest, Catalog and independent Verify. Policy, external formal approval
and ChainAuthority bind the acceptance Hash before T11 runs. Unknown keys never fall back to a
different run or a `latest` directory.

## Consequences

This repairs storage availability without changing historical facts or research semantics. The
damaged file remains visible as failure evidence. Any supplement drift is a terminal failure.
Because the source binding and code commit change, the old rehearsal and approval cannot authorize
the successor.

