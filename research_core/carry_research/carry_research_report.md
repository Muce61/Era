# Carry Research Report (Funding / Basis Carry)

**Base branch:** codex/adaptive-leverage-10x-20x  
**Base commit:** e56054f0f074920e54e742a1050b1bcb29ec2543  
**Research branch:** grok/funding-basis-carry-research  
**Research start commit:** 670f076d5834ca092970cc2055a4c0a3e42b7753  
**Research head commit:** b417b3f94b5ca6d6c349ae83a9f8871d3351579b (see `git rev-parse HEAD` + user §16 commands for exact final)  
**Data:** real 1-year funding rates (/Users/muce/1m_data/derivatives_data) + aligned 1m klines (new_backtest_data_1year_1m / merged) for BTC/ETH/SOL  
**Date:** 2026-06-30  
**Executed by:** Grok Build (following the detailed prompt; validity-fix round complete)

## Executive Summary
This is a **preliminary feasibility scan** (not a production strategy) for delta-neutral Funding Carry (FRC1) and Basis Carry (BSC1) as an independent second source alongside P4 on the base codex branch.

**Overall conclusion: F. insufficient data / implementation to validate**

**Funding Carry (perp): E. insufficient data/implementation** (real two-leg PnL now implemented with asof prices at entry/exit for available symbols; next-settled rate timing semantics applied; multi-period episodes modeled; but full coverage across all events/symbols/periods incomplete, net after costs negative or marginal in 1y sample, insufficient robustness evidence).

**Delivery / Expiry Basis Carry: E. insufficient historical data** (no usable historical delivery contract klines + expiry/roll rules found; marked data_unavailable in inventory).

Current multi-period prototypes (threshold ~5bp, hold while attractive up to 6 periods) with base/high/stress costs produce negative mean net in the tested window. High-rate episodes exist but after realistic roundtrip (fees+slippage) and residuals the edge is not reliably positive. No bootstrap/regime stability validation completed to production gate.

## What Was Done (addressing user review + prompt)
- Branch isolated: grok/funding-basis-carry-research created from e56054f (codex/adaptive-leverage-10x-20x). Confirmed 0 carry_research files or changes leaked to codex.
- Data audit: data_inventory.csv + data_quality_report.md. Spot 1m + perp funding (calc_time known proxy) available; delivery **data_unavailable**.
- All source scripts provided: funding_event_study.py, carry_execution.py (FRC1 multi-period), carry_accounting.py, carry_margin.py, carry_portfolio_analysis.py, run_carry_research.py, tests/test_carry_no_lookahead.py.
- Funding event study (4095 events): fixed to treat row rate as for upcoming, use next settled (shift) for realized_income_rate attribution, forward_delta as change (not absolute), cost coverage estimate.
- Prototypes: FRC1 episode holding (avg hold 2.88 periods), costs only on entry/exit, real prices (close/mark asof <= time) for two-leg PnL on symbols with data (residuals now computed, not zero).
- Decomposition: funding_income + spot_pnl + deriv_pnl (basis/residual embedded) - costs (3 scenarios).
- Tests: 4/4 pass (no-future-rate, timestamp align, multi-period costs-once, two-leg fields).
- Report: rephrased per review (no "edge proven consumed"; use "insufficient data/implementation"); outputs regenerated; metadata/SHAs updated.
- Orchestrator: run_carry_research.py produces all.

All outputs under research_core/carry_research/ (parquet, csv, md). No changes to P4, backtest/, strategy/, or base logic.

## Key Results (1y real data, 2024-12 ~ 2026-06)
- Events: 4095 total (BTC/ETH/SOL ~1365 each; BNB limited).
- Mean known_rate: BTC 4.9bp, ETH 4.6bp, SOL 0.4bp.
- Mean realized (next): nearly identical; mean_forward_delta ≈ 0 (tiny negative).
- % positive realized: high (BTC 85.9%, ETH 82%, SOL 59%).
- Est. cost coverage (vs 5bp period proxy): 0.098 / 0.091 / 0.007 — rates do not cover assumed base costs on average.
- Episodes (FRC1 5bp thresh, max 6p): 680 , mean hold 2.88 periods.
- Mean net_return per episode: -0.000348 ( -3.48bp ), ~27.9% positive net.
- Funding_income positive in selected episodes but offset by roundtrip ~10bp (base) + price residuals (volatile; mean residual positive in sample but insufficient to overcome costs+drag reliably).
- Two-leg: for BTC-loaded episodes, spot+deriv captured (e.g. first episodes show residuals largely offsetting or adding modestly); not all symbols have full price alignment in every run.
- High vol drag observed in sub-periods; low rate regime (SOL) worthless.
- Costs: base (0.05%), high, stress expanded.
- P4 combo stub: no demonstrated complement (corr N/A, no clear positive carry on P4 down-months).
- Robustness: no full bootstrap/block, regime, remove-top performed (would likely fail given net negative).
- No-lookahead: enforced (known only for entry; prices asof<= ; realized outcome only for attribution).

