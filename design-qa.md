# Stage 2 Progress Web — Design QA

## Evidence

- source: `/private/tmp/Era-stage2-v2-planning/design-source-current.png`
- implementation: `/private/tmp/Era-stage2-v2-planning/design-implementation-live.png`
- source capture: 1329 × 1019
- implementation full-page capture: 1280 × 1483
- implementation URL: `http://127.0.0.1:8765/`
- compared state: successor final packing complete; independent Release running at capture time
- current API state after capture: Release failed unpublished on the stale 200-object Catalog gate

The source and implementation images were opened together in one comparison input. The 49-pixel
capture-width difference does not change the responsive desktop layout; the added full-page height
is intentional because the implementation exposes every execution subflow instead of hiding the
release chain below one aggregate status.

## Full-page comparison

The dark navy governance dashboard, dense monospace data treatment, blue active-state emphasis,
green PASS state, one-pixel separators, square card geometry and compact evidence hierarchy remain
consistent with the reference. The new 11-card execution grid is inserted into the existing
information architecture and uses the established tokens rather than introducing a second visual
language.

## Focused region

The live execution section exposes these distinct cards: monthly adoption, Foundation BTC,
Foundation ETH, final packing, four Group-1 components, Release, Verify and exact comparison. Each
card has a state, evidence summary and progress rail. Release failure now overrides the otherwise
complete checkpoint summary so the page visibly reports `RELEASE FAILED / UNPUBLISHED`.

## Fidelity surfaces

| Surface | Result |
| --- | --- |
| Layout and hierarchy | PASS — original authority/run structure preserved; execution grid extends it |
| Typography and density | PASS — compact sans/mono pairing and numeric hierarchy preserved |
| Color, borders and states | PASS — navy surfaces, blue RUNNING, green PASS and red FAILED are consistent |
| Data truthfulness | PASS — 8,708 adopted files, 44 packed seals and 27 resource anomalies are exposed |
| Responsive behavior | PASS — desktop capture remains aligned with no clipping or overlap |

## Interaction and runtime checks

- execution-explanation dialog: opened and content verified;
- evidence drawer: opened and closed successfully;
- Escape/drawer behavior: verified;
- automatic `/api/status` refresh: verified;
- browser page-error watch after reload: none;
- browser console-event watch after reload: none;
- HTML JavaScript compilation through Node `new Function`: PASS;
- current `/healthz`: PASS;
- current failure projection: Release `FAILED`, publication record absent, comparison report absent.

## Fix history

1. Removed the false assumption that final packing should stop at 19 seals; completion now follows
   the actual `FINAL_PACKING PASS` evidence and displays the real 44-seal result.
2. Split the aggregate progress into 11 user-visible execution cards.
3. Added append-only evidence counters and per-task resource anomaly counts.
4. Made Release, Verify and exact comparison independently visible.
5. Made a failed downstream flow override the completed build checkpoint in the page conclusion,
   while preserving the underlying checkpoint status for audit.

final result: passed
