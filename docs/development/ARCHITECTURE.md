# Architecture Record Template

The manual recognizes high-level boundaries for the data layer, research layer, replay layer, state and risk layer, execution-capability validation layer, and forward layer. This file records approved boundaries, data flows, interfaces, constraints, and decisions.

No package names, module layout, technology selection, or implementation topology is approved yet. Those details must be introduced by an approved Stage and Task with linked rules and ADRs.

## Stage 2 v1.1 DRAFT Research Extension Boundary

This section is planning-only and grants no implementation authority while Stage 2 remains `DRAFT`.

The research layer is split into stable orchestration contracts and independently versioned research definitions:

```text
Stage 1 VALID published baseline
→ causal FeatureSnapshot
→ ResearchSetupRegistry + ContextModelRegistry
→ approved event/gate pipeline
→ MarketEpisode and candidate records
→ shared path/label/statistics pipeline
→ deterministic reports and event evidence cards
```

- `ResearchSetup` owns an event family, gate set, label contract and required data capability. V1.3.4 currently permits only `KEY_LOW_SWEEP_RECLAIM_HOLD_V1` for execution in Stage 2.
- `ContextModel` is a causal, preregistered G1 research extension. It may classify trend/range/volatility/session or similar context, but cannot change MarketEpisode identity/consumption or introduce a new FROZEN strategy family.
- `StrategyVariant` keeps `V1_PRICE` and `V1_FLOW` separate. Instrument, setup, context and variant results cannot be pooled silently.
- A fixture-only dummy setup is allowed solely for registry conformance tests. Unknown or unapproved setups fail closed.
- A new context within the approved family requires preregistration and isolated evidence. A new strategy family, direction, venue or risk behavior requires the applicable Change Request and formal specification approval.

## Stage 2 v1.1 DRAFT Evidence Visualization Boundary

Event visualization is a reporting adapter and cannot alter event detection, labels or statistics.

- `EVENT_EXPLAINER` is an educational schematic. Fixture or illustrative data must carry a visible `ILLUSTRATIVE_FIXTURE / 非真实市场证据` mark.
- `EVENT_EVIDENCE_CARD` is generated only from an immutable validated event slice and must include instrument, episode/event ID, UTC window, setup/context/variant, run ID and data/config/code/template hashes.
- Formal evidence images are deterministic artifacts, not generative images. Missing historical Bid/Ask, execution, latency, partial-fill or slippage fields remain `UNAVAILABLE` and are never drawn as facts.
- The canonical reviewable artifact is semantic SVG plus a machine-readable sidecar; PNG is a derived sharing format. A new rendering dependency requires an ADR and a newly approved Task version.
- BTC/ETH and different setup/context/variant outputs remain independently indexed. Large rendered outputs live only under the approved Stage 2 external work root.
