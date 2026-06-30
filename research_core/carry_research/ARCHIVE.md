# FRC1 Carry Research Archive

**Status:** ARCHIVED — Failed Research

**Date:** 2026-06-30 (final closure)

**Branch:** grok/funding-basis-carry-research (retained, not merged)

**Base:** codex/adaptive-leverage-10x-20x (untouched for Carry logic)

## Final Conclusions (fixed, no further changes)

Funding Carry:
E. insufficient validated perpetual execution data

Delivery Basis Carry:
E. insufficient historical delivery data

Overall:
F. no_validated_carry_alpha

Archive:
FRC1_CURRENT_IMPLEMENTATION_ARCHIVED

## Rules (permanent for this archive)
- No merging into P4 or main strategy.
- No further modification of threshold, holding periods, fee assumptions, or any parameters.
- This is treated as a failed research archive.
- All code, data, tests, and reports in research_core/carry_research/ are preserved for historical reference.
- Validity-fix round (4 specific fixes only) was the last allowed engineering work.

## What was produced (for reference only)
- funding_event_study.py + audits
- carry_execution.py (with correct bp units, qty-based linear perp PnL, next-bar executable prices)
- carry_accounting.py + explicit cost scenarios (base/high/stress)
- Full test suite (test_carry_validity_fix.py + previous)
- Multiple backtest CSVs, alignment audits, cost summaries
- Detailed report

This archive documents that even after correcting units, accounting, timing, and cost recomputation, the current FRC1 implementation did not produce validated positive net carry meeting the strict criteria.

Future research on Funding Carry (if any) must start fresh with better data (real perp executable prices at decision + next-bar, full borrow costs, longer history) and is outside this archive.