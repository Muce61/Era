# ADR-S2-006 — Hybrid V2 Feature Foundation and Deterministic Cut-over

- Status: ACCEPTED
- Date: 2026-07-17
- Decision owner: Muce
- Change requests: `CR-2026-007`, `CR-2026-008`
- Applies to: S2-T10 v1.8 and future separately approved Stage 2 event experiments
- Rule status: engineering contract plus research validation protocol; no FROZEN strategy change

## Context

The current formal Run A completed all Group-1 generation and finalization work. Its optimized
CR-2026-006 release child is still running, while the stopped legacy parent would otherwise create
another daily-file full Run B. Repeating the original raw Trades and publication architecture for
each future event is not operationally sustainable.

The repository already defines a stable Research Setup boundary, but its current full runner binds
source scanning, feature calculation, event detection, daily physical files, publication and
determinism into one pipeline. The cut-over must reduce repeated source work without changing the
approved event or weakening the current full deterministic test.

## Decision

Use a hybrid cut-over. Let the authorized Run A release child reach a terminal result, suppress
the legacy parent and legacy Run B, and make S2-T10 v1.8 produce a fresh V2 Run B from the frozen
Stage 1 source. V2 first publishes a complete Feature Foundation and then reconstructs Group 1
from that Foundation. Run A remains a valid formal run only if CR-2026-006 quality and publication
pass.

## Feature Foundation

Every Feature Definition is immutable and binds its formula, causal availability, evidence
capability, source schemas/hashes, config and code-tree hash. Every Feature Snapshot binds one
definition and one instrument/time partition. A Feature Foundation Manifest enumerates the exact
definitions and snapshots permitted as event input.

Feature nodes are content addressed by definition/version, code tree, config, source logical
hashes, instrument and logical UTC partition. Only an exact key may be reused. Changes propagate
through an explicit dependency graph; old facts remain append-only.

H2 aggregate facts do not imply exact trade ordering. An event requiring ordering must consume an
approved exact Trade Window Snapshot or block for a feature extension. Historical Bid/Ask, L2,
receive latency, partial fills, real slippage and private flow are never synthesized.

## Registry and event execution

The registry is explicit and fail closed. It binds setup, context and variant versions to required
Feature Definition hashes, parameter schemas, input/output contracts, ownership rules, evidence
capabilities and implementation tree hashes. Plugins are deterministic research functions and do
not perform filesystem, network, publication or trading operations.

Only the existing key-low sweep/reclaim/hold family is approved in this cut-over. Infrastructure
for future plugins is not approval to register or run one.

V2 runtime code is isolated under `src/era100x/research/stage_2/runtime_v2/` and is invoked only by
`scripts/run_stage2_research.py`. The legacy candidate CLI remains a V1 Run A compatibility
interface and cannot create V2 Run B.

## Physical and logical partitions

Logical ownership remains the approved UTC day. V2 may store multiple logical days in a larger
physical file and represent empty logical days by Catalog receipts. Each owner day retains a
canonical semantic hash, row count, identity hash and quality record. Physical file hashes and
paths remain separate integrity facts.

For current Group 1, V2 must emit a compatibility projection for every dataset that is exactly
equivalent to formal Run A after grouping by instrument, variant, dataset and owner day. The
FROZEN MarketEpisode identity and all candidate semantics remain unchanged.

## Determinism

Current acceptance compares the complete formal Run A with a complete fresh V2 Run B using the
layout-independent protocol in CR-2026-008. Future events may use the Tier F/E/D protocol only
after separate Task and preregistration approval. Tiering changes source-reuse scope, not the rule
that the same approved input must produce the same semantic output.

## Failure and rollback

The Run A release child is isolated from V2 implementation. A Run A failure blocks Group-1
acceptance. A Feature, receipt, registry, identity or comparison failure prevents V2 publication
or acceptance. The fallback is to stop and retain all evidence; no process silently switches to
another root, source, setup, parameter set or comparison rule.

Reverting V2 code does not delete its Foundation or failed runs. Any published V2 artifact remains
append-only and is marked invalid when its authority changes.

## Consequences

- Plan v1.2 and its Task DAG remain unchanged; S2-T10 remains the sole Group-1 full builder.
- S2-T10 advances to v1.8 under the approved hybrid path.
- No S2-T11 through S2-T20 work is authorized.
- Future events normally compute from frozen Feature Snapshots instead of repeating raw Trades
  scans, but each event still requires its own research approval.
