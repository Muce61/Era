#!/usr/bin/env python3
"""Main orchestrator for Carry research.

Runs the full pipeline per the prompt §0-16.
Focus: Funding Carry (perp), delivery basis marked unavailable.
Includes: event study (next-settled timing), multi-period FRC1 with real two-leg prices where possible,
decomp, costs (base/high/stress), stubs for margin/P4.
"""

from pathlib import Path
import sys
import pandas as pd

# Ensure local imports work when run as script or -m
sys.path.insert(0, str(Path(__file__).parent))

from funding_event_study import run_funding_event_study
from carry_execution import main as run_execution
from carry_accounting import main as run_accounting
from carry_margin import main as run_margin
from carry_portfolio_analysis import main as run_p4

def main():
    data_dir = Path("/Users/muce/1m_data")
    symbols = ["ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT"]
    out = Path("research_core/carry_research")
    out.mkdir(parents=True, exist_ok=True)

    print("=== Carry Research Orchestrator (Grok Build - validity fix round) ===")
    print("Step 1: Funding Event Study (known-at-time, next settled rate semantics)...")
    ev = run_funding_event_study(data_dir, symbols, out)

    print("Step 2: FRC1 Multi-period Execution (real prices two-leg where aligned)...")
    run_execution()

    print("Step 3: Carry Accounting / Decomposition...")
    run_accounting()

    print("Step 4: Margin stress stub...")
    run_margin()

    print("Step 5: P4 combo stub (read-only)...")
    run_p4()

    print("Pipeline complete. Delivery Basis Carry: data_unavailable.")
    print("See carry_research_report.md + outputs in research_core/carry_research/ .")

if __name__ == "__main__":
    main()
