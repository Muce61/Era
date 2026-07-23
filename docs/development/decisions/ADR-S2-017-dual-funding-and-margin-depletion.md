# ADR-S2-017 — Historical funding is Primary and adverse funding is Stress

## Status

APPROVED — 2026-07-23 by Muce

## Decision

Primary lifecycle evidence uses signed historical funding at the actual settlement events.
Stress evidence is derived from the same historical cash flows:

```text
PRIMARY = actual_signed_funding
STRESS_1_5X = positive_payment * 1.5; negative_receipt unchanged
STRESS_2X = positive_payment * 2; negative_receipt unchanged
STRESS_NO_CREDIT = max(actual_signed_funding, 0)
```

Funding is cumulative and causal at every lifecycle observation. A settlement after the observation
cannot affect that observation.

The Stage 2 theoretical liquidation condition is net margin depletion:

```text
scenario_net_pnl <= -8U
terminal_ticket_equity <= 2U
```

Crossing is evaluated on `CONTRACT_PRICE_H3_PROXY`. It is not a historical exchange liquidation,
does not claim Mark Price and does not validate a live leverage bracket.

## Consequences

Primary and Stress must have separate scenario IDs, summaries and Hashes. Missing historical
funding blocks Primary rather than becoming zero. Stress may quantify robustness but cannot rescue
or replace Primary.