## Answers to the 24 Questions (from prompt §0-16)
1. Is there independent carry alpha (funding or basis) as second source? Preliminary scan: no validated.
2. Data inventory complete? Yes for funding (calc_time), spot prices partial for two-leg; delivery unavailable.
3. Funding known-at-time semantics correct (no post-settle lookahead)? Yes (fixed in validity round): calc_time + row rate for upcoming; next-settled for realized attribution.
4. Persistence / forward? Rates cluster positive for BTC/ETH; forward_delta ~0 (no strong continuation bias after costs).
5. Single vs multi-period? Now multi-period modeled with hysteresis; still net negative.
6. Cost coverage? No: mean realized << base costs; even positive rate episodes frequently net <0 after 10bp roundtrip.
7-8. Basis Carry (delivery/expiry convergence)? Data unavailable; cannot evaluate.
9. PnL decomposition clean (funding + basis + residual - all costs)? Yes in scripts; real price residuals now included.
10. Multiple cost scenarios? Yes (base/high/stress).
11. Execution frictions (fees, slippage, borrow, margin)? Included; margin stub present; real borrow data not in inventory for spot leg.
12. Risks (liq, gap, regime shift, crowding)? Acknowledged; high vol destroys; no full stress test beyond stub.
13. Stability (bootstrap, block-bootstrap, remove top N, regime splits)? Not executed; given negative mean expected to be unstable.
14. P4 combo (read-only): correlation, complement on down months, joint DD? Stub shows not demonstrated.
15. Strict no OOS / no peeking? Yes, all on historical known; separate from P4 development.
16. Code / repro? Full .py + orchestrator + test + outputs present. Run run_carry_research.py to reproduce.
17. Timestamp/alignment exact (15m/1m close + next open semantics)? Events use 8h calc; prices asof for entry/exit; no future.
18. Episode vs per-period? Episode based (multi hold); costs on roundtrip only.
19. Is Carry invalidated? No. Result is "insufficient data/implementation to validate positive robust net after costs in this window".
20. Longer data / other venues needed? Yes for any follow-up (current ~1y, limited symbols for full two-leg).
21-22. Git hygiene: branch grok/... only; base e56054f untouched; files only in research_core/carry_research + one test.
23. Artifacts: carry_event_table.parquet, *_summary.csv, decomposition.csv, cost_*.csv, margin_*, p4_*, report.md.
24. Conclusion letter? F (overall); sub-E for Funding and Delivery due to implementation/data limits. No A/B/C/D.

## Updated Numbers (post validity-fix run)
- 4095 funding events.
- 680 multi-period episodes.
- Mean net_return -0.0348%.
- Two-leg residual implemented (BTC episodes use close/mark asof).
- All 4 carry tests pass.
- Delivery: data_unavailable.

## Conclusion (F per prompt, rephrased)
**F. insufficient data/implementation to validate**

The current 1y dataset, partial price alignment for two-leg PnL, and FRC1 prototype (even after multi-period + next-settled timing fixes) do not produce a cost-positive, robust, stable carry that meets the strict independent-source gates.

This is a research closure on the attempted implementation, not a claim that funding carry "cannot work". With exact mark/index at every settlement, full spot borrow costs, longer multi-year aligned history, lower assumed costs, and regime filters it may be re-evaluable. But per the prompt criteria and what is present now: F.

## Next (per user instruction)
- Do not switch topics yet. Validity fix round addressed: source code, timing (next settled), real prices, episode design, tests, report, metadata.
- User to run §16 git commands in clean tree for exact SHAs/log/status in final.
- Possible follow-ups (not started): longer data pull, full stability scripts, basis if delivery data appears, or archive Carry.

All artifacts committed to research_core/carry_research/ on grok/funding-basis-carry-research.

**Autonomous push record:** Latest commits (incl. this note + metadata) pushed autonomously via `git push origin grok/funding-basis-carry-research` (ssh auth successful, branch now in sync). HEAD at time of last push: e23e5fb (see `git log` on remote for exact). Per user instruction: every R&D completion will auto-commit + push.

(End of report)
