# ADR-S2-024 — T19 evidence-gate contract

## Status

APPROVED — 2026-07-27 by Muce

## Decision

1. Apply ADR-S2-004 F1–F10 to the strict BTC Primary evidence. Any failure yields
   `PRIMARY_FAILED`; exploratory results cannot rescue it.
2. Classify ETH only after BTC. BTC failure forces ETH `PRIMARY_FAILED`.
3. Project the V1.3.5 lifecycle gates separately for BTC and ETH. Missing or censored evidence
   remains `INCONCLUSIVE` and is never filled with zero.
4. Overall precedence is invalid input → `FAILED_UNPUBLISHED`; H2 failure →
   `NO_GO_CURRENT_EVIDENCE`; H2 pass plus incomplete lifecycle →
   `INCONCLUSIVE_CURRENT_EVIDENCE`; both complete and passing →
   `READY_FOR_STAGE2_FINAL_ACCEPTANCE`.
5. Publish the complete OVERALL parameter landscape and annual frequency/waiting summaries.
6. Engineering PASS never changes the research result and never unlocks Stage 3.

## Consequences

T19 performs no Trades read, outcome calculation, bootstrap or FDR. A successful T19 Run remains
`EVIDENCE_SYNTHESIS_COMPLETE_FINAL_HUMAN_GATE_PENDING`.
